"""Diagnostic: measure where time is spent in the upload path.

Splits the work into (1) request body download, (2) multipart parsing,
(3) disk write. Helps decide which optimization actually helps.
"""
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import app.main as backend  # noqa: E402

PORT = 18766
CHUNK = 1024 * 1024
SIZES = [100 * 1024 * 1024, 500 * 1024 * 1024, 1024 * 1024 * 1024]


def start_backend() -> Path:
    root = Path(tempfile.mkdtemp(prefix="devdrop-diag-"))
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


def upload(host: str, port: int, size: int) -> float:
    boundary = f"----DevDrop{os.urandom(8).hex()}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="x.bin"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    pad = b"\x00" * CHUNK
    remain = size
    while remain > 0:
        take = min(CHUNK, remain)
        body += pad[:take]
        remain -= take
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"http://{host}:{port}/api/upload",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    t = time.perf_counter()
    with urllib.request.urlopen(req) as resp:
        resp.read()
    return time.perf_counter() - t


def disk_write_only(path: Path, size: int) -> float:
    """Sequential disk write speed into the session dir, same as receive_file does."""
    payload = b"\x00" * CHUNK
    t = time.perf_counter()
    with path.open("wb") as f:
        remain = size
        while remain > 0:
            take = min(CHUNK, remain)
            f.write(payload[:take])
            remain -= take
    return time.perf_counter() - t


def main() -> None:
    root = start_backend()
    try:
        session_dir = root / "session"
        print("Disk-only sequential write speeds:")
        for size in SIZES:
            target = session_dir / "disk-bench.bin"
            elapsed = disk_write_only(target, size)
            mb = size / (1024 * 1024)
            print(f"  {mb:>6.0f} MB : {elapsed:6.2f}s  {mb / elapsed:7.2f} MB/s")
            target.unlink(missing_ok=True)

        print()
        print("End-to-end /api/upload (multipart + disk):")
        for size in SIZES:
            elapsed = upload("127.0.0.1", PORT, size)
            mb = size / (1024 * 1024)
            print(f"  {mb:>6.0f} MB : {elapsed:6.2f}s  {mb / elapsed:7.2f} MB/s")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
