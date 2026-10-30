"""Ephemeral test PKI, generated with OpenSSL; never used by the application."""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from app.transport import certificate_fingerprint

PASSWORD = "test-only-password"


def make_pki(root: Path):
    if not shutil.which("openssl"):
        raise unittest.SkipTest("OpenSSL CLI required for ephemeral TLS test certificates")
    def run(*args):
        subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=20)
    ca, ca_key = root / "ca.pem", root / "ca-key.pem"
    run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
        "-keyout", ca_key, "-out", ca, "-days", "2", "-subj", "/CN=DevDrop ephemeral test CA",
        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    extensions = root / "extensions.cnf"
    extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n")
    for name in ("server", "replacement"):
        key, csr, cert = (root / (name + suffix) for suffix in ("-key.pem", ".csr", ".pem"))
        run("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
            "-aes-256-cbc", "-pass", f"pass:{PASSWORD}", "-out", key)
        if os.name != "nt": key.chmod(0o600)
        run("req", "-new", "-key", key, "-passin", f"pass:{PASSWORD}", "-out", csr, "-subj", "/CN=localhost")
        run("x509", "-req", "-in", csr, "-CA", ca, "-CAkey", ca_key, "-set_serial", "1" if name == "server" else "2",
            "-days", "2", "-extfile", extensions, "-out", cert)
    config = root / "tls.json"
    config.write_text(json.dumps({"certificate": str(root / "server.pem"), "key": str(root / "server-key.pem"),
                                  "ca": str(ca), "host": "localhost", "sha256": certificate_fingerprint(root / "server.pem")}))
    return config
