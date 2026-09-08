/* Byte inspection only. This module never calls a print endpoint. */
(() => {
  const $ = id => document.getElementById(id);
  const PAGE_BYTES = 1024;
  class ReceiptOutputLog {
    constructor(build, onChange, log) {
      this.build = build; this.onChange = onChange; this.log = log;
      this.key = null; this.plan = null; this.version = 0; this.page = 0; this.verified = false;
      this.state = 'Awaiting receipt preview';
      $('output-prev').onclick = () => { this.page = Math.max(0, this.page-1); this.render(); };
      $('output-next').onclick = () => { this.page++; this.render(); };
      this.render();
    }
    keyFor(snapshot, settings) {
      if (!snapshot || !Number.isInteger(settings.copies) || settings.copies < 1 || settings.copies > 10 ||
          !Number.isInteger(settings.feed_lines) || settings.feed_lines < (settings.cut ? 8 : 0) || settings.feed_lines > 20) return null;
      return JSON.stringify([snapshot.token, settings.cut, settings.feed_lines, settings.copies]);
    }
    ready(snapshot, settings) {
      return this.verified && !!this.key && this.key === this.keyFor(snapshot, settings) && this.plan?.key === this.key;
    }
    update(snapshot, settings) {
      const key = this.keyFor(snapshot, settings);
      if (key === this.key) return;
      this.key = key;
      this.verified = false;
      const version = ++this.version;
      this.controller?.abort();
      if (!key) {
        if (!['Sending', 'USB accepted', 'Failed / delivery uncertain'].includes(this.state)) this.state = 'Stale — waiting for a valid preview';
        this.render(); return;
      }
      this.state = 'Encoding — not sent'; this.render();
      this.controller = new AbortController();
      this.load(snapshot, {...settings}, key, version, this.controller.signal);
    }
    async load(snapshot, settings, key, version, signal) {
      try {
        const form = new FormData();
        form.append('snapshot', snapshot.token);
        for (const [name, value] of Object.entries(settings)) form.append(name, value);
        const response = await fetch('/api/receipt-output', {method:'POST', body:form, signal});
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Cannot encode output');
        if (version !== this.version) return;
        if (data.build_id !== this.build) throw new Error('Server updated. Refresh this page.');
        const bytes = Uint8Array.from(atob(data.raw_base64), char => char.charCodeAt(0));
        if (bytes.length !== data.bytes) throw new Error('Output byte count mismatch');
        this.plan = {...data, bytes, key}; this.page = 0; this.verified = true;
        this.state = 'Prepared — not sent';
        if (this.url) URL.revokeObjectURL(this.url);
        this.url = URL.createObjectURL(new Blob([bytes], {type:'application/octet-stream'}));
        $('download-raw').href = this.url;
        $('download-raw').setAttribute('aria-disabled','false');
        this.log(`PREPARED ${bytes.length} bytes · ${data.parts} parts · ${data.copies} copies · SHA-256 ${data.sha256}`);
      } catch (error) {
        if (version !== this.version || error.name === 'AbortError') return;
        this.state = `Output error: ${error.message}`;
        this.log(this.state);
      } finally {
        if (version === this.version) { this.render(); this.onChange(); }
      }
    }
    mark(state, plan) {
      if (plan === this.plan) { this.state = state; this.render(); }
    }
    render() {
      $('output-status').textContent = this.state;
      const plan = this.plan;
      if (!plan) {
        $('raw-output').textContent = 'No encoded bytes yet.';
        $('output-page').textContent = '';
        $('output-prev').disabled = $('output-next').disabled = true;
        return;
      }
      const pages = Math.max(1, Math.ceil(plan.bytes.length / PAGE_BYTES));
      this.page = Math.max(0, Math.min(this.page, pages-1));
      $('raw-output').textContent = ReceiptEditor.hexDump(plan.bytes, this.page*PAGE_BYTES, PAGE_BYTES);
      $('raw-output').scrollTop = 0;
      $('output-page').textContent = `Page ${this.page+1}/${pages} · ${plan.bytes.length.toLocaleString()} bytes · ${plan.parts} parts`;
      $('output-page').title = `SHA-256 ${plan.sha256}. Offsets are hexadecimal; non-printable bytes are shown as dots in the ASCII column.`;
      $('output-prev').disabled = this.page === 0;
      $('output-next').disabled = this.page === pages-1;
    }
  }
  globalThis.ReceiptOutputLog = ReceiptOutputLog;
})();
