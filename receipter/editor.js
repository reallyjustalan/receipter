/* Pure editor state helpers, shared by the page and Node regression tests. */
(function (root) {
  function switchDensity(previousMode, nextMode, current, remembered) {
    remembered[previousMode] = {...current};
    const settings = {...remembered[nextMode]};
    settings.width = Math.max(32, Math.min(Number(settings.width), nextMode === '0' ? 200 : 400));
    return settings;
  }
  function printBlockReasons(state) {
    const reasons = [];
    if (state.statusError) reasons.push(`Cannot check printer: ${state.statusError}`);
    else if (!state.statusKnown) reasons.push('Checking printer status…');
    else {
      if (!state.buildMatches) reasons.push('Server updated. Refresh this page before printing.');
      if (!state.connected) reasons.push('Printer not detected. Check power and USB connection.');
    }
    if (state.stopped) reasons.push('Printing is stopped. Power-cycle the printer, then press Resume.');
    if (state.busy || state.serverBusy) reasons.push('Another job is active. Wait for it to finish, or use STOP.');
    if (!state.hasFile) reasons.push('Choose an image first.');
    else if (!state.previewReady) reasons.push(state.previewError
      ? `Preview failed: ${state.previewError}`
      : 'Waiting for an up-to-date preview. If it stalls, click Refresh preview.');
    if (state.validationError) reasons.push(state.validationError);
    return reasons;
  }
  const api = {switchDensity, printBlockReasons};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ReceiptEditor = api;
})(globalThis);
