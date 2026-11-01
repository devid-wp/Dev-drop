"""Interactive first-run provisioning for a local DevDrop HTTPS identity."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from app.config import config_dir
from app.transport import TLSConfigurationMissing, TLSSettings, TransportError, certificate_fingerprint, config_file


def _run_openssl(arguments: list[str], password: str) -> None:
    environment = os.environ.copy()
    environment["DEVDROP_TLS_KEY_PASSWORD"] = password
    try:
        subprocess.run(["openssl", *arguments], check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       env=environment, text=True)
    except FileNotFoundError:
        raise TransportError("OpenSSL is required for first-run HTTPS setup. Install OpenSSL and retry.") from None
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        if "pass phrase" in detail.lower() or "bad decrypt" in detail.lower() or "unable to load" in detail.lower():
            raise TransportError("Could not use the existing local CA/key. Verify the TLS key password; existing files were preserved.") from None
        raise TransportError("OpenSSL could not prepare the local HTTPS identity. Existing CA and key files were preserved.") from None


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".tls-config-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2)
            output.write("\n")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def provision_local_tls(password: str, destination: Path | None = None) -> TLSSettings:
    """Create only missing local TLS assets, reusing the dedicated local CA."""
    if not password:
        raise TransportError("TLS key password cannot be empty.")
    config_path = destination or config_file()
    base = config_dir()
    tls_dir = base / "tls"
    ca_dir = base / "ca"
    ca_cert = ca_dir / "ca.pem"
    ca_key = ca_dir / "ca-key.pem"
    server_cert = tls_dir / "server.pem"
    server_key = tls_dir / "server-key.pem"
    csr = tls_dir / "server.csr"
    ext = tls_dir / "server.ext"
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        base.mkdir(parents=True, exist_ok=True)
        base.chmod(0o700)
        tls_dir.chmod(0o700)
        ca_dir.chmod(0o700)

    if config_path.exists():
        raise TransportError(f"TLS config already exists at {config_path}; it was not overwritten. Inspect or repair it manually.")

    # Preserve the CA identity if present. A certificate without its private key
    # can still verify an existing leaf, but cannot issue a new server cert.
    if not ca_cert.exists():
        if ca_key.exists():
            _run_openssl([
                "req", "-new", "-x509", "-key", str(ca_key), "-passin", "env:DEVDROP_TLS_KEY_PASSWORD",
                "-sha256", "-days", "3650", "-out", str(ca_cert), "-subj", "/CN=DevDrop Local Test CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            ], password)
        else:
            _run_openssl([
                "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-aes-256-cbc",
                "-pass", "env:DEVDROP_TLS_KEY_PASSWORD", "-out", str(ca_key),
            ], password)
            if os.name != "nt":
                ca_key.chmod(0o600)
            _run_openssl([
                "req", "-new", "-x509", "-key", str(ca_key), "-passin", "env:DEVDROP_TLS_KEY_PASSWORD",
                "-sha256", "-days", "3650", "-out", str(ca_cert), "-subj", "/CN=DevDrop Local Test CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            ], password)

    if not server_key.exists() and not server_cert.exists():
        if not ca_key.exists():
            raise TransportError(f"Cannot issue a server certificate: CA certificate exists but its private key is missing at {ca_key}. Existing files were preserved.")
        _run_openssl([
            "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-aes-256-cbc",
            "-pass", "env:DEVDROP_TLS_KEY_PASSWORD", "-out", str(server_key),
        ], password)
        if os.name != "nt":
            server_key.chmod(0o600)
        _run_openssl([
            "req", "-new", "-key", str(server_key), "-passin", "env:DEVDROP_TLS_KEY_PASSWORD",
            "-out", str(csr), "-subj", "/CN=DevDrop Local Test Server",
        ], password)
        ext.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectAltName=IP:127.0.0.1,DNS:localhost\n",
            encoding="ascii",
        )
        _run_openssl([
            "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
            "-passin", "env:DEVDROP_TLS_KEY_PASSWORD", "-CAcreateserial", "-sha256", "-days", "90",
            "-extfile", str(ext), "-out", str(server_cert),
        ], password)
    elif not (server_key.is_file() and server_cert.is_file()):
        raise TransportError(f"Incomplete existing server identity in {tls_dir}; refusing to replace the certificate or key.")

    if not (ca_cert.is_file() and server_cert.is_file() and server_key.is_file()):
        raise TransportError("Local HTTPS setup is incomplete; existing TLS files were preserved.")
    fingerprint = certificate_fingerprint(server_cert)
    _atomic_json(config_path, {
        "certificate": str(server_cert.resolve()), "key": str(server_key.resolve()),
        "ca": str(ca_cert.resolve()), "host": "127.0.0.1", "sha256": fingerprint,
    })
    return TLSSettings.load()


def tls_for_server(
    consent: Callable[[], bool],
    password_prompt: Callable[[bool], str],
) -> tuple[TLSSettings, str | None]:
    """Load existing settings or ask before provisioning on first server start."""
    try:
        return TLSSettings.load(), None
    except TLSConfigurationMissing:
        pass

    if not consent():
        raise TransportError("HTTPS setup was declined. Configure TLS with docs/TRANSPORT.md, then run `devdrop serve` again.")
    password = password_prompt(False)
    if not password:
        raise TransportError("HTTPS setup cancelled: the TLS key password cannot be empty.")
    confirmation = password_prompt(True)
    if password != confirmation:
        raise TransportError("HTTPS setup cancelled: the TLS key passwords did not match.")
    return provision_local_tls(password), password
