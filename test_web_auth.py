"""Run the existing browser script with a small DOM/fetch harness (Node optional)."""
import shutil
import subprocess
import unittest


class WebAuthTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed to execute browser JavaScript")
    def test_pair_send_and_expire(self):
        script = r'''
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
const context = vm.createContext({
 document: {querySelector: element, querySelectorAll: () => [], createElement: element},
 window: {setTimeout: f => {f(); return 1}, clearTimeout(){}},
 FormData: class {append(){}}, URL,
 fetch: async (url, options = {}) => {
  calls.push([url, options]);
  const status = expire ? 401 : 200;
  return {status, ok: status === 200, text: async () => '', json: async () =>
   url === '/api/pair' ? {paired: true, token: 'test-session'} : {servers: []}};
 }
});
vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
(async () => {
 vm.runInContext('openTransferScreen()', context);
 assert(!element('.card').classList.values.has('hidden'));
 element('#pair-code').value = '123456789';
 await element('.pairing-form').handlers.submit({preventDefault(){}});
 assert(element('.card').classList.values.has('hidden'));
 element('#text-content').value = 'hello';
 await vm.runInContext('sendText()', context);
 await vm.runInContext('selectedFiles = [{name:"a.txt"}]; sendFile()', context);
 for (const path of ['/api/text', '/api/upload']) {
  assert.equal(calls.find(c => c[0] === path)[1].headers.Authorization, 'Bearer test-session');
 }
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
