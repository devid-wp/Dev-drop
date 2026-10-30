import hashlib
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app import main
from app.relay import RelayService
from app.transfer_requests import TransferService
from app.transport import TLSSettings
import test_file_offer_downloads as downloads


class RelayHTTPSTests(downloads.FileOfferTLSFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.b, self.c = main.create_session(), main.create_session()
        approvals = TransferService()
        self.enterContext(patch.object(main,'transfer_service',approvals))
        self.enterContext(patch.object(main,'relay_service',RelayService(approvals,self.service,main.session_is_valid)))

    def relay(self, data=b'hello', size=None, digest=None):
        payload = {'type':'file','sender':'Unverified name','description':'file for B',
            'recipient_id':main.recipient_id(self.b),'files':[{'name':'relay.txt','size':len(data) if size is None else size,
            'sha256':digest or hashlib.sha256(data).hexdigest()}]}
        status, _, body = self.call('POST','/api/relays',payload,token=self.token)
        self.assertEqual(status,200,body)
        return json.loads(body)['id'], payload

    def decide(self, identity, decision='approve'):
        self.assertEqual(self.call('POST',f'/api/transfer-requests/{identity}/{decision}')[0],200)

    def upload(self, identity, data=b'hello', token=None, path=None, chunks=None, substitute=False):
        boundary='devdrop-relay-test'
        header=(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="relay.txt"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode()
        def body():
            yield header
            if chunks is None: yield data
            else: yield from chunks
            if substitute:
                yield (f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="recipient_id"\r\n\r\n{main.recipient_id(self.c)}').encode()
            yield f'\r\n--{boundary}--\r\n'.encode()
        connection=TLSSettings.load().connection(self.port,timeout=10)
        headers={'Content-Type':f'multipart/form-data; boundary={boundary}','Authorization':f'Bearer {token or self.token}',
                 'X-Transfer-ID':identity}
        try:
            connection.request('POST',path or f'/api/relays/{identity}/upload',body=body(),headers=headers,encode_chunked=True)
            response=connection.getresponse()
            return response.status,response.read()
        finally: connection.close()

    def test_relay_owner_approval_accept_download_and_replay(self):
        identity,_=self.relay()
        self.assertEqual(self.upload(identity)[0],409)
        self.decide(identity)
        status,body=self.upload(identity)
        self.assertEqual(status,200,body)
        relay=json.loads(body)
        offer=relay['offer_id']
        self.assertEqual(self.call('GET',f'/api/incoming-offers/{offer}/download',token=self.b)[0],409)
        cookie=self.accept(offer,token=self.b)
        self.assertEqual(self.call('GET',f'/api/incoming-offers/{offer}/download',cookie=cookie)[2],b'hello')
        self.assertEqual(self.call('GET',f'/api/incoming-offers/{offer}/download',cookie=cookie)[0],409)
        self.assertEqual(self.upload(identity)[0],409)
        status,_,body=self.call('GET',f'/api/relays/{identity}',token=self.token)
        self.assertEqual(json.loads(body)['status'],'sent')
        self.assertEqual(list((self.temp/'private').iterdir()),[])

    def test_owner_and_receiver_can_reject(self):
        identity,_=self.relay()
        self.decide(identity,'reject')
        self.assertEqual(self.upload(identity)[0],409)
        self.assertEqual(self.service.list(),[])
        identity,_=self.relay()
        self.decide(identity)
        _,body=self.upload(identity)
        offer=json.loads(body)['offer_id']
        self.assertEqual(self.call('POST',f'/api/incoming-offers/{offer}/reject',token=self.b)[0],200)
        self.assertEqual(json.loads(self.call('GET',f'/api/relays/{identity}',token=self.token)[2])['status'],'rejected')
        self.assertEqual(list((self.temp/'private').iterdir()),[])

    def test_recipient_privacy_and_foreign_session(self):
        status,_,body=self.call('GET','/api/relay-recipients',token=self.token)
        self.assertEqual(status,200)
        peers=json.loads(body)['sessions']
        self.assertEqual({p['id'] for p in peers},{main.recipient_id(self.b),main.recipient_id(self.c)})
        self.assertTrue(all(set(p)=={'id'} for p in peers))
        for token in (self.token,self.b,self.c): self.assertNotIn(token.encode(),body)
        main.sessions[self.c]=time.time()-main.SESSION_LIFETIME-1
        self.assertEqual(len(json.loads(self.call('GET','/api/relay-recipients',token=self.token)[2])['sessions']),1)
        identity,_=self.relay()
        self.assertEqual(self.call('GET',f'/api/relays/{identity}',token=main.create_session())[0],409)
        self.assertEqual(self.call('POST',f'/api/relays/{identity}/cancel',token=self.b)[0],409)
        self.decide(identity)
        self.assertEqual(self.upload(identity,token=self.b)[0],409)
        self.assertEqual(self.call('GET','/api/relay-recipients')[0],401)

    def test_substitution_and_old_api_bypasses_are_refused(self):
        identity,payload=self.relay()
        self.assertEqual(self.call('POST','/api/transfer-requests',payload,token=self.token)[0],409)
        invalid=dict(payload,path='/etc/passwd')
        self.assertEqual(self.call('POST','/api/relays',invalid,token=self.token)[0],422)
        self.decide(identity)
        self.assertEqual(self.upload(identity,path='/api/upload')[0],409)
        self.assertEqual(self.upload(identity,data=b'other')[0],409)
        status,body=self.upload(identity,substitute=True)
        self.assertEqual(status,200,body)
        self.assertEqual(self.service.list(self.c),[])
        self.assertEqual(self.service.list(self.b)[0]['id'],json.loads(body)['offer_id'])

    def test_cancel_and_expiry_revoke_download(self):
        for action in ('cancel','expire'):
            identity,_=self.relay()
            self.decide(identity)
            _,body=self.upload(identity)
            relay=json.loads(body)
            cookie=self.accept(relay['offer_id'],token=self.b)
            path=f"/api/incoming-offers/{relay['offer_id']}/download"
            if action=='cancel':
                self.assertEqual(self.call('POST',f'/api/relays/{identity}/cancel',token=self.token)[0],200)
                self.assertEqual(self.call('GET',path,cookie=cookie)[0],409)
            else:
                with patch.object(self.service,'clock',return_value=relay['expires_at']):
                    self.assertEqual(self.call('GET',path,cookie=cookie)[0],409)
            self.assertEqual(list((self.temp/'private').iterdir()),[])

    def test_concurrent_relay_uploads_create_one_offer(self):
        identity,_=self.relay()
        self.decide(identity)
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(lambda _: self.upload(identity)[0],range(4)))
        self.assertEqual(statuses.count(200),1)
        self.assertEqual(statuses.count(409),3)
        self.assertEqual(len(self.service.list(self.b)),1)

    def test_large_relay_is_streamed_and_cleaned(self):
        size=20*1024*1024
        block=b'\0'*(64*1024)
        digest=hashlib.sha256()
        for _ in range(size//len(block)): digest.update(block)
        identity,_=self.relay(size=size,digest=digest.hexdigest())
        self.decide(identity)
        status,body=self.upload(identity,chunks=(block for _ in range(size//len(block))))
        self.assertEqual(status,200,body)
        relay=json.loads(body)
        cookie=self.accept(relay['offer_id'],token=self.b)
        connection=TLSSettings.load().connection(self.port,timeout=10)
        try:
            connection.request('GET',f"/api/incoming-offers/{relay['offer_id']}/download",headers={'Cookie':cookie})
            response=connection.getresponse()
            self.assertEqual(response.status,200)
            received=hashlib.sha256()
            count=0
            while chunk:=response.read(64*1024): received.update(chunk); count+=len(chunk)
            self.assertEqual(count,size)
            self.assertEqual(received.hexdigest(),digest.hexdigest())
        finally: connection.close()
        self.assertEqual(list((self.temp/'private').iterdir()),[])


    def test_self_unknown_and_expired_recipient_cannot_create_relay(self):
        identity,payload=self.relay()
        for target in (main.recipient_id(self.token),'0'*64):
            changed=dict(payload,recipient_id=target)
            self.assertEqual(self.call('POST','/api/relays',changed,token=self.token)[0],409)
        main.sessions[self.b]=time.time()-main.SESSION_LIFETIME-1
        self.assertEqual(self.call('POST','/api/relays',payload,token=self.token)[0],409)
        self.decide(identity)
        self.assertEqual(self.upload(identity)[0],409)
        self.assertEqual(self.service.list(),[])
