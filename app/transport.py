"""Fail-closed HTTPS configuration and verified desktop connections.

Certificates are provisioned out of band. This module never creates a CA,
installs trust, learns a pin from the network or persists a key password.
"""
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import ssl
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.config import config_dir


class TransportError(RuntimeError):
    pass


class TLSConfigurationMissing(TransportError):
    pass


def config_file() -> Path:
    return Path(os.environ.get("DEVDROP_TLS_CONFIG", config_dir() / "tls.json"))


def _migrate_legacy_config(path: Path) -> None:
    """Move the early setup script's nested config into the documented location."""
    if "DEVDROP_TLS_CONFIG" in os.environ or path.exists():
        return
    legacy = config_dir() / "tls" / "tls.json"
    if not legacy.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        # Preserve the original file and its referenced key material. Create the
        # canonical config atomically and with owner-only permissions.
        shutil.copyfile(legacy, temporary)
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)
    except OSError as error:
        raise TransportError(f"Cannot migrate existing TLS config {legacy} to {path}: {error.strerror or 'I/O error'}") from None


def certificate_fingerprint(path: Path) -> str:
    pem = path.read_text(encoding="ascii")
    match = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
    if match is None:
        raise TransportError("TLS certificate is not PEM")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(match.group())).hexdigest()


@dataclass(frozen=True)
class TLSSettings:
    certificate: Path
    key: Path
    ca: Path
    host: str
    fingerprint: str

    @classmethod
    def load(cls):
        path = config_file()
        _migrate_legacy_config(path)
        if not path.exists():
            raise TLSConfigurationMissing(
                f"TLS config is missing: {path}. Run `devdrop serve` and accept first-run HTTPS setup, or create it per docs/TRANSPORT.md. HTTP is disabled."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("top-level JSON must be an object")
            missing = [name for name in ("certificate", "key", "ca", "host", "sha256") if name not in data]
            if missing:
                raise ValueError(f"missing fields: {', '.join(missing)}")
            settings = cls(*(Path(data[name]).expanduser().resolve() for name in ("certificate", "key", "ca")),
                           host=data["host"], fingerprint=data["sha256"].lower())
            for name, file_path in (("certificate", settings.certificate), ("key", settings.key), ("CA certificate", settings.ca)):
                if not file_path.is_file():
                    raise ValueError(f"{name} file does not exist: {file_path}")
            try:
                ipaddress.ip_address(settings.host)
            except ValueError:
                if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", settings.host):
                    raise ValueError("Invalid TLS host")
            if not re.fullmatch(r"[a-f0-9]{64}", settings.fingerprint):
                raise ValueError("Invalid TLS fingerprint")
            if not hmac.compare_digest(certificate_fingerprint(settings.certificate), settings.fingerprint):
                raise TransportError("TLS server identity changed. Verify the new certificate out of band and update tls.json; no automatic trust.")
            return settings
        except TransportError:
            raise
        except json.JSONDecodeError as error:
            raise TransportError(f"TLS config {path} is not valid JSON (line {error.lineno}, column {error.colno}). Fix it; HTTP is disabled.") from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise TransportError(f"TLS config {path} is invalid: {error}. Fix the indicated file or field; HTTP is disabled.") from None

    def url(self, port):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}:{port}"

    def client_context(self):
        try:
            context = ssl.create_default_context(cafile=str(self.ca))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.hostname_checks_common_name = False  # SAN required
            return context
        except (OSError, ssl.SSLError) as error:
            raise TransportError(f"Cannot load configured CA certificate {self.ca}: {error}.") from None

    def server_options(self, password):
        try:
            if not password or "-----BEGIN ENCRYPTED PRIVATE KEY-----" not in self.key.read_text(encoding="ascii"):
                raise TransportError("An encrypted PKCS#8 private key and a nonempty password are required")
            if os.name != "nt" and self.key.stat().st_mode & 0o077:
                raise TransportError("TLS private key must be owner-only (chmod 600)")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
            try:
                context.load_cert_chain(self.certificate, self.key, password)
            except ssl.SSLError:
                raise TransportError("Cannot unlock TLS private key: the password is incorrect or the key file is damaged. Check the password and encrypted PKCS#8 key.") from None
            # Check expiry, chain, SANs and pin without opening any network port.
            for host in {self.host, "127.0.0.1"}:
                verify_in_memory(context, self.client_context(), host, self.fingerprint)
            return {"ssl_certfile": str(self.certificate), "ssl_keyfile": str(self.key),
                    "ssl_keyfile_password": password, "ssl_version": ssl.PROTOCOL_TLS_SERVER,
                    "ssl_ciphers": "ECDHE+AESGCM:ECDHE+CHACHA20"}
        except TransportError:
            raise
        except ssl.SSLError as error:
            raise TransportError(f"TLS certificate validation failed for {self.host} or 127.0.0.1: {error}. Check certificate dates, CA trust and SAN entries.") from None
        except PermissionError as error:
            raise TransportError(f"Cannot read TLS material: permission denied for {error.filename or 'a configured file'}.") from None
        except (OSError, ValueError, ssl.SSLError) as error:
            raise TransportError(f"TLS startup validation failed: {error}. Check key/certificate match, validity, CA trust and SANs for {self.host} and 127.0.0.1.") from None

    def connection(self, port, timeout=60):
        return PinnedHTTPSConnection("127.0.0.1", port, timeout=timeout,
                                     context=self.client_context(), fingerprint=self.fingerprint)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, fingerprint, **kwargs):
        self.fingerprint = fingerprint
        super().__init__(*args, **kwargs)

    def connect(self):
        super().connect()  # Chain and hostname validation happens first.
        actual = hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(actual, self.fingerprint):
            self.close()
            raise ssl.SSLCertVerificationError("TLS server identity changed; request was not sent")


class _PinnedHandler(urllib.request.HTTPSHandler):
    def __init__(self, settings):
        super().__init__(context=settings.client_context())
        self.settings = settings

    def https_open(self, request):
        def connection(host, **kwargs):
            return PinnedHTTPSConnection(host, fingerprint=self.settings.fingerprint, **kwargs)
        return self.do_open(connection, request, context=self._context)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise TransportError("HTTPS redirects are disabled; server identity must remain unchanged")


def open_local(request, timeout):
    settings = TLSSettings.load()
    from urllib.parse import urlsplit
    url = urlsplit(request.full_url)
    if url.scheme != "https" or url.hostname != "127.0.0.1" or url.username or url.password:
        raise TransportError("Desktop requests require direct loopback HTTPS")
    # Do not send secrets through environment-configured HTTP(S) proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         _PinnedHandler(settings), _NoRedirect())
    return opener.open(request, timeout=timeout)


def verify_in_memory(server_context, client_context, hostname, fingerprint):
    server_in, server_out, client_in, client_out = (ssl.MemoryBIO() for _ in range(4))
    server = server_context.wrap_bio(server_in, server_out, server_side=True)
    client = client_context.wrap_bio(client_in, client_out, server_hostname=hostname)
    done = [False, False]
    for _ in range(20):
        for index, peer in enumerate((client, server)):
            if not done[index]:
                try:
                    peer.do_handshake()
                    done[index] = True
                except ssl.SSLWantReadError:
                    pass
        if client_out.pending:
            server_in.write(client_out.read())
        if server_out.pending:
            client_in.write(server_out.read())
        if all(done):
            if not hmac.compare_digest(hashlib.sha256(client.getpeercert(binary_form=True)).hexdigest(), fingerprint):
                raise TransportError("TLS server identity changed")
            return
    raise TransportError("TLS handshake validation did not complete")
