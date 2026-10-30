import shutil
import subprocess
import unittest


class WebIncomingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required to execute browser code')
    def test_incoming_accept_reject_and_native_download_without_token_url(self):
        script = r'''
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
function element() {
 return {value:'', textContent:'', children:[], handlers:{},
  classList:{add(){},remove(){},toggle(){}}, focus(){}, querySelector(){return element()},
  appendChild(child){this.children.push(child)}, replaceChildren(){this.children=[]},
  addEventListener(name, handler){this.handlers[name]=handler}, setAttribute(){}, removeAttribute(){}};
}
const elements = new Map();
const get = key => {if (!elements.has(key)) elements.set(key, element()); return elements.get(key)};
const calls = [];
const offered = {id:'offer-id',filename:'<script>file.txt',size:100,sender:'Computer owner',status:'pending'};
let status = 'pending';
const context = vm.createContext({
 document:{querySelector:get,querySelectorAll:()=>[],createElement:element},
 window:{location:{protocol:'https:',origin:'https://localhost'},clearInterval(){},setInterval(){return 1},clearTimeout(){},setTimeout(){return 1}},
 fetch:async(url,options={})=>{
  calls.push([url,options]);
  if(url.endsWith('/accept')) status='accepted';
  if(url.endsWith('/reject')) status='rejected';
  return {ok:true,status:200,json:async()=>url==='/api/incoming-offers' ?
   {offers:[{...offered,status}],session_id:'browser-session'} : {status}};
 }
});
vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
(async()=>{
 vm.runInContext('sessionToken="primary-secret"',context);
 await vm.runInContext('refreshIncoming()',context);
 const row = get('#incoming-files').children[0];
 assert.equal(row.children[0].textContent, '<script>file.txt | 100 B | Computer owner | pending');
 assert.equal(row.children[1].textContent,'Accept');
 assert.equal(row.children[2].textContent,'Reject');
 assert(!calls.some(([url])=>url.endsWith('/download')));
 await row.children[1].handlers.click();
 assert.equal(status,'accepted');
 const link = row.children[1];
 assert.equal(link.href,'/api/incoming-offers/offer-id/download');
 assert.equal(link.download,offered.filename);
 assert(!link.href.includes('primary-secret'));
 assert(!calls.some(([url])=>url.endsWith('/download'))); // No fetch/blob/automatic download.
 assert.equal(calls.find(([url])=>url.endsWith('/accept'))[1].headers.Authorization,'Bearer primary-secret');
 status='pending';
 await vm.runInContext('refreshIncoming()',context);
 await get('#incoming-files').children[0].children[2].handlers.click();
 assert.equal(status,'rejected');
 assert.equal(get('#incoming-status').textContent,'File rejected');
 vm.runInContext('returnToPairing()',context);
 assert.equal(get('#incoming-files').children.length,0);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
