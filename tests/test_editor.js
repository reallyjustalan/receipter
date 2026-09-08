const assert = require('node:assert/strict');
const {switchDensity, printBlockReasons} = require('../receipter/editor.js');
const remembered = {'0': {width: 200, scale: 1}, '1': {width: 400, scale: 0.5}};
assert.deepEqual(switchDensity('1', '0', {width: 400, scale: 0.5}, remembered), {width: 200, scale: 1});
assert.deepEqual(switchDensity('0', '1', {width: 200, scale: 1}, remembered), {width: 400, scale: 0.5});
assert.deepEqual(switchDensity('1', '0', {width: 320, scale: 0.7}, remembered), {width: 200, scale: 1});
assert.deepEqual(switchDensity('0', '1', {width: 160, scale: 1.1}, remembered), {width: 320, scale: 0.7});
assert.deepEqual(switchDensity('1', '0', {width: 320, scale: 0.7}, remembered), {width: 160, scale: 1.1});
console.log('Density round-trip, custom widths and per-mode aspect settings passed.');

const ready = {statusKnown: true, buildMatches: true, connected: true, stopped: false,
  busy: false, serverBusy: false, hasFile: true, previewReady: true,
  statusError: '', previewError: '', validationError: ''};
assert.deepEqual(printBlockReasons(ready), []);
for (const [changes, expected] of [
  [{statusKnown: false}, /Checking printer/],
  [{statusError: 'Network failed'}, /Network failed/],
  [{buildMatches: false}, /Refresh this page/],
  [{connected: false}, /not detected/],
  [{stopped: true}, /Resume/],
  [{busy: true}, /job is active/],
  [{serverBusy: true}, /job is active/],
  [{hasFile: false}, /Choose an image/],
  [{previewReady: false}, /up-to-date preview/],
  [{previewReady: false, previewError: 'Prepared image exceeds 1024 rows'}, /Preview failed: Prepared image exceeds 1024 rows/],
  [{validationError: 'Trailing feed must be at least 8'}, /Trailing feed must be at least 8/],
]) {
  const reasons = printBlockReasons({...ready, ...changes});
  assert.equal(reasons.length, 1);
  assert.match(reasons[0], expected);
}
assert.equal(printBlockReasons({...ready, buildMatches: false, hasFile: false, stopped: true}).length, 3);
assert.equal(printBlockReasons({...ready, hasFile: false, previewReady: false, previewError: 'old error'}).length, 1);
console.log('Every disabled-print state has a reason; preview errors and multiple blockers preserved.');
