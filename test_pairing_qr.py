import threading
import unittest

from app.pairing import PairingError, PairingService


class QRPairingTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.issued = []
        self.service = PairingService(lambda: self.issued.append("bearer") or "bearer",
                                      lifetime=120, clock=lambda: self.now[0])
        self.window = self.service.window()
        self.claim_data = dict(attempt_id=self.window["attempt_id"], token=self.window["token"],
                               poll_key="p" * 48, code="035271", device="Android phone", peer="192.0.2.1")

    def test_owner_approval_issues_session_only_after_matching_code(self):
        claimed = self.service.claim(**self.claim_data)
        self.assertEqual(self.issued, [])
        self.assertEqual(self.service.pending()[0]["device"], "Android phone")
        self.assertEqual(self.service.window()["state"], "waiting_for_owner")
        with self.assertRaisesRegex(PairingError, "did not match"):
            self.service.decide(claimed["attempt_id"], "035272", True)
        self.assertEqual(self.issued, [])
        self.assertEqual(self.service.result(claimed["attempt_id"], "p" * 48)["state"], "rejected")

    def test_approval_and_poll_deliver_bearer_exactly_once(self):
        claimed = self.service.claim(**self.claim_data)
        self.assertEqual(self.service.decide(claimed["attempt_id"], "035271", True)["state"], "approved")
        result = self.service.result(claimed["attempt_id"], "p" * 48)
        self.assertEqual(result, {"state": "approved", "token": "bearer"})
        self.assertEqual(self.service.result(claimed["attempt_id"], "p" * 48), {"state": "delivered"})
        self.assertEqual(self.issued, ["bearer"])

    def test_qr_token_is_single_use_under_concurrent_claims(self):
        barrier = threading.Barrier(8)
        results = []
        def claim(index):
            barrier.wait()
            data = dict(self.claim_data, code=f"{index:06d}", poll_key=f"p{index}" * 24)
            try:
                results.append(self.service.claim(**data))
            except PairingError:
                results.append(None)
        threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.service.pending()), 1)

    def test_expired_qr_cannot_be_claimed(self):
        self.now[0] += 121
        with self.assertRaisesRegex(PairingError, "expired"):
            self.service.claim(**self.claim_data)

    def test_poll_key_is_required_and_rejection_creates_no_session(self):
        claimed = self.service.claim(**self.claim_data)
        self.service.decide(claimed["attempt_id"], "", False)
        with self.assertRaises(PairingError):
            self.service.result(claimed["attempt_id"], "wrong" * 10)
        self.assertEqual(self.service.result(claimed["attempt_id"], "p" * 48)["state"], "rejected")
        self.assertEqual(self.issued, [])

    def test_claim_rate_limit_is_per_peer(self):
        for _ in range(8):
            window = self.service.window()
            created = self.service.claim(window["attempt_id"], window["token"], "p" * 48,
                                         "035271", "phone", "192.0.2.1")
            self.service.decide(created["attempt_id"], "", False)
        window = self.service.window()
        with self.assertRaisesRegex(PairingError, "Too many"):
            self.service.claim(window["attempt_id"], window["token"], "p" * 48,
                               "035271", "phone", "192.0.2.1")


if __name__ == "__main__":
    unittest.main()
