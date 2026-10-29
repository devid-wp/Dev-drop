from pathlib import Path

from fastapi import HTTPException


def safe_upload_name(filename: str | None) -> str:
    """Return a filesystem-safe basename for an uploaded file."""
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
    """Create a new upload file, adding a suffix if its name already exists."""
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
