import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_NAME = "DevDrop"
DEFAULT_PORT = 8765


@dataclass(slots=True)
class DevDropConfig:
    session_root: Path
    port: int = DEFAULT_PORT


def default_session_root() -> Path:
    return Path.home() / APP_NAME


def config_dir() -> Path:
    root = os.environ.get("APPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> DevDropConfig:
    path = config_path()
    if not path.exists():
        return DevDropConfig(session_root=default_session_root())

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DevDropConfig(session_root=default_session_root())

    return DevDropConfig(
        session_root=Path(str(data.get("session_root") or default_session_root())).expanduser(),
        port=_coerce_port(data.get("port"), DEFAULT_PORT),
    )


def save_config(config: DevDropConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "session_root": str(config.session_root),
        "port": config.port,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _coerce_port(value: object, fallback: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return fallback

    if 1 <= port <= 65535:
        return port
    return fallback
