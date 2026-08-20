import shutil
import sys
import subprocess
import os
from pathlib import Path

import uvicorn

from app.config import DEFAULT_PORT
from app.runtime import HOST, create_session_folder, get_local_ip
import app.main as backend


PORT = DEFAULT_PORT
FIREWALL_RULE_NAME = "DevDrop LAN"


def ensure_firewall_rule(port: int) -> tuple[bool, str]:
    if os.name != "nt":
        return True, "Non-Windows platform"
    try:
        check = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if "No rules match" not in check.stdout:
            return True, "Firewall rule already exists"
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Start-Process powershell -ArgumentList '-NoProfile -Command "
                f"New-NetFirewallRule -DisplayName \"{FIREWALL_RULE_NAME}\" "
                f"-Direction Inbound -Protocol TCP -LocalPort {port} "
                f"-Action Allow -Profile Domain,Private' -Verb RunAs"
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, "Firewall rule created"
        else:
            return False, f"Failed to create firewall rule (need admin): {result.stderr}"
    except Exception as e:
        return False, f"Firewall check failed: {e}"


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

    session_dir = create_session_folder(Path.home() / "DevDrop")
    backend.SESSION_DIR = session_dir
    backend.SERVER_PORT = PORT
    ip = get_local_ip()

    # Ensure Windows Firewall allows LAN access
    ok, msg = ensure_firewall_rule(PORT)
    if not ok:
        print(f"Warning: {msg}")
        print("  Phone access may be blocked. Run as Administrator to auto-fix.")

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
