"""Owner-only storage for local cryptographic key material."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.transport import TransportError


def protect_private_file(path: Path) -> None:
    """Apply OS access controls: POSIX owner-only mode or Windows user ACL."""
    if os.name == "nt":
        try:
            identity = subprocess.run(["whoami"], check=True, capture_output=True,
                                      text=True, timeout=5).stdout.strip()
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r",
                 f"{identity}:(F)", "SYSTEM:(F)"],
                check=True, capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise TransportError(f"Could not restrict access to TLS private key {path}. Windows user-only ACL is required.") from error
    else:
        try:
            path.chmod(0o600)
            if path.stat().st_mode & 0o077:
                raise OSError("group or other access remains enabled")
        except OSError as error:
            raise TransportError(f"Could not restrict access to TLS private key {path}: {error}.") from error


def protect_private_directory(path: Path) -> None:
    if os.name != "nt":
        try:
            path.chmod(0o700)
            if path.stat().st_mode & 0o077:
                raise OSError("group or other access remains enabled")
        except OSError as error:
            raise TransportError(f"Could not restrict access to TLS directory {path}: {error}.") from error
