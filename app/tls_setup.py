"""Automatic, local-first TLS provisioning and managed SAN renewal."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.config import config_dir
from app.runtime import get_local_addresses, get_local_ip
from app.secure_storage import protect_private_directory, protect_private_file
from app.transport import TLSConfigurationMissing, TLSSettings, TransportError, certificate_fingerprint, config_file


def _atomic_write(path: Path, content: bytes, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if private:
            protect_private_file(temporary)
        temporary.replace(path)
        if private:
            protect_private_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def _key_bytes(key: ec.EllipticCurvePrivateKey, password: str | None) -> bytes:
    encryption = (serialization.BestAvailableEncryption(password.encode("utf-8"))
                  if password else serialization.NoEncryption())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)


def _load_key(path: Path, password: str | None):
    try:
        return serialization.load_pem_private_key(path.read_bytes(), password=password.encode() if password else None)
    except (OSError, TypeError, ValueError) as error:
        raise TransportError(f"Could not unlock local TLS key {path}. Check its password and file integrity.") from error


def _san_values() -> tuple[list[str], list[str], str]:
    names = {"localhost"}
    addresses = {"127.0.0.1", "::1", *get_local_addresses()}
    try:
        hostname = socket.gethostname().rstrip(".")
        if hostname and len(hostname) <= 253 and all(
            label and len(label) <= 63 and label[0].isalnum() and label[-1].isalnum()
            and all(char.isalnum() or char == "-" for char in label)
            for label in hostname.split(".")
        ):
            names.add(hostname.lower())
            try:
                addresses.update(item[4][0].split("%", 1)[0] for item in socket.getaddrinfo(hostname, None))
            except OSError:
                pass
    except OSError:
        pass
    clean_ips = set()
    for value in addresses:
        try:
            ip = ipaddress.ip_address(value)
            if ip.is_unspecified or ip.is_multicast or ip.is_link_local or (not ip.is_private and not ip.is_loopback):
                continue
            clean_ips.add(str(ip))
        except ValueError:
            continue
    preferred = get_local_ip()
    try:
        host = str(ipaddress.ip_address(preferred))
    except ValueError:
        host = "127.0.0.1"
    if host not in clean_ips:
        host = "127.0.0.1"
    return sorted(names), sorted(clean_ips), host


def _general_names(names: list[str], ips: list[str]) -> x509.SubjectAlternativeName:
    values: list[x509.GeneralName] = [x509.DNSName(name) for name in names]
    values.extend(x509.IPAddress(ipaddress.ip_address(address)) for address in ips)
    return x509.SubjectAlternativeName(values)


def _issue_ca(password: str | None) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DevDrop Local CA")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=None, decipher_only=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def _issue_server(ca_key, ca_cert: x509.Certificate, names: list[str], ips: list[str],
                  key=None) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    server_key = key or ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DevDrop Server")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_cert.subject)
            .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=None, decipher_only=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(_general_names(names, ips), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return server_key, cert


def _write_config(path: Path, certificate: Path, key: Path, ca: Path,
                  host: str, key_mode: str, managed: bool = True,
                  ca_key: Path | None = None) -> None:
    payload = {
        "certificate": str(certificate.resolve()), "key": str(key.resolve()),
        "ca": str(ca.resolve()), "host": host,
        "sha256": certificate_fingerprint(certificate),
        "key_mode": key_mode, "managed": managed,
        "security_mode": "advanced" if key_mode == "password" else "os",
    }
    if ca_key is not None:
        payload["ca_key"] = str(ca_key.resolve())
    descriptor, name = tempfile.mkstemp(prefix=".tls-config-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def provision_local_tls(password: str | None = None, destination: Path | None = None) -> TLSSettings:
    """Create a local CA and leaf using cryptography, with owner-only key files."""
    config_path = destination or config_file()
    base = config_dir()
    tls_dir, ca_dir = base / "tls", base / "ca"
    ca_key_path, ca_cert_path = ca_dir / "ca-key.pem", ca_dir / "ca.pem"
    server_key_path, server_cert_path = tls_dir / "server-key.pem", tls_dir / "server.pem"
    if config_path.exists():
        raise TransportError(f"TLS config already exists at {config_path}; it was not overwritten.")
    existing = [path for path in (ca_key_path, ca_cert_path, server_key_path, server_cert_path) if path.exists()]
    if existing:
        if all(path.is_file() for path in (ca_cert_path, server_key_path, server_cert_path)):
            try:
                key_pem = server_key_path.read_text(encoding="ascii")
            except (OSError, UnicodeError) as error:
                raise TransportError(f"Cannot inspect existing TLS key {server_key_path}: {error}.") from error
            key_mode = "password" if "-----BEGIN ENCRYPTED PRIVATE KEY-----" in key_pem else "os"
            if os.name != "nt":
                protect_private_file(server_key_path)
                if ca_key_path.is_file():
                    protect_private_file(ca_key_path)
            _write_config(config_path, server_cert_path, server_key_path, ca_cert_path,
                          get_local_ip(), key_mode,
                          ca_key=ca_key_path if ca_key_path.exists() else None)
            return TLSSettings.load()
        raise TransportError(
            "Existing TLS files were found without a usable config. They were preserved; "
            "repair or migrate the config rather than creating a new identity."
        )
    base.mkdir(parents=True, exist_ok=True)
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_dir.mkdir(parents=True, exist_ok=True)
    protect_private_directory(base)
    protect_private_directory(tls_dir)
    protect_private_directory(ca_dir)

    names, ips, host = _san_values()
    ca_key, ca_cert = _issue_ca(password)
    server_key, server_cert = _issue_server(ca_key, ca_cert, names, ips)
    _atomic_write(ca_key_path, _key_bytes(ca_key, password), private=True)
    _atomic_write(ca_cert_path, ca_cert.public_bytes(serialization.Encoding.PEM))
    _atomic_write(server_key_path, _key_bytes(server_key, password), private=True)
    _atomic_write(server_cert_path, server_cert.public_bytes(serialization.Encoding.PEM))
    key_mode = "password" if password else "os"
    _write_config(config_path, server_cert_path, server_key_path, ca_cert_path, host,
                  key_mode, ca_key=ca_key_path)
    return TLSSettings.load()


def _certificate_sans(path: Path) -> tuple[set[str], set[str]]:
    try:
        cert = x509.load_pem_x509_certificate(path.read_bytes())
        extension = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return ({item.lower() for item in extension.get_values_for_type(x509.DNSName)},
                {str(item) for item in extension.get_values_for_type(x509.IPAddress)})
    except (OSError, ValueError, x509.ExtensionNotFound) as error:
        raise TransportError(f"Cannot inspect managed TLS certificate {path}: {error}.") from error


def refresh_managed_certificate(settings: TLSSettings, password: str | None = None) -> TLSSettings:
    """Refresh a managed leaf for current SANs while retaining its CA and key."""
    if not settings.managed:
        return settings
    names, ips, host = _san_values()
    current_names, current_ips = _certificate_sans(settings.certificate)
    if not any(not ipaddress.ip_address(address).is_loopback for address in ips) and any(
        not ipaddress.ip_address(address).is_loopback for address in current_ips
    ):
        # A temporarily disconnected host should not revoke SANs that were
        # provisioned for its LAN. Refresh once an address is observable again.
        return settings
    if set(names) == current_names and set(ips) == current_ips and host == settings.host:
        return settings
    base = config_dir()
    ca_key_path = settings.ca_key or (base / "ca" / "ca-key.pem")
    if not ca_key_path.is_file():
        raise TransportError(f"The managed CA signing key is missing at {ca_key_path}; the existing certificate was kept.")
    ca_key = _load_key(ca_key_path, password)
    server_key = _load_key(settings.key, password if settings.key_mode == "password" else None)
    try:
        ca_cert = x509.load_pem_x509_certificate(settings.ca.read_bytes())
    except (OSError, ValueError) as error:
        raise TransportError(f"Cannot read managed CA certificate {settings.ca}: {error}.") from error
    _, server_cert = _issue_server(ca_key, ca_cert, names, ips, key=server_key)
    pem = server_cert.public_bytes(serialization.Encoding.PEM)
    leaf_id = hashlib.sha256(pem).hexdigest()[:16]
    new_cert_path = settings.certificate.parent / f"server-{leaf_id}.pem"
    if not new_cert_path.exists():
        _atomic_write(new_cert_path, pem)
    _write_config(config_file(), new_cert_path, settings.key, settings.ca, host, settings.key_mode,
                  ca_key=ca_key_path)
    return TLSSettings.load()


def migrate_managed_keys_to_os(settings: TLSSettings, password: str) -> TLSSettings:
    """Keep encrypted originals and switch the same keys to owner-only OS files."""
    if not settings.managed or settings.key_mode != "password":
        return settings
    base = config_dir()
    old_ca_key = settings.ca_key or (base / "ca" / "ca-key.pem")
    if not old_ca_key.is_file():
        raise TransportError(f"Cannot migrate key storage: managed CA key was not found at {old_ca_key}.")
    # Unlock both before writing anything, so a wrong password never leaves a
    # half migrated identity.
    server_key = _load_key(settings.key, password)
    ca_key = _load_key(old_ca_key, password)
    new_server_key = settings.key.with_name("server-key-os.pem")
    new_ca_key = old_ca_key.with_name("ca-key-os.pem")
    if new_server_key.exists() or new_ca_key.exists():
        raise TransportError("Passwordless key files already exist; they were not overwritten.")
    _atomic_write(new_server_key, _key_bytes(server_key, None), private=True)
    _atomic_write(new_ca_key, _key_bytes(ca_key, None), private=True)
    _write_config(config_file(), settings.certificate, new_server_key, settings.ca,
                  settings.host, "os", ca_key=new_ca_key)
    return TLSSettings.load()


def tls_for_server(
    consent: Callable[[], bool],
    password_prompt: Callable[[bool], str],
    advanced_prompt: Callable[[], bool] = lambda: False,
    passwordless_migration_prompt: Callable[[], bool] = lambda: False,
) -> tuple[TLSSettings, str | None]:
    """Load legacy/current settings or provision on consent; return any key password."""
    try:
        settings = TLSSettings.load()
    except TLSConfigurationMissing:
        if not consent():
            raise TransportError("HTTPS setup was declined. Run `devdrop serve` and approve local TLS setup, or configure TLS manually.")
        password = None
        if advanced_prompt():
            password = password_prompt(False)
            if not password:
                raise TransportError("Advanced Security setup cancelled: password cannot be empty.")
            if password != password_prompt(True):
                raise TransportError("Advanced Security setup cancelled: passwords did not match.")
        settings = provision_local_tls(password)
        if settings.managed:
            settings = refresh_managed_certificate(settings, password)
        return settings, password

    if settings.managed:
        password = None
        if settings.key_mode == "password":
            migrate = settings.legacy_key_storage and passwordless_migration_prompt()
            if not settings.legacy_key_storage:
                # Persist that the user explicitly chose Advanced Security so
                # later launches do not repeat the migration question.
                _write_config(config_file(), settings.certificate, settings.key, settings.ca,
                              settings.host, "password", ca_key=settings.ca_key)
                settings = TLSSettings.load()
            password = password_prompt(False)
            if not password:
                raise TransportError("TLS key password cannot be empty.")
            if migrate:
                settings = migrate_managed_keys_to_os(settings, password)
                password = None
            elif settings.legacy_key_storage:
                _write_config(config_file(), settings.certificate, settings.key, settings.ca,
                              settings.host, "password", ca_key=settings.ca_key)
                settings = TLSSettings.load()
        settings = refresh_managed_certificate(settings, password)
        return settings, password
    return settings, None
