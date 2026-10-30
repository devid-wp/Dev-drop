import hashlib
import asyncio
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal
from urllib.parse import urlsplit
from app.transfer_requests import TransferDescription, TransferError, TransferService

from app.history_store import HistoryStore, HistoryStoreError
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
transfer_service = TransferService()
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
    type: Literal["text", "link"] = "text"


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
        return HISTORY_PATH
    return require_session_dir() / "transfer_history.json"


def history_store() -> HistoryStore:
    legacy = history_path()
    return HistoryStore(legacy.with_suffix(".sqlite3"), legacy)


def load_transfer_history() -> list[dict[str, object]]:
    return history_store().read()


def save_transfer_history(history: list[dict[str, object]]) -> None:
    history_store().replace(history[-20:])


def record_transfers(files: list[tuple[str, int]], sender_ip: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    history_store().append([
        {"filename": filename, "size": size, "timestamp": timestamp, "sender_ip": sender_ip}
        for filename, size in files
    ])


@app.exception_handler(HistoryStoreError)
async def history_unavailable(request: Request, error: HistoryStoreError):
    return JSONResponse(status_code=503, content={"detail": "Transfer history is unavailable"})


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
async def get_pairing_code(request: Request):
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Management endpoint is local-only")
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


async def require_transfer_session(request: Request) -> str:
    """Require an existing session for every sender, including loopback clients."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or not session_is_valid(token):
        raise HTTPException(
            status_code=401, detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


@app.middleware("http")
async def gate_transfer_body(request: Request, call_next):
    if request.scope.get("scheme") != "https":
        return JSONResponse(status_code=426, content={"detail": "HTTPS is required; HTTP is disabled"})
    # Reject before FastAPI parses/spools a multipart body. Actual content and
    # atomic one-use consumption are still checked in the receive handlers.
    if request.method == "POST" and request.url.path.rstrip("/") in {"/api/text", "/api/upload"}:
        try:
            token = await require_transfer_session(request)
            transfer_service.check_approved(request.headers.get("X-Transfer-ID", ""), token)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers=error.headers)
        except TransferError as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
    return await call_next(request)


@app.exception_handler(TransferError)
async def transfer_error(request: Request, error: TransferError):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.post("/api/transfer-requests")
async def create_transfer(description: TransferDescription, token: str = Depends(require_transfer_session)):
    return transfer_service.create(token, description)


def require_local_owner(request: Request):
    # Only the direct loopback connection is authoritative. Block browser
    # cross-origin submissions and DNS rebinding for these decision endpoints.
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Management endpoint is local-only")
    for value in (request.headers.get("origin"), request.headers.get("host")):
        if not value:
            continue
        try:
            host = urlsplit(value if "://" in value else "http://" + value).hostname
        except ValueError:
            host = None
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=403, detail="Local owner origin required")


@app.get("/api/transfer-requests")
async def pending_transfers(request: Request):
    require_local_owner(request)
    return {"requests": transfer_service.pending()}


@app.get("/api/transfer-requests/{identity}")
async def transfer_state(identity: str, token: str = Depends(require_transfer_session)):
    return transfer_service.state(identity, token)


@app.post("/api/transfer-requests/{identity}/cancel")
async def cancel_transfer(identity: str, token: str = Depends(require_transfer_session)):
    return transfer_service.cancel(identity, token)


@app.post("/api/transfer-requests/{identity}/{decision}")
async def decide_transfer(identity: str, decision: Literal["approve", "reject"], request: Request):
    require_local_owner(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(status_code=403, detail="JSON request required")
    return transfer_service.decide(identity, decision == "approve")


@app.post("/api/text", dependencies=[Depends(require_transfer_session)])
async def receive_text(request: TextRequest, http_request: Request, token: str = Depends(require_transfer_session)):
    raw = request.content.encode("utf-8")
    transfer_service.consume(http_request.headers.get("X-Transfer-ID", ""), token,
                             request.type, len(raw), hashlib.sha256(raw).hexdigest())
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


@app.post("/api/upload", dependencies=[Depends(require_transfer_session)])
def receive_file(request: Request, files: list[UploadFile] = File(...), token: str = Depends(require_transfer_session)):
    manifest = []
    for file in files:
        digest = hashlib.sha256()
        size = 0
        while chunk := file.file.read(TRANSFER_COPY_BUFFER_SIZE):
            digest.update(chunk)
            size += len(chunk)
        file.file.seek(0)
        manifest.append({"name": file.filename, "size": size, "sha256": digest.hexdigest()})
    transfer_service.consume(request.headers.get("X-Transfer-ID", ""), token, "file",
                             sum(item["size"] for item in manifest), files=manifest)
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
    return host in {"127.0.0.1", "::1"}
