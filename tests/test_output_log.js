// Exercise output-request races without USB or a browser dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
const pending = [];
const context = {
  document: {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {setAttribute() {}, textContent: '', disabled: false});
    return elements.get(id);
  }},
  ReceiptEditor: require('../receipter/editor.js'), Uint8Array, Blob, AbortController, FormData, atob,
  URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}},
  fetch: (url, options) => new Promise(resolve => pending.push({url, options, resolve})),
};
vm.runInNewContext(fs.readFileSync(require.resolve('../receipter/output-log.js'), 'utf8'), context);
const flush = () => new Promise(resolve => setImmediate(resolve));
function complete(request, copies, ok = true) {
  request.resolve({ok, json: async () => ok ? {
    build_id: 'build', raw_base64: 'Gz0B', bytes: 3, sha256: `hash-${copies}`, parts: copies, copies,
  } : {detail: 'Expired'}});
}
(async () => {
  const events = [];
  const log = new context.ReceiptOutputLog('build', () => {}, message => events.push(message));
  const snapshot = {token: 'snapshot'};
  const settings = copies => ({copies, cut: true, feed_lines: 8});
  log.update(snapshot, settings(1));
  assert.equal(log.ready(snapshot, settings(1)), false);
  complete(pending[0], 1); await flush();
  assert.equal(log.ready(snapshot, settings(1)), true);
  log.update(snapshot, settings(2));
  log.update(snapshot, settings(3));
  assert.equal(pending[1].options.signal.aborted, true);
  complete(pending[2], 3); await flush();
  complete(pending[1], 2); await flush(); // A late response must not replace copy count 3.
  assert.equal(log.plan.copies, 3);
  assert.equal(log.ready(snapshot, settings(3)), true);
  assert.equal(log.ready(snapshot, settings(2)), false);
  log.update(snapshot, settings(0));
  assert.equal(log.ready(snapshot, settings(3)), false);
  log.update(snapshot, settings(3)); // Same old plan, but a new inspection is in flight.
  assert.equal(log.ready(snapshot, settings(3)), false);
  complete(pending[3], 3); await flush();
  const submitted = log.plan;
  log.mark('Sending', submitted);
  log.mark('USB accepted', submitted);
  log.update(null, settings(3));
  assert.equal(log.state, 'USB accepted'); // Preserve actual last-job status, not "not sent".
  assert.equal(log.ready(snapshot, settings(3)), false);
  log.update({token: 'new'}, settings(3));
  complete(pending[4], 3, false); await flush();
  assert.equal(log.ready({token: 'new'}, settings(3)), false);
  assert.match(log.state, /Output error: Expired/);
  assert.equal(events.filter(e => e.startsWith('PREPARED')).length, 3);
  assert.equal(pending.every(p => p.url === '/api/receipt-output'), true);
  console.log('Output-log request races, stale-byte blocking and non-printing inspection passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
