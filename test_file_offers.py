import json
import hashlib
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
        self.assertEqual(offer['sha256'], hashlib.sha256(b'original').hexdigest())
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

    def test_stream_byte_progress_and_terminal_states(self):
        offer = self.create()
        _, grant = self.service.accept(offer['id'], 'session-a')
        state, stream = self.service.claim(offer['id'], grant, lambda _: True)
        self.assertEqual(state['sent_bytes'], 0)
        self.service.record_stream_bytes(offer['id'], 3)
        self.assertEqual(self.service.list('session-a')[0]['sent_bytes'], 3)
        self.service.record_stream_bytes(offer['id'], 99)
        self.assertEqual(self.service.list('session-a')[0]['sent_bytes'], 8)
        stream.close()
        self.service.finish(offer['id'], True)
        self.assertEqual(self.service.list('session-a')[0]['status'], 'sent')
        self.assertEqual(self.service.list('session-a')[0]['sent_bytes'], 8)

    def test_receipt_requires_sent_state_and_exact_size_and_digest(self):
        offer = self.create()
        with self.assertRaises(OfferError):
            self.service.confirm_received(offer['id'], 'session-a', offer['size'], offer['sha256'])
        _, grant = self.service.accept(offer['id'], 'session-a')
        _, stream = self.service.claim(offer['id'], grant, lambda _: True)
        stream.read()
        stream.close()
        self.service.record_stream_bytes(offer['id'], offer['size'])
        self.service.finish(offer['id'], True)
        with self.assertRaises(OfferError):
            self.service.confirm_received(offer['id'], 'foreign-session', offer['size'], offer['sha256'])
        with self.assertRaises(OfferError):
            self.service.confirm_received(offer['id'], 'session-a', offer['size'] - 1, offer['sha256'])
        with self.assertRaises(OfferError):
            self.service.confirm_received(offer['id'], 'session-a', offer['size'], '0' * 64)
        with ThreadPoolExecutor(max_workers=8) as pool:
            confirmations = list(pool.map(lambda _: self.service.confirm_received(
                offer['id'], 'session-a', offer['size'], offer['sha256']), range(16)))
        received = confirmations[0]
        self.assertEqual(received['status'], 'received')
        self.assertIsNotNone(received['received_at'])
        self.assertTrue(all(item == received for item in confirmations))
        with self.assertRaises(OfferError):
            self.service.confirm_received(offer['id'], 'session-a', offer['size'], '1' * 64)

    def test_failed_stream_preserves_only_recipient_scoped_progress(self):
        offer = self.create()
        _, grant = self.service.accept(offer['id'], 'session-a')
        _, stream = self.service.claim(offer['id'], grant, lambda _: True)
        self.service.record_stream_bytes(offer['id'], 2)
        stream.close()
        self.service.finish(offer['id'], False)
        self.assertEqual(self.service.list('session-a')[0]['status'], 'failed')
        self.assertEqual(self.service.list('session-b'), [])

    def test_parallel_stream_progress_stays_with_each_offer(self):
        first, second = self.create(), self.create()
        _, grant_a = self.service.accept(first['id'], 'session-a')
        _, grant_b = self.service.accept(second['id'], 'session-a')
        _, stream_a = self.service.claim(first['id'], grant_a, lambda _: True)
        _, stream_b = self.service.claim(second['id'], grant_b, lambda _: True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda args: self.service.record_stream_bytes(*args),
                          [(first['id'], 3), (second['id'], 6)]))
        states = {item['id']: item['sent_bytes'] for item in self.service.list('session-a')}
        self.assertEqual(states[first['id']], 3)
        self.assertEqual(states[second['id']], 6)
        stream_a.close(); stream_b.close()


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
        return self.service.create(self.source, self.token, self.selector)['id']

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

    def test_progress_state_is_bound_to_recipient_session(self):
        identity = self.create()
        other = {'Authorization': f'Bearer {main.create_session()}'}
        self.assertEqual(request(f'/api/incoming-offers/{identity}/state', headers=self.headers)[0], 200)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/state', headers=other)[0], 404)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/state')[0], 401)

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

    def test_receipt_api_is_session_bound_and_checks_size_hash(self):
        identity = self.create()
        other = {'Authorization': f'Bearer {main.create_session()}'}
        self.assertEqual(request(f'/api/incoming-offers/{identity}/receipt', 'POST',
            {'size': 5, 'sha256': hashlib.sha256(b'hello').hexdigest()}, self.headers)[0], 409)
        _, grant = self.service.accept(identity, self.token)
        _, stream = self.service.claim(identity, grant, main.session_is_valid, self.token)
        stream.read(); stream.close()
        self.service.record_stream_bytes(identity, 5)
        self.service.finish(identity, True)
        wrong_hash = {'size': 5, 'sha256': '0' * 64}
        self.assertEqual(request(f'/api/incoming-offers/{identity}/receipt', 'POST', wrong_hash, self.headers)[0], 409)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/receipt', 'POST',
            {'size': 4, 'sha256': hashlib.sha256(b'hello').hexdigest()}, self.headers)[0], 409)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/receipt', 'POST',
            {'size': 5, 'sha256': hashlib.sha256(b'hello').hexdigest()}, other)[0], 409)
        self.assertEqual(request(f'/api/incoming-offers/{identity}/receipt', 'POST',
            {'size': True, 'sha256': hashlib.sha256(b'hello').hexdigest()}, self.headers)[0], 422)
        status, body = request(f'/api/incoming-offers/{identity}/receipt', 'POST',
            {'size': 5, 'sha256': hashlib.sha256(b'hello').hexdigest()}, self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'received')
        status, body = request(f'/api/incoming-offers/{identity}/state', headers=self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'received')

    def test_session_revoke_cancels_recipient_offers_and_grants(self):
        pending = self.create()
        accepted = self.create()
        _, grant = self.service.accept(accepted, self.token)
        streaming = self.create()
        _, streaming_grant = self.service.accept(streaming, self.token)
        _, stream = self.service.claim(streaming, streaming_grant, main.session_is_valid, self.token)
        status, body = request('/api/session', 'DELETE', headers=self.headers)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['revoked'])
        statuses = {item['id']: item['status'] for item in self.service.list()}
        self.assertEqual(statuses[pending], 'cancelled')
        self.assertEqual(statuses[accepted], 'cancelled')
        self.assertEqual(statuses[streaming], 'cancelled')
        with self.assertRaises(OfferError):
            self.service.claim(accepted, grant, main.session_is_valid, self.token)
        with self.assertRaises(OfferError):
            self.service.check_streaming(streaming, main.session_is_valid)
        stream.close()
        self.service.finish(streaming, False)
        self.assertEqual(request('/api/incoming-offers', headers=self.headers)[0], 401)
        self.assertEqual(list((self.root / 'snapshots').iterdir()), [])
