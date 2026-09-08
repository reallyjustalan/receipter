/* Pure editor state helpers, shared by the page and Node regression tests. */
(function (root) {
  function printBlockReasons(state) {
    const reasons = [];
    if (state.statusError) reasons.push(`Cannot check printer: ${state.statusError}`);
    else if (!state.statusKnown) reasons.push('Checking printer status…');
    else {
      if (!state.buildMatches) reasons.push('Server updated. Refresh this page before printing.');
      if (!state.connected) reasons.push('Printer not detected. Connect and power it on to print; you can keep editing offline.');
    }
    if (state.stopped) reasons.push('Printing is stopped. Power-cycle the printer, then press Resume.');
    if (state.busy || state.serverBusy) reasons.push('Another job is active. Wait for it to finish, or use STOP.');
    if (!state.hasReceipt) reasons.push('Add a receipt section first.');
    else if (!state.previewReady) reasons.push(state.previewError
      ? `Preview failed: ${state.previewError}`
      : 'Waiting for an up-to-date preview. If it stalls, click Refresh preview.');
    if (state.validationError) reasons.push(state.validationError);
    return reasons;
  }
  function moveBlock(blocks, id, index) {
    const from = blocks.findIndex(block => block.id === id);
    if (from < 0) return blocks;
    const result = [...blocks];
    const [block] = result.splice(from, 1);
    result.splice(Math.max(0, Math.min(index, result.length)), 0, block);
    return result;
  }
  function receiptTotal(items) {
    return items.reduce((sum, item) => sum + Math.round(Number(item.price) * 100) * Number(item.quantity), 0) / 100;
  }
  function defaultEdits(logo = false) {
    return {rotation: 0, flip_horizontal: false, flip_vertical: false,
      brightness: 1, contrast: 1, threshold: 128, dither: true, assignment: 'auto',
      black_ink: 100, red_ink: 100, crop_zoom: 1, crop_x: .5, crop_y: .5,
      fit: logo ? 'contain' : 'cover'};
  }
  const api = {printBlockReasons, moveBlock, receiptTotal, defaultEdits};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ReceiptEditor = api;
})(globalThis);
