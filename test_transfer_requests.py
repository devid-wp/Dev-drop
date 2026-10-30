import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import main
from app.transfer_requests import TransferDescription, TransferError, TransferService
from test_auth import request


def description(kind="text", data=b"hello"):
    fields = dict(type=kind, sender="Claimed name", description="hello",
                  size=len(data), sha256=hashlib.sha256(data).hexdigest())
    if kind == "file":
        fields.pop("sha256")
        fields["files"] = [{"name": "a.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]
    return TransferDescription(**fields)


class TransferServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.service = TransferService(clock=lambda: self.now)

    def create(self, kind="text"):
        return self.service.create("session-a", description(kind))["id"]

    def consume(self, identity, **kwargs):
        fields = dict(kind="text", size=5, digest=hashlib.sha256(b"hello").hexdigest())
        fields.update(kwargs)
        self.service.consume(identity, "session-a", **fields)

    def test_approval_is_one_use(self):
        identity = self.create()
        self.assertEqual(self.service.state(identity, "session-a")["status"], "pending")
        with self.assertRaises(TransferError): self.consume(identity)
        self.service.decide(identity, True)
        self.consume(identity)
        self.assertTrue(self.service.state(identity, "session-a")["used"])
        with self.assertRaises(TransferError): self.consume(identity)
        self.assertNotIn("session", self.service.state(identity, "session-a"))

    def test_rejection_cancellation_and_expiration(self):
        for state in ["rejected", "cancelled", "expired"]:
            with self.subTest(state=state):
                identity = self.create()
                if state == "rejected": self.service.decide(identity, False)
                if state == "cancelled": self.service.cancel(identity, "session-a")
                if state == "expired":
                    self.service.decide(identity, True)
                    self.now += 121
                self.assertEqual(self.service.state(identity, "session-a")["status"], state)
                with self.assertRaises(TransferError): self.consume(identity)
                with self.assertRaises(TransferError): self.service.decide(identity, True)

    def test_other_session_cannot_read_cancel_or_consume(self):
        identity = self.create()
        self.service.decide(identity, True)
        for operation in [lambda: self.service.state(identity, "session-b"),
                          lambda: self.service.cancel(identity, "session-b"),
                          lambda: self.service.consume(identity, "session-b", "text", 5)]:
            with self.assertRaises(TransferError): operation()
        self.consume(identity)

    def test_type_size_digest_and_manifest_are_bound(self):
        identity = self.create()
        self.service.decide(identity, True)
        for mismatch in [dict(kind="link"), dict(size=6), dict(digest="0" * 64)]:
            with self.assertRaises(TransferError): self.consume(identity, **mismatch)
        self.consume(identity)
        identity = self.create("file")
        self.service.decide(identity, True)
        manifest = description("file").model_dump()["files"]
        for field, value in [("name", "b.txt"), ("size", 6), ("sha256", "0" * 64)]:
            altered = [dict(manifest[0], **{field: value})]
            with self.assertRaises(TransferError):
                self.consume(identity, kind="file", digest=None, files=altered)
        self.consume(identity, kind="file", digest=None, files=manifest)

    def test_concurrent_consumers_only_one_succeeds(self):
        identity = self.create()
        self.service.decide(identity, True)
        def attempt(_):
            try:
                self.consume(identity)
                return True
            except TransferError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(40))), 1)

    def test_concurrent_creation_and_limits(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            identities = list(pool.map(lambda _: self.create(), range(20)))
        self.assertEqual(len(set(identities)), 20)
        with self.assertRaises(TransferError): self.create()
        self.now += 121
        self.assertEqual(self.service.pending(), [])
        self.create()

    def test_restart_has_no_permissions(self):
        identity = self.create()
        with self.assertRaises(TransferError): TransferService().state(identity, "session-a")


class TransferAPITests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(main, "SESSION_DIR", self.root))
        self.enterContext(patch.object(main, "transfer_service", TransferService()))
        self.enterContext(patch.object(main, "sessions", {}))
        main.invalidate_session_stats()
        self.addCleanup(main.invalidate_session_stats)
        self.token = main.create_session()
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def create(self, kind="text", data=b"hello"):
        status, body = request("/api/transfer-requests", "POST", description(kind, data).model_dump(), self.headers)
        self.assertEqual(status, 200)
        return json.loads(body)["id"]

    def test_owner_approval_and_replay_protection(self):
        identity = self.create()
        status, body = request("/api/transfer-requests", host="127.0.0.1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["requests"][0]["id"], identity)
        headers = dict(self.headers, **{"X-Transfer-ID": identity})
        self.assertEqual(request("/api/text", "POST", {"content": "hello"}, headers)[0], 409)
        self.assertEqual(list(self.root.iterdir()), [])
        path = f"/api/transfer-requests/{identity}/approve"
        self.assertEqual(request(path, "POST", host="127.0.0.1")[0], 200)
        self.assertEqual(request("/api/text", "POST", {"content": "hello"}, headers)[0], 200)
        self.assertEqual(request("/api/text", "POST", {"content": "hello"}, headers)[0], 409)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_owner_endpoints_deny_remote_spoofed_and_cross_origin(self):
        identity = self.create()
        for path, method in [("/api/transfer-requests", "GET"),
                             (f"/api/transfer-requests/{identity}/approve", "POST"),
                             (f"/api/transfer-requests/{identity}/reject", "POST")]:
            self.assertEqual(request(path, method, headers={"X-Forwarded-For": "127.0.0.1"})[0], 403)
            for headers in [{"Origin": "http://evil.example"}, {"Host": "evil.example"}]:
                self.assertEqual(request(path, method, headers=headers, host="127.0.0.1")[0], 403)

    def test_missing_permission_and_foreign_session_and_substitution(self):
        self.assertEqual(request("/api/text", "POST", {"content": "hello"}, self.headers)[0], 409)
        identity = self.create()
        main.transfer_service.decide(identity, True)
        other = main.create_session()
        other_headers = {"Authorization": f"Bearer {other}", "X-Transfer-ID": identity}
        self.assertEqual(request(f"/api/transfer-requests/{identity}", headers=other_headers)[0], 409)
        self.assertEqual(request("/api/text", "POST", {"content": "hello"}, other_headers)[0], 409)
        headers = dict(self.headers, **{"X-Transfer-ID": identity})
        for payload in [{"content": "other"}, {"content": "hello", "type": "link"}]:
            self.assertEqual(request("/api/text", "POST", payload, headers)[0], 409)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_link_and_cancel(self):
        identity = self.create("link", b"https://example.com")
        main.transfer_service.decide(identity, True)
        headers = dict(self.headers, **{"X-Transfer-ID": identity})
        self.assertEqual(request("/api/text", "POST", {"content": "https://example.com", "type": "link"}, headers)[0], 200)
        identity = self.create()
        self.assertEqual(request(f"/api/transfer-requests/{identity}/cancel", "POST", headers=self.headers)[0], 200)

    def test_rejected_expired_and_pending_text_do_not_write(self):
        for state in ("pending", "rejected", "expired"):
            identity = self.create()
            if state == "rejected":
                main.transfer_service.decide(identity, False)
            if state == "expired":
                expiry = main.transfer_service.state(identity, self.token)["expires_at"]
                with patch.object(main.transfer_service, "clock", return_value=expiry + 1):
                    main.transfer_service.pending()
            headers = dict(self.headers, **{"X-Transfer-ID": identity})
            self.assertEqual(request("/api/text", "POST", {"content": "hello"}, headers)[0], 409)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_unapproved_upload_body_is_not_parsed(self):
        # Even a malformed multipart body must be refused at the header gate.
        headers = dict(self.headers, **{"Content-Type": "multipart/form-data"})
        with patch("starlette.requests.Request.form", side_effect=AssertionError("Body parsed before approval")):
            self.assertEqual(request("/api/upload", "POST", headers=headers)[0], 409)

    def test_gui_waits_for_explicit_owner_decision(self):
        from devdrop_gui import BackendClient
        from urllib.parse import urlsplit
        source = self.root / "gui.txt"
        source.write_bytes(b"hello")
        client = BackendClient(8765)
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        def urlopen(req, **kwargs):
            path = urlsplit(req.full_url).path
            if req.get_method() == "GET":
                identity = path.rsplit("/", 1)[-1]
                self.assertEqual(main.transfer_service.state(identity, self.token)["status"], "pending")
                self.assertEqual(request(path + "/approve", "POST", host="127.0.0.1")[0], 200)
            status, body = request(path, req.get_method(), json.loads(req.data) if req.data else None,
                                   {"Authorization": req.get_header("Authorization")})
            self.assertEqual(status, 200)
            return Response(body)
        with patch("devdrop_gui.urllib.request.urlopen", side_effect=urlopen):
            identity = client.await_approval([source], self.token)
        main.transfer_service.consume(identity, self.token, "file", 5,
                                      files=[{"name": "gui.txt", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest()}])

    def test_creation_requires_session_and_valid_manifest(self):
        self.assertEqual(request("/api/transfer-requests", "POST", description().model_dump())[0], 401)
        invalid = description("file").model_dump()
        invalid["size"] = 100
        self.assertEqual(request("/api/transfer-requests", "POST", invalid, self.headers)[0], 422)
