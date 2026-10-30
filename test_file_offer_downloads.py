"""Native-cookie downloads over real, verified loopback TLS."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch

import uvicorn
from app import main
from app.file_offers import FileOfferService
from app.transport import TLSSettings
from tls_test_support import PASSWORD, make_pki


class FileOfferDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix='devdrop-download-test-')
        cls.addClassCleanup(directory.cleanup)
        cls.root = Path(directory.name)
        config = make_pki(cls.root)
        env = patch.dict(os.environ, {'DEVDROP_TLS_CONFIG': str(config)})
        env.start()
        cls.addClassCleanup(env.stop)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        cls.port = listener.getsockname()[1]
        config = uvicorn.Config(main.app, host='127.0.0.1', port=cls.port,
                                proxy_headers=False, lifespan='off', log_level='error',
                                **TLSSettings.load().server_options(PASSWORD))
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=lambda: cls.server.run(sockets=[listener]), daemon=True)
        cls.thread.start()
        def stop():
            cls.server.should_exit = True
            cls.thread.join(timeout=10)
            listener.close()
        cls.addClassCleanup(stop)
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.server.started:
            raise RuntimeError('Test TLS server did not start')

    def setUp(self):
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.temp / 'пример.txt'
        self.source.write_bytes(b'phone file')
        self.service = FileOfferService(directory=self.temp / 'private')
        self.enterContext(patch.object(main, 'file_offers', self.service))
        self.enterContext(patch.object(main, 'sessions', {}))
        self.enterContext(patch.object(main, 'session_client_info', {}))
        self.addCleanup(self.service.close)
        self.token = main.create_session()

    def call(self, method, path, payload=None, token=None, cookie=None):
        headers = {'Content-Type': 'application/json'}
        if token: headers['Authorization'] = f'Bearer {token}'
        if cookie: headers['Cookie'] = cookie
        connection = TLSSettings.load().connection(self.port, timeout=5)
        try:
            connection.request(method, path, body=json.dumps(payload).encode() if payload is not None else None, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def offer(self):
        status, _, body = self.call('POST', '/api/outgoing-offers', {'path':str(self.source), 'recipient_id':main.recipient_id(self.token)})
        self.assertEqual(status, 200, body)
        return json.loads(body)['id']

    def accept(self, identity):
        status, headers, body = self.call('POST', f'/api/incoming-offers/{identity}/accept', token=self.token)
        self.assertEqual(status, 200, body)
        cookie = SimpleCookie()
        cookie.load(headers['set-cookie'])
        value = cookie['__Secure-dd_download_' + identity]
        self.assertTrue(value['secure'])
        self.assertTrue(value['httponly'])
        self.assertEqual(value['samesite'].lower(), 'strict')
        self.assertEqual(value['path'], f'/api/incoming-offers/{identity}/download')
        self.assertNotIn(self.token, headers['set-cookie'])
        self.assertNotIn(value.value.encode(), body)
        return value.OutputString(attrs=[])

    def test_accept_native_download_and_replay(self):
        identity = self.offer()
        path = f'/api/incoming-offers/{identity}/download'
        self.assertEqual(self.call('GET', path, token=self.token)[0], 409)
        cookie = self.accept(identity)
        self.source.unlink()  # The offered snapshot remains available.
        status, headers, body = self.call('GET', path, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(body, b'phone file')
        self.assertEqual(headers['content-type'], 'application/octet-stream')
        self.assertTrue(headers['content-disposition'].startswith("attachment; filename*=UTF-8''"))
        self.assertEqual(headers['x-content-type-options'], 'nosniff')
        self.assertEqual(headers['cache-control'], 'no-store')
        self.assertEqual(self.call('GET', path, cookie=cookie)[0], 409)
        self.assertEqual(self.service.list()[0]['status'], 'sent')

    def test_foreign_session_cannot_accept_or_download(self):
        identity = self.offer()
        other = main.create_session()
        self.assertEqual(self.call('POST', f'/api/incoming-offers/{identity}/accept', token=other)[0], 409)
        cookie = self.accept(identity)
        path = f'/api/incoming-offers/{identity}/download'
        self.assertEqual(self.call('GET', path, token=other)[0], 409)
        self.assertEqual(self.call('GET', path, token=other, cookie=cookie)[0], 409)
        self.assertEqual(self.call('GET', path + '?path=/etc/passwd', cookie=cookie)[2], b'phone file')

    def test_cancel_expire_and_session_expire_revoke_cookie(self):
        for state in ('cancel', 'expire', 'session'):
            identity = self.offer()
            cookie = self.accept(identity)
            path = f'/api/incoming-offers/{identity}/download'
            if state == 'cancel':
                self.assertEqual(self.call('POST', f'/api/outgoing-offers/{identity}/cancel')[0], 200)
            elif state == 'expire':
                deadline = self.service.list()[-1]['expires_at']
                with patch.object(self.service, 'clock', return_value=deadline):
                    self.assertEqual(self.call('GET', path, cookie=cookie)[0], 409)
                continue
            else:
                main.sessions[self.token] = time.time() - main.SESSION_LIFETIME - 1
            self.assertEqual(self.call('GET', path, cookie=cookie)[0], 409)

    def test_large_file_download_reads_in_chunks(self):
        size = 20 * 1024 * 1024
        with self.source.open('wb') as source:
            source.truncate(size)
        identity = self.offer()
        cookie = self.accept(identity)
        connection = TLSSettings.load().connection(self.port, timeout=10)
        try:
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Whole-file read is forbidden')):
                connection.request('GET', f'/api/incoming-offers/{identity}/download', headers={'Cookie':cookie})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(int(response.getheader('Content-Length')), size)
                received = 0
                while chunk := response.read(64 * 1024):
                    self.assertEqual(chunk.count(0), len(chunk))
                    received += len(chunk)
                self.assertEqual(received, size)
        finally:
            connection.close()

    def test_source_missing_is_not_registered(self):
        self.source.unlink()
        status, _, _ = self.call('POST', '/api/outgoing-offers', {'path':str(self.source), 'recipient_id':main.recipient_id(self.token)})
        self.assertEqual(status, 409)
        self.assertEqual(self.service.list(), [])


    def test_empty_file_and_insecure_transport(self):
        from test_auth import request
        self.source.write_bytes(b"")
        identity = self.offer()
        cookie = self.accept(identity)
        path = f'/api/incoming-offers/{identity}/download'
        self.assertEqual(request(path, headers={"Cookie":cookie}, host="127.0.0.1", scheme="http")[0], 426)
        status, headers, body = self.call('GET', path, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(headers['content-length'], '0')
        self.assertEqual(body, b'')
