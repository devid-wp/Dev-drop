import hashlib
import asyncio
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from urllib.parse import urlsplit
from app.transfer_requests import TransferDescription, TransferError, TransferService

from app.file_offers import FileOfferService, OfferError
from app.relay import RelayCreate, RelayError, RelayService
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
file_offers = FileOfferService()
session_client_info: dict[str, dict[str, str]] = {}
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
        for token, created_at in list(sessions.items())
        if now - created_at >= SESSION_LIFETIME
    ]

    for token in expired:
        sessions.pop(token, None)
        session_client_info.pop(token, None)


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
        session_client_info.pop(token, None)
        return False

    return True


relay_service = RelayService(transfer_service, file_offers, lambda token: session_is_valid(token))


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
    file_offers.close()
    if DISCOVERY_SERVICE is not None:
        DISCOVERY_SERVICE.stop()


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


def require_owner_panel(request: Request) -> None:
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Owner panel is local-only")
    host_header = request.headers.get("host", "")
    try:
        request_host = urlsplit("//" + host_header).hostname
    except ValueError:
        request_host = None
    if request_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Local owner host required")


@app.get("/panel")
async def owner_panel(request: Request):
    """Serve the owner control panel only over a direct loopback HTTPS request."""
    require_owner_panel(request)
    return FileResponse(WEB_DIR / "panel.html", headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    })


@app.get("/panel-assets/{asset_name}")
async def owner_panel_asset(asset_name: str, request: Request):
    require_owner_panel(request)
    if asset_name not in {"panel.css", "panel.js"}:
        raise HTTPException(status_code=404, detail="Panel asset not found")
    return FileResponse(WEB_DIR / asset_name, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


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
    require_local_owner(request)

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
    require_local_owner(request)
    return {"transfers": load_transfer_history()}


@app.delete("/api/history")
async def clear_transfer_history(request: Request):
    require_local_owner(request)
    save_transfer_history([])
    return {"success": True}


@app.get("/api/pairing-code")
async def get_pairing_code(request: Request):
    require_local_owner(request)
    if not pairing_is_valid():
        generate_pairing_code()

    return {
        "code": pairing_code,
        "expires_in": max(0, int(PAIRING_LIFETIME - (time.time() - pairing_created_at))),
    }


@app.post("/api/regenerate-pairing-code")
async def post_regenerate_pairing_code(request: Request):
    require_local_owner(request)

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
    session_client_info[token] = {"peer": client_ip, "agent": request.headers.get("user-agent", "Unknown client")[:100]}

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
    parts = request.url.path.strip("/").split("/")
    if request.method == "POST" and len(parts) == 4 and parts[:2] == ["api", "relays"] and parts[3] == "upload":
        try:
            token = await require_transfer_session(request)
            relay_service.check_upload(parts[2], token)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers=error.headers)
        except (RelayError, TransferError) as error:
            return JSONResponse(status_code=409, content={"detail": str(error)})
    response = await call_next(request)
    if request.url.path.startswith(("/api/incoming-offers", "/api/outgoing-offers", "/api/recipient-sessions", "/api/relays", "/api/relay-recipients")):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path in {"/api/status", "/api/history", "/api/pairing-code", "/api/regenerate-pairing-code"} or request.url.path.startswith("/api/transfer-requests"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(TransferError)
async def transfer_error(request: Request, error: TransferError):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.post("/api/transfer-requests")
async def create_transfer(description: TransferDescription, token: str = Depends(require_transfer_session)):
    if description.recipient_id is not None:
        raise TransferError("Use the relay API to bind a recipient")
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


class OfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)
    recipient_id: str = Field(pattern=r"^[a-f0-9]{64}$")


def recipient_id(token: str) -> str:
    # This opaque selector is not an authorization credential.
    return hashlib.sha256(token.encode()).hexdigest()


def offer_owner(request: Request):
    require_local_owner(request)
    if request.method == "POST" and request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(status_code=403, detail="JSON request required")


@app.exception_handler(OfferError)
async def offer_error(request: Request, error: OfferError):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.get("/api/recipient-sessions")
async def recipient_sessions(request: Request):
    offer_owner(request)
    cleanup_expired_sessions()
    return {"sessions": [{"id": recipient_id(token), "created_at": created,
                           **session_client_info.get(token, {"peer": "unknown", "agent": "Unknown client"})}
                          for token, created in list(sessions.items())]}


@app.post("/api/outgoing-offers")
def create_file_offer(data: OfferCreate, request: Request):
    offer_owner(request)
    target = next((token for token in list(sessions) if recipient_id(token) == data.recipient_id and session_is_valid(token)), None)
    if target is None:
        raise OfferError("Recipient session is unavailable")
    # Only the local owner may register a path; downloads never take a path.
    return file_offers.create(Path(data.path), target, data.recipient_id)


@app.get("/api/outgoing-offers")
async def outgoing_file_offers(request: Request):
    offer_owner(request)
    return {"offers": file_offers.list()}


@app.post("/api/outgoing-offers/{identity}/cancel")
async def cancel_file_offer(identity: str, request: Request):
    offer_owner(request)
    return file_offers.cancel(identity)


@app.get("/api/incoming-offers")
async def incoming_file_offers(token: str = Depends(require_transfer_session)):
    return {"offers": file_offers.list(token), "session_id": recipient_id(token)}


@app.get("/api/incoming-offers/{identity}/state")
async def incoming_offer_state(identity: str, token: str = Depends(require_transfer_session)):
    try:
        offer = next(item for item in file_offers.list(token) if item["id"] == identity)
        return offer
    except (StopIteration, OfferError):
        raise HTTPException(status_code=404, detail="File offer is unavailable")


@app.post("/api/incoming-offers/{identity}/accept")
async def accept_file_offer(identity: str, token: str = Depends(require_transfer_session)):
    offer, grant = file_offers.accept(identity, token)
    response = JSONResponse(offer, headers={"Cache-Control": "no-store"})
    response.set_cookie("__Secure-dd_download_" + identity, grant, secure=True, httponly=True,
                        samesite="strict", path=f"/api/incoming-offers/{identity}/download",
                        max_age=max(1, int(offer["expires_at"] - time.time())))
    return response


@app.post("/api/incoming-offers/{identity}/reject")
async def reject_file_offer(identity: str, token: str = Depends(require_transfer_session)):
    return file_offers.reject(identity, token)


class OfferDownloadResponse(StreamingResponse):
    def __init__(self, *args, cleanup, on_chunk=lambda _amount: None, **kwargs):
        self.cleanup = cleanup
        self.on_chunk = on_chunk
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        async def tracked_send(message):
            await send(message)
            if message.get("type") == "http.response.body" and message.get("body"):
                self.on_chunk(len(message["body"]))
        try:
            await super().__call__(scope, receive, tracked_send)
        finally:
            # Also runs on disconnect or a failed send, before request teardown.
            self.cleanup()


@app.get("/api/incoming-offers/{identity}/download")
async def download_file_offer(identity: str, request: Request):
    token = await require_transfer_session(request) if request.headers.get("authorization") else None
    offer, source = file_offers.claim(identity, request.cookies.get("__Secure-dd_download_" + identity, ""),
                                     session_is_valid, token)
    def stream():
        complete = False
        try:
            while True:
                file_offers.check_streaming(identity)
                chunk = source.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
            complete = True
        finally:
            source.close()
            file_offers.finish(identity, complete)
    def cleanup():
        source.close()
        file_offers.finish(identity, False)
    from urllib.parse import quote
    filename = quote(offer["filename"], safe="")
    response = OfferDownloadResponse(stream(), media_type="application/octet-stream", headers={
        "Content-Length": str(offer["size"]), "Content-Disposition": "attachment; filename*=UTF-8''" + filename,
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "none",
    }, cleanup=cleanup, on_chunk=lambda amount: file_offers.record_stream_bytes(identity, amount))
    response.delete_cookie("__Secure-dd_download_" + identity, path=f"/api/incoming-offers/{identity}/download",
                           secure=True, httponly=True, samesite="strict")
    return response


@app.exception_handler(RelayError)
async def relay_error(request: Request, error: RelayError):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.get("/api/relay-recipients")
async def relay_recipients(token: str = Depends(require_transfer_session)):
    cleanup_expired_sessions()
    return {"sessions": [{"id": recipient_id(other)} for other in list(sessions) if other != token]}


@app.post("/api/relays")
async def create_relay(description: RelayCreate, token: str = Depends(require_transfer_session)):
    target = next((other for other in list(sessions) if recipient_id(other) == description.recipient_id and session_is_valid(other)), None)
    if target is None:
        raise RelayError("Recipient session is unavailable")
    return relay_service.create(token, target, recipient_id(token), description)


@app.get("/api/relays")
async def sent_relays(token: str = Depends(require_transfer_session)):
    return {"relays": relay_service.list(token)}


@app.get("/api/relays/{identity}")
async def relay_state(identity: str, token: str = Depends(require_transfer_session)):
    return relay_service.state(identity, token)


@app.post("/api/relays/{identity}/cancel")
async def cancel_relay(identity: str, token: str = Depends(require_transfer_session)):
    return relay_service.cancel(identity, token)


def upload_manifest(files):
    manifest = []
    for file in files:
        digest = hashlib.sha256()
        size = 0
        while chunk := file.file.read(TRANSFER_COPY_BUFFER_SIZE):
            digest.update(chunk)
            size += len(chunk)
        file.file.seek(0)
        manifest.append({"name": file.filename, "size": size, "sha256": digest.hexdigest()})
    return manifest


@app.post("/api/relays/{identity}/upload")
def upload_relay(identity: str, files: list[UploadFile] = File(...), token: str = Depends(require_transfer_session)):
    if len(files) != 1:
        raise RelayError("Choose exactly one file for relay")
    return relay_service.upload(identity, token, upload_manifest(files), files[0].file)


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
    manifest = upload_manifest(files)
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
