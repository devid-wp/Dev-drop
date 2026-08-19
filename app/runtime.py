import socket
from datetime import datetime
from pathlib import Path


HOST = "0.0.0.0"


def get_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.connect(("255.255.255.255", 9))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def create_session_folder(root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session = root.expanduser() / f"session-{timestamp}"
    session.mkdir(parents=True, exist_ok=False)
    return session
