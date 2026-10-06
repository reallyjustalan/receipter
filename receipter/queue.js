/* Queue state lives on the server Mac, never in browser storage. */
(() => {
  const build = document.querySelector('meta[name="receipter-build"]').content;
  const panel = document.getElementById('print-queue');
  const list = document.getElementById('queue-jobs');
  const note = document.getElementById('queue-status');
  const stateNames = {waiting:'Waiting', sending:'Sending', awaiting_confirmation:'Awaiting confirmation',
    interrupted:'Interrupted — check output', confirmed:'Confirmed'};
  let pending = false, version = 0, lastRender = '';
  async function request(path, form) {
    const response = await fetch(path, form ? {method:'POST', headers:{'X-Receipter-Build':build}, body:form} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Queue request failed');
    return result;
  }
  async function refresh() {
    const current = ++version;
    try {
      const data = await request('/api/queue');
      if (current !== version) return;
      const active = data.jobs.filter(j => j.state !== 'confirmed');
      document.getElementById('queue-count').textContent = `(${active.length})`;
      if (panel.hidden || pending) return;
      note.textContent = data.paused ? 'Paused — click Start / continue to send.'
        : 'Running — each receipt waits for your confirmation before the next one sends.';
      document.getElementById('queue-storage-path').textContent = data.path;
      const head = active[0];
      document.getElementById('queue-summary').textContent = head
        ? `Next / current: ${head.label} · ${stateNames[head.state]} · ${active.length} active ${active.length === 1 ? 'receipt' : 'receipts'}`
        : 'No active receipts. Add a receipt from Printer preview to get started.';
      const history = document.getElementById('queue-history').checked;
      const key = JSON.stringify([data, history]);
      // Keep keyboard focus and expanded proofs stable between unchanged polls.
      if (key === lastRender) return;
      lastRender = key;
      const expanded = new Set(Array.from(list.querySelectorAll('details[open]'), d => d.dataset.job));
      const focused = document.activeElement;
      const focusJob = focused?.closest('.queue-job')?.dataset.job;
      const focusAction = focused?.dataset.action;
      list.replaceChildren();
      const jobs = data.jobs.filter(j => history ? j.state === 'confirmed' : j.state !== 'confirmed');
      if (!jobs.length) {
        const empty = document.createElement('p'); empty.className = 'queue-empty';
        empty.textContent = history ? 'No confirmed receipts yet. Nothing moves here until you confirm the paper.'
          : 'Your queue is empty. Prepare a receipt, choose copies, then Add to queue.';
        list.append(empty);
      }
      for (const job of jobs) {
        const row = document.createElement('section');
        row.className = 'queue-job'; row.dataset.job = job.id; row.dataset.state = job.state;
        const image = document.createElement('img');
        image.className = 'queue-thumbnail'; image.src = `/api/queue/${job.id}/preview`;
        image.alt = `Saved receipt for ${job.label}`; image.loading = 'lazy'; row.append(image);
        const info = document.createElement('div'); info.className = 'queue-job-info';
        const title = document.createElement('strong');
        title.textContent = `${job.label} · ${job.send_copies} ${job.send_copies === 1 ? 'copy' : 'copies'} · ${stateNames[job.state]}`;
        info.append(title);
        const detail = document.createElement('p'); detail.textContent = job.detail; info.append(detail);
        const created = document.createElement('p'); created.className = 'muted';
        created.textContent = `Saved ${new Date(job.created * 1000).toLocaleString()}`; info.append(created);
        row.append(info);
        const actions = document.createElement('div'); actions.className = 'queue-job-actions';
        function button(text, action) {
          const b = document.createElement('button'); b.textContent = text; b.dataset.action = action;
          if (action === 'confirm') b.className = 'primary';
          if (action === 'delete') b.className = 'remove';
          b.onclick = async () => {
            if (pending) return;
            const form = new FormData(); form.append('action', action);
            if (action === 'delete' && !confirm('Permanently delete this saved receipt? This cannot be undone.')) return;
            if (action === 'confirm' && !confirm('Have you physically checked all requested copies and cuts?')) return;
            if (action === 'reprint') {
              const count = prompt('How many copies should be resent? Inspect the paper first.', String(job.copies));
              if (count === null) return;
              if (!/^([1-9]|10)$/.test(count)) { alert('Choose a whole number from 1 to 10.'); return; }
              form.append('copies', count);
            }
            pending = true;
            try { await request(`/api/queue/${job.id}/action`, form); }
            catch (error) { alert(error.message); }
            finally { pending = false; await refresh(); }
          };
          b.disabled = job.state === 'sending'; actions.append(b);
        }
        if (head?.id === job.id && ['awaiting_confirmation','interrupted'].includes(job.state)) button('Confirm & next', 'confirm');
        if (['awaiting_confirmation','interrupted','confirmed'].includes(job.state)) button('Reprint / remaining copies', 'reprint');
        button('Delete permanently', 'delete'); row.append(actions);
        const proof = document.createElement('details'); proof.className = 'queue-proof'; proof.dataset.job = job.id;
        proof.open = expanded.has(job.id);
        const summary = document.createElement('summary'); summary.textContent = 'View full receipt'; proof.append(summary);
        const full = document.createElement('img'); full.src = image.src; full.alt = `Full saved receipt for ${job.label}`;
        full.loading = 'lazy'; proof.append(full); row.append(proof);
        list.append(row);
      }
      if (focusJob && focusAction) {
        const row = Array.from(list.children).find(r => r.dataset.job === focusJob);
        Array.from(row?.querySelectorAll('button') || []).find(b => b.dataset.action === focusAction)?.focus({preventScroll:true});
      }
    } catch (error) {
      if (current !== version) return;
      note.textContent = `Queue unavailable: ${error.message}. Saved receipts are retained on the Mac.`;
    }
  }
  document.getElementById('queue-history').onchange = refresh;
  for (const action of ['start','pause']) document.getElementById(`queue-${action}`).onclick = async () => {
    if (pending) return;
    pending = true;
    try { await request(`/api/queue/${action}`, new FormData()); }
    catch (error) { alert(error.message); }
    finally { pending = false; await refresh(); }
  };
  window.addEventListener('receipter-mode-changed', () => { if (!panel.hidden) refresh(); });
  window.receipterQueueRefresh = refresh;
  setInterval(refresh, 1500);
  refresh();
})();
