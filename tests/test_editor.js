const assert = require('node:assert/strict');
const {printBlockReasons, moveBlock, receiptTotal, itemQuantity, defaultEdits, formatReceiptDate, hexDump} = require('../receipter/editor.js');

const ready = {statusKnown: true, buildMatches: true, connected: true, stopped: false,
  busy: false, serverBusy: false, hasReceipt: true, previewReady: true,
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
  [{hasReceipt: false}, /Add a receipt section/],
  [{previewReady: false}, /up-to-date preview/],
  [{previewReady: false, previewError: 'Prepared image exceeds 1024 rows'}, /Preview failed: Prepared image exceeds 1024 rows/],
  [{validationError: 'Trailing feed must be at least 8'}, /Trailing feed must be at least 8/],
]) {
  const reasons = printBlockReasons({...ready, ...changes});
  assert.equal(reasons.length, 1);
  assert.match(reasons[0], expected);
}
assert.equal(printBlockReasons({...ready, buildMatches: false, hasReceipt: false, stopped: true}).length, 3);
assert.equal(printBlockReasons({...ready, hasReceipt: false, previewReady: false, previewError: 'old error'}).length, 1);
console.log('Every disabled-print state has a reason; preview errors and multiple blockers preserved.');

const photoA = {id: 'a', edits: defaultEdits()};
const photoB = {id: 'b', edits: {...defaultEdits(), crop_zoom: 2, assignment: 'red'}};
const blocks = [{id: 'header'}, photoA, photoB, {id: 'footer'}];
const reordered = moveBlock(blocks, 'b', 1);
assert.deepEqual(reordered.map(b => b.id), ['header', 'b', 'a', 'footer']);
assert.deepEqual(blocks.map(b => b.id), ['header', 'a', 'b', 'footer']);
assert.equal(reordered[1], photoB);
assert.equal(reordered[1].edits.crop_zoom, 2);
assert.equal(reordered[2].edits.crop_zoom, 1);
assert.equal(moveBlock(blocks, 'unknown', 1), blocks);
assert.equal(moveBlock(blocks, 'a', -20)[0], photoA);
assert.equal(moveBlock(blocks, 'a', 20).at(-1), photoA);
assert.equal(defaultEdits(true).fit, 'contain');
assert.equal(defaultEdits().fit, 'cover');
assert.equal(receiptTotal([{quantity: 3, price: '0.10'}, {quantity: 1, price: '0.20'}]), .50);
assert.equal(receiptTotal([]), 0);
const autoItem = {quantity: 7, quantity_mode: 'photos', price: '0.10'};
const manualItem = {quantity: 2, price: '1.25'};
for (const photos of [0, 1, 2, 3]) {
  assert.equal(itemQuantity(autoItem, photos), photos);
  assert.equal(itemQuantity(manualItem, photos), 2);
  assert.equal(receiptTotal([autoItem, manualItem], photos), (photos * 10 + 250) / 100);
}
assert.equal(autoItem.quantity, 7, 'Automatic counts must not overwrite the manual fallback');
console.log('Stable section reordering, independent edits and cent-accurate totals passed.');
assert.equal(formatReceiptDate(new Date(2026, 8, 8, 4, 5)), '08/09/2026 04:05');
assert.equal(formatReceiptDate(new Date(2026, 11, 31, 23, 59)), '31/12/2026 23:59');
const sample = Uint8Array.from([0x1b, 0x3d, 0x01, 0x41, 0x3c, 0x26, 0xff]);
assert.match(hexDump(sample), /^00000000  1b 3d 01 41 3c 26 ff/);
assert.ok(hexDump(sample).endsWith('|.=.A<&.|'));
assert.equal(hexDump(new Uint8Array()), '');
assert.match(hexDump(new Uint8Array(2048), 1024, 16), /^00000400  /);
assert.equal(hexDump(new Uint8Array(2048), 1024, 16).split('\n').length, 1);
console.log('Local receipt timestamps and paged hex/ASCII output formatting passed.');
