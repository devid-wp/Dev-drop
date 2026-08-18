import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path

import uvicorn

import app.main as backend


HOST = "0.0.0.0"
PORT = 8765


def get_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def create_session_folder() -> Path:
    root = Path.home() / "DevDrop"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session = root / f"session-{timestamp}"
    session.mkdir(parents=True, exist_ok=False)
    return session


def format_code(code: str) -> str:
    return f"{code[:3]} {code[3:6]} {code[6:]}"


def print_banner(ip: str, session_dir: Path) -> None:
    code = format_code(backend.pairing_code)

    print()
    print("╭────────────────────────────────────────────────────────╮")
    print("│                                                        │")
    print("│                        DevDrop                         │")
    print("│                                                        │")
    print("│              Local sharing made simple.               │")
    print("│                                                        │")
    print("╰────────────────────────────────────────────────────────╯")
    print()
    print(f"  Pairing code   {code}")
    print(f"  Open           http://{ip}:{PORT}")
    print(f"  Session        {session_dir}")
    print()
    print("Waiting for devices...")
    print()


def ask_to_delete_session(session_dir: Path) -> None:
    print()
    print(f"Session folder: {session_dir}")

    try:
        answer = input("Delete this session folder? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        answer = ""

    if answer in {"y", "yes"}:
        try:
            shutil.rmtree(session_dir)
            print("Session folder deleted.")
        except OSError as error:
            print(f"Could not delete session folder: {error}")
    else:
        print("Session folder kept.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    session_dir = create_session_folder()
    backend.SESSION_DIR = session_dir
    ip = get_local_ip()
    print_banner(ip, session_dir)

    try:
        uvicorn.run(
            backend.app,
            host=HOST,
            port=PORT,
            log_level="warning",
        )
    except KeyboardInterrupt:
        pass
    finally:
        ask_to_delete_session(session_dir)


if __name__ == "__main__":
    main()
