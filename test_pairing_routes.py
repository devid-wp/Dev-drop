"""ASGI-level checks for QR pairing owner and phone endpoints."""
import asyncio
import json
import unittest
from unittest.mock import patch

from app import main
from app.pairing import PairingService


def call(path, method="GET", payload=None, headers=None, peer="127.0.0.1"):
    raw = json.dumps(payload).encode() if payload is not None else b""
    hdrs = [(b"host", b"localhost:8765"), (b"content-type", b"application/json")]
    hdrs.extend((key.lower().encode(), value.encode()) for key, value in (headers or {}).items())
    output = []
    async def run():
        sent = False
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            await asyncio.Event().wait()
        async def send(message): output.append(message)
        await main.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                        "method": method, "scheme": "https", "path": path,
                        "raw_path": path.encode(), "query_string": b"", "root_path": "",
                        "headers": hdrs, "client": (peer, 54321),
                        "server": ("127.0.0.1", 8765)}, receive, send)
    asyncio.run(run())
    return output[0]["status"], json.loads(b"".join(message.get("body", b"") for message in output))


class QRPairingRouteTests(unittest.TestCase):
    def setUp(self):
        self.sessions_patch = patch.object(main, "sessions", {})
        self.sessions_patch.start()
        self.addCleanup(self.sessions_patch.stop)
        self.info_patch = patch.object(main, "session_client_info", {})
        self.info_patch.start()
        self.addCleanup(self.info_patch.stop)
        self.service_patch = patch.object(main, "qr_pairing", PairingService(main.create_session))
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

    def test_phone_claims_then_owner_approves_and_phone_gets_one_bearer(self):
        window = main.qr_pairing.window()
        payload = {**window, "poll_key": "poll" * 12, "code": "120034", "device": "Pixel"}
        status, claim = call("/api/pairing/claims", "POST", payload, peer="192.168.1.20")
        self.assertEqual(status, 200)
        identity = claim["attempt_id"]
        self.assertEqual(call("/api/pairing/requests")[1]["requests"][0]["device"], "Pixel")
        status, approved = call(f"/api/pairing/requests/{identity}/approve", "POST", {"code": "120034"})
        self.assertEqual(status, 200)
        self.assertNotIn("token", approved)
        headers = {"X-Pairing-Poll-Key": payload["poll_key"]}
        status, result = call(f"/api/pairing/claims/{identity}", headers=headers, peer="192.168.1.20")
        self.assertEqual(status, 200)
        self.assertTrue(main.session_is_valid(result["token"]))
        self.assertEqual(call(f"/api/pairing/claims/{identity}", headers=headers, peer="192.168.1.20")[1],
                         {"state": "delivered"})

    def test_management_routes_remain_loopback_only_and_code_mismatch_rejects(self):
        window = main.qr_pairing.window()
        claim = {**window, "poll_key": "poll" * 12, "code": "120034", "device": "Pixel"}
        _, created = call("/api/pairing/claims", "POST", claim, peer="192.168.1.20")
        identity = created["attempt_id"]
        self.assertEqual(call("/api/pairing/requests")[0], 200)
        self.assertEqual(call("/api/pairing/requests", peer="192.168.1.20")[0], 403)
        status, _ = call(f"/api/pairing/requests/{identity}/approve", "POST", {"code": "999999"})
        self.assertEqual(status, 403)
        result = call(f"/api/pairing/claims/{identity}", headers={"X-Pairing-Poll-Key": claim["poll_key"]},
                      peer="192.168.1.20")[1]
        self.assertEqual(result["state"], "rejected")
        self.assertEqual(main.sessions, {})


if __name__ == "__main__":
    unittest.main()
