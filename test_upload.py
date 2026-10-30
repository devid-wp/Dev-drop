#!/usr/bin/env python3
"""Integration tests for the DevDrop upload path.

Spawns the backend in-process on an ephemeral port with a throwaway session
root, then exercises single, multi, large and duplicate-filename uploads over
real HTTP (multipart). Uses http.client so large files stream chunked instead
of buffering the whole body in memory.
"""
import hashlib
import http.client
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch
from app.transport import TLSSettings, open_local
from tls_test_support import make_pki, PASSWORD

import uvicorn  # noqa: E402

import app.main as backend  # noqa: E402

PORT = 18771
TOKEN = ""
TRANSFER_ID = ""
BOUNDARY_TAG = "----DevDropTests"
_SERVER: uvicorn.Server | None = None


def _start_server() -> None:
    global _SERVER
    backend.SERVER_PORT = PORT
    cfg = uvicorn.Config(backend.app, host="127.0.0.1", port=PORT, log_level="error", proxy_headers=False,
                         **TLSSettings.load().server_options(PASSWORD))
    _SERVER = uvicorn.Server(cfg)
    threading.Thread(target=_SERVER.run, daemon=True).start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with open_local(urllib.request.Request(f"https://127.0.0.1:{PORT}/api/health"), timeout=0.3):
                return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.05)
    raise RuntimeError("backend did not start")


def _stop_server() -> None:
    if _SERVER is not None:
        _SERVER.should_exit = True


def _post(body: bytes, content_type: str) -> tuple[int, dict]:
    conn = TLSSettings.load().connection(PORT)
    try:
        conn.request("POST", "/api/upload", body=body, headers={"Content-Type": content_type, "Authorization": f"Bearer {TOKEN}", "X-Transfer-ID": TRANSFER_ID})
        resp = conn.getresponse()
        payload = resp.read().decode("utf-8")
        import json

        return resp.status, json.loads(payload)
    finally:
        conn.close()


def _multipart_body(files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """Build a single-shot multipart body from (filename, content) pairs."""
    global TRANSFER_ID
    from app.transfer_requests import TransferDescription
    manifest = [{"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files]
    transfer = backend.transfer_service.create(TOKEN, TransferDescription(
        type="file", sender="test", description="upload test", files=manifest))
    backend.transfer_service.decide(transfer["id"], True)
    TRANSFER_ID = transfer["id"]
    boundary = f"{BOUNDARY_TAG}{os.urandom(4).hex()}"
    parts = []
    for name, data in files:
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _chunked_upload(filename: str, size_bytes: int, chunk_size: int = 1024 * 1024) -> int:
    """Stream a large file via Transfer-Encoding: chunked (mirrors the GUI)."""
    boundary = f"{BOUNDARY_TAG}{os.urandom(4).hex()}"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    trailer = b"\r\n--" + boundary.encode() + b"--\r\n"

    from app.transfer_requests import TransferDescription
    transfer = backend.transfer_service.create(TOKEN, TransferDescription(
        type="file", sender="test", description="large upload", files=[{
            "name": filename, "size": size_bytes, "sha256": hashlib.sha256(b"\x00" * size_bytes).hexdigest()}]))
    backend.transfer_service.decide(transfer["id"], True)
    conn = TLSSettings.load().connection(PORT)
    conn.putrequest("POST", "/api/upload")
    conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.putheader("Authorization", f"Bearer {TOKEN}")
    conn.putheader("X-Transfer-ID", transfer["id"])
    conn.endheaders()

    def send(data: bytes) -> None:
        if data:
            conn.send(f"{len(data):X}\r\n".encode() + data + b"\r\n")

    send(header)
    payload = b"\x00" * chunk_size
    remaining = size_bytes
    while remaining > 0:
        take = min(chunk_size, remaining)
        send(payload[:take])
        remaining -= take
    send(trailer)
    # Terminating zero-length chunk: without it the server never finishes
    # reading the request body and the response never arrives.
    conn.send(b"0\r\n\r\n")

    resp = conn.getresponse()
    resp.read()
    status = resp.status
    conn.close()
    return status


class UploadIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tls_directory = tempfile.TemporaryDirectory(prefix="devdrop-tls-test-")
        cls.addClassCleanup(tls_directory.cleanup)
        config = make_pki(Path(tls_directory.name))
        tls_patch = patch.dict(os.environ, {"DEVDROP_TLS_CONFIG": str(config)})
        tls_patch.start()
        cls.addClassCleanup(tls_patch.stop)
        global TOKEN
        TOKEN = backend.create_session()
        cls.addClassCleanup(backend.sessions.pop, TOKEN, None)
        cls.root = Path(tempfile.mkdtemp(prefix="devdrop-test-"))
        cls.session = cls.root / "session"
        cls.session.mkdir()
        backend.SESSION_DIR = cls.session
        backend.HISTORY_PATH = cls.root / "transfer_history.json"
        backend.invalidate_session_stats()
        backend.initialize_session_stats(cls.session)
        _start_server()

    @classmethod
    def tearDownClass(cls) -> None:
        _stop_server()
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self) -> None:
        self.base_files = backend._session_stats_count
        self.base_bytes = backend._session_stats_bytes
        self.base_dir_count = len([p for p in self.session.iterdir() if p.is_file()])

    def _stats_delta(self) -> tuple[int, int]:
        return (
            backend._session_stats_count - self.base_files,
            backend._session_stats_bytes - self.base_bytes,
        )

    def test_single_file_upload(self) -> None:
        body, ctype = _multipart_body([("single.txt", b"hello world")])
        status, payload = _post(body, ctype)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["saved"], ["single.txt"])
        self.assertTrue((self.session / "single.txt").read_bytes() == b"hello world")
        self.assertEqual(self._stats_delta(), (1, 11))

    def test_multiple_files_upload(self) -> None:
        body, ctype = _multipart_body([("a.txt", b"aaa"), ("b.txt", b"bbbb"), ("c.txt", b"ccccc")])
        status, payload = _post(body, ctype)
        self.assertEqual(status, 200)
        self.assertEqual(sorted(payload["saved"]), ["a.txt", "b.txt", "c.txt"])
        self.assertEqual(self._stats_delta(), (3, 12))

    def test_duplicate_filenames_get_unique_suffix(self) -> None:
        body, ctype = _multipart_body([("dup.txt", b"one"), ("dup.txt", b"two")])
        status, payload = _post(body, ctype)
        self.assertEqual(status, 200)
        self.assertEqual(sorted(payload["saved"]), ["dup (1).txt", "dup.txt"])

    def test_upload_permission_cannot_be_missing_replayed_or_substituted(self) -> None:
        global TRANSFER_ID, TOKEN
        body, ctype = _multipart_body([("secure.txt", b"hello")])
        identity = TRANSFER_ID
        TRANSFER_ID = ""
        self.assertEqual(_post(body, ctype)[0], 409)
        self.assertFalse((self.session / "secure.txt").exists())
        TRANSFER_ID = identity
        self.assertEqual(_post(body.replace(b"hello", b"other"), ctype)[0], 409)
        self.assertFalse((self.session / "secure.txt").exists())
        owner_token = TOKEN
        TOKEN = backend.create_session()
        try:
            self.assertEqual(_post(body, ctype)[0], 409)
        finally:
            backend.sessions.pop(TOKEN, None)
            TOKEN = owner_token
        self.assertEqual(_post(body, ctype)[0], 200)
        self.assertEqual(_post(body, ctype)[0], 409)
        self.assertFalse((self.session / "secure (1).txt").exists())

    def test_upload_pending_rejected_and_expired_permissions(self) -> None:
        global TRANSFER_ID
        from app.transfer_requests import TransferDescription
        from unittest.mock import patch
        for decision in ("pending", "rejected", "expired"):
            body, ctype = _multipart_body([("unapproved.txt", b"hello")])
            transfer = backend.transfer_service.create(TOKEN, TransferDescription(
                type="file", sender="test", description="unapproved", files=[{
                    "name": "unapproved.txt", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest()}]))
            TRANSFER_ID = transfer["id"]
            if decision == "rejected":
                backend.transfer_service.decide(TRANSFER_ID, False)
            if decision == "expired":
                with patch.object(backend.transfer_service, "clock", return_value=transfer["expires_at"] + 1):
                    self.assertEqual(_post(body, ctype)[0], 409)
            else:
                self.assertEqual(_post(body, ctype)[0], 409)
            self.assertFalse((self.session / "unapproved.txt").exists())

    def test_gui_upload_with_unicode_filename_requires_approval(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from devdrop_gui import BackendClient, FileDropArea
        from app.transfer_requests import TransferDescription
        source = self.root / "пример.txt"
        source.write_bytes(b"GUI data")
        decisions = []
        def approve(client, files, token):
            transfer = backend.transfer_service.create(token, TransferDescription(
                type="file", sender="GUI test", description="unicode file", files=[{
                    "name": source.name, "size": 8, "sha256": hashlib.sha256(b"GUI data").hexdigest()}]))
            decisions.append(transfer["id"])
            backend.transfer_service.decide(transfer["id"], True)
            return transfer["id"]
        sender = SimpleNamespace(_send_chunk=FileDropArea._send_chunk)
        with patch.object(BackendClient, "await_approval", autospec=True, side_effect=approve):
            saved = FileDropArea._upload_files(sender, [source], PORT)
        self.assertEqual(saved, [source.name])
        self.assertEqual((self.session / source.name).read_bytes(), b"GUI data")
        self.assertEqual(len(decisions), 1)

    def test_large_file_streams_without_crash(self) -> None:
        size = 16 * 1024 * 1024
        status = _chunked_upload("large.bin", size)
        self.assertEqual(status, 200)
        self.assertEqual((self.session / "large.bin").stat().st_size, size)
        self.assertEqual(self._stats_delta()[0], 1)

    def test_dangerous_filename_is_sanitized(self) -> None:
        body, ctype = _multipart_body([("../../evil.txt", b"x")])
        status, payload = _post(body, ctype)
        self.assertEqual(status, 200)
        # Path separators are stripped to the basename; the file lands inside
        # the session dir, never outside it.
        self.assertEqual(payload["saved"], ["evil.txt"])
        self.assertTrue((self.session / "evil.txt").read_bytes() == b"x")
        self.assertFalse((self.session.parent / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()