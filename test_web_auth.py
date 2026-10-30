"""Run the existing browser script with a small DOM/fetch harness (Node optional)."""
import shutil
import subprocess
import unittest


class WebAuthTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed to execute browser JavaScript")
    def test_pair_send_and_expire(self):
        script = r'''
const {TextEncoder} = require("node:util");
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const elements = new Map();
function element(key) {
 if (!elements.has(key)) elements.set(key, {
  value: '', disabled: false, textContent: '', handlers: {},
  classList: {values: new Set(), add(x){this.values.add(x)}, remove(x){this.values.delete(x)}, toggle(){}},
  addEventListener(name, handler){this.handlers[name] = handler},
  querySelector(name){return element(key + name)}, focus(){}, appendChild(){},
  setAttribute(){}, removeAttribute(){}, replaceChildren(){}
 });
 return elements.get(key);
}
const calls = [];
let expire = false;
let approvalStatus = "approved";
const context = vm.createContext({
 document: {querySelector: element, querySelectorAll: () => [], createElement: element},
 crypto: require("node:crypto").webcrypto,
 window: {location: {protocol:"https:",origin:"https://localhost:8765"}, setTimeout: f => {f(); return 1}, clearTimeout(){}},
 TextEncoder, FormData: class {append(){}}, URL,
 fetch: async (url, options = {}) => {
  calls.push([url, options]);
  const status = expire ? 401 : 200;
  return {status, ok: status === 200, text: async () => '', json: async () =>
   url === '/api/pair' ? {paired: true, token: 'test-session'} :
   url === '/api/transfer-requests' ? {id:'request-1'} :
   url === '/api/transfer-requests/request-1' ? {status:approvalStatus, used:false} : {servers: []}};
 }
});
vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
(async () => {
 for (const length of [0, 1, 55, 56, 63, 64, 65, 127, 128, 1024, 16384]) {
  const data = Uint8Array.from({length}, (_, i) => i % 251);
  context.testBuffer = data.buffer;
  assert.equal(await vm.runInContext('sha256(testBuffer)', context),
   require('node:crypto').createHash('sha256').update(data).digest('hex'));
 }
 assert.equal(await vm.runInContext('sha256(new TextEncoder().encode("abc").buffer)', context),
  'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
 vm.runInContext('openTransferScreen()', context);
 assert(!element('.card').classList.values.has('hidden'));
 element('#pair-code').value = '123456789';
 await element('.pairing-form').handlers.submit({preventDefault(){}});
 assert(element('.card').classList.values.has('hidden'));
 element('#text-content').value = 'hello';
 await vm.runInContext('sendText()', context);
 await vm.runInContext('selectedFiles = [{name:"a.txt",size:3,arrayBuffer:async()=>new TextEncoder().encode("abc").buffer}]; sendFile()', context);
 for (const path of ['/api/text', '/api/upload']) {
  assert.equal(calls.find(c => c[0] === path)[1].headers.Authorization, 'Bearer test-session');
  assert.equal(calls.find(c => c[0] === path)[1].headers['X-Transfer-ID'], 'request-1');
 }
 for (const state of ['rejected', 'expired']) {
  approvalStatus = state;
  const previous = calls.filter(c => c[0] === '/api/text').length;
  element('#text-content').value = 'blocked';
  await vm.runInContext('sendText()', context);
  assert.equal(calls.filter(c => c[0] === '/api/text').length, previous);
  assert.equal(element('#transfer-status').textContent, `Transfer ${state}`);
 }
 approvalStatus = 'approved';
 context.window.location.protocol = 'http:';
 const beforeHttp = calls.length;
 await element('.pairing-form').handlers.submit({preventDefault(){}});
 await vm.runInContext('sendText()', context);
 assert.equal(calls.length, beforeHttp);
 context.window.location.protocol = 'https:';
 expire = true;
 element('#text-content').value = 'again';
 await vm.runInContext('sendText()', context);
 assert.equal(vm.runInContext('sessionToken', context), null);
 assert(element('#transfer-screen').classList.values.has('hidden'));
 assert(!element('.card').classList.values.has('hidden'));
})().catch(e => {console.error(e); process.exitCode = 1});
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
