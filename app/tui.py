"""Interactive Textual terminal UI backed by DevDrop's existing local APIs."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from app.cli import CliError, _api
from app.config import DevDropConfig, load_config, save_config
from app.discovery import DiscoveryService
from app.runtime import get_local_ip
from app.transport import TLSSettings, TransportError, certificate_fingerprint


def _safe(value: object, limit: int = 240) -> str:
    return "".join(char for char in str(value) if char.isprintable())[:limit]


def _format_size(value: object) -> str:
    try:
        size = max(0, int(value))
    except (ValueError, TypeError):
        return "Unknown size"
    units = ("B", "KB", "MB", "GB", "TB")
    number = float(size)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{int(number)} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{size} B"


@dataclass
class TuiSnapshot:
    status: dict[str, Any] | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    outgoing_offers: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    pairing: dict[str, Any] | None = None
    security: dict[str, Any] | None = None
    config: DevDropConfig = field(default_factory=load_config)
    errors: dict[str, str] = field(default_factory=dict)


class SnapshotLoaded(Message):
    def __init__(self, snapshot: TuiSnapshot):
        super().__init__()
        self.snapshot = snapshot


class UiNotice(Message):
    def __init__(self, text: str, refresh: bool = False):
        super().__init__()
        self.text = text
        self.refresh = refresh


class SettingsSaved(Message):
    def __init__(self, config: DevDropConfig | None, text: str):
        super().__init__()
        self.config = config
        self.text = text


@dataclass
class BackgroundTask:
    cancelled: threading.Event
    thread: threading.Thread


class TuiServices:
    """Thin facade over existing transport, discovery, config and API helpers."""

    request_timeout = 1.5

    def snapshot(self, cancelled: Callable[[], bool] = lambda: False) -> TuiSnapshot:
        snapshot = TuiSnapshot(config=load_config())

        def request(name: str, path: str) -> dict[str, Any] | None:
            if cancelled():
                return None
            try:
                return _api("GET", path, timeout=self.request_timeout)
            except CliError as error:
                snapshot.errors[name] = str(error)
                return None

        snapshot.status = request("server", "/api/status")
        if cancelled():
            return snapshot
        try:
            local_ip = get_local_ip()
            snapshot.devices = [device for device in DiscoveryService(snapshot.config.port).discover()
                                if not (device.get("ip") == local_ip and device.get("port") == snapshot.config.port)]
        except OSError:
            snapshot.errors["devices"] = "Device discovery is unavailable on this network."
        if cancelled():
            return snapshot
        transfers = request("transfers", "/api/transfer-requests")
        if transfers is not None:
            snapshot.requests = list(transfers.get("requests", []))
        if cancelled():
            return snapshot
        offers = request("offers", "/api/outgoing-offers")
        if offers is not None:
            snapshot.outgoing_offers = list(offers.get("offers", []))
        if cancelled():
            return snapshot
        history = request("history", "/api/history")
        if history is not None:
            snapshot.history = list(history.get("transfers", []))
        if cancelled():
            return snapshot
        snapshot.pairing = request("pairing", "/api/pairing-code")
        try:
            tls = TLSSettings.load()
            snapshot.security = {
                "https": True,
                "host": tls.host,
                "address": tls.url(snapshot.config.port),
                "fingerprint": tls.fingerprint,
                "ca_fingerprint": certificate_fingerprint(tls.ca),
            }
        except (TransportError, OSError):
            snapshot.security = {"https": False}
        return snapshot

    def decide(self, identity: str, approve: bool) -> dict[str, Any]:
        action = "approve" if approve else "reject"
        return _api("POST", f"/api/transfer-requests/{identity}/{action}", {}, timeout=self.request_timeout)

    @staticmethod
    def update_config(port: int, session_root: str) -> DevDropConfig:
        config = DevDropConfig(Path(session_root).expanduser(), port)
        save_config(config)
        return config


class ConfirmDialog(ModalScreen[bool | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel", show=False)]

    CSS = """
    ConfirmDialog { align: center middle; background: $background 75%; }
    #dialog { width: 1fr; max-width: 72; max-height: 90%; border: round #a78bfa; background: #171421; padding: 1 2; }
    #dialog-copy { height: auto; min-height: 4; margin-bottom: 1; }
    #dialog-buttons { height: 3; align-horizontal: right; }
    #dialog-buttons Button { margin-left: 1; }
    """

    def __init__(self, title: str, message: str, approve_label: str = "Confirm", reject_label: str = "Cancel"):
        super().__init__()
        self.title_text = title
        self.message = message
        self.approve_label = approve_label
        self.reject_label = reject_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.title_text, classes="section-title", markup=False)
            yield Static(self.message, id="dialog-copy", markup=False)
            with Horizontal(id="dialog-buttons"):
                yield Button(self.reject_label, id="dialog-cancel")
                yield Button(self.approve_label, id="dialog-confirm", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dialog-confirm":
            self.dismiss(True)
        elif event.button.id == "dialog-cancel":
            self.dismiss(False)


class HelpDialog(ModalScreen[None]):
    CSS = """
    HelpDialog { align: center middle; background: $background 75%; }
    #help-copy { width: 1fr; max-width: 68; height: auto; border: round #a78bfa; background: #171421; padding: 1 2; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Keyboard shortcuts\n\nQ  Exit\nR  Refresh data\nD  Dashboard\nT  Transfers\nH  History\n?  Help\n\nEsc  Close dialog", id="help-copy", markup=False)

    def on_key(self, _event) -> None:
        self.dismiss(None)


class DevDropTui(App[None]):
    TITLE = "Dev-Drop"
    SUB_TITLE = "Terminal Control Center"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
        Binding("d", "show_dashboard", "Dashboard"),
        Binding("t", "show_transfers", "Transfers"),
        Binding("h", "show_history", "History"),
        Binding("question_mark", "show_help", "Help"),
    ]

    CSS = """
    Screen { background: #100e17; color: #eeeaf5; }
    Header { background: #171421; color: #eeeaf5; }
    Footer { background: #171421; color: #c4b5fd; }
    #shell { height: 1fr; }
    #sidebar { width: 22; min-width: 15; background: #171421; border-right: solid #30283e; padding: 1; }
    #brand { height: 3; color: #c4b5fd; text-style: bold; content-align: left middle; }
    .nav-button { width: 100%; height: 3; margin-bottom: 1; background: #171421; border: none; content-align: left middle; }
    .nav-button:hover, .nav-button:focus { background: #302442; color: #ddd6fe; }
    #nav-gap { height: 1fr; }
    #main-pane { width: 1fr; padding: 1 2; }
    #topline { height: 3; margin-bottom: 1; }
    #screen-title { width: 1fr; height: 3; content-align: left middle; text-style: bold; color: #f5f3ff; }
    #refresh { width: 15; background: #302442; border: round #6d4db1; }
    .page { display: none; height: 1fr; }
    .page.active { display: block; }
    .page-scroll { height: 1fr; }
    #dashboard-cards { grid-size: 2; grid-columns: 1fr 1fr; grid-rows: auto; grid-gutter: 1; height: auto; margin-bottom: 1; }
    .card { height: 7; border: round #342a45; background: #191622; padding: 1; }
    .card-label { color: #a99dbb; height: 1; }
    .card-value { color: #c4b5fd; text-style: bold; height: 2; }
    .panel { border: round #342a45; background: #171421; padding: 1; margin-bottom: 1; height: auto; }
    .section-title { color: #c4b5fd; text-style: bold; height: 1; margin-bottom: 1; }
    .muted { color: #a99dbb; }
    DataTable { height: 1fr; min-height: 8; border: round #342a45; background: #14121c; }
    #transfer-layout, #history-layout, #devices-layout { height: 1fr; }
    #transfer-table, #history-table, #devices-table { width: 2fr; }
    #outgoing-table { height: 1fr; min-height: 6; }
    #transfer-detail, #history-detail { width: 1fr; min-width: 24; border: round #342a45; background: #171421; padding: 1; margin-left: 1; }
    #transfer-detail-copy, #history-detail-copy { height: 1fr; }
    #transfer-actions { height: 3; }
    #transfer-actions Button { width: 1fr; margin-right: 1; }
    #settings-form { width: 1fr; max-width: 90; }
    .field-label { height: 1; color: #c4b5fd; margin-top: 1; }
    Input { border: round #483b5b; background: #14121c; }
    #settings-save { margin-top: 2; background: #5b3d91; }
    #security-copy { height: auto; }
    #status-line { height: 1; color: #a99dbb; margin-top: 1; }
    Screen.compact #sidebar { width: 15; min-width: 13; padding: 1 0; }
    Screen.compact #main-pane { padding: 1; }
    Screen.compact #dashboard-cards { grid-size: 1; grid-columns: 1fr; }
    Screen.compact #transfer-detail, Screen.compact #history-detail { min-width: 18; }
    Screen.tiny #sidebar { width: 12; min-width: 11; }
    Screen.tiny #transfer-detail, Screen.tiny #history-detail { display: none; }
    Screen.tiny #transfer-table, Screen.tiny #history-table, Screen.tiny #outgoing-table { width: 1fr; }
    Screen.tiny #refresh { width: 12; }
    """

    def __init__(self, services: TuiServices | None = None):
        super().__init__()
        self.services = services or TuiServices()
        self.snapshot_data = TuiSnapshot()
        self.current_page = "dashboard"
        self.selected_request: dict[str, Any] | None = None
        self.selected_history: dict[str, Any] | None = None
        self._tasks: dict[str, BackgroundTask] = {}
        self._tasks_lock = threading.Lock()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static("DEV-DROP", id="brand", markup=False)
                yield Button("▦  Dashboard", id="nav-dashboard", classes="nav-button")
                yield Button("⌕  Devices", id="nav-devices", classes="nav-button")
                yield Button("⇄  Transfers", id="nav-transfers", classes="nav-button")
                yield Button("◷  History", id="nav-history", classes="nav-button")
                yield Button("◆  Security", id="nav-security", classes="nav-button")
                yield Button("⚙  Settings", id="nav-settings", classes="nav-button")
                yield Static("", id="nav-gap")
                yield Static("Q exit · R refresh", classes="muted", markup=False)
            with Vertical(id="main-pane"):
                with Horizontal(id="topline"):
                    yield Static("Dashboard", id="screen-title", markup=False)
                    yield Button("Refresh  R", id="refresh")
                with VerticalScroll(id="page-dashboard", classes="page active"):
                    with Grid(id="dashboard-cards"):
                        yield self._card("Local server", "Checking…", "server")
                        yield self._card("Discovered devices", "Checking…", "devices")
                        yield self._card("Pending approval", "Checking…", "pending")
                        yield self._card("Active transfers", "Not exposed", "active")
                    with Vertical(classes="panel"):
                        yield Static("Latest events", classes="section-title", markup=False)
                        yield Static("Loading activity…", id="dashboard-events", markup=False)
                with Vertical(id="page-devices", classes="page"):
                    yield Static("Devices found on the local network", classes="section-title", markup=False)
                    yield DataTable(id="devices-table", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="devices-empty", classes="muted", markup=False)
                with Vertical(id="page-transfers", classes="page"):
                    yield Static("Each request waits for a decision from you.", classes="muted", markup=False)
                    with Horizontal(id="transfer-layout"):
                        yield DataTable(id="transfer-table", cursor_type="row", zebra_stripes=True)
                        with Vertical(id="transfer-detail"):
                            yield Static("Select a request to inspect it.", id="transfer-detail-copy", markup=False)
                            with Horizontal(id="transfer-actions"):
                                yield Button("Approve", id="approve-transfer", variant="success", disabled=True)
                                yield Button("Reject", id="reject-transfer", variant="error", disabled=True)
                    yield Static("", id="transfer-empty", classes="muted", markup=False)
                    yield Static("Outgoing PC-to-phone offers show server-reported bytes. Incoming upload progress is not exposed by the backend.", classes="muted", markup=False)
                    yield Static("Outgoing offers", classes="section-title", markup=False)
                    yield DataTable(id="outgoing-table", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="outgoing-empty", classes="muted", markup=False)
                with Vertical(id="page-history", classes="page"):
                    with Horizontal(id="history-layout"):
                        yield DataTable(id="history-table", cursor_type="row", zebra_stripes=True)
                        with Vertical(id="history-detail"):
                            yield Static("Select a saved transfer to inspect details.", id="history-detail-copy", markup=False)
                    yield Static("", id="history-empty", classes="muted", markup=False)
                with VerticalScroll(id="page-security", classes="page"):
                    yield Static("Pairing and transport", classes="section-title", markup=False)
                    yield Static("Loading security state…", id="security-copy", classes="panel", markup=False)
                with VerticalScroll(id="page-settings", classes="page"):
                    with Vertical(id="settings-form", classes="panel"):
                        yield Static("Safe local settings", classes="section-title", markup=False)
                        yield Static("These settings change the port and session folder used by the next server start.", classes="muted", markup=False)
                        yield Static("HTTPS port", classes="field-label", markup=False)
                        yield Input(placeholder="8765", id="settings-port", type="integer")
                        yield Static("Session folder root", classes="field-label", markup=False)
                        yield Input(placeholder="~/DevDrop", id="settings-root")
                        yield Button("Review changes", id="settings-save", variant="primary")
                        yield Static("", id="settings-message", classes="muted", markup=False)
                yield Static("", id="status-line", markup=False)
        yield Footer()

    @staticmethod
    def _card(label: str, value: str, identity: str) -> Vertical:
        return Vertical(Static(label, classes="card-label", markup=False),
                       Static(value, id=f"card-{identity}", classes="card-value", markup=False),
                       classes="card")

    def on_mount(self) -> None:
        self._apply_responsive_layout(self.size.width)
        for table_id, columns in (
            ("devices-table", ("Device", "HTTPS address", "Status")),
            ("transfer-table", ("Sender", "Request", "Files", "Size", "State")),
            ("outgoing-table", ("Direction", "Recipient ID", "File", "Server bytes sent", "State")),
            ("history-table", ("Time", "Direction", "File", "Size", "Status")),
        ):
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_columns(*columns)
        self._apply_config_inputs()
        self.refresh_data()

    def on_resize(self, event) -> None:
        self._apply_responsive_layout(event.size.width)

    def _apply_responsive_layout(self, width: int) -> None:
        self.set_class(width < 82, "compact")
        self.set_class(width < 62, "tiny")

    def on_unmount(self) -> None:
        self._stop_background_tasks()

    async def action_quit(self) -> None:
        self._stop_background_tasks()
        self.exit()

    def action_refresh_data(self) -> None:
        self.refresh_data()

    def action_show_dashboard(self) -> None:
        self.show_page("dashboard")

    def action_show_transfers(self) -> None:
        self.show_page("transfers")

    def action_show_history(self) -> None:
        self.show_page("history")

    def action_show_help(self) -> None:
        self.push_screen(HelpDialog())

    def show_page(self, page: str) -> None:
        if page not in {"dashboard", "devices", "transfers", "history", "security", "settings"}:
            return
        self.current_page = page
        for name in ("dashboard", "devices", "transfers", "history", "security", "settings"):
            self.query_one(f"#page-{name}").set_class(name == page, "active")
        self.query_one("#screen-title", Static).update(page.title())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        identity = event.button.id or ""
        if identity.startswith("nav-"):
            self.show_page(identity.removeprefix("nav-"))
        elif identity == "refresh":
            self.refresh_data()
        elif identity == "approve-transfer":
            self._confirm_transfer(True)
        elif identity == "reject-transfer":
            self._confirm_transfer(False)
        elif identity == "settings-save":
            self._confirm_settings()

    def refresh_data(self) -> None:
        def load(cancelled: threading.Event) -> None:
            try:
                data = self.services.snapshot(cancelled.is_set)
                if not cancelled.is_set():
                    self.post_message(SnapshotLoaded(data))
            except Exception:
                if not cancelled.is_set():
                    self.post_message(UiNotice("Could not load DevDrop state."))
        self._start_background("refresh", load)

    def _start_background(self, name: str, operation: Callable[[threading.Event], None]) -> None:
        self._cancel_task(name, wait=False)
        cancelled = threading.Event()

        def run() -> None:
            try:
                operation(cancelled)
            finally:
                with self._tasks_lock:
                    current = self._tasks.get(name)
                    if current is not None and current.cancelled is cancelled:
                        self._tasks.pop(name, None)

        thread = threading.Thread(target=run, name=f"devdrop-tui-{name}", daemon=True)
        with self._tasks_lock:
            self._tasks[name] = BackgroundTask(cancelled, thread)
        thread.start()

    def _cancel_task(self, name: str, wait: bool = True) -> None:
        with self._tasks_lock:
            task = self._tasks.get(name)
            if task is not None:
                task.cancelled.set()
        if task is not None and wait and task.thread is not threading.current_thread():
            task.thread.join(timeout=2.0)

    def _stop_background_tasks(self) -> None:
        with self._tasks_lock:
            tasks = list(self._tasks.values())
            for task in tasks:
                task.cancelled.set()
        for task in tasks:
            if task.thread is not threading.current_thread():
                task.thread.join(timeout=2.0)

    def _show_connection_error(self, message: str) -> None:
        self.query_one("#status-line", Static).update(message)

    def on_snapshot_loaded(self, message: SnapshotLoaded) -> None:
        self._apply_snapshot(message.snapshot)

    def on_ui_notice(self, message: UiNotice) -> None:
        self._show_connection_error(_safe(message.text))
        if message.refresh:
            self.refresh_data()

    def on_settings_saved(self, message: SettingsSaved) -> None:
        self._settings_done(message.config, message.text)

    def _apply_config_inputs(self) -> None:
        config = self.snapshot_data.config
        self.query_one("#settings-port", Input).value = str(config.port)
        self.query_one("#settings-root", Input).value = str(config.session_root)

    def _apply_snapshot(self, data: TuiSnapshot) -> None:
        self.snapshot_data = data
        self._fill_devices()
        self._fill_transfers()
        self._fill_outgoing_offers()
        self._fill_history()
        self._render_dashboard()
        self._render_security()
        self._apply_config_inputs()
        error = next(iter(data.errors.values()), "")
        self.query_one("#status-line", Static).update(_safe(error) if error else "Connected to local DevDrop controls · Data refreshed")

    def _render_dashboard(self) -> None:
        data = self.snapshot_data
        server = data.status
        address = (data.security or {}).get("address", f"https://127.0.0.1:{data.config.port}")
        self.query_one("#card-server", Static).update(f"Online · HTTPS\n{address}" if server else "Unavailable")
        self.query_one("#card-devices", Static).update("Unavailable" if "devices" in data.errors else str(len(data.devices)))
        self.query_one("#card-pending", Static).update("Unavailable" if "transfers" in data.errors else str(len(data.requests)))
        active_offers = [offer for offer in data.outgoing_offers if offer.get("status") in {"preparing", "pending", "accepted", "streaming"}]
        self.query_one("#card-active", Static).update("Unavailable" if "offers" in data.errors else f"{len(active_offers)} PC → phone")
        events: list[str] = []
        if data.requests:
            for request in data.requests[:3]:
                files = request.get("files") or []
                names = ", ".join(_safe(item.get("name", "file"), 60) for item in files) or _safe(request.get("description", "Transfer"))
                events.append(f"Waiting for approval · {_safe(request.get('sender', 'sender'), 50)} · {names}")
        for row in reversed(data.history[-3:]):
            events.append(f"Saved · {_safe(row.get('filename', 'file'), 80)} · {_format_size(row.get('size'))}")
        for offer in data.outgoing_offers[:2]:
            if offer.get("status") in {"pending", "accepted", "streaming"}:
                sent = _format_size(offer.get("sent_bytes"))
                events.append(f"PC → phone · {_safe(offer.get('filename', 'file'), 70)} · {sent} sent")
        empty_text = "Activity unavailable; refresh to retry." if "history" in data.errors and "transfers" in data.errors else "No transfer activity is recorded yet."
        self.query_one("#dashboard-events", Static).update("\n".join(events[:5]) or empty_text)

    def _fill_devices(self) -> None:
        table = self.query_one("#devices-table", DataTable)
        table.clear()
        for device in self.snapshot_data.devices:
            table.add_row(Text(_safe(device.get("name", "DevDrop"))),
                          Text(_safe(device.get("url", ""))), Text(_safe(device.get("status", "Available"))))
        empty_text = self.snapshot_data.errors.get("devices", "No other DevDrop devices were discovered.")
        self.query_one("#devices-empty", Static).update(empty_text if not self.snapshot_data.devices else "")

    def _fill_transfers(self) -> None:
        table = self.query_one("#transfer-table", DataTable)
        table.clear()
        for request in self.snapshot_data.requests:
            files = request.get("files") or []
            summary = ", ".join(_safe(item.get("name", "file"), 40) for item in files) or _safe(request.get("description", "File transfer"), 60)
            table.add_row(Text(_safe(request.get("sender", "Unknown sender"), 60)), Text(summary),
                          str(len(files)), _format_size(request.get("size")), _safe(request.get("status", "pending")),
                          key=str(request.get("id", "")))
        empty_text = self.snapshot_data.errors.get("transfers", "No pending transfer requests.")
        self.query_one("#transfer-empty", Static).update(empty_text if not self.snapshot_data.requests else "")
        if self.selected_request and not any(str(row.get("id")) == str(self.selected_request.get("id")) for row in self.snapshot_data.requests):
            self.selected_request = None
            self._render_transfer_detail()

    def _fill_outgoing_offers(self) -> None:
        table = self.query_one("#outgoing-table", DataTable)
        table.clear()
        for offer in self.snapshot_data.outgoing_offers:
            sent = max(0, int(offer.get("sent_bytes") or 0))
            total = max(0, int(offer.get("size") or 0))
            table.add_row(Text("PC → phone"), Text(_safe(offer.get("recipient_id", "unknown"), 16)),
                          Text(_safe(offer.get("filename", "file"), 80)),
                          f"{_format_size(sent)} / {_format_size(total)}",
                          Text(_safe(offer.get("status", "unknown"))), key=str(offer.get("id", "")))
        empty_text = self.snapshot_data.errors.get("offers", "No outgoing offers.")
        self.query_one("#outgoing-empty", Static).update(empty_text if not self.snapshot_data.outgoing_offers else "")

    def _fill_history(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()
        for index, row in enumerate(reversed(self.snapshot_data.history)):
            table.add_row(Text(_safe(row.get("timestamp", "Unknown time"), 36)), Text("Received"),
                          Text(_safe(row.get("filename", "file"), 70)), _format_size(row.get("size")),
                          Text("Saved"), key=f"history-{index}")
        empty_text = self.snapshot_data.errors.get("history", "No saved transfers in history.")
        self.query_one("#history-empty", Static).update(empty_text if not self.snapshot_data.history else "")
        if self.selected_history and not any(row.get("filename") == self.selected_history.get("filename") and row.get("timestamp") == self.selected_history.get("timestamp") for row in self.snapshot_data.history):
            self.selected_history = None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "transfer-table":
            key = str(event.row_key.value)
            self.selected_request = next((item for item in self.snapshot_data.requests if str(item.get("id")) == key), None)
            self._render_transfer_detail()
        elif event.data_table.id == "history-table":
            try:
                index = int(str(event.row_key.value).removeprefix("history-"))
                records = list(reversed(self.snapshot_data.history))
                self.selected_history = records[index]
            except (ValueError, IndexError):
                self.selected_history = None
            self._render_history_detail()

    def _render_transfer_detail(self) -> None:
        request = self.selected_request
        copy = self.query_one("#transfer-detail-copy", Static)
        if request is None:
            copy.update("Select a request to inspect it.")
            self.query_one("#approve-transfer", Button).disabled = True
            self.query_one("#reject-transfer", Button).disabled = True
            return
        files = request.get("files") or []
        details = [f"Sender claim: {_safe(request.get('sender', 'Unknown sender'), 100)}",
                   f"Description: {_safe(request.get('description', 'File transfer'))}",
                   f"Total size: {_format_size(request.get('size'))}",
                   f"State: {_safe(request.get('status', 'pending'))}", "", "Files:"]
        details.extend(f"• {_safe(item.get('name', 'file'), 120)} — {_format_size(item.get('size'))}" for item in files)
        details.extend(["", "Sender details are unverified claims."])
        copy.update("\n".join(details))
        self.query_one("#approve-transfer", Button).disabled = request.get("status") != "pending"
        self.query_one("#reject-transfer", Button).disabled = request.get("status") != "pending"

    def _render_history_detail(self) -> None:
        row = self.selected_history
        text = "Select a saved transfer to inspect details." if row is None else (
            f"Direction: Received\nStatus: Saved\nFile: {_safe(row.get('filename', 'file'), 160)}\n"
            f"Size: {_format_size(row.get('size'))}\nTime: {_safe(row.get('timestamp', 'Unknown time'), 80)}\n"
            f"Sender address: {_safe(row.get('sender_ip', 'Unknown'), 80)}")
        self.query_one("#history-detail-copy", Static).update(text)

    def _render_security(self) -> None:
        data = self.snapshot_data
        pairing = data.pairing
        security = data.security or {"https": False}
        if security.get("https"):
            tls_state = (f"HTTPS: Configured\nTLS host: {_safe(security.get('host', 'unknown'), 120)}\n"
                         f"Server certificate SHA-256: {security.get('fingerprint', 'unknown')}\n"
                         f"CA certificate SHA-256: {security.get('ca_fingerprint', 'unknown')}")
        else:
            tls_state = "HTTPS: Not configured or certificate validation failed. HTTP fallback is disabled."
        if pairing:
            code = str(pairing.get("code", ""))
            formatted = f"{code[:3]} {code[3:6]} {code[6:]}" if len(code) == 9 else "Unavailable"
            code_line = f"Local pairing code: {formatted}\nExpires in: {pairing.get('expires_in', 0)} seconds"
        else:
            code_line = "Local pairing code unavailable; verify that the local server is running."
        self.query_one("#security-copy", Static).update(f"{code_line}\n\n{tls_state}\n\nTransfers still require explicit one-use owner approval.")

    def _confirm_transfer(self, approve: bool) -> None:
        request = self.selected_request
        if request is None or request.get("status") != "pending":
            return
        names = "\n".join(f"• {_safe(item.get('name', 'file'), 140)} — {_format_size(item.get('size'))}" for item in request.get("files", []))
        title = "Approve this transfer?" if approve else "Reject this transfer?"
        message = (f"Sender claim: {_safe(request.get('sender', 'Unknown sender'), 100)}\n"
                   f"Total size: {_format_size(request.get('size'))}\n{names}\n\n"
                   "Sender information is unverified. This decision applies once to this request.")
        self.push_screen(ConfirmDialog(title, message, "Approve" if approve else "Reject", "Cancel"),
                         lambda confirmed: self._start_decision(request, approve) if confirmed else None)

    def _start_decision(self, request: dict[str, Any], approve: bool) -> None:
        identity = str(request.get("id", ""))

        def decide(cancelled: threading.Event) -> None:
            try:
                self.services.decide(identity, approve)
                if not cancelled.is_set():
                    self.post_message(UiNotice("Request approved." if approve else "Request rejected.", refresh=True))
            except CliError as error:
                if not cancelled.is_set():
                    self.post_message(UiNotice(str(error), refresh=True))
        self._start_background("decision", decide)

    def _confirm_settings(self) -> None:
        port_text = self.query_one("#settings-port", Input).value.strip()
        root = self.query_one("#settings-root", Input).value.strip()
        try:
            port = int(port_text)
            if not 1 <= port <= 65535 or not root:
                raise ValueError
        except ValueError:
            self.query_one("#settings-message", Static).update("Enter a port from 1 to 65535 and a session folder.")
            return
        message = f"Apply these settings for the next server start?\n\nPort: {port}\nSession root: {root}"
        self.push_screen(ConfirmDialog("Review settings change", message, "Save settings", "Cancel"),
                         lambda confirmed: self._settings_worker(port, root) if confirmed else None)

    def _settings_worker(self, port: int, root: str) -> None:
        def save(cancelled: threading.Event) -> None:
            try:
                config = self.services.update_config(port, root)
                if not cancelled.is_set():
                    self.post_message(SettingsSaved(config, "Settings saved."))
            except (OSError, ValueError) as error:
                if not cancelled.is_set():
                    self.post_message(SettingsSaved(None, _safe(error)))
        self._start_background("settings", save)

    def _settings_done(self, config: DevDropConfig | None, message: str) -> None:
        self.query_one("#settings-message", Static).update(_safe(message))
        if config is not None:
            self.snapshot_data.config = config
            self._apply_config_inputs()


def run_tui() -> int:
    DevDropTui().run()
    return 0
