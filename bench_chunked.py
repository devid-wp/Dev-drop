"""Test: send a chunked upload and see if it changes throughput.

If chunked encoding makes no difference, the bottleneck is server-side
(multipart parser or write loop).
"""
import io
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import app.main as backend  # noqa: E402

PORT = 18767
CHUNK = 1024 * 1024


def start_backend() -> Path:
    root = Path(tempfile.mkdtemp(prefix="devdrop-chunked-"))
    session = root / "session"
    session.mkdir()
    backend.SESSION_DIR = session
    backend.HISTORY_PATH = root / "transfer_history.json"
    backend.SERVER_PORT = PORT
    import uvicorn

    cfg = uvicorn.Config(backend.app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=0.5):
                return root
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    raise RuntimeError("backend did not start")


def upload_chunked(size: int) -> float:
    """Stream body in 1 MiB chunks via http.client (no full-body buffering)."""
    boundary = f"----DevDrop{os.urandom(8).hex()}"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="chunked.bin"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    trailer = b"\r\n--" + boundary.encode() + b"--\r\n"

    conn = HTTPConnection("127.0.0.1", PORT)
    conn.putrequest("POST", "/api/upload")
    conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()

    def chunk(data: bytes) -> None:
        if not data:
            return
        conn.send(f"{len(data):X}\r\n".encode() + data + b"\r\n")

    t = time.perf_counter()
    chunk(header)
    remain = size
    payload = b"\x00" * CHUNK
    while remain > 0:
        take = min(CHUNK, remain)
        chunk(payload[:take])
        remain -= take
    chunk(trailer)
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return time.perf_counter() - t


def main() -> None:
    root = start_backend()
    try:
        print("Chunked upload (streaming client, no full-body buffer):")
        for size in [100 * 1024 * 1024, 500 * 1024 * 1024]:
            elapsed = upload_chunked(size)
            mb = size / (1024 * 1024)
            print(f"  {mb:>6.0f} MB : {elapsed:6.2f}s  {mb / elapsed:7.2f} MB/s")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
