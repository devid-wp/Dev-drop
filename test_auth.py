"""Exercise real ASGI routing with explicit peer addresses and temporary data."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


def request(path, method="GET", payload=None, headers=None, host="192.0.2.10", scheme="https"):
    body = json.dumps(payload).encode() if payload is not None else b""
    raw_headers = [(b"content-type", b"application/json")]
    raw_headers += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    messages = []

    async def run():
        delivered = False
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        await main.app({"type": "http", "asgi": {"version": "3.0"},
                        "http_version": "1.1", "method": method, "scheme": scheme,
                        "path": path, "raw_path": path.encode(), "query_string": b"",
                        "root_path": "", "headers": raw_headers,
                        "client": (host, 1234), "server": ("127.0.0.1", 8765)}, receive, send)
    asyncio.run(run())
    return messages[0]["status"], b"".join(m.get("body", b"") for m in messages)


class AuthTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        self.enterContext(patch.object(main, "SESSION_DIR", self.root))
        self.enterContext(patch.object(main, "HISTORY_PATH", self.root / "history.json"))
        self.enterContext(patch.object(main, "sessions", {}))
        self.enterContext(patch.object(main, "session_client_info", {}))
        main.generate_pairing_code()
        main.invalidate_session_stats()
        self.addCleanup(main.invalidate_session_stats)

    def test_management_remote_denied_even_with_forwarded_headers(self):
        for path, method in [("/api/pairing-code", "GET"), ("/api/status", "GET"),
                             ("/api/history", "GET"), ("/api/history", "DELETE"),
                             ("/api/regenerate-pairing-code", "POST")]:
            with self.subTest(path=path, method=method):
                status, body = request(path, method, headers={"X-Forwarded-For": "127.0.0.1", "Host": "localhost"})
                self.assertEqual(status, 403)
                self.assertNotIn(main.pairing_code.encode(), body)

    def test_local_management_rejects_dns_rebinding_hosts_and_cross_site_mutations(self):
        protected=[("/api/status","GET"),("/api/history","GET"),("/api/history","DELETE"),
                   ("/api/pairing-code","GET"),("/api/regenerate-pairing-code","POST")]
        for path,method in protected:
            with self.subTest(path=path,method=method):
                self.assertEqual(request(path,method,{},headers={"Host":"attacker.example"},host="127.0.0.1")[0],403)
                self.assertEqual(request(path,method,{},headers={"Host":"localhost:8765","Origin":"https://evil.example"},host="127.0.0.1")[0],403)

    def test_local_management_remains_available(self):
        for host in ["127.0.0.1", "::1"]:
            for path in ["/api/pairing-code", "/api/status", "/api/history"]:
                with self.subTest(host=host, path=path):
                    self.assertEqual(request(path, host=host)[0], 200)

    def test_missing_invalid_expired_tokens_cannot_transfer_even_locally(self):
        main.sessions["expired"] = time.time() - main.SESSION_LIFETIME - 1
        for host in ["192.0.2.10", "127.0.0.1"]:
            for auth in [None, "Bearer wrong", "Bearer expired", "Basic wrong"]:
                for path in ["/api/text", "/api/upload"]:
                    with self.subTest(host=host, auth=auth, path=path):
                        headers = {"Authorization": auth} if auth else {}
                        status, body = request(path, "POST", {"content": "secret"}, headers, host)
                        self.assertEqual(status, 401)
                        self.assertNotIn(b"expired\"", body)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pairing_token_allows_text(self):
        status, body = request("/api/pair", "POST", {"code": main.pairing_code})
        self.assertEqual(status, 200)
        token = json.loads(body)["token"]
        from app.transfer_requests import TransferDescription
        import hashlib
        identity = main.transfer_service.create(token, TransferDescription(
            type="text", sender="test", description="hello", size=5,
            sha256=hashlib.sha256(b"hello").hexdigest()))["id"]
        main.transfer_service.decide(identity, True)
        status, body = request("/api/text", "POST", {"content": "hello"},
                               {"Authorization": f"Bearer {token}", "X-Transfer-ID": identity})
        self.assertEqual(status, 200)
        self.assertEqual((self.root / json.loads(body)["filename"]).read_text(), "hello")

    def test_pairing_code_is_consumed_once_and_owner_gets_a_fresh_code(self):
        code = main.pairing_code
        status, body = request("/api/pair", "POST", {"code": code})
        self.assertEqual(status, 200)
        first = json.loads(body)["token"]
        self.assertTrue(main.session_is_valid(first))
        self.assertEqual(main.pairing_code, "")
        self.assertEqual(request("/api/pair", "POST", {"code": code})[0], 401)
        next_code = (int(code) + 1) % 1_000_000_000
        with patch("app.main.secrets.randbelow", return_value=next_code):
            status, body = request("/api/pairing-code", host="127.0.0.1")
        self.assertEqual(status, 200)
        fresh = json.loads(body)["code"]
        self.assertNotEqual(code, fresh)
        self.assertEqual(request("/api/pair", "POST", {"code": fresh})[0], 200)

    def test_concurrent_pairing_requests_only_create_one_session(self):
        from concurrent.futures import ThreadPoolExecutor
        code = main.pairing_code
        with ThreadPoolExecutor(max_workers=12) as workers:
            results = list(workers.map(lambda _: request("/api/pair", "POST", {"code": code}), range(24)))
        accepted = [body for status, body in results if status == 200]
        rejected = [status for status, _ in results if status == 401]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 23)
        self.assertEqual(len(main.sessions), 1)

    def test_authenticated_session_revocation_only_invalidates_current_token(self):
        token = main.create_session()
        other = main.create_session()
        status, body = request("/api/session", "DELETE", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["revoked"])
        self.assertFalse(main.session_is_valid(token))
        self.assertTrue(main.session_is_valid(other))
        self.assertEqual(request("/api/session", "DELETE", headers={"Authorization": f"Bearer {token}"})[0], 401)

    def test_gui_uses_loopback_pairing_and_authorized_upload(self):
        from devdrop_gui import BackendClient, FileDropArea
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        # Execute the GUI client's pairing flow against the actual ASGI application.
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        def urlopen(req, **kwargs):
            from urllib.parse import urlsplit
            status, body = request(urlsplit(req.full_url).path, req.get_method(),
                                   json.loads(req.data) if req.data else None, host="127.0.0.1")
            self.assertEqual(status, 200)
            return Response(body)
        with patch("devdrop_gui.open_local", side_effect=urlopen):
            token = BackendClient(8765).transfer_token()
        self.assertTrue(main.session_is_valid(token))
        source = self.root / "source.txt"
        source.write_text("gui file")
        connection = MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"saved": ["source.txt"]}'
        sender = SimpleNamespace(window=lambda: SimpleNamespace(active_port=8765),
                                 _send_chunk=FileDropArea._send_chunk)
        with patch.object(BackendClient, "await_approval", return_value="approved-request") as approval, patch.object(BackendClient, "transfer_token", return_value=token), patch(
            "app.transport.TLSSettings.load"
        ) as settings:
            settings.return_value.connection.return_value = connection
            self.assertEqual(FileDropArea._upload_files(sender, [source]), ["source.txt"])
        connection.putheader.assert_any_call("Authorization", f"Bearer {token}")
        connection.putheader.assert_any_call("X-Transfer-ID", "approved-request")
        approval.assert_called_once_with([source], token)
