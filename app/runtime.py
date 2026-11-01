import os
import ipaddress
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


HOST = "0.0.0.0"
FIREWALL_RULE_NAME = "DevDrop LAN"


def get_local_ip() -> str:
    """Return the LAN IPv4 address used to reach the internet.
    Connects to a known external IP (8.8.8.8) to force the OS to select
    the correct LAN interface, avoiding VPN/virtual interfaces.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Connect to Google DNS - forces OS to pick the interface that
        # routes to the internet (typically the primary LAN interface)
        sock.connect(("8.8.8.8", 53))
        ip = sock.getsockname()[0]
        # Ensure it's a private LAN IP, not loopback or VPN
        if ip.startswith("127.") or ip.startswith("169.254."):
            raise OSError("Non-LAN IP detected")
        return ip
    except OSError:
        # Fallback: try to find a private IP from all interfaces
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        if (ip.startswith("10.") or
                            ip.startswith("172.16.") or
                            ip.startswith("192.168.")):
                            return ip
        except Exception:
            pass
        return "127.0.0.1"
    finally:
        sock.close()


def get_local_addresses() -> list[str]:
    """Return unique non-loopback local IPs suitable for TLS SANs."""
    candidates: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM):
            candidates.add(item[4][0].split("%", 1)[0])
    except OSError:
        pass
    try:
        preferred = get_local_ip()
    except OSError:
        preferred = "127.0.0.1"
    if preferred:
        candidates.add(preferred)
    filtered = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if (address.is_loopback or address.is_link_local or address.is_unspecified
                or address.is_multicast or not address.is_private):
            continue
        filtered.append(str(address))
    return sorted(set(filtered), key=lambda value: (ipaddress.ip_address(value).version, value))


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
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        finally:
            os.unlink(script_path)
        out = result.stdout.strip()
        if out in ("Public", "Private", "Domain", "DomainAuthenticated"):
            return out
        return "Unknown"
    except Exception:
        return "Unknown"


# Module-level cache to avoid repeated firewall checks
_firewall_rule_checked = False
_firewall_rule_ok = True


def ensure_firewall_rule(port: int) -> tuple[bool, str]:
    """Ensure Windows Firewall allows inbound connections on the given port.
    Returns (success, message). Requires administrator privileges.
    """
    global _firewall_rule_checked, _firewall_rule_ok
    
    if os.name != "nt":
        return True, "Non-Windows platform"

    # Skip if already checked this session
    if _firewall_rule_checked:
        return _firewall_rule_ok, "Firewall rule already verified this session"

    _firewall_rule_checked = True
    
    try:
        profile = get_network_profile()
        
        # Check if rule already exists (no window)
        check = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if "No rules match" not in check.stdout:
            _firewall_rule_ok = True
            return True, f"Firewall rule exists (profile: {profile})"

        # Create rule with ALL profiles including Public - use CREATE_NO_WINDOW
        # We use a scheduled task approach to avoid UAC prompt window
        ps_cmd = (
            f"New-NetFirewallRule -DisplayName \"{FIREWALL_RULE_NAME}\" "
            f"-Direction Inbound -Protocol TCP -LocalPort {port} "
            f"-Action Allow -Profile Domain,Private,Public"
        )
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Start-Process powershell -ArgumentList '-NoProfile -Command {ps_cmd}' -Verb RunAs -WindowStyle Hidden"
            ],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            _firewall_rule_ok = True
            return True, f"Firewall rule created (profile: {profile})"
        else:
            _firewall_rule_ok = False
            return False, f"Need admin rights to create firewall rule (profile: {profile})"
    except Exception as e:
        _firewall_rule_ok = False
        return False, f"Firewall check failed: {e}"


def create_session_folder(root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session = root.expanduser() / f"session-{timestamp}"
    session.mkdir(parents=True, exist_ok=False)
    return session
