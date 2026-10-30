import hashlib
import inspect
import queue
import time
import json
import http.client
import mimetypes
import os
import ssl
import socket
import sys
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import uvicorn
from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QComboBox,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QListWidget,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.config import DevDropConfig, load_config, save_config
from app.runtime import HOST, create_session_folder, get_local_ip, ensure_firewall_rule, get_network_profile
from app.transport import TLSSettings, TransportError, open_local
import app.main as backend


VERSION = "0.1.2"
POLL_INTERVAL_MS = 2000
# Faster initial health check (0.5s vs 1.5s), normal polls stay at 1.5s
INITIAL_TIMEOUT_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 1.5
FIREWALL_RULE_NAME = "DevDrop LAN"


def ensure_firewall_rule(port: int) -> tuple[bool, str]:
    """Ensure Windows Firewall allows inbound connections on the given port.
    Returns (success, message). Requires administrator privileges.
    """
    if os.name != "nt":
        return True, "Non-Windows platform, firewall not managed"
    try:
        # Check if rule already exists
        check = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if "No rules match" not in check.stdout:
            return True, "Firewall rule already exists"

        # Create rule (requires admin)
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Start-Process powershell -ArgumentList '-NoProfile -Command "
                f"New-NetFirewallRule -DisplayName \"{FIREWALL_RULE_NAME}\" "
                f"-Direction Inbound -Protocol TCP -LocalPort {port} "
                f"-Action Allow -Profile Domain,Private' -Verb RunAs"
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, "Firewall rule created successfully"
        else:
            return False, f"Failed to create firewall rule (need admin): {result.stderr}"
    except Exception as e:
        return False, f"Firewall check failed: {e}"


def background(widget, work, success, failure, progress=None):
    """Run blocking work off the Qt thread; deliver results on its timer."""
    results = queue.Queue()
    timer = QTimer(widget)
    def run():
        try:
            value = work(report) if inspect.signature(work).parameters else work()
            results.put((True, value))
        except Exception as error:
            results.put((False, str(error)))
    def report(value):
        results.put(("progress", value))
    def poll():
        while True:
            try:
                item = results.get_nowait()
            except queue.Empty:
                return
            if item[0] == "progress":
                if progress:
                    progress(item[1])
                continue
            ok, value = item
            break
        timer.stop()
        timer.deleteLater()
        (success if ok else failure)(value)
    timer.timeout.connect(poll)
    timer.start(100)
    threading.Thread(target=run, daemon=True).start()


class BackendClient:
    def __init__(self, port: int) -> None:
        self.port = port

    @property
    def base_url(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    def get_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/status")

    def regenerate_code(self) -> dict[str, Any]:
        return self._request("POST", "/api/regenerate-pairing-code")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def get_history(self) -> dict[str, Any]:
        return self._request("GET", "/api/history")

    def clear_history(self) -> dict[str, Any]:
        return self._request("DELETE", "/api/history")

    def transfer_token(self) -> str:
        # Use the same pairing flow as browsers, over loopback only.
        code = self._request("GET", "/api/pairing-code")["code"]
        request = urllib.request.Request(
            f"{self.base_url}/api/pair",
            data=json.dumps({"code": code}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with open_local(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))["token"]

    def transfer_request(self, method, path, payload=None, token=None, timeout=REQUEST_TIMEOUT_SECONDS):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}", method=method, headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        with open_local(request, timeout=timeout) as response:
            return json.loads(response.read())

    def await_approval(self, files, token):
        manifest = []
        for file in files:
            if "\r" in file.name or "\n" in file.name:
                raise ValueError("Filenames containing newlines cannot be sent")
            digest = hashlib.sha256()
            size = 0
            with file.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            manifest.append({"name": file.name, "size": size, "sha256": digest.hexdigest()})
        transfer = self.transfer_request("POST", "/api/transfer-requests", {
            "type": "file", "sender": "Desktop GUI (unverified)",
            "description": ", ".join(file.name for file in files)[:500],
            "size": sum(item["size"] for item in manifest), "files": manifest,
        }, token)
        deadline = time.monotonic() + 125
        while time.monotonic() < deadline:
            state = self.transfer_request("GET", f"/api/transfer-requests/{transfer['id']}", token=token)
            if state["status"] == "approved" and not state["used"]:
                return transfer["id"]
            if state["status"] != "pending":
                raise ValueError(f"Transfer {state['status']}")
            time.sleep(0.5)
        raise ValueError("Approval expired")

    def _request(self, method: str, path: str) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}{path}", method=method)
        with open_local(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)


class BackendManager:
    def __init__(self, config: DevDropConfig) -> None:
        self.config = config
        self.client = BackendClient(config.port)
        self.session_dir: Path | None = None
        self.thread: threading.Thread | None = None
        self.started_here = False
        self.start_error: str | None = None

    def ensure_backend(self) -> None:
        if self._is_devdrop_available():
            return

        if self._port_accepts_connections():
            raise RuntimeError(
                f"Port {self.config.port} is already in use by another application."
            )

        tls = TLSSettings.load()
        password, accepted = QInputDialog.getText(None, "DevDrop HTTPS", "TLS private-key password:", QLineEdit.EchoMode.Password)
        if not accepted:
            raise TransportError("HTTPS startup cancelled")
        tls_options = tls.server_options(password)
        # Ensure Windows Firewall allows LAN access (auto-elevates to admin)
        ok, msg = ensure_firewall_rule(self.config.port)
        if not ok:
            # Non-fatal: warn but continue (user can add rule manually)
            print(f"Firewall: {msg}")

        self.session_dir = create_session_folder(self.config.session_root)
        backend.SESSION_DIR = self.session_dir
        backend.HISTORY_PATH = self.config.session_root / "transfer_history.json"
        backend.SERVER_PORT = self.config.port

        server_config = uvicorn.Config(
            backend.app,
            **tls_options,
            host=HOST,
            proxy_headers=False,
            port=self.config.port,
            log_level="warning",
            log_config=None,
        )
        server = uvicorn.Server(server_config)

        self.thread = threading.Thread(target=server.run, daemon=True)
        self.thread.start()
        self.started_here = True

    def _is_devdrop_available(self) -> bool:
        try:
            request = urllib.request.Request(f"{self.client.base_url}/api/health", method="GET")
            with open_local(request, timeout=INITIAL_TIMEOUT_SECONDS) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
        except TransportError:
            raise
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                raise TransportError("TLS server identity or trust validation failed; verify the certificate out of band") from error
            return False
        except (OSError, TimeoutError, json.JSONDecodeError):
            return False
        return data.get("app") == "DevDrop"

    def _port_accepts_connections(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", self.config.port)) == 0


class Toast(QWidget):
    """Lightweight non-modal toast notification.

    Appears at the bottom-right of the parent widget and fades out automatically.
    """

    _TOAST_DURATION_MS = 2000
    _TOAST_FADE_MS = 250
    _TOAST_OFFSET_Y = 24

    def __init__(self, message: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        # Frameless, tool-style window that does not steal focus.
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        label = QLabel(message)
        label.setObjectName("toastLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.addWidget(label)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(self._TOAST_FADE_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade)

        self._fade.finished.connect(self._finalize)

    def show_toast(self) -> None:
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            parent_rect = parent.rect()
            self.move(
                parent_rect.right() - self.width() - self._TOAST_OFFSET_Y,
                parent_rect.bottom() - self.height() - self._TOAST_OFFSET_Y,
            )
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self._hide_timer.start(self._TOAST_DURATION_MS)

    def _start_fade(self) -> None:
        self._fade.start()

    def _finalize(self) -> None:
        self.hide()
        self.deleteLater()


class StatusDot(QWidget):
    """Small colored circle used as a status indicator.

    The color is provided externally (green = connected, red = waiting,
    amber = unknown). The widget is purely cosmetic — no images, just a paint.
    """

    _DIAMETER = 12

    def __init__(self, color: QColor | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusDot")
        self._color = color or QColor("#73737d")
        self.setFixedSize(QSize(self._DIAMETER, self._DIAMETER))

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(0, 0, self._DIAMETER, self._DIAMETER)
        painter.end()


class FileDropArea(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(132)
        self.selected_files: list[Path] = []

        self.title = QLabel("Drop files here")
        self.title.setObjectName("dropTitle")
        self.hint = QLabel("Files will be added to the current session")
        self.hint.setObjectName("muted")
        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setMaximumHeight(92)
        self.file_list.hide()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()

        self.choose_button = QPushButton("Choose files")
        self.send_button = QPushButton("Send files")
        self.choose_button.clicked.connect(self.choose_files)
        self.send_button.clicked.connect(self.send_files)
        self.send_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.choose_button)
        buttons.addWidget(self.send_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addWidget(self.file_list)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._has_local_files(event.mimeData()):
            self._set_dragging(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._has_local_files(event.mimeData()):
            self._set_dragging(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, _event) -> None:  # type: ignore[override]
        self._set_dragging(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_dragging(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.set_files(paths)
        event.acceptProposedAction()

    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files")
        if files:
            self.set_files([Path(file) for file in files])

    def set_files(self, files: list[Path]) -> None:
        self.selected_files = [file for file in files if file.is_file()]
        self.file_list.clear()
        for file in self.selected_files:
            self.file_list.addItem(str(file))
        has_files = bool(self.selected_files)
        self.file_list.setVisible(has_files)
        self.send_button.setEnabled(has_files)
        self.title.setText(
            f"{len(self.selected_files)} file(s) selected" if has_files else "Drop files here"
        )
        self.hint.setText(
            "Review the selection, then send files"
            if has_files
            else "Files will be added to the current session"
        )

    def send_files(self) -> None:
        if not self.selected_files:
            return
        files = list(self.selected_files)
        port = self.window().active_port
        self.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.hint.setText("Waiting for owner approval...")
        def finished(saved):
            self.setEnabled(True)
            self.progress.setValue(100)
            self.progress.hide()
            self.set_files([])
            self.hint.setText(f"Sent {len(saved)} file(s)")
        def failed(message):
            self.setEnabled(True)
            self.progress.hide()
            self.hint.setText(message)
        def progress(update):
            self.progress.setRange(0, 100 if update["total"] else 0)
            if update["total"]:
                self.progress.setValue(int(update["sent"] * 100 / update["total"]))
            self.hint.setText(update["label"])
        background(self, lambda report: self._upload_files(files, port, report), finished, failed, progress)

    def _upload_files(self, files: list[Path], port=None, progress=None) -> list[str]:
        port = self.window().active_port if port is None else port
        client = BackendClient(port)
        token = client.transfer_token()
        identity = client.await_approval(files, token)
        total = sum(file.stat().st_size for file in files)
        sent = 0
        started = time.monotonic()
        if progress:
            names = ", ".join(f"{file.name} ({format_bytes(file.stat().st_size)})" for file in files)
            progress({"sent": 0, "total": total, "label": f"Transferring {names}: 0 / {format_bytes(total)}"})
        boundary = f"----DevDrop{os.urandom(12).hex()}"
        connection = TLSSettings.load().connection(port, timeout=60)
        connection.putrequest("POST", "/api/upload")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("X-Transfer-ID", identity)
        connection.endheaders()
        try:
            for file in files:
                filename = file.name.replace("\\", "\\\\").replace('"', '\\"')
                content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                header = (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8")
                self._send_chunk(connection, header)
                with file.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        self._send_chunk(connection, chunk)
                        sent += len(chunk)
                        if progress:
                            elapsed = max(time.monotonic() - started, 0.001)
                            rate = sent / elapsed
                            eta = (total - sent) / rate if rate > 0 else 0
                            progress({"sent": sent, "total": total,
                                "label": f"Sending {file.name}: {format_bytes(sent)} / {format_bytes(file.stat().st_size)} · total {format_bytes(total)} · {format_bytes(int(rate))}/s · ETA {int(eta)}s (server confirmation pending)"})
                self._send_chunk(connection, b"\r\n")
            self._send_chunk(connection, f"--{boundary}--\r\n".encode())
            # Terminating zero-length chunk: required to close a chunked body,
            # otherwise the server waits forever and the response never arrives.
            connection.send(b"0\r\n\r\n")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            if response.status >= 400:
                raise ValueError(payload.get("detail", "Upload failed"))
            return [str(name) for name in payload.get("saved", [])]
        finally:
            connection.close()

    @staticmethod
    def _send_chunk(connection: http.client.HTTPConnection, data: bytes) -> None:
        connection.send(f"{len(data):X}\r\n".encode() + data + b"\r\n")

    @staticmethod
    def _has_local_files(mime_data) -> bool:
        return any(
            url.isLocalFile() and Path(url.toLocalFile()).is_file()
            for url in mime_data.urls()
        )

    def _set_dragging(self, dragging: bool) -> None:
        self.setProperty("dragging", dragging)
        self.style().unpolish(self)
        self.style().polish(self)


class SettingsDialog(QDialog):
    def __init__(self, config: DevDropConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DevDrop Settings")
        self.setModal(True)
        self.config = DevDropConfig(
            session_root=Path(config.session_root),
            port=config.port,
        )

        self.root_input = QLineEdit(str(self.config.session_root))
        self.root_input.setMinimumWidth(420)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._choose_root)

        root_row = QHBoxLayout()
        root_row.addWidget(self.root_input, 1)
        root_row.addWidget(browse_button)

        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(self.config.port)

        note = QLabel(
            "Changes are saved for the next session. The current session folder is not moved."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")

        form = QFormLayout()
        form.addRow("Session root", root_row)
        form.addRow("Port", self.port_input)

        save_button = QPushButton("Save")
        apply_button = QPushButton("Apply")
        cancel_button = QPushButton("Cancel")
        save_button.clicked.connect(self._save_and_close)
        apply_button.clicked.connect(self._apply)
        cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(apply_button)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.setStyleSheet(APP_STYLES)

    def _choose_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose DevDrop session root",
            self.root_input.text(),
        )
        if directory:
            self.root_input.setText(directory)

    def _apply(self) -> bool:
        root = Path(self.root_input.text()).expanduser()
        if not self._validate_root(root):
            return False

        self.config = DevDropConfig(session_root=root, port=self.port_input.value())
        save_config(self.config)
        return True

    def _save_and_close(self) -> None:
        if self._apply():
            self.accept()

    def _validate_root(self, root: Path) -> bool:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".devdrop_write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as error:
            QMessageBox.warning(self, "Invalid session root", str(error))
            return False
        return True


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.active_port = self.config.port
        self.backend_manager = BackendManager(self.config)
        self.client = self.backend_manager.client
        self.current_session_path: Path | None = None

        self.setWindowTitle("DevDrop")
        self.setMinimumSize(800, 520)

        self.address_value = QLabel("-")
        self.code_value = QLabel("-")
        self.status_value = QLabel("Starting backend...")
        self.status_dot = StatusDot(QColor("#73737d"), self)
        self.session_value = QLabel("-")
        self.files_value = QLabel("0")
        self.size_value = QLabel("0 B")
        self.qr_code_value = QLabel("QR unavailable")
        self.qr_code_value.setObjectName("qrCode")
        self.qr_code_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_code_value.setFixedSize(180, 180)
        self.qr_address_value = QLabel("-")
        self.qr_address_value.setObjectName("muted")
        self.qr_address_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_address_value.setWordWrap(True)
        self._qr_payload: str | None = None
        self._last_status_snapshot: tuple[Any, ...] | None = None
        # History only changes when a transfer completes; we skip both the
        # network fetch and the widget rebuild unless the received-file count
        # actually moved, keeping the 2s poll cheap and flicker-free.
        self._last_history_files: int | None = None
        self._last_history_signature: tuple[tuple[str, int, str], ...] | None = None
        self.settings_note = QLabel(
            "Settings changes apply to the next session. The current folder stays where it is."
        )
        self.settings_note.setObjectName("muted")
        self.settings_note.setWordWrap(True)
        self.recipient_box = QComboBox()
        self.offer_button = QPushButton("Choose file and offer to browser")
        self.offer_button.clicked.connect(self.offer_to_browser)
        self.outgoing_list = QListWidget()
        self.cancel_offer_button = QPushButton("Cancel selected offer")
        self.cancel_offer_button.clicked.connect(self.cancel_outgoing_offer)
        self.outgoing_status = QLabel("")
        self.outgoing_status.setWordWrap(True)
        self._outgoing_busy = False
        self._outgoing_progress_samples: dict[str, tuple[float, int]] = {}
        self._creating_offer = False
        self.pending_list = QListWidget()
        self.approve_button = QPushButton("Approve")
        self.reject_button = QPushButton("Reject")
        self.approve_button.clicked.connect(lambda: self.decide_pending("approve"))
        self.reject_button.clicked.connect(lambda: self.decide_pending("reject"))
        self._pending_busy = False
        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setMinimumHeight(110)
        self.clear_history_button = QPushButton("Clear history")
        self.clear_history_button.clicked.connect(self.clear_history)

        self.regenerate_button = QPushButton("Regenerate code")
        self.open_folder_button = QPushButton("Open session folder")
        self.settings_button = QPushButton("Settings")
        self.copy_address_button = QPushButton("Copy")
        self.drop_area = FileDropArea(self)
        self.regenerate_button.clicked.connect(self.regenerate_code)
        self.open_folder_button.clicked.connect(self.open_session_folder)
        self.settings_button.clicked.connect(self.open_settings)
        self.copy_address_button.clicked.connect(self.copy_lan_address)

        self._build_ui()
        self.setStyleSheet(APP_STYLES)

        self.approval_timer = QTimer(self)
        self.approval_timer.timeout.connect(self.refresh_pending)
        self.approval_timer.timeout.connect(self.refresh_outgoing)
        self.approval_timer.start(1000)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh_status)

        self.start_backend()

    def _build_ui(self) -> None:
        title = QLabel("DevDrop")
        title.setObjectName("title")
        version = QLabel(f"v{VERSION}")
        version.setObjectName("version")

        header = QHBoxLayout()
        header.addWidget(title)
        header.addWidget(version)
        header.addStretch(1)

        connection = self._section("Connection")
        connection.addLayout(self._address_row())
        connection.addLayout(self._code_row())
        connection.addLayout(self._status_row())

        # Network profile indicator
        self.network_value = QLabel("-")
        self.network_value.setObjectName("rowValue")
        self.network_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.network_value.setWordWrap(True)
        connection.addLayout(self._row("Network", self.network_value))

        qr_panel = QFrame()
        qr_panel.setObjectName("qrPanel")
        # Reserve a dedicated QR column: fixed width, but the height follows its
        # content (heading + QR image + address) so it never overflows its row.
        qr_panel.setFixedWidth(236)
        qr_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        qr_panel_layout = QVBoxLayout(qr_panel)
        qr_panel_layout.setContentsMargins(16, 16, 16, 16)
        qr_panel_layout.setSpacing(12)

        qr_heading = QLabel("QR Code")
        qr_heading.setObjectName("sectionHeading")
        qr_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_panel_layout.addWidget(qr_heading)
        qr_panel_layout.addWidget(self.qr_code_value, 0, Qt.AlignmentFlag.AlignCenter)
        qr_panel_layout.addWidget(self.qr_address_value)

        # Grid gives the QR its own isolated cell; the connection details take
        # the remaining width (column 0 stretches). Neither can overlap.
        connection_area = QGridLayout()
        connection_area.setHorizontalSpacing(24)
        connection_area.setColumnStretch(0, 1)
        connection_area.addLayout(connection, 0, 0)
        connection_area.addWidget(qr_panel, 0, 1, Qt.AlignmentFlag.AlignTop)

        actions = QHBoxLayout()
        actions.addWidget(self.regenerate_button)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.settings_button)

        transfer = self._section("Send files")
        transfer.addWidget(self.drop_area)

        session = self._section("Session")
        session.addLayout(self._row("Current folder", self.session_value))
        session.addLayout(self._row("Received files", self.files_value))
        session.addLayout(self._row("Received size", self.size_value))
        session.addWidget(self.settings_note)

        history = self._section("Recent transfers")
        history.addWidget(self.history_list)
        history.addWidget(self.clear_history_button, 0, Qt.AlignmentFlag.AlignLeft)

        # The content sits inside a scroll area so that, when the window is
        # smaller than the content's natural size, it scrolls instead of the
        # layout compressing widgets over one another. When the window is
        # larger, the container fills the viewport as before.
        container = QWidget()
        container.setObjectName("contentRoot")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(24)
        layout.addLayout(header)
        layout.addWidget(self._line())
        layout.addLayout(connection_area)
        layout.addLayout(actions)
        layout.addWidget(self._line())
        pending = self._section("Pending transfers — sender names are unverified")
        pending.addWidget(self.pending_list)
        approval_actions = QHBoxLayout()
        approval_actions.addWidget(self.approve_button)
        approval_actions.addWidget(self.reject_button)
        pending.addLayout(approval_actions)
        outgoing = self._section("Send to browser — select the session shown on the phone")
        outgoing.addWidget(self.recipient_box)
        outgoing.addWidget(self.offer_button)
        outgoing.addWidget(self.outgoing_list)
        outgoing.addWidget(self.cancel_offer_button)
        outgoing.addWidget(self.outgoing_status)
        layout.addLayout(outgoing)
        layout.addLayout(pending)
        layout.addLayout(transfer)
        layout.addWidget(self._line())
        layout.addLayout(session)
        layout.addLayout(history)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Text wraps (all labels use wordWrap), so horizontal scrolling is never
        # needed; keep content within the window width and scroll only vertically.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        self.setCentralWidget(scroll)

    def _section(self, heading: str) -> QVBoxLayout:
        label = QLabel(heading)
        label.setObjectName("sectionHeading")
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.addWidget(label)
        return layout

    def _row(self, label_text: str, value: QLabel) -> QHBoxLayout:
        label = QLabel(label_text)
        label.setObjectName("rowLabel")
        value.setObjectName("rowValue")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setWordWrap(True)

        layout = QHBoxLayout()
        layout.setSpacing(16)
        layout.addWidget(label, 0)
        layout.addWidget(value, 1)
        return layout

    def _address_row(self) -> QHBoxLayout:
        layout = self._row("LAN address", self.address_value)
        self.copy_address_button.setObjectName("inlineAction")
        self.copy_address_button.setMinimumWidth(72)
        layout.addWidget(self.copy_address_button, 0)
        return layout

    def _code_row(self) -> QHBoxLayout:
        # The pairing code itself is clickable to copy; keep a hint cursor.
        self.code_value.setObjectName("rowValue")
        self.code_value.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.code_value.setWordWrap(True)
        self.code_value.setCursor(Qt.CursorShape.PointingHandCursor)
        self.code_value.mousePressEvent = self._on_code_clicked  # type: ignore[assignment]

        label = QLabel("Pairing code")
        label.setObjectName("rowLabel")

        layout = QHBoxLayout()
        layout.setSpacing(16)
        layout.addWidget(label, 0)
        layout.addWidget(self.code_value, 1)
        return layout

    def _status_row(self) -> QHBoxLayout:
        label = QLabel("Status")
        label.setObjectName("rowLabel")
        self.status_value.setObjectName("rowValue")
        self.status_value.setWordWrap(True)

        layout = QHBoxLayout()
        layout.setSpacing(10)
        # Vertically center the dot against the label baseline.
        dot_row = QHBoxLayout()
        dot_row.setSpacing(10)
        dot_row.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        dot_row.addWidget(self.status_value, 1)
        layout.addWidget(label, 0)
        layout.addLayout(dot_row, 1)
        return layout

    def _line(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("separator")
        return line

    def start_backend(self) -> None:
        try:
            self.backend_manager.ensure_backend()
        except OSError as error:
            self._set_unavailable(f"Could not create session folder: {error}")
            return
        except RuntimeError as error:
            self._set_unavailable(str(error))
            return

        # Brief wait for server to fully accept connections
        QTimer.singleShot(300, self._wait_for_ready)
        self.poll_timer.start(POLL_INTERVAL_MS)

    def _wait_for_ready(self) -> None:
        """Poll quickly until backend responds, then switch to normal polling."""
        def check_ready() -> None:
            try:
                request = urllib.request.Request(f"{self.client.base_url}/api/health", method="GET")
                with open_local(request, timeout=0.3) as resp:
                    if resp.status == 200:
                        self.refresh_status()
                        return
            except Exception:
                pass
            QTimer.singleShot(150, check_ready)
        check_ready()

    def refresh_outgoing(self):
        if self._outgoing_busy:
            return
        self._outgoing_busy = True
        def work():
            recipients = self.client.transfer_request("GET", "/api/recipient-sessions")
            offers = self.client.transfer_request("GET", "/api/outgoing-offers")
            return recipients, offers
        def done(result):
            self._outgoing_busy = False
            recipients, offers = result
            selected = self.recipient_box.currentData()
            self.recipient_box.clear()
            for session in recipients.get("sessions", []):
                label = f"{session['id'][:8]} | {session['peer']} | {session['agent']}"
                self.recipient_box.addItem(label, session["id"])
            index = self.recipient_box.findData(selected)
            if index >= 0:
                self.recipient_box.setCurrentIndex(index)
            self.offer_button.setEnabled(self.recipient_box.count() > 0 and not self._creating_offer)
            item = self.outgoing_list.currentItem()
            identity = item.data(Qt.ItemDataRole.UserRole) if item else None
            self.outgoing_list.clear()
            for offer in offers.get("offers", []):
                state = offer['status']
                sent = int(offer.get("sent_bytes") or 0)
                size = int(offer["size"])
                text = f"{offer['filename']} | {format_bytes(size)} | {offer['recipient_id'][:8]} | {state}"
                if offer.get("stream_started_at") is not None:
                    percent = int(sent * 100 / size) if size else (100 if state == "sent" else 0)
                    now = time.monotonic()
                    previous = self._outgoing_progress_samples.get(offer["id"])
                    if previous and now > previous[0] and sent >= previous[1]:
                        rate = (sent - previous[1]) / (now - previous[0])
                        if rate > 0 and state == "streaming":
                            eta = max(0, int((size - sent) / rate))
                            text += f" | {format_bytes(sent)} / {format_bytes(size)} ({percent}%) | {format_bytes(int(rate))}/s | ETA {eta}s"
                        else:
                            text += f" | {format_bytes(sent)} / {format_bytes(size)} ({percent}%)"
                    else:
                        text += f" | {format_bytes(sent)} / {format_bytes(size)} ({percent}%)"
                    self._outgoing_progress_samples[offer["id"]] = (now, sent)
                if state == "sent":
                    text += " | browser save not confirmed"
                self.outgoing_list.addItem(text)
                item = self.outgoing_list.item(self.outgoing_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, offer["id"])
                if offer["id"] == identity:
                    self.outgoing_list.setCurrentItem(item)
        def failed(message):
            self._outgoing_busy = False
            self.outgoing_status.setText(message)
        background(self, work, done, failed)

    def offer_to_browser(self):
        recipient = self.recipient_box.currentData()
        if not recipient or self._creating_offer:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Offer file to browser")
        if not filename:
            return
        self._creating_offer = True
        self.offer_button.setEnabled(False)
        self.outgoing_status.setText("Preparing a private file copy...")
        def done(offer):
            self._creating_offer = False
            self.outgoing_status.setText(f"Offered {offer['filename']}; waiting for recipient")
            self.offer_button.setEnabled(True)
            self.refresh_outgoing()
        def failed(message):
            self._creating_offer = False
            self.offer_button.setEnabled(True)
            self.outgoing_status.setText(message)
        background(self, lambda: self.client.transfer_request("POST", "/api/outgoing-offers",
            {"path": filename, "recipient_id": recipient}, timeout=120), done, failed)

    def cancel_outgoing_offer(self):
        item = self.outgoing_list.currentItem()
        if item is None:
            return
        identity = item.data(Qt.ItemDataRole.UserRole)
        background(self, lambda: self.client.transfer_request("POST", f"/api/outgoing-offers/{identity}/cancel"),
                   lambda _: self.refresh_outgoing(), lambda message: self.outgoing_status.setText(message))

    def refresh_pending(self):
        if self._pending_busy:
            return
        self._pending_busy = True
        def done(data):
            self._pending_busy = False
            selected = self.pending_list.currentItem()
            identity = selected.data(Qt.ItemDataRole.UserRole) if selected else None
            self.pending_list.clear()
            for transfer in data.get("requests", []):
                size = format_bytes(transfer["size"]) if transfer["size"] is not None else "unknown size"
                text = f"{transfer['type']} | {transfer['sender']} | {size}\n{transfer['description']}"
                if transfer.get("recipient_id"):
                    text += "\nRelay recipient: " + transfer["recipient_id"][:8]
                if transfer["files"]:
                    text += "\n" + ", ".join(item["name"] for item in transfer["files"])
                self.pending_list.addItem(text)
                item = self.pending_list.item(self.pending_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, transfer["id"])
                if transfer["id"] == identity:
                    self.pending_list.setCurrentItem(item)
        def failed(message):
            self._pending_busy = False
            self.pending_list.clear()
        background(self, lambda: self.client.transfer_request("GET", "/api/transfer-requests"), done, failed)

    def decide_pending(self, decision):
        item = self.pending_list.currentItem()
        if item is None:
            return
        identity = item.data(Qt.ItemDataRole.UserRole)
        background(self, lambda: self.client.transfer_request(
            "POST", f"/api/transfer-requests/{identity}/{decision}"),
            lambda _: self.refresh_pending(),
            lambda message: QMessageBox.warning(self, "Transfer request", message))

    def refresh_status(self) -> None:
        try:
            data = self.client.get_status()
        except (TransportError, OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            self._set_unavailable(f"Backend unavailable: {error}")
            return

        try:
            lan_address = TLSSettings.load().url(self.active_port)
        except TransportError as error:
            self._set_unavailable(str(error))
            return
        self._update_qr_code(lan_address)

        # Network profile (Public/Private/Domain) - important for LAN visibility
        net_profile = get_network_profile()
        if net_profile:
            self.network_value.setText(net_profile)
            # Highlight if Public (blocks LAN by default)
            if net_profile == "Public":
                self.network_value.setStyleSheet("color: #ef4444;")
            else:
                self.network_value.setStyleSheet("color: #22c55e;")
        else:
            self.network_value.setText("Unknown")
            self.network_value.setStyleSheet("color: #73737d;")

        received_files = int(data.get("received_files") or 0)
        if received_files != self._last_history_files:
            self.refresh_history()
            self._last_history_files = received_files

        connected_devices = int(data.get("connected_devices") or 0)
        status_text = (
            "1 device connected"
            if connected_devices == 1
            else f"{connected_devices} devices connected"
            if connected_devices > 1
            else "Waiting for devices..."
        )

        session_path = Path(str(data.get("session_path") or ""))
        self.current_session_path = session_path if str(session_path) else None

        pairing_code = format_code(str(data.get("pairing_code") or ""))
        session_text = str(session_path) if str(session_path) else "-"
        files_text = str(data.get("received_files", 0))
        size_text = format_bytes(int(data.get("received_size") or 0))
        snapshot = (
            lan_address,
            pairing_code,
            status_text,
            connected_devices,
            session_text,
            files_text,
            size_text,
        )
        if snapshot == self._last_status_snapshot:
            return

        self._last_status_snapshot = snapshot
        self.address_value.setText(lan_address)
        self.code_value.setText(pairing_code)
        self.status_value.setText(status_text)
        self.status_dot.set_color(QColor("#22c55e" if connected_devices > 0 else "#ef4444"))
        self.session_value.setText(session_text)
        self.files_value.setText(files_text)
        self.size_value.setText(size_text)
        self.regenerate_button.setEnabled(True)
        self.open_folder_button.setEnabled(bool(self.current_session_path))
        self.copy_address_button.setEnabled(True)

    def regenerate_code(self) -> None:
        self.regenerate_button.setEnabled(False)
        try:
            data = self.client.regenerate_code()
        except (TransportError, OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            self._set_unavailable(f"Could not regenerate code: {error}")
            return

        self.code_value.setText(format_code(str(data.get("code") or "")))
        self.refresh_status()
        self._show_toast("Pairing code regenerated")

    def refresh_history(self) -> None:
        try:
            data = self.client.get_history()
        except (TransportError, OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return

        transfers = data.get("transfers") or []
        # Rebuild the widget only when the underlying data actually changed.
        signature = tuple(
            (str(transfer.get("filename") or ""), int(transfer.get("size") or 0), str(transfer.get("timestamp") or ""))
            for transfer in transfers[-20:]
        )
        self.clear_history_button.setEnabled(bool(transfers))
        if signature == self._last_history_signature:
            return
        self._last_history_signature = signature

        self.history_list.clear()
        for transfer in reversed(transfers[-20:]):
            filename = str(transfer.get("filename") or "upload.bin")
            size = format_bytes(int(transfer.get("size") or 0))
            sender_ip = str(transfer.get("sender_ip") or "unknown")
            timestamp = format_history_timestamp(str(transfer.get("timestamp") or ""))
            self.history_list.addItem(f"{filename}\n{size}    {sender_ip}    {timestamp}")

    def clear_history(self) -> None:
        try:
            self.client.clear_history()
        except (TransportError, OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Could not clear history", str(error))
            return
        self.refresh_history()
        self._show_toast("Transfer history cleared")

    def open_session_folder(self) -> None:
        if not self.current_session_path:
            QMessageBox.information(self, "Session folder", "No active session folder yet.")
            return

        try:
            self.current_session_path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(self, "Could not open folder", str(error))
            return

        if sys.platform.startswith("win"):
            try:
                os.startfile(str(self.current_session_path))  # type: ignore[attr-defined]
                self._show_toast("Session folder opened")
                return
            except OSError as error:
                QMessageBox.warning(self, "Could not open folder", str(error))
                return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_session_path)))
        self._show_toast("Session folder opened")

    def open_settings(self) -> None:
        dialog = SettingsDialog(load_config(), self)
        result = dialog.exec()
        self.config = load_config()
        if result == QDialog.DialogCode.Accepted:
            self.settings_note.setText(
                "Settings saved. They apply to the next session; the current folder was not moved."
            )

    def _set_unavailable(self, message: str) -> None:
        self._last_status_snapshot = None
        self.status_value.setText(message)
        self.status_dot.set_color(QColor("#73737d"))
        self.address_value.setText("HTTPS unavailable — configure TLS")
        self.qr_code_value.clear()
        self.qr_address_value.setText("No trusted HTTPS address")
        self._qr_payload = None
        self.regenerate_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.copy_address_button.setEnabled(False)

    def _update_qr_code(self, address: str) -> None:
        if address == self._qr_payload:
            return

        self._qr_payload = address
        self.qr_address_value.setText(address)
        try:
            import qrcode

            qr = qrcode.QRCode(box_size=8, border=4)
            qr.add_data(address)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            image_buffer = BytesIO()
            image.save(image_buffer, format="PNG")
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_buffer.getvalue(), "PNG"):
                raise ValueError("Could not load generated QR image")
            self.qr_code_value.setPixmap(
                pixmap.scaled(
                    self.qr_code_value.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )
            self.qr_code_value.setText("")
        except Exception:
            self.qr_code_value.setPixmap(QPixmap())
            self.qr_code_value.setText("QR unavailable")

    def _on_code_clicked(self, _event) -> None:
        text = self.code_value.text()
        # Copy the raw digits only, mirroring the "Clipboard contains: 646737045" example.
        digits = "".join(character for character in text if character.isdigit())
        if not digits:
            return
        self._copy_to_clipboard(digits)
        self._show_toast("Pairing code copied")

    def copy_lan_address(self) -> None:
        address = self.address_value.text().strip()
        if not address or address == "-":
            return
        self._copy_to_clipboard(address)
        self._show_toast("Address copied")

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _show_toast(self, message: str) -> None:
        toast = Toast(message, self)
        toast.show_toast()


def format_code(code: str) -> str:
    digits = "".join(character for character in code if character.isdigit())
    if len(digits) != 9:
        return code or "-"
    return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def format_history_timestamp(timestamp: str) -> str:
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp or "-"
    return value.astimezone().strftime("%H:%M")


APP_STYLES = """
QMainWindow, QDialog {
    background: #0d0d0f;
    color: #f2f2f2;
}
QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 14px;
    color: #f2f2f2;
}
QLabel#title {
    color: #a970ff;
    font-size: 34px;
    font-weight: 700;
}
QLabel#version {
    color: #73737d;
    padding-top: 12px;
}
QLabel#sectionHeading {
    color: #f2f2f2;
    font-size: 16px;
    font-weight: 600;
}
QLabel#rowLabel {
    min-width: 126px;
    color: #a1a1aa;
}
QLabel#rowValue {
    color: #f2f2f2;
}
QLabel#muted {
    color: #85858f;
    font-size: 13px;
}
QLabel#qrCode {
    background: #ffffff;
    border: 1px solid #2b2b30;
    color: #85858f;
    font-size: 13px;
    font-weight: 600;
}
QFrame#qrPanel {
    background: #141416;
    border: 1px solid #2b2b30;
    border-radius: 8px;
}
QFrame#dropArea {
    background: #141416;
    border: 1px dashed #454550;
    border-radius: 8px;
}
QFrame#dropArea[dragging="true"] {
    background: #211c2b;
    border: 1px solid #b98cff;
}
QLabel#dropTitle {
    color: #f2f2f2;
    font-size: 16px;
    font-weight: 600;
}
QListWidget#fileList {
    background: #19191c;
    border: 1px solid #2b2b30;
    color: #f2f2f2;
}
QListWidget#historyList {
    background: #141416;
    border: 1px solid #2b2b30;
    color: #f2f2f2;
}
QFrame#separator {
    color: #2b2b30;
    background: #2b2b30;
    max-height: 1px;
}
QPushButton {
    min-height: 40px;
    padding: 0 16px;
    border: 1px solid #7c4dff;
    border-radius: 8px;
    background: #1a181f;
    color: #a970ff;
    font-weight: 600;
}
QPushButton:hover {
    background: #211c2b;
    color: #b98cff;
    border-color: #b98cff;
}
QPushButton:disabled {
    color: #686871;
    border-color: #353540;
    background: #151518;
}
QPushButton#inlineAction {
    min-height: 32px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 500;
}
QWidget#toast {
    background: #1a181f;
    border: 1px solid #7c4dff;
    border-radius: 8px;
}
QLabel#toastLabel {
    color: #f2f2f2;
    font-size: 13px;
    padding: 0 4px;
}
QLineEdit, QSpinBox {
    min-height: 38px;
    padding: 0 10px;
    border: 1px solid #2b2b30;
    border-radius: 8px;
    background: #19191c;
    color: #f2f2f2;
}
QLineEdit:focus, QSpinBox:focus {
    border-color: #7c4dff;
}
QMessageBox {
    background: #141416;
}
QScrollArea {
    background: #0d0d0f;
    border: none;
}
QScrollBar:vertical {
    background: #0d0d0f;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2b2b30;
    border-radius: 6px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: #454550;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("DevDrop")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
