import secrets
import shutil
import sys
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="DevDrop")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

SESSION_LIFETIME = 60 * 60
PAIRING_LIFETIME = 5 * 60

SESSION_DIR: Path | None = None
sessions: dict[str, float] = {}
pairing_code = ""
pairing_created_at = 0.0


class PairRequest(BaseModel):
    code: str


class TextRequest(BaseModel):
    content: str


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


def pairing_is_valid() -> bool:
    return bool(pairing_code) and time.time() - pairing_created_at < PAIRING_LIFETIME


def require_session_dir() -> Path:
    if SESSION_DIR is None:
        raise HTTPException(
            status_code=500,
            detail="Session directory is not initialized",
        )

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR.resolve()


def safe_upload_name(filename: str | None) -> str:
    # Normalize both Windows and POSIX path separators before taking the basename.
    basename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    forbidden = '<>:"/\\|?*'
    cleaned = "".join(
        "_" if character in forbidden or ord(character) < 32 else character
        for character in basename
    ).strip().rstrip(". ")

    if cleaned in {"", ".", ".."}:
        return "upload.bin"

    return cleaned


def open_unique_upload(session_dir: Path, filename: str):
    original = Path(filename)
    stem = original.stem
    suffix = original.suffix
    number = 0

    while True:
        candidate_name = filename if number == 0 else f"{stem} ({number}){suffix}"
        candidate = (session_dir / candidate_name).resolve()

        if candidate.parent != session_dir:
            raise HTTPException(status_code=400, detail="Invalid filename")

        try:
            return candidate, candidate.open("xb")
        except FileExistsError:
            number += 1


generate_pairing_code()


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "DevDrop"}


@app.get("/api/pairing-code")
async def get_pairing_code():
    if not pairing_is_valid():
        generate_pairing_code()

    return {
        "code": pairing_code,
        "expires_in": max(0, int(PAIRING_LIFETIME - (time.time() - pairing_created_at))),
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
            break
        except FileExistsError:
            number += 1

    cli_print()
    cli_print("↓ Text received")
    cli_print(f"  Saved: {file_path.name}")
    cli_print()

    return {"success": True, "filename": file_path.name}


@app.post("/api/upload")
def receive_file(files: list[UploadFile] = File(...)):
    session_dir = require_session_dir()
    saved_files = []

    for file in files:
        filename = safe_upload_name(file.filename)
        file_path, output = open_unique_upload(session_dir, filename)

        try:
            with output:
                shutil.copyfileobj(file.file, output, length=1024 * 1024)
            saved_files.append(file_path.name)
        except Exception:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not save file")

    # Print CLI output
    if len(saved_files) == 1:
        cli_print()
        cli_print("↓ File received")
        cli_print(f"  Saved: {saved_files[0]}")
        cli_print()
    else:
        cli_print()
        cli_print(f"↓ {len(saved_files)} files received")
        cli_print()
        for filename in saved_files:
            cli_print(f"  Saved: {filename}")
        cli_print()

    return {"success": True, "saved": saved_files}
