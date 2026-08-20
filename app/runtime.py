import os
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


HOST = "0.0.0.0"
FIREWALL_RULE_NAME = "DevDrop LAN"


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


def get_network_profile() -> str:
    """Get Windows network profile (Domain, Private, Public)."""
    try:
        ps_cmd = r"""
Get-NetConnectionProfile | 
Where-Object { $_.IPv4Connectivity -eq 'Internet' -and $_.NetworkCategory -ne 'DomainAuthenticated' } | 
Sort-Object IPv4Address | 
Select-Object -First 1 -ExpandProperty NetworkCategory
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False) as f:
            f.write(ps_cmd)
            script_path = f.name
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script_path],
                capture_output=True, text=True, timeout=5
            )
        finally:
            os.unlink(script_path)
        out = result.stdout.strip()
        if out in ("Public", "Private", "Domain", "DomainAuthenticated"):
            return out
        return "Unknown"
    except Exception:
        return "Unknown"
    except Exception:
        return "Unknown"


def ensure_firewall_rule(port: int) -> tuple[bool, str]:
    """Ensure Windows Firewall allows inbound connections on the given port.
    Returns (success, message). Requires administrator privileges.
    """
    if os.name != "nt":
        return True, "Non-Windows platform"

    try:
        # Check current profile
        profile = get_network_profile()
        
        # Check if rule already exists
        check = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if "No rules match" not in check.stdout:
            return True, f"Firewall rule exists (profile: {profile})"

        # Create rule with ALL profiles including Public
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Start-Process powershell -ArgumentList '-NoProfile -Command "
                f"New-NetFirewallRule -DisplayName \"{FIREWALL_RULE_NAME}\" "
                f"-Direction Inbound -Protocol TCP -LocalPort {port} "
                f"-Action Allow -Profile Domain,Private,Public' -Verb RunAs"
            ],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, f"Firewall rule created (profile: {profile})"
        else:
            return False, f"Need admin rights to create firewall rule (profile: {profile})"
    except Exception as e:
        return False, f"Firewall check failed: {e}"


def create_session_folder(root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session = root.expanduser() / f"session-{timestamp}"
    session.mkdir(parents=True, exist_ok=False)
    return session
