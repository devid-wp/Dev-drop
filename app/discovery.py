import json
import secrets
import socket
import threading
from typing import Any

from app.runtime import get_local_ip


DISCOVERY_PORT = 8766
DISCOVERY_MAGIC = "DEVDROP_DISCOVERY_V1"
DISCOVERY_TIMEOUT_SECONDS = 0.35


def make_query(nonce: str) -> bytes:
    return json.dumps(
        {"magic": DISCOVERY_MAGIC, "action": "discover", "nonce": nonce}
    ).encode("ascii")


def make_response(query: dict[str, Any], server_name: str, port: int) -> bytes:
    return json.dumps(
        {
            "magic": DISCOVERY_MAGIC,
            "action": "response",
            "nonce": query["nonce"],
            "name": server_name,
            "ip": get_local_ip(),
            "port": port,
        }
    ).encode("ascii")


def parse_message(data: bytes) -> dict[str, Any] | None:
    try:
        message = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict) or message.get("magic") != DISCOVERY_MAGIC:
        return None
    return message


class DiscoveryService:
    def __init__(self, server_port: int, server_name: str | None = None) -> None:
        self.server_port = server_port
        self.server_name = server_name or f"DevDrop-{socket.gethostname()}"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._thread = None

    def discover(self) -> list[dict[str, object]]:
        nonce = secrets.token_hex(16)
        query = make_query(nonce)
        servers: dict[tuple[str, int], dict[str, object]] = {}

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(DISCOVERY_TIMEOUT_SECONDS)
            try:
                sock.sendto(query, ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                return []

            while True:
                try:
                    data, address = sock.recvfrom(2048)
                except socket.timeout:
                    break
                except OSError:
                    break

                response = parse_message(data)
                if not response or response.get("action") != "response":
                    continue
                if response.get("nonce") != nonce:
                    continue
                ip = address[0]
                port = _valid_port(response.get("port"))
                if port is None:
                    continue
                servers[(ip, port)] = {
                    "name": str(response.get("name") or "DevDrop"),
                    "ip": ip,
                    "port": port,
                    "url": f"https://{ip}:{port}",
                    "status": "Available",
                }

        local_ip = get_local_ip()
        servers.setdefault(
            (local_ip, self.server_port),
            {
                "name": self.server_name,
                "ip": local_ip,
                "port": self.server_port,
                "url": f"https://{local_ip}:{self.server_port}",
                "status": "Available",
            },
        )
        return sorted(servers.values(), key=lambda server: (str(server["name"]), str(server["ip"])))

    def _serve(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("", DISCOVERY_PORT))
                sock.settimeout(0.5)
                while not self._stop_event.is_set():
                    try:
                        data, address = sock.recvfrom(2048)
                    except socket.timeout:
                        continue
                    except OSError:
                        return

                    query = parse_message(data)
                    if not query or query.get("action") != "discover":
                        continue
                    if not isinstance(query.get("nonce"), str):
                        continue
                    try:
                        sock.sendto(make_response(query, self.server_name, self.server_port), address)
                    except OSError:
                        continue
        except OSError:
            return


def _valid_port(value: object) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None
