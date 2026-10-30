import hashlib
import io
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.file_offers import FileOfferService, OfferError
from app.relay import RelayCreate, RelayError, RelayService
from app.transfer_requests import TransferService, TransferError


A, B, C = 'session-a', 'session-b', 'session-c'
B_ID = hashlib.sha256(B.encode()).hexdigest()
A_ID = hashlib.sha256(A.encode()).hexdigest()


def description(data=b'hello'):
    return RelayCreate(type='file', sender='claimed name', description='relay file', recipient_id=B_ID,
        files=[{'name':'../../example.txt', 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}])


class RelayServiceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.now = 100.0
        self.approvals = TransferService(clock=lambda:self.now)
        self.offers = FileOfferService(directory=self.root, clock=lambda:self.now)
        self.addCleanup(self.offers.close)
        self.relays = RelayService(self.approvals, self.offers, lambda token:token in {A,B,C}, clock=lambda:self.now)

    def create(self, approve=False):
        relay = self.relays.create(A, B, A_ID, description())
        if approve: self.approvals.decide(relay['id'], True)
        return relay['id']

    def upload(self, identity):
        return self.relays.upload(identity, A, description().model_dump()['files'], io.BytesIO(b'hello'))

    def test_owner_approval_and_recipient_accept_are_both_required(self):
        identity = self.create()
        with self.assertRaises(RelayError): self.upload(identity)
        self.approvals.decide(identity, True)
        relay = self.upload(identity)
        self.assertEqual(relay['status'], 'offered')
        self.assertEqual(self.offers.list(B)[0]['filename'], 'example.txt')
        with self.assertRaises(OfferError): self.offers.claim(relay['offer_id'], '', lambda _:True)
        _, grant = self.offers.accept(relay['offer_id'], B)
        _, source = self.offers.claim(relay['offer_id'], grant, lambda _:True)
        with source: self.assertEqual(source.read(), b'hello')
        self.offers.finish(relay['offer_id'], True)
        self.assertEqual(self.relays.state(identity, A)['status'], 'sent')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_owner_and_recipient_rejection(self):
        identity = self.create()
        self.approvals.decide(identity, False)
        self.assertEqual(self.relays.state(identity, A)['status'], 'rejected')
        with self.assertRaises(RelayError): self.upload(identity)
        identity = self.create(True)
        offer = self.upload(identity)['offer_id']
        self.offers.reject(offer, B)
        self.assertEqual(self.relays.state(identity, A)['status'], 'rejected')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_foreign_session_and_old_upload_permission_bypass(self):
        identity = self.create(True)
        with self.assertRaises(RelayError): self.relays.state(identity, C)
        with self.assertRaises(RelayError): self.relays.cancel(identity, B)
        with self.assertRaises(RelayError): self.relays.check_upload(identity, B)
        with self.assertRaises(TransferError): self.approvals.check_approved(identity, A)
        with self.assertRaises(TransferError):
            self.approvals.consume(identity, A, 'file', 5, files=description().model_dump()['files'])
        self.upload(identity)
        with self.assertRaises(RelayError): self.upload(identity)

    def test_recipient_or_content_cannot_be_substituted(self):
        identity = self.create(True)
        with self.assertRaises(TransferError):
            self.approvals.consume(identity, A, 'file', 5, files=description().model_dump()['files'], recipient_id='0'*64)
        altered = description(b'other').model_dump()['files']
        with self.assertRaises(TransferError): self.relays.upload(identity, A, altered, io.BytesIO(b'other'))
        relay = self.upload(identity)
        self.assertEqual(self.offers.list(C), [])
        self.assertEqual(self.offers.list(B)[0]['id'], relay['offer_id'])

    def test_expiry_during_approval_and_after_accept(self):
        identity = self.create(True)
        self.now += 121
        with self.assertRaises(RelayError): self.upload(identity)
        identity = self.create(True)
        relay = self.upload(identity)
        _, grant = self.offers.accept(relay['offer_id'], B)
        self.now = relay['expires_at']
        with self.assertRaises(OfferError): self.offers.claim(relay['offer_id'], grant, lambda _:True)
        self.assertEqual(self.relays.state(identity,A)['status'], 'expired')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_pending_accepted_and_streaming(self):
        identity = self.create()
        self.relays.cancel(identity,A)
        with self.assertRaises(RelayError): self.relays.check_upload(identity,A)
        for streaming in (False, True):
            identity = self.create(True)
            relay = self.upload(identity)
            _, grant = self.offers.accept(relay['offer_id'], B)
            source = None
            if streaming: _, source = self.offers.claim(relay['offer_id'], grant, lambda _:True)
            self.relays.cancel(identity,A)
            with self.assertRaises(OfferError): self.offers.claim(relay['offer_id'], grant, lambda _:True)
            with self.assertRaises(OfferError): self.offers.check_streaming(relay['offer_id'])
            if source: source.close()
            self.offers.finish(relay['offer_id'],False)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancellation_during_disk_copy_never_publishes(self):
        started, resume = threading.Event(), threading.Event()
        class PausedStream(io.BytesIO):
            def read(self, size=-1):
                started.set()
                if not resume.wait(3): raise RuntimeError('Test timeout')
                return super().read(size)
        identity = self.create(True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.relays.upload,identity,A,description().model_dump()['files'],PausedStream(b'hello'))
            try:
                self.assertTrue(started.wait(3))
                self.relays.cancel(identity,A)
            finally: resume.set()
            with self.assertRaises(RelayError): future.result(timeout=3)
        self.assertEqual(self.offers.list(B), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_concurrent_uploads_spend_approval_once(self):
        identity = self.create(True)
        def upload(_):
            try: self.upload(identity); return 1
            except (RelayError, TransferError): return 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(upload,range(20))),1)
        self.assertEqual(len(self.offers.list(B)),1)


    def test_copy_failure_or_expiry_never_leaves_a_published_file(self):
        identity = self.create(True)
        class BrokenStream:
            def read(self, size): raise OSError("disk failure")
        with self.assertRaises(OfferError):
            self.relays.upload(identity,A,description().model_dump()['files'],BrokenStream())
        self.assertEqual(self.relays.state(identity,A)['status'],'failed')
        self.assertEqual(list(self.root.iterdir()),[])
        identity = self.create(True)
        owner = self
        class ExpiringStream(io.BytesIO):
            def read(self, size=-1):
                owner.now += 301
                return super().read(size)
        with self.assertRaises(OfferError):
            self.relays.upload(identity,A,description().model_dump()['files'],ExpiringStream(b'hello'))
        self.assertEqual(self.offers.list(B),[])
        self.assertEqual(list(self.root.iterdir()),[])
