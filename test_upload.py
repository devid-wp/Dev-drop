#!/usr/bin/env python3
"""Integration tests for the DevDrop upload path.

Spawns the backend in-process on an ephemeral port with a throwaway session
root, then exercises single, multi, large and duplicate-filename uploads over
real HTTP (multipart). Uses http.client so large files stream chunked instead
of buffering the whole body in memory.
"""
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

import uvicorn  # noqa: E402

import app.main as backend  # noqa: E402

PORT = 18771
TOKEN = ""
BOUNDARY_TAG = "----DevDropTests"
_SERVER: uvicorn.Server | None = None


def _start_server() -> None:
    global _SERVER
    backend.SERVER_PORT = PORT
    cfg = uvicorn.Config(backend.app, host="127.0.0.1", port=PORT, log_level="error")
    _SERVER = uvicorn.Server(cfg)
    threading.Thread(target=_SERVER.run, daemon=True).start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=0.3):
                return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.05)
    raise RuntimeError("backend did not start")


def _stop_server() -> None:
    if _SERVER is not None:
        _SERVER.should_exit = True


def _post(body: bytes, content_type: str) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", PORT)
    try:
        conn.request("POST", "/api/upload", body=body, headers={"Content-Type": content_type, "Authorization": f"Bearer {TOKEN}"})
        resp = conn.getresponse()
        payload = resp.read().decode("utf-8")
        import json

        return resp.status, json.loads(payload)
    finally:
        conn.close()


def _multipart_body(files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """Build a single-shot multipart body from (filename, content) pairs."""
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

    conn = http.client.HTTPConnection("127.0.0.1", PORT)
    conn.putrequest("POST", "/api/upload")
    conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.putheader("Authorization", f"Bearer {TOKEN}")
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