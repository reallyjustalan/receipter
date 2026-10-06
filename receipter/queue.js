/* Queue state lives on the server Mac, never in browser storage. */
(() => {
  const build = document.querySelector('meta[name="receipter-build"]').content;
  const dialog = document.getElementById('print-queue');
  const list = document.getElementById('queue-jobs');
  const note = document.getElementById('queue-status');
  let pending = false;
  async function request(path, form) {
    const response = await fetch(path, form ? {method:'POST', headers:{'X-Receipter-Build':build}, body:form} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Queue request failed');
    return result;
  }
  async function refresh() {
    try {
      const data = await request('/api/queue');
      document.getElementById('open-queue').textContent = `Queue (${data.jobs.filter(j => j.state !== 'confirmed').length})`;
      if (!dialog.open || pending) return;
      note.textContent = `${data.paused ? 'Paused — Start / continue explicitly to send.' : 'Running — waits for operator confirmation after each receipt.'} Saved on this Mac: ${data.path}`;
      list.replaceChildren();
      const history = document.getElementById('queue-history').checked;
      for (const job of data.jobs.filter(j => history ? j.state === 'confirmed' : j.state !== 'confirmed')) {
        const row = document.createElement('section');
        row.className = 'queue-job';
        const image = document.createElement('img');
        image.src = `/api/queue/${job.id}/preview`;
        image.alt = 'Saved receipt preview';
        row.append(image);
        const title = document.createElement('strong');
        title.textContent = `${job.label} · ${job.send_copies} copies · ${job.state.replaceAll('_', ' ')}`;
        row.append(title);
        const detail = document.createElement('p'); detail.textContent = job.detail; row.append(detail);
        function button(text, action) {
          const b = document.createElement('button'); b.textContent = text;
          b.onclick = async () => {
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
          b.disabled = job.state === 'sending'; row.append(b);
        }
        if (['awaiting_confirmation','interrupted'].includes(job.state)) button('Confirm & next', 'confirm');
        if (['awaiting_confirmation','interrupted','confirmed'].includes(job.state)) button('Reprint / remaining copies', 'reprint');
        button('Delete permanently', 'delete');
        list.append(row);
      }
    } catch (error) { note.textContent = `Queue unavailable: ${error.message}. Saved receipts are retained on the Mac.`; }
  }
  document.getElementById('open-queue').onclick = () => { dialog.showModal(); refresh(); };
  document.getElementById('close-queue').onclick = () => dialog.close();
  document.getElementById('queue-history').onchange = refresh;
  for (const action of ['start','pause']) document.getElementById(`queue-${action}`).onclick = async () => {
    try { await request(`/api/queue/${action}`, new FormData()); await refresh(); }
    catch (error) { alert(error.message); }
  };
  window.receipterQueueRefresh = refresh;
  setInterval(refresh, 1500);
  refresh();
})();
