import importlib.util
import json
import os
import socket
import tempfile
import threading
import time
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import patch

import uvicorn
from app import main
from app.tls_setup import provision_local_tls, tls_for_server
from app.transport import TLSSettings, TransportError


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography package required")
class TLSFirstRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devdrop-first-run-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "tls.json"
        self.base_patch = patch("app.tls_setup.config_dir", return_value=self.root)
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)
        self.env_patch = patch.dict(os.environ, {"DEVDROP_TLS_CONFIG": str(self.config)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_first_run_uses_os_protected_key_without_password_prompt(self):
        tls, password = tls_for_server(lambda: True,
                                       lambda _confirm: self.fail("normal mode must not ask for a password"),
                                       lambda: False)
        self.assertIsNone(password)
        self.assertEqual(tls, TLSSettings.load())
        self.assertTrue(self.config.is_file())
        self.assertIn("BEGIN PRIVATE KEY", tls.key.read_text(encoding="ascii"))
        self.assertEqual(tls.key_mode, "os")
        self.assertTrue(tls.server_options(None)["ssl_certfile"])

    def test_advanced_mode_keeps_encrypted_key(self):
        prompts = iter(("friendly local test password", "friendly local test password"))
        tls, password = tls_for_server(lambda: True, lambda _confirm: next(prompts), lambda: True)
        self.assertEqual(password, "friendly local test password")
        self.assertEqual(tls.key_mode, "password")
        self.assertIn("ENCRYPTED PRIVATE KEY", tls.key.read_text(encoding="ascii"))
        self.assertTrue(tls.server_options(password)["ssl_certfile"])

    def test_legacy_encrypted_identity_migrates_only_after_consent(self):
        tls = provision_local_tls("legacy migration password")
        legacy_config = json.loads(self.config.read_text(encoding="utf-8"))
        legacy_config.pop("security_mode")
        self.config.write_text(json.dumps(legacy_config), encoding="utf-8")
        ca = tls.ca.read_bytes()
        certificate = tls.certificate.read_bytes()
        encrypted_server_key = tls.key
        encrypted_ca_key = self.root / "ca" / "ca-key.pem"
        migrated, password = tls_for_server(
            lambda: self.fail("existing identity must not trigger new CA setup"),
            lambda _confirm: "legacy migration password",
            passwordless_migration_prompt=lambda: True,
        )
        self.assertIsNone(password)
        self.assertEqual(migrated.key_mode, "os")
        self.assertEqual(migrated.ca.read_bytes(), ca)
        self.assertEqual(migrated.certificate.read_bytes(), certificate)
        self.assertTrue(encrypted_server_key.exists())
        self.assertTrue(encrypted_ca_key.exists())
        self.assertIn("ENCRYPTED PRIVATE KEY", encrypted_server_key.read_text(encoding="ascii"))
        self.assertIn("BEGIN PRIVATE KEY", migrated.key.read_text(encoding="ascii"))

    def test_declining_first_run_does_not_create_files(self):
        with self.assertRaisesRegex(TransportError, "declined"):
            tls_for_server(lambda: False, lambda _confirm: self.fail("should not request password"))
        self.assertFalse(self.config.exists())
        self.assertFalse((self.root / "ca").exists())

    def test_repeat_run_reuses_config_and_ca_without_prompts(self):
        tls = provision_local_tls()
        original_ca = tls.ca.read_bytes()
        original_cert = tls.certificate.read_bytes()
        loaded, password = tls_for_server(lambda: self.fail("repeat run must not ask consent"),
                                          lambda _confirm: self.fail("repeat run must not ask setup password"))
        self.assertIsNone(password)
        self.assertEqual(loaded.ca.read_bytes(), original_ca)
        self.assertEqual(loaded.certificate.read_bytes(), original_cert)

    def test_existing_ca_and_leaf_are_reused_when_config_is_missing(self):
        first = provision_local_tls()
        ca_bytes = first.ca.read_bytes()
        cert_bytes = first.certificate.read_bytes()
        key_bytes = first.key.read_bytes()
        self.config.unlink()
        with patch("app.tls_setup._issue_ca", side_effect=AssertionError("must reuse CA")), \
             patch("app.tls_setup._issue_server", side_effect=AssertionError("must reuse server key and certificate")):
            restored = provision_local_tls()
        self.assertEqual(restored.ca.read_bytes(), ca_bytes)
        self.assertEqual(restored.certificate.read_bytes(), cert_bytes)
        self.assertEqual(restored.key.read_bytes(), key_bytes)

    def test_wrong_key_password_has_specific_error(self):
        tls, _ = tls_for_server(lambda: True, lambda _confirm: "correct local password", lambda: True)
        with self.assertRaisesRegex(TransportError, "password is incorrect"):
            tls.server_options("incorrect local password")

    def test_provisioned_identity_starts_fastapi_over_verified_https(self):
        tls = provision_local_tls()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = uvicorn.Config(main.app, host="127.0.0.1", port=port,
                                proxy_headers=False, log_level="critical",
                                lifespan="off", **tls.server_options(None))
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not server.started:
                time.sleep(0.02)
            self.assertTrue(server.started, "Uvicorn did not start")
            request = urllib.request.Request(f"https://127.0.0.1:{port}/api/health")
            with urllib.request.urlopen(request, context=tls.client_context(), timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["app"], "DevDrop")
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "Uvicorn server did not shut down")

    def test_lan_ip_change_reissues_leaf_and_preserves_ca_and_key(self):
        initial = (["localhost"], ["127.0.0.1", "::1", "192.168.1.10"], "192.168.1.10")
        changed = (["localhost"], ["127.0.0.1", "::1", "192.168.1.20"], "192.168.1.20")
        with patch("app.tls_setup._san_values", return_value=initial):
            original = provision_local_tls()
        original_ca = original.ca.read_bytes()
        original_key = original.key.read_bytes()
        original_cert = original.certificate
        with patch("app.tls_setup._san_values", return_value=changed):
            refreshed, password = tls_for_server(lambda: self.fail("existing identity must not ask consent"),
                                                  lambda _confirm: self.fail("OS-protected mode has no password"))
        self.assertIsNone(password)
        self.assertNotEqual(refreshed.certificate, original_cert)
        self.assertTrue(original_cert.exists())
        self.assertEqual(refreshed.ca.read_bytes(), original_ca)
        self.assertEqual(refreshed.key.read_bytes(), original_key)
        self.assertEqual(refreshed.host, "192.168.1.20")
        refreshed.server_options(None)

    def test_corrupt_config_is_diagnosed_and_never_overwritten(self):
        original = b'{"certificate": '
        self.config.write_bytes(original)
        with self.assertRaisesRegex(TransportError, "not valid JSON"):
            tls_for_server(lambda: self.fail("corrupt config is not first run"),
                           lambda _confirm: self.fail("do not regenerate over corrupt config"))
        self.assertEqual(self.config.read_bytes(), original)

    def test_legacy_nested_config_is_migrated_without_reissuing_certificate(self):
        tls = provision_local_tls()
        certificate = tls.certificate.read_bytes()
        data = json.loads(self.config.read_text(encoding="utf-8"))
        self.config.unlink()
        legacy = self.root / "tls" / "tls.json"
        legacy.write_text(json.dumps(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEVDROP_TLS_CONFIG", None)
            with patch("app.transport.config_dir", return_value=self.root):
                migrated = TLSSettings.load()
        self.assertTrue(self.config.exists())
        self.assertEqual(migrated.certificate.read_bytes(), certificate)
        self.assertTrue(legacy.exists())


if __name__ == "__main__":
    unittest.main()
