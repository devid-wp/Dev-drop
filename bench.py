"""Baseline benchmark for DevDrop transfer path.

Spawns the backend in-process on a temp session root, then uploads
synthetic files of 100 MB / 500 MB / 1 GB and records total time,
throughput, and peak resident set size (Windows: psutil if available).
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

SIZES = [100 * 1024 * 1024, 500 * 1024 * 1024, 1024 * 1024 * 1024]
PORT = 18765
CHUNK = 1024 * 1024


def start_backend() -> Path:
    session_root = Path(tempfile.mkdtemp(prefix="devdrop-bench-"))
    session_dir = session_root / "session"
    session_dir.mkdir()
    history_path = session_root / "transfer_history.json"

    backend.SESSION_DIR = session_dir
    backend.HISTORY_PATH = history_path
    backend.SERVER_PORT = PORT

    import uvicorn

    config = uvicorn.Config(backend.app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # wait for readiness
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=0.5) as r:
                if r.status == 200:
                    return session_root
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    raise RuntimeError("Backend did not start")


def upload_one(host: str, port: int, size_bytes: int) -> float:
    boundary = f"----DevDrop{os.urandom(8).hex()}"
    body_chunks = []
    body_chunks.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="bench.bin"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )

    payload = b"\x00" * CHUNK
    total = 0
    while total < size_bytes:
        remaining = size_bytes - total
        chunk = payload if remaining >= CHUNK else payload[:remaining]
        body_chunks.append(chunk)
        total += len(chunk)
    body_chunks.append(b"\r\n")
    body_chunks.append(f"--{boundary}--\r\n".encode())

    body = b"".join(body_chunks)

    req = urllib.request.Request(
        f"http://{host}:{port}/api/upload",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    start = time.perf_counter()
    with urllib.request.urlopen(req) as response:
        response.read()
    return time.perf_counter() - start


def peak_rss_mb() -> float | None:
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        return round(process.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        try:
            import ctypes
            import ctypes.wintypes  # noqa: F401

            class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
                ctypes.windll.kernel32.GetCurrentProcess(),  # type: ignore[attr-defined]
                ctypes.byref(counters),
                counters.cb,
            ):
                return round(counters.WorkingSetSize / 1024 / 1024, 1)
            return None
        except Exception:
            return None


def main() -> None:
    session_root = start_backend()
    try:
        print(f"Backend ready on port {PORT}; session_root={session_root}")
        print()
        for size in SIZES:
            elapsed = upload_one("127.0.0.1", PORT, size)
            mb = size / (1024 * 1024)
            mbps = mb / elapsed
            rss = peak_rss_mb()
            rss_str = f"{rss} MB" if rss is not None else "n/a"
            print(f"{mb:>6.0f} MB : {elapsed:6.2f}s  {mbps:7.2f} MB/s  RSS={rss_str}")
    finally:
        shutil.rmtree(session_root, ignore_errors=True)


if __name__ == "__main__":
    main()
