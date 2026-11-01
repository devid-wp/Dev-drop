from getpass import getpass
from app.transport import TLSSettings, TransportError
from app.tls_setup import tls_for_server
import shutil
import sys
import subprocess
import os
from pathlib import Path

import uvicorn

from app.config import DEFAULT_PORT
from app.runtime import HOST, create_session_folder, get_local_ip, ensure_firewall_rule, get_network_profile
import app.main as backend


PORT = DEFAULT_PORT


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
    print("  Pairing codes are one-use; run `devdrop pair` for the next device.")
    print(f"  Open           {TLSSettings.load().url(PORT)}")
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

    try:
        tls, password = tls_for_server(
            consent=lambda: input("HTTPS is not configured. Create a local HTTPS identity now? [y/N]: ").strip().lower() in {"y", "yes"},
            password_prompt=lambda confirm: getpass(
                "Choose TLS private-key password: " if not confirm else "Repeat TLS private-key password: "
            ),
        )
        if password is None:
            password = getpass("TLS private-key password: ")
        tls_options = tls.server_options(password)
    except (TransportError, EOFError) as error:
        print(f"HTTPS startup refused: {error}")
        return
    session_dir = create_session_folder(Path.home() / "DevDrop")
    backend.SESSION_DIR = session_dir
    backend.SERVER_PORT = PORT
    ip = get_local_ip()

    # Network profile (affects LAN visibility)
    net_profile = get_network_profile()
    if net_profile:
        print(f"  Network profile: {net_profile}" + (" ⚠️ Public blocks LAN" if net_profile == "Public" else ""))

    # Ensure Windows Firewall allows LAN access
    ok, msg = ensure_firewall_rule(PORT)
    if not ok:
        print(f"Warning: {msg}")
        print("  Phone access may be blocked. Run as Administrator to auto-fix.")

    print_banner(ip, session_dir)

    try:
        uvicorn.run(
            backend.app,
            **tls_options,
            host=HOST,
            proxy_headers=False,
            port=PORT,
            log_level="warning",
        )
    except KeyboardInterrupt:
        pass
    finally:
        ask_to_delete_session(session_dir)


if __name__ == "__main__":
    main()
