import asyncio
import json
import os
import ssl
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

import uvicorn
from app import main
from app.transport import (TLSSettings, TransportError, PinnedHTTPSConnection,
                           open_local, verify_in_memory)
from test_auth import request
from tls_test_support import PASSWORD, make_pki


@contextmanager
def local_server(settings, replacement=False, redirect=None):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass  # Expected when a pin mismatch closes TLS without HTTP.
        def do_GET(self):
            seen.append(dict(self.headers))
            if redirect:
                self.send_response(302)
                self.send_header("Location", redirect)
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        def log_message(self, *args): pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert = settings.certificate.parent / "replacement.pem" if replacement else settings.certificate
    key = settings.key.parent / "replacement-key.pem" if replacement else settings.key
    context.load_cert_chain(cert, key, PASSWORD)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="devdrop-transport-test-")
        cls.addClassCleanup(directory.cleanup)
        cls.root = Path(directory.name)
        cls.config = make_pki(cls.root)
        cls.env = patch.dict(os.environ, {"DEVDROP_TLS_CONFIG": str(cls.config)})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)

    def test_tls_configuration_validates_material_and_minimum_version(self):
        settings = TLSSettings.load()
        options = settings.server_options(PASSWORD)
        config = uvicorn.Config(main.app, proxy_headers=False, **options)
        config.load()
        self.assertIsInstance(config.ssl, ssl.SSLContext)
        self.assertGreaterEqual(config.ssl.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertFalse(config.proxy_headers)
        self.assertTrue(settings.client_context().check_hostname)
        self.assertEqual(settings.client_context().verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(settings.url(8765), "https://localhost:8765")

    def test_wrong_key_password_and_missing_configuration_fail_closed(self):
        with self.assertRaises(TransportError): TLSSettings.load().server_options("wrong")
        with self.assertRaises(TransportError): TLSSettings.load().server_options("")
        with patch.dict(os.environ, {"DEVDROP_TLS_CONFIG": str(self.root / "missing.json")}):
            with self.assertRaises(TransportError): TLSSettings.load()

    def test_replaced_local_certificate_requires_explicit_pin_update(self):
        data = json.loads(self.config.read_text())
        data["certificate"] = str(self.root / "replacement.pem")
        changed = self.root / "changed.json"
        changed.write_text(json.dumps(data))
        with patch.dict(os.environ, {"DEVDROP_TLS_CONFIG": str(changed)}):
            with self.assertRaisesRegex(TransportError, "identity changed"):
                TLSSettings.load()

    @unittest.skipIf(os.name == "nt", "POSIX permissions; Windows uses encrypted key and user ACLs")
    def test_private_key_permissions_are_enforced(self):
        key = TLSSettings.load().key
        key.chmod(0o644)
        try:
            with self.assertRaisesRegex(TransportError, "owner-only"):
                TLSSettings.load().server_options(PASSWORD)
        finally:
            key.chmod(0o600)

    def test_unencrypted_private_key_is_refused(self):
        key = self.root / "plain-key.pem"
        key.write_text("-----BEGIN PRIVATE KEY-----\nnot-used\n-----END PRIVATE KEY-----")
        if os.name != "nt":
            key.chmod(0o600)
        with self.assertRaisesRegex(TransportError, "encrypted PKCS#8"):
            replace(TLSSettings.load(), key=key).server_options(PASSWORD)

    def test_verified_gui_https_client(self):
        settings = TLSSettings.load()
        with local_server(settings) as (port, seen):
            req = urllib.request.Request(f"https://127.0.0.1:{port}/", headers={"Authorization": "Bearer test-only"})
            with open_local(req, timeout=2) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(seen[0]["Authorization"], "Bearer test-only")

    def test_untrusted_certificate_sends_no_http_headers(self):
        settings = TLSSettings.load()
        with local_server(settings) as (port, seen):
            connection = PinnedHTTPSConnection("127.0.0.1", port, context=ssl.create_default_context(),
                                                fingerprint=settings.fingerprint, timeout=2)
            try:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    connection.request("GET", "/", headers={"Authorization": "Bearer must-not-send"})
            finally:
                connection.close()
            self.assertEqual(seen, [])

    def test_changed_server_identity_under_same_ca_sends_no_headers(self):
        settings = TLSSettings.load()
        with local_server(settings, replacement=True) as (port, seen):
            connection = settings.connection(port, timeout=2)
            try:
                with self.assertRaisesRegex(ssl.SSLCertVerificationError, "identity changed"):
                    connection.request("GET", "/", headers={"Authorization": "Bearer must-not-send"})
            finally:
                connection.close()
            self.assertEqual(seen, [])

    def test_hostname_mismatch_fails(self):
        settings = TLSSettings.load()
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.load_cert_chain(settings.certificate, settings.key, PASSWORD)
        with self.assertRaises(ssl.SSLCertVerificationError):
            verify_in_memory(server, settings.client_context(), "192.0.2.100", settings.fingerprint)

    def test_http_url_and_redirect_are_not_followed(self):
        req = urllib.request.Request("http://127.0.0.1:8765/api/pair", data=b"secret")
        with self.assertRaises(TransportError): open_local(req, timeout=2)
        settings = TLSSettings.load()
        with local_server(settings, redirect="http://127.0.0.1:1/leak") as (port, seen):
            with self.assertRaisesRegex(TransportError, "redirects are disabled"):
                open_local(urllib.request.Request(f"https://127.0.0.1:{port}/"), timeout=2)
            self.assertEqual(len(seen), 1)

    def test_http_routes_fail_before_body_read_even_with_forwarded_proto(self):
        async def run(path):
            messages = []
            async def receive():
                raise AssertionError("Insecure request body was read")
            async def send(message): messages.append(message)
            await main.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                            "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
                            "query_string": b"", "root_path": "", "client": ("127.0.0.1", 1),
                            "server": ("127.0.0.1", 8765), "headers": [(b"x-forwarded-proto", b"https")]}, receive, send)
            self.assertEqual(messages[0]["status"], 426)
        for path in ("/api/pair", "/api/text", "/api/upload", "/api/transfer-requests"):
            asyncio.run(run(path))
        self.assertEqual(request("/api/pairing-code", host="127.0.0.1", scheme="http")[0], 426)


    def test_cli_missing_tls_does_not_start_server_or_create_session(self):
        import devdrop
        with patch("devdrop.TLSSettings.load", side_effect=TransportError("TLS missing")), patch(
            "devdrop.uvicorn.run"
        ) as start, patch("devdrop.create_session_folder") as create:
            devdrop.main()
        start.assert_not_called()
        create.assert_not_called()

    def test_gui_manager_passes_tls_options_and_does_not_fallback(self):
        from devdrop_gui import BackendManager
        from app.config import DevDropConfig
        manager = BackendManager(DevDropConfig(self.root / "sessions"))
        with patch.object(manager, "_is_devdrop_available", return_value=False), patch.object(
            manager, "_port_accepts_connections", return_value=False
        ), patch("devdrop_gui.QInputDialog.getText", return_value=(PASSWORD, True)), patch(
            "devdrop_gui.ensure_firewall_rule", return_value=(True, "test")
        ), patch("devdrop_gui.threading.Thread"), patch.object(main, "SESSION_DIR"), patch.object(
            main, "HISTORY_PATH"
        ), patch.object(main, "SERVER_PORT"), patch("devdrop_gui.uvicorn.Server") as server:
            manager.ensure_backend()
            config = server.call_args.args[0]
            self.assertTrue(config.is_ssl)
            self.assertFalse(config.proxy_headers)
            self.assertEqual(config.ssl_certfile, str(TLSSettings.load().certificate))
        manager = BackendManager(DevDropConfig(self.root / "unused"))
        with patch.object(manager, "_is_devdrop_available", return_value=False), patch.object(
            manager, "_port_accepts_connections", return_value=False
        ), patch("devdrop_gui.QInputDialog.getText", return_value=("", False)), patch(
            "devdrop_gui.uvicorn.Server"
        ) as server:
            with self.assertRaises(TransportError): manager.ensure_backend()
            server.assert_not_called()
