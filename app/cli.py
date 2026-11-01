"""Terminal-first command line for local DevDrop administration.

The CLI talks to local management routes only through app.transport's pinned
loopback HTTPS client. It never handles or prints Bearer sessions.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import DevDropConfig, config_path, load_config, save_config
from app.discovery import DiscoveryService
from app.runtime import HOST, create_session_folder, get_local_ip
from app.transport import TLSSettings, TransportError, open_local
from app.tls_setup import tls_for_server


VERSION = "2.0.0"
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNAVAILABLE = 3


class CliError(RuntimeError):
    def __init__(self, message: str, exit_code: int = EXIT_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


def _api(method: str, path: str, payload: dict[str, Any] | None = None,
         timeout: float = 5.0) -> dict[str, Any]:
    config = load_config()
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"https://127.0.0.1:{config.port}{path}", data=body, method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with open_local(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise CliError("The local server returned an invalid response.", EXIT_UNAVAILABLE)
        return result
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise CliError("The local server does not support this operation.", EXIT_UNAVAILABLE) from None
        if error.code in (401, 403):
            raise CliError("The local server refused this management request.", EXIT_UNAVAILABLE) from None
        raise CliError(f"The local server returned HTTP {error.code}.", EXIT_UNAVAILABLE) from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, TransportError) as error:
        # Never include request data, TLS key material, pairing codes or tokens.
        raise CliError(_safe_transport_message(error), EXIT_UNAVAILABLE) from None


def _safe_transport_message(error: BaseException) -> str:
    if isinstance(error, TransportError):
        return str(error)
    return "Could not reach the local HTTPS server. Check that it is running and TLS is configured."


def _emit(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _terminal_text(value: object, limit: int = 240) -> str:
    return "".join(ch for ch in str(value) if ch.isprintable())[:limit]


def command_version(args: argparse.Namespace) -> int:
    if args.json:
        _emit({"name": "DevDrop", "version": VERSION}, True)
    else:
        print(f"DevDrop {VERSION}")
    return EXIT_OK


def command_status(args: argparse.Namespace) -> int:
    data = _api("GET", "/api/status")
    # The code is disclosed only by the explicit `pair` command.
    data.pop("pairing_code", None)
    if args.json:
        _emit(data, True)
    else:
        print("DevDrop server: running")
        print(f"Version: {data.get('version', 'unknown')}")
        print(f"Port: {load_config().port}")
        print(f"Session: {data.get('session_path', 'unknown')}")
        print(f"Connected devices: {data.get('connected_devices', 0)}")
        print(f"Received: {data.get('received_files', 0)} files, {data.get('received_size', 0)} bytes")
    return EXIT_OK


def command_pair(args: argparse.Namespace) -> int:
    data = _api("GET", "/api/pairing-code")
    code = str(data.get("code", ""))
    if len(code) != 9 or not code.isdigit():
        raise CliError("The local server returned an invalid pairing code.", EXIT_UNAVAILABLE)
    if args.json:
        _emit({"code": code, "expires_in": data.get("expires_in")}, True)
    else:
        print(f"Pairing code: {code[:3]} {code[3:6]} {code[6:]}")
        print(f"Expires in: {data.get('expires_in', 0)} seconds")
    return EXIT_OK


def command_devices(args: argparse.Namespace) -> int:
    config = load_config()
    local_ip = get_local_ip()
    devices = [device for device in DiscoveryService(config.port).discover()
               if not (device.get("ip") == local_ip and device.get("port") == config.port)]
    if args.json:
        _emit(devices, True)
    elif not devices:
        print("No DevDrop devices found.")
    else:
        for device in devices:
            print(f"{_terminal_text(device['name'], 80)}  {_terminal_text(device['url'], 180)}  {_terminal_text(device['status'], 40)}")
    return EXIT_OK


def command_transfers(args: argparse.Namespace) -> int:
    if args.approve and args.reject:
        raise CliError("Choose either --approve or --reject.")
    if args.approve or args.reject:
        identity = args.approve or args.reject
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
            raise CliError("Transfer ID contains unsupported characters.")
        decision = "approve" if args.approve else "reject"
        data = _api("POST", f"/api/transfer-requests/{identity}/{decision}", {})
        if args.json:
            _emit(data, True)
        else:
            print(f"Transfer {identity}: {data.get('status', decision + 'd')}.")
        return EXIT_OK
    data = _api("GET", "/api/transfer-requests")
    requests = data.get("requests", [])
    if args.json:
        _emit({"requests": requests}, True)
    elif not requests:
        print("No pending transfer requests.")
    else:
        for item in requests:
            files = item.get("files", [])
            description = item.get("description", "file transfer")
            print(f"{_terminal_text(item.get('id', ''))}  {_terminal_text(item.get('sender', 'sender'), 100)}  {_terminal_text(description)}  ({len(files)} file(s), {item.get('size', 0)} bytes)")
        print("Review requests before deciding: devdrop transfers --approve ID | --reject ID")
    return EXIT_OK


def command_history(args: argparse.Namespace) -> int:
    records = _api("GET", "/api/history").get("transfers", [])
    records = list(reversed(records))
    if args.json:
        _emit({"transfers": records}, True)
    elif not records:
        print("No transfer history.")
    else:
        for row in records:
            print(f"{_terminal_text(row.get('timestamp', 'unknown time'), 80)}  {_terminal_text(row.get('filename', 'file'))}  {row.get('size', 0)} bytes  {_terminal_text(row.get('sender_ip', 'unknown sender'), 80)}")
    return EXIT_OK


def command_config(args: argparse.Namespace) -> int:
    config = load_config()
    if args.port is not None or args.session_root is not None:
        config = DevDropConfig(
            session_root=Path(args.session_root).expanduser() if args.session_root else config.session_root,
            port=args.port if args.port is not None else config.port,
        )
        save_config(config)
    result = {"config_path": str(config_path()), "session_root": str(config.session_root), "port": config.port}
    if args.json:
        _emit(result, True)
    else:
        print(f"Config: {result['config_path']}")
        print(f"Session root: {config.session_root}")
        print(f"Port: {config.port}")
    return EXIT_OK


def command_doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []
    try:
        tls = TLSSettings.load()
        checks.append({"name": "TLS configuration", "ok": True, "detail": "Configured certificate fingerprint and CA are valid."})
    except TransportError as error:
        tls = None
        checks.append({"name": "TLS configuration", "ok": False, "detail": str(error)})
    config = load_config()
    try:
        config.session_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".devdrop-write-check-", dir=config.session_root):
            pass
        checks.append({"name": "Session directory", "ok": True, "detail": str(config.session_root)})
    except OSError:
        checks.append({"name": "Session directory", "ok": False, "detail": "Session directory is not writable."})
    local_server_ok = False
    if tls is not None:
        try:
            _api("GET", "/api/health")
            local_server_ok = True
            checks.append({"name": "Local server", "ok": True, "detail": "Pinned HTTPS health check succeeded."})
        except CliError:
            checks.append({"name": "Local server", "ok": False, "detail": "No verified local HTTPS server responded."})
    try:
        with socket.socket() as probe_socket:
            probe_socket.bind(("127.0.0.1", config.port))
        checks.append({"name": "Port", "ok": True, "detail": f"TCP port {config.port} is available."})
    except OSError:
        checks.append({"name": "Port", "ok": local_server_ok, "detail": f"TCP port {config.port} is used by the verified local server." if local_server_ok else f"TCP port {config.port} is already in use."})
    if args.json:
        _emit({"checks": checks, "ok": all(check["ok"] for check in checks)}, True)
    else:
        for check in checks:
            print(f"{'OK' if check['ok'] else 'FAIL'}  {check['name']}: {check['detail']}")
    return EXIT_OK if all(check["ok"] for check in checks) else EXIT_UNAVAILABLE


def command_serve(args: argparse.Namespace) -> int:
    from app import main as backend
    import uvicorn

    config = load_config()
    port = args.port if args.port is not None else config.port
    root = Path(args.session_root).expanduser() if args.session_root else config.session_root
    try:
        tls, password = tls_for_server(
            consent=lambda: input("HTTPS is not configured. Create a local HTTPS identity now? [y/N]: ").strip().lower() in {"y", "yes"},
            password_prompt=lambda confirm: getpass.getpass(
                "Choose TLS private-key password: " if not confirm else "Repeat TLS private-key password: "
            ),
        )
        if password is None:
            password = getpass.getpass("TLS private-key password: ")
        tls_options = tls.server_options(password)
        session_dir = create_session_folder(root)
    except (TransportError, OSError, EOFError) as error:
        raise CliError(str(error), EXIT_ERROR) from None
    if args.port is not None or args.session_root is not None:
        save_config(DevDropConfig(root, port))
    backend.SESSION_DIR = session_dir
    backend.SERVER_PORT = port
    print(f"DevDrop HTTPS server starting at {tls.url(port)}")
    print(f"Session directory: {session_dir}")
    print("Pair a phone with `devdrop pair`; stop with Ctrl+C. Files are retained on exit.")
    try:
        uvicorn.run(backend.app, **tls_options, host=HOST, proxy_headers=False,
                    port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def command_tui(_args: argparse.Namespace) -> int:
    try:
        from app.tui import run_tui
        return run_tui()
    except ImportError:
        raise CliError("Textual is not installed. Install the project dependencies to use `devdrop tui`.") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devdrop", description="Terminal-first local file sharing and DevDrop server administration.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sub = subparsers.add_parser("version", help="Show CLI version")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_version)

    sub = subparsers.add_parser("status", help="Show local server status")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_status)

    sub = subparsers.add_parser("serve", help="Start the local HTTPS server")
    sub.add_argument("--port", type=_port, help="Listen port (default: configured port)")
    sub.add_argument("--session-root", help="Root for session folders")
    sub.set_defaults(handler=command_serve)

    sub = subparsers.add_parser("devices", help="Discover DevDrop devices on the local network")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_devices)

    sub = subparsers.add_parser("pair", help="Show this computer's pairing code for a phone or browser")
    sub.add_argument("--json", action="store_true", help="Print pairing code as JSON")
    sub.set_defaults(handler=command_pair)

    sub = subparsers.add_parser("transfers", help="List or decide pending owner approval requests")
    decision = sub.add_mutually_exclusive_group()
    decision.add_argument("--approve", metavar="ID", help="Approve this pending transfer")
    decision.add_argument("--reject", metavar="ID", help="Reject this pending transfer")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_transfers)

    sub = subparsers.add_parser("history", help="Show recent received-file history")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_history)

    sub = subparsers.add_parser("config", help="Show or update non-secret configuration")
    sub.add_argument("--port", type=_port, help="Set server port")
    sub.add_argument("--session-root", help="Set session directory root")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_config)

    sub = subparsers.add_parser("doctor", help="Check TLS, storage, port, and local server readiness")
    sub.add_argument("--json", action="store_true", help="Print JSON")
    sub.set_defaults(handler=command_doctor)

    sub = subparsers.add_parser("tui", help="Open the interactive terminal dashboard")
    sub.set_defaults(handler=command_tui)
    return parser


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except CliError as error:
        if "--json" in argv:
            print(json.dumps({"error": str(error), "exit_code": error.exit_code}), file=sys.stderr)
        else:
            print(f"devdrop: error: {error}", file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError) as error:
        print(f"devdrop: error: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
