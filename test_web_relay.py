import shutil
import subprocess
import unittest


class WebRelayTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for browser JavaScript')
    def test_relay_recipient_approval_status_and_cancel(self):
        script=r'''
const vm=require('node:vm'), fs=require('node:fs'), assert=require('node:assert/strict');
function node(){return {value:'',textContent:'',children:[],handlers:{},classList:{add(){},remove(){},toggle(){}},
 addEventListener(k,v){this.handlers[k]=v},querySelector(){return node()},appendChild(x){this.children.push(x)},
 replaceChildren(){this.children=[]},focus(){},setAttribute(){},removeAttribute(){}}}
const elements=new Map(); const get=k=>{if(!elements.has(k))elements.set(k,node());return elements.get(k)};
const calls=[]; let approval='approved'; let relayStatus='offered';
const b='b'.repeat(64),c='c'.repeat(64);
const context=vm.createContext({
 document:{querySelector:get,querySelectorAll:()=>[],createElement:node},
 window:{location:{protocol:'https:',origin:'https://localhost'},clearInterval(){},setInterval(){return 1},setTimeout(){return 1},clearTimeout(){}},
 crypto:require('node:crypto').webcrypto,TextEncoder,AbortController,URL,
 FormData:class{append(){}},
 fetch:async(url,options={})=>{
  calls.push([url,options]);
  let data={};
  if(url==='/api/relay-recipients')data={sessions:[{id:b},{id:c}]};
  if(url==='/api/relays'&&options.method==='POST')data={id:'relay-id',status:'pending'};
  else if(url==='/api/relays')data={relays:[{id:'relay-id',filename:'file.txt',recipient_id:b,status:relayStatus}]};
  if(url==='/api/relays/relay-id'){data={status:approval};get('#relay-recipient').value=c;}
  if(url==='/api/relays/relay-id/upload')data={status:'offered',offer_id:'offer-id'};
  if(url==='/api/relays/relay-id/cancel'){data={status:'cancelled'};relayStatus='cancelled';}
  return {ok:true,status:200,json:async()=>data,text:async()=>''};
 }
});
vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
(async()=>{
 vm.runInContext('sessionToken="token-a"',context);
 await vm.runInContext('refreshRelayState(sessionToken)',context);
 assert.equal(get('#relay-recipient').children[1].textContent,'Session bbbbbbbb');
 get('#relay-recipient').value=b;
 await vm.runInContext('selectedFiles=[{name:"file.txt",size:5,arrayBuffer:async()=>new TextEncoder().encode("hello").buffer}];sendFile()',context);
 const creation=calls.find(([url,opt])=>url==='/api/relays'&&opt.method==='POST');
 assert.equal(JSON.parse(creation[1].body).recipient_id,b);
 assert.equal(JSON.parse(creation[1].body).files[0].size,5);
 assert(!('path' in JSON.parse(creation[1].body)));
 assert(calls.some(([url])=>url==='/api/relays/relay-id/upload'));
 assert(!calls.some(([url])=>url==='/api/upload'));
 await vm.runInContext('refreshRelayState(sessionToken)',context);
 const row=get('#relay-outgoing').children[0];
 assert(row.children[0].textContent.includes('offered'));
 await row.children[1].handlers.click();
 assert(calls.some(([url])=>url==='/api/relays/relay-id/cancel'));
 approval='rejected';get('#relay-recipient').value=b;
 const before=calls.filter(([url])=>url.endsWith('/upload')).length;
 await vm.runInContext('selectedFiles=[{name:"file.txt",size:5,arrayBuffer:async()=>new TextEncoder().encode("hello").buffer}];sendFile()',context);
 assert.equal(calls.filter(([url])=>url.endsWith('/upload')).length,before);
 assert.equal(get('#transfer-status').textContent,'Transfer rejected');
 for(const [url,opt] of calls.filter(([url])=>url.startsWith('/api/relays'))){
  assert(!url.includes('token-a'));
  assert.equal(opt.headers.Authorization,'Bearer token-a');
 }
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
