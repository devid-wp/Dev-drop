import asyncio
import json
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.discovery import DiscoveryService
from app.uploads import open_unique_upload, safe_upload_name


if getattr(sys, "frozen", False):
    # Running in PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="DevDrop")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

SESSION_LIFETIME = 60 * 60
PAIRING_LIFETIME = 5 * 60

SESSION_DIR: Path | None = None
HISTORY_PATH: Path | None = None
SERVER_PORT = 8765
DISCOVERY_SERVICE: DiscoveryService | None = None
sessions: dict[str, float] = {}
pairing_code = ""
pairing_created_at = 0.0
# Incremental session counters: updated when a transfer completes, never rescanned.
_session_stats_count = 0
_session_stats_bytes = 0
_session_stats_dir: Path | None = None
# 4 MiB strikes a good balance: bigger reduces syscalls per GB, smaller
# keeps memory pressure low during multi-file transfers.
TRANSFER_COPY_BUFFER_SIZE = 4 * 1024 * 1024


class PairRequest(BaseModel):
    code: str


class TextRequest(BaseModel):
    content: str


def cleanup_expired_sessions() -> None:
    now = time.time()
    expired = [
        token
        for token, created_at in sessions.items()
        if now - created_at >= SESSION_LIFETIME
    ]

    for token in expired:
        sessions.pop(token, None)


def cli_print(message: str = "") -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        safe_message = message.encode(encoding, errors="replace").decode(encoding)
        print(safe_message)


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    sessions[token] = time.time()
    return token


def session_is_valid(token: str) -> bool:
    created_at = sessions.get(token)

    if created_at is None:
        return False

    if time.time() - created_at >= SESSION_LIFETIME:
        sessions.pop(token, None)
        return False

    return True


def generate_pairing_code() -> str:
    global pairing_code, pairing_created_at

    pairing_code = f"{secrets.randbelow(1_000_000_000):09d}"
    pairing_created_at = time.time()
    return pairing_code


def regenerate_pairing_code() -> str:
    return generate_pairing_code()


def pairing_is_valid() -> bool:
    return bool(pairing_code) and time.time() - pairing_created_at < PAIRING_LIFETIME


# Cached resolved session dir. `mkdir` + `resolve` are syscalls that used to
# run on every management poll; resolved once and reused until SESSION_DIR changes.
_resolved_session_dir: Path | None = None
_session_dir_source: Path | None = None


def require_session_dir() -> Path:
    global _resolved_session_dir, _session_dir_source

    if SESSION_DIR is None:
        raise HTTPException(
            status_code=500,
            detail="Session directory is not initialized",
        )

    if _resolved_session_dir is None or _session_dir_source != SESSION_DIR:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        _resolved_session_dir = SESSION_DIR.resolve()
        _session_dir_source = SESSION_DIR
    return _resolved_session_dir


def history_path() -> Path:
    if HISTORY_PATH is not None:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        return HISTORY_PATH
    return require_session_dir() / "transfer_history.json"


def load_transfer_history() -> list[dict[str, object]]:
    path = history_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)][-20:]


def save_transfer_history(history: list[dict[str, object]]) -> None:
    path = history_path()
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(history[-20:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def record_transfers(files: list[tuple[str, int]], sender_ip: str) -> None:
    history = load_transfer_history()
    timestamp = datetime.now(timezone.utc).isoformat()
    history.extend(
        {
            "filename": filename,
            "size": size,
            "timestamp": timestamp,
            "sender_ip": sender_ip,
        }
        for filename, size in files
    )
    save_transfer_history(history)


def initialize_session_stats(session_dir: Path) -> None:
    """Seed the in-memory session counters from the current directory contents.

    Called once at startup; subsequent updates are purely incremental.
    """
    global _session_stats_count, _session_stats_bytes, _session_stats_dir

    _session_stats_dir = session_dir
    try:
        entries = list(session_dir.iterdir())
    except OSError:
        entries = []
    count = 0
    size = 0
    for entry in entries:
        try:
            if entry.is_file():
                count += 1
                size += entry.stat().st_size
        except OSError:
            continue
    _session_stats_count = count
    _session_stats_bytes = size


def bump_session_stats(count_delta: int, bytes_delta: int) -> None:
    """Increment the in-memory session counters after a successful transfer."""
    global _session_stats_count, _session_stats_bytes

    _session_stats_count += count_delta
    _session_stats_bytes += bytes_delta


def invalidate_session_stats() -> None:
    """Drop the cached stats so the next call re-initializes from the directory."""
    global _session_stats_count, _session_stats_bytes, _session_stats_dir

    _session_stats_count = 0
    _session_stats_bytes = 0
    _session_stats_dir = None


def session_stats() -> dict[str, int]:
    """Return in-memory session counters; never scans the directory."""
    global _session_stats_dir

    session_dir = require_session_dir()
    # Lazy one-time initialization for legacy callers that set SESSION_DIR
    # directly (e.g. unit tests) without going through initialize_session_stats.
    if _session_stats_dir != session_dir:
        initialize_session_stats(session_dir)

    return {
        "received_files": _session_stats_count,
        "received_size": _session_stats_bytes,
    }


generate_pairing_code()


@app.on_event("startup")
async def start_discovery() -> None:
    global DISCOVERY_SERVICE

    if SESSION_DIR is not None:
        initialize_session_stats(SESSION_DIR)

    DISCOVERY_SERVICE = DiscoveryService(SERVER_PORT)
    DISCOVERY_SERVICE.start()


@app.on_event("shutdown")
async def stop_discovery() -> None:
    if DISCOVERY_SERVICE is not None:
        DISCOVERY_SERVICE.stop()


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "DevDrop"}


@app.get("/api/discover")
async def discover_servers():
    if DISCOVERY_SERVICE is None:
        return {"servers": []}
    return {"servers": await asyncio.to_thread(DISCOVERY_SERVICE.discover)}


@app.get("/api/status")
async def status(request: Request):
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Management endpoint is local-only")

    if not pairing_is_valid():
        generate_pairing_code()

    cleanup_expired_sessions()
    stats = session_stats()
    session_dir = require_session_dir()

    return {
        "app": "DevDrop",
        "version": "0.1.1",
        "pairing_code": pairing_code,
        "pairing_expires_in": max(0, int(PAIRING_LIFETIME - (time.time() - pairing_created_at))),
        "connected_devices": len(sessions),
        "session_path": str(session_dir),
        **stats,
    }


@app.get("/api/history")
async def transfer_history(request: Request):
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Management endpoint is local-only")
    return {"transfers": load_transfer_history()}


@app.delete("/api/history")
async def clear_transfer_history(request: Request):
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Management endpoint is local-only")
    save_transfer_history([])
    return {"success": True}


@app.get("/api/pairing-code")
async def get_pairing_code():
    if not pairing_is_valid():
        generate_pairing_code()

    return {
        "code": pairing_code,
        "expires_in": max(0, int(PAIRING_LIFETIME - (time.time() - pairing_created_at))),
    }


@app.post("/api/regenerate-pairing-code")
async def post_regenerate_pairing_code(request: Request):
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Management endpoint is local-only")

    code = regenerate_pairing_code()
    return {
        "code": code,
        "expires_in": PAIRING_LIFETIME,
    }


@app.post("/api/pair")
async def pair_device(pair: PairRequest, request: Request):
    if not pairing_is_valid():
        generate_pairing_code()
        raise HTTPException(status_code=401, detail="Pairing code expired")

    clean_code = "".join(character for character in pair.code if character.isdigit())

    if not secrets.compare_digest(clean_code, pairing_code):
        raise HTTPException(status_code=401, detail="Invalid pairing code")

    token = create_session()
    client_ip = request.client.host if request.client else "unknown"

    cli_print()
    cli_print("● Device connected")
    cli_print(f"  IP: {client_ip}")
    cli_print()
    cli_print("Waiting for transfers...")
    cli_print()

    return {"paired": True, "token": token}


@app.post("/api/text")
async def receive_text(request: TextRequest):
    session_dir = require_session_dir()
    content = request.content.strip()

    if not content:
        raise HTTPException(status_code=400, detail="Text is empty")

    number = 1
    while True:
        file_path = session_dir / f"text-{number:03}.txt"
        try:
            with file_path.open("x", encoding="utf-8") as output:
                output.write(content)
            bump_session_stats(1, len(content.encode("utf-8")))
            break
        except FileExistsError:
            number += 1

    cli_print()
    cli_print("↓ Text received")
    cli_print(f"  Saved: {file_path.name}")
    cli_print()

    return {"success": True, "filename": file_path.name}


@app.post("/api/upload")
def receive_file(request: Request, files: list[UploadFile] = File(...)):
    session_dir = require_session_dir()
    saved_files: list[str] = []
    transfer_details: list[tuple[str, int]] = []
    total_bytes = 0

    for file in files:
        filename = safe_upload_name(file.filename)
        file_path, output = open_unique_upload(session_dir, filename)

        try:
            with output:
                shutil.copyfileobj(
                    file.file,
                    output,
                    length=TRANSFER_COPY_BUFFER_SIZE,
                )
            size = file_path.stat().st_size
            total_bytes += size
            saved_files.append(file_path.name)
            transfer_details.append((file_path.name, size))
        except Exception:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not save file")

    bump_session_stats(len(saved_files), total_bytes)
    sender_ip = request.client.host if request and request.client else "unknown"
    record_transfers(transfer_details, sender_ip)

    if len(saved_files) == 1:
        cli_print(f"↓ File received: {saved_files[0]}")
    else:
        cli_print(f"↓ {len(saved_files)} files received")

    return {"success": True, "saved": saved_files}


def _is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}
