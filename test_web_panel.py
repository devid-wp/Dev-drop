"""Local-only Web Panel routing and owner decision checks."""
import asyncio
import hashlib
import shutil
import subprocess
import unittest

from app import main
from app.transfer_requests import TransferDescription
from test_auth import request as api_request


def panel_request(path, method="GET", *, peer="127.0.0.1", host="localhost:8765", scheme="https", headers=None):
    messages=[]
    raw=[(b"host",host.encode())]
    raw.extend((key.lower().encode(),value.encode()) for key,value in (headers or {}).items())
    async def run():
        delivered=False
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {"type":"http.request","body":b"","more_body":False}
            await asyncio.Event().wait()
        async def send(message): messages.append(message)
        await main.app({"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":method,
                        "scheme":scheme,"path":path,"raw_path":path.encode(),"query_string":b"","root_path":"",
                        "headers":raw,"client":(peer,1234),"server":("127.0.0.1",8765)},receive,send)
    asyncio.run(run())
    return messages[0]["status"],dict(messages[0].get("headers",[])),b"".join(m.get("body",b"") for m in messages)


def call_panel_route(peer="127.0.0.1",host="localhost:8765"):
    scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"GET","scheme":"https",
           "path":"/panel","raw_path":b"/panel","query_string":b"","root_path":"",
           "headers":[(b"host",host.encode())],"client":(peer,1234),"server":("127.0.0.1",8765)}
    return asyncio.run(main.owner_panel(__import__("starlette.requests",fromlist=["Request"]).Request(scope)))


def call_panel_asset(asset,peer="127.0.0.1",host="localhost:8765"):
    scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"GET","scheme":"https",
           "path":f"/panel-assets/{asset}","raw_path":f"/panel-assets/{asset}".encode(),"query_string":b"","root_path":"",
           "headers":[(b"host",host.encode())],"client":(peer,1234),"server":("127.0.0.1",8765)}
    return asyncio.run(main.owner_panel_asset(asset,__import__("starlette.requests",fromlist=["Request"]).Request(scope)))


class WebPanelTests(unittest.TestCase):
    def test_panel_is_loopback_only_https_and_does_not_embed_secrets(self):
        secret_code = main.generate_pairing_code()
        response=call_panel_route()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers.get("cache-control"),"no-store")
        self.assertIn("frame-ancestors 'none'",response.headers.get("content-security-policy"))
        body=response.path.read_bytes()
        self.assertIn(b"/panel-assets/panel.js",body)
        self.assertNotIn(secret_code.encode(),body)
        self.assertEqual(call_panel_asset("panel.css").status_code,200)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as remote: call_panel_route(peer="192.0.2.8")
        self.assertEqual(remote.exception.status_code,403)
        with self.assertRaises(HTTPException) as remote_asset: call_panel_asset("panel.js",peer="192.0.2.8")
        self.assertEqual(remote_asset.exception.status_code,403)
        with self.assertRaises(HTTPException) as bad_host: call_panel_route(host="attacker.example")
        self.assertEqual(bad_host.exception.status_code,403)
        self.assertEqual(api_request("/panel",host="127.0.0.1",scheme="http",headers={"Host":"localhost:8765"})[0],426)

    def test_panel_owner_decisions_retain_backend_origin_authorization(self):
        token=main.create_session()
        def create():
            return main.transfer_service.create(token,TransferDescription(
                type="text",sender="Browser",description="example",size=7,
                sha256=hashlib.sha256(b"example").hexdigest()))["id"]
        approve_id=create()
        reject_id=create()
        path=f"/api/transfer-requests/{approve_id}/approve"
        self.assertEqual(api_request(path,"POST",{},headers={"Origin":"https://localhost","Host":"localhost:8765"},host="192.0.2.8")[0],403)
        self.assertEqual(api_request(path,"POST",{},headers={"Origin":"https://evil.example","Host":"localhost:8765"},host="127.0.0.1")[0],403)
        local_headers={"Origin":"https://localhost","Host":"localhost:8765"}
        self.assertEqual(api_request(path,"POST",{},headers=local_headers,host="127.0.0.1")[0],200)
        self.assertEqual(api_request(f"/api/transfer-requests/{reject_id}/reject","POST",{},headers=local_headers,host="127.0.0.1")[0],200)
        self.assertEqual(main.transfer_service.state(approve_id,token)["status"],"approved")
        self.assertEqual(main.transfer_service.state(reject_id,token)["status"],"rejected")

    def test_sensitive_local_api_responses_are_not_cached(self):
        status,headers,_=panel_request("/api/pairing-code")
        self.assertEqual(status,200)
        self.assertEqual(headers.get(b"cache-control"),b"no-store")

    def test_styles_include_mobile_navigation_and_reduced_motion(self):
        css=(main.WEB_DIR/"panel.css").read_text(encoding="utf-8")
        self.assertIn("@media(max-width:620px)",css)
        self.assertIn("grid-template-columns:repeat(6,1fr)",css)
        self.assertIn("prefers-reduced-motion:reduce",css)

    @unittest.skipUnless(shutil.which("node"),"Node is needed for the Web Panel DOM harness")
    def test_empty_states_backend_errors_and_explicit_decision_dialog(self):
        harness=r'''const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class Element{constructor(id=''){this.id=id;this.children=[];this.handlers={};this.dataset={};this.attributes={};this.hidden=false;this.disabled=false;this.value='';this.className='';this._text='';this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),toggle:(x,v)=>v?this.classes.add(x):this.classes.delete(x),contains:x=>this.classes.has(x)};this.classes=new Set()}
 set textContent(v){this._text=String(v);this.children=[]}get textContent(){return this._text+this.children.map(x=>x.textContent).join('')}
 append(...nodes){this.children.push(...nodes)}appendChild(n){this.children.push(n)}replaceChildren(...nodes){this.children=[...nodes];this._text=''}
 addEventListener(name,fn){this.handlers[name]=fn}setAttribute(k,v){this.attributes[k]=v}removeAttribute(k){delete this.attributes[k]}
 querySelector(sel){if(sel==='span'){if(!this.span)this.span=new Element();return this.span}return new Element()}
 showModal(){this.open=true}close(){this.open=false}focus(){}}
const els=new Map(),get=id=>{if(!els.has(id))els.set(id,new Element(id));return els.get(id)};
const nav=['dashboard','devices','transfers','history','security','settings'].map(x=>{const e=new Element();e.dataset.page=x;return e});
const pageEls=['dashboard','devices','transfers','history','security','settings'].map(x=>{const e=new Element('page-'+x);e.id='page-'+x;return e});
const refreshEls=[new Element()];let failHistory=false;const calls=[];let requests=[];
const responses={ '/api/status':{pairing_code:'987654321',connected_devices:0,session_path:'/tmp/devdrop-session'},'/api/recipient-sessions':{sessions:[]},'/api/discover':{servers:[]},'/api/transfer-requests':null,'/api/outgoing-offers':{offers:[]},'/api/history':{transfers:[]},'/api/pairing/qr':{version:1,url:'https://localhost:8765',state:'ready',attempt_id:'a'.repeat(24),token:'t'.repeat(48),expires_in:90,qr_svg:'<svg></svg>'},'/api/pairing/requests':{requests:[]} };
const context=vm.createContext({document:{getElementById:get,createElement:tag=>{const e=new Element();e.tag=tag;return e},querySelectorAll:s=>s==='.nav-link'?nav:s==='.page'?pageEls:s==='.refresh-page'?refreshEls:[]},
 location:{hash:'#dashboard',protocol:'https:',host:'localhost:8765'},window:{location:{hash:'#dashboard',protocol:'https:',host:'localhost:8765'},addEventListener(){},setInterval(){return 1},clearTimeout(){},setTimeout(){return 1},confirm(){return true}},
 fetch:async(path,options={})=>{calls.push([path,options]);if(path==='/api/history'&&failHistory)return{ok:false,status:503,json:async()=>({})};if(path==='/api/transfer-requests'&&options.method==='POST')return{ok:true,status:200,json:async()=>({})};if(path==='/api/transfer-requests')return{ok:true,status:200,json:async()=>({requests})};const data=responses[path]||{};return{ok:true,status:200,json:async()=>data};}});
vm.runInContext(fs.readFileSync('web/panel.js','utf8'),context);
(async()=>{
 await new Promise(resolve=>setTimeout(resolve,0));
 await vm.runInContext('refresh()',context);
 assert.match(get('recent-activity').textContent,/No recent activity/);
 assert.match(get('discovered-devices').textContent,/No other Dev-Drop servers/);
 assert.match(get('pending-transfers').textContent,/No transfer requests/);
 assert(!get('page-dashboard').textContent.includes('987654321'));
 assert.equal(get('setting-path').textContent,'/tmp/devdrop-session');
 assert(get('pairing-qr').classList.contains('visible'));
 assert.match(get('pairing-state').textContent,/Ready to scan/);
 assert.equal(calls.filter(([p,o])=>p.includes('/approve')||p.includes('/reject')).length,0);
 requests=[{id:'request-1',type:'file',status:'pending',sender:'Phone',description:'photo.png',size:12,files:[{name:'photo.png',size:12,sha256:'a'.repeat(64)}],created_at:new Date().toISOString()}];
 await vm.runInContext('refresh()',context);
 const action=get('pending-transfers').children[0].children[2].children[1];action.handlers.click();
 assert.equal(get('decision-dialog').open,true);
 assert.match(get('dialog-details').textContent,/photo.png/);
 assert.equal(calls.filter(([p,o])=>p.includes('/approve')||p.includes('/reject')).length,0);
 await vm.runInContext("decide('approve')",context);
 assert(calls.some(([p,o])=>p==='/api/transfer-requests/request-1/approve'&&o.method==='POST'));
 responses['/api/pairing/requests']={requests:[{attempt_id:'pairing-1',device:'Pixel',peer:'192.168.1.20',expires_in:80}]};
 await vm.runInContext('refresh()',context);
 assert.equal(get('pairing-requests').children.length,1);
 const pairApprove=get('pairing-requests').children[0].children[2].children[1];pairApprove.onclick();
 assert.equal(get('pairing-dialog').open,true);
 get('pairing-confirmation-code').value='123456';
 await vm.runInContext('decidePairing(true)',context);
 assert(calls.some(([p,o])=>p==='/api/pairing/requests/pairing-1/approve'&&o.method==='POST'&&JSON.parse(o.body).code==='123456'));
 responses['/api/recipient-sessions']={sessions:[{id:'b'.repeat(64),agent:'Pixel',peer:'192.168.1.20'}]};
 await vm.runInContext('refresh()',context);
 const remove=get('paired-devices').children[0].children[3].children[0];remove.handlers.click();
 await new Promise(resolve=>setTimeout(resolve,0));
 assert(calls.some(([p,o])=>p==='/api/recipient-sessions/'+('b'.repeat(64))+'/revoke'&&o.method==='POST'));
 failHistory=true;await vm.runInContext('refresh()',context);
 assert.match(get('recent-activity').textContent,/could not read transfer history/);
 assert.match(get('history-list').textContent,/could not read transfer history/);
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result=subprocess.run(["node","-e",harness],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
