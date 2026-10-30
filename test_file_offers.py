import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import main
from app.file_offers import FileOfferService, OfferError
from test_auth import request


class FileOfferTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'report.txt'
        self.source.write_bytes(b'original')
        self.now = 100.0
        self.service = FileOfferService(clock=lambda: self.now, directory=self.root / 'snapshots')
        self.addCleanup(self.service.close)

    def create(self):
        return self.service.create(self.source, 'session-a', 'recipient-a')

    def test_create_list_and_safe_filename_without_private_fields(self):
        offer = self.create()
        self.assertEqual(offer['filename'], 'report.txt')
        self.assertEqual(offer['size'], 8)
        self.assertEqual(self.service.list('session-a'), [offer])
        self.assertEqual(self.service.list('session-b'), [])
        for private in ('snapshot', 'recipient', 'grant_hash', 'path'):
            self.assertNotIn(private, offer)

    def test_accept_snapshot_is_immutable_and_one_use(self):
        offer = self.create()
        self.source.write_bytes(b'changed')
        accepted, grant = self.service.accept(offer['id'], 'session-a')
        self.assertEqual(accepted['status'], 'accepted')
        metadata, stream = self.service.claim(offer['id'], grant, lambda _: True)
        with stream:
            self.assertEqual(stream.read(), b'original')
        with self.assertRaises(OfferError):
            self.service.claim(offer['id'], grant, lambda _: True)
        self.service.finish(offer['id'], True)
        self.assertEqual(self.service.list()[0]['status'], 'sent')
        self.assertEqual(list((self.root / 'snapshots').iterdir()), [])

    def test_reject_cancel_expire_are_terminal(self):
        for status in ('rejected', 'cancelled', 'expired'):
            with self.subTest(status=status):
                offer = self.create()
                if status == 'rejected': self.service.reject(offer['id'], 'session-a')
                if status == 'cancelled': self.service.cancel(offer['id'])
                if status == 'expired': self.now = offer['expires_at']
                self.assertEqual(self.service.list()[-1]['status'], status)
                with self.assertRaises(OfferError): self.service.accept(offer['id'], 'session-a')
                with self.assertRaises(OfferError): self.service.claim(offer['id'], 'invalid', lambda _: True)

    def test_pending_foreign_wrong_grant_and_expired_session_cannot_download(self):
        offer = self.create()
        with self.assertRaises(OfferError): self.service.claim(offer['id'], '', lambda _: True)
        with self.assertRaises(OfferError): self.service.accept(offer['id'], 'session-b')
        with self.assertRaises(OfferError): self.service.reject(offer['id'], 'session-b')
        _, grant = self.service.accept(offer['id'], 'session-a')
        for provided, valid, recipient in [(grant, True, 'session-b'), ('wrong', True, None), (grant, False, None)]:
            with self.assertRaises(OfferError):
                self.service.claim(offer['id'], provided, lambda _: valid, recipient)

    def test_cancel_and_expiry_revoke_accepted_grant(self):
        for expired in (False, True):
            offer = self.create()
            _, grant = self.service.accept(offer['id'], 'session-a')
            if expired: self.now = offer['expires_at']
            else: self.service.cancel(offer['id'])
            with self.assertRaises(OfferError): self.service.claim(offer['id'], grant, lambda _: True)

    def test_source_missing_directory_or_snapshot_missing(self):
        for source in (self.root / 'missing', self.root):
            with self.assertRaises(OfferError): self.service.create(source, 'session-a', 'recipient-a')
        offer = self.create()
        _, grant = self.service.accept(offer['id'], 'session-a')
        self.service._offers[offer['id']].snapshot.unlink()
        with self.assertRaises(OfferError): self.service.claim(offer['id'], grant, lambda _: True)
        self.assertEqual(self.service.list()[0]['status'], 'failed')

    def test_unreadable_or_changing_source_leaves_no_offer(self):
        with patch("app.file_offers.os.open", side_effect=PermissionError("denied")):
            with self.assertRaises(OfferError): self.create()
        def copy_and_change(incoming, output, length):
            output.write(incoming.read())
            self.source.write_bytes(b"changed during copy")
        with patch("app.file_offers.shutil.copyfileobj", side_effect=copy_and_change):
            with self.assertRaises(OfferError): self.create()
        self.assertEqual(self.service.list(), [])
        self.assertEqual(list((self.root / "snapshots").iterdir()), [])

    def test_stream_response_cleans_up_on_disconnect(self):
        import asyncio
        from starlette.requests import ClientDisconnect
        offer = self.create()
        _, grant = self.service.accept(offer['id'], 'session-a')
        _, source = self.service.claim(offer['id'], grant, lambda _: True)
        def cleanup():
            source.close()
            self.service.finish(offer['id'], False)
        response = main.OfferDownloadResponse(iter([b"data"]), cleanup=cleanup)
        async def run():
            async def receive(): return {"type": "http.disconnect"}
            async def send(message):
                if message["type"] == "http.response.body": raise OSError("client disconnected")
            with self.assertRaises(ClientDisconnect):
                await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        asyncio.run(run())
        self.assertTrue(source.closed)
        self.assertEqual(self.service.list()[0]['status'], 'failed')
        self.assertEqual(list((self.root / "snapshots").iterdir()), [])

    def test_symlink_is_not_offered(self):
        link = self.root / 'link'
        try: link.symlink_to(self.source)
        except OSError: self.skipTest('Symlinks unavailable')
        with self.assertRaises(OfferError): self.service.create(link, 'session-a', 'recipient-a')

    def test_concurrent_claims_have_exactly_one_winner(self):
        offer = self.create()
        _, grant = self.service.accept(offer['id'], 'session-a')
        def claim(_):
            try:
                _, source = self.service.claim(offer['id'], grant, lambda _: True)
                source.close()
                return 1
            except OfferError: return 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(claim, range(40))), 1)
        self.service.finish(offer['id'], False)

    def test_concurrent_offers_have_unique_ids(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            offers = list(pool.map(lambda _: self.create(), range(20)))
        self.assertEqual(len({offer['id'] for offer in offers}), 20)


class FileOfferAPITests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'file.txt'
        self.source.write_bytes(b'hello')
        self.service = FileOfferService(directory=self.root / 'snapshots')
        self.enterContext(patch.object(main, 'file_offers', self.service))
        self.enterContext(patch.object(main, 'sessions', {}))
        self.enterContext(patch.object(main, 'session_client_info', {}))
        self.addCleanup(self.service.close)
        self.token = main.create_session()
        self.headers = {'Authorization': f'Bearer {self.token}'}
        self.selector = main.recipient_id(self.token)

    def create(self):
        status, body = request('/api/outgoing-offers', 'POST', {'path': str(self.source), 'recipient_id': self.selector}, host='127.0.0.1')
        self.assertEqual(status, 200)
        return json.loads(body)['id']

    def test_local_sessions_and_offer_list_do_not_expose_tokens_or_paths(self):
        status, body = request('/api/recipient-sessions', host='127.0.0.1')
        self.assertEqual(status, 200)
        self.assertNotIn(self.token.encode(), body)
        self.assertEqual(json.loads(body)['sessions'][0]['id'], self.selector)
        identity = self.create()
        status, body = request('/api/incoming-offers', headers=self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['offers'][0]['id'], identity)
        self.assertNotIn(str(self.root).encode(), body)

    def test_remote_owner_routes_and_spoofed_local_headers_are_denied(self):
        identity = self.create()
        for path, method, payload in [('/api/recipient-sessions', 'GET', None),
            ('/api/outgoing-offers', 'GET', None),
            ('/api/outgoing-offers', 'POST', {'path': str(self.source), 'recipient_id': self.selector}),
            (f'/api/outgoing-offers/{identity}/cancel', 'POST', None)]:
            self.assertEqual(request(path, method, payload, dict(self.headers, **{'X-Forwarded-For':'127.0.0.1'}))[0], 403)
            self.assertEqual(request(path, method, payload, {'Origin':'https://evil.example'}, host='127.0.0.1')[0], 403)

    def test_foreign_session_and_no_token_are_denied(self):
        identity = self.create()
        other = {'Authorization': f'Bearer {main.create_session()}'}
        self.assertEqual(json.loads(request('/api/incoming-offers', headers=other)[1])['offers'], [])
        for decision in ('accept', 'reject'):
            path = f'/api/incoming-offers/{identity}/{decision}'
            self.assertEqual(request(path, 'POST', headers=other)[0], 409)
            self.assertEqual(request(path, 'POST')[0], 401)
        self.assertEqual(request('/api/incoming-offers')[0], 401)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/download', headers=other)[0], 409)

    def test_cancel_reject_and_path_injection(self):
        identity = self.create()
        self.assertEqual(request(f'/api/outgoing-offers/{identity}/cancel', 'POST', host='127.0.0.1')[0], 200)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/accept', 'POST', headers=self.headers)[0], 409)
        identity = self.create()
        self.assertEqual(request(f'/api/incoming-offers/{identity}/reject', 'POST', headers=self.headers)[0], 200)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/download', headers=self.headers)[0], 409)
        self.assertEqual(request('/api/outgoing-offers', 'POST', {'path':str(self.source), 'recipient_id':self.selector,
            'download_path':'/etc/passwd'}, host='127.0.0.1')[0], 422)
        self.assertEqual(request('/api/incoming-offers/..%2Fetc%2Fpasswd/download', headers=self.headers)[0], 409)
