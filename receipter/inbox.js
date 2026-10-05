'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('photo-inbox');
  const selected = new Set();
  let photos = [], limit = 100, loading = false;
  async function api(path = '', options = {}) {
    const response = await fetch('/api/inbox' + path, options);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Inbox request failed');
    }
    return response.json();
  }
  function render() {
    const grid = $('inbox-photos');
    grid.replaceChildren();
    for (const photo of photos) {
      const label = document.createElement('label');
      const check = document.createElement('input');
      check.type = 'checkbox'; check.checked = selected.has(photo.id);
      check.onchange = () => check.checked ? selected.add(photo.id) : selected.delete(photo.id);
      const image = document.createElement('img');
      image.src = `/api/inbox/photos/${photo.id}/thumbnail`;
      image.alt = photo.name; image.loading = 'lazy';
      const name = document.createElement('span'); name.textContent = photo.name;
      label.append(check, image, name); grid.append(label);
    }
  }
  async function refresh(settings = false) {
    if (loading) return;
    loading = true;
    try {
      const status = await api();
      if (settings) {
        $('inbox-folder').value = status.folder;
        $('inbox-enabled').checked = status.enabled;
      }
      $('inbox-status').textContent = `${status.enabled ? 'Watching' : 'Paused'} · ${status.count} saved photos${status.error ? ' · ' + status.error : ''}`;
      const incoming = [];
      for (let offset = 0; offset < limit; offset += 100) {
        const page = await api('/photos?offset=' + offset);
        incoming.push(...page);
        if (page.length < 100) break;
      }
      if (JSON.stringify(incoming) !== JSON.stringify(photos)) { photos = incoming; render(); }
      $('inbox-more').hidden = photos.length >= status.count;
    } catch (error) { $('inbox-status').textContent = error.message; }
    finally { loading = false; }
  }
  async function save(importExisting = false) {
    try {
      await api('/settings', {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({folder: $('inbox-folder').value, enabled: $('inbox-enabled').checked, import_existing: importExisting})
      });
      await refresh(true);
    } catch (error) { $('inbox-status').textContent = error.message; }
  }
  $('open-inbox').onclick = () => { dialog.showModal(); refresh(true); };
  $('close-inbox').onclick = () => dialog.close();
  $('inbox-settings').onsubmit = event => { event.preventDefault(); save(); };
  $('inbox-import').onclick = () => {
    if (!$('inbox-enabled').checked) {
      $('inbox-status').textContent = 'Enable watching to import existing JPEGs.'; return;
    }
    save(true);
  };
  $('inbox-more').onclick = () => { limit += 100; refresh(); };
  $('inbox-add').onclick = async () => {
    if (!selected.size) { $('inbox-status').textContent = 'Select photos first.'; return; }
    if (selected.size > window.receipterPhotoCapacity()) {
      $('inbox-status').textContent = `This receipt has room for ${window.receipterPhotoCapacity()} more photos.`; return;
    }
    $('inbox-add').disabled = true;
    try {
      const files = [];
      for (const id of selected) {
        const response = await fetch(`/api/inbox/photos/${id}/original`);
        if (!response.ok) throw new Error('Could not load photo');
        files.push(new File([await response.blob()], photos.find(p => p.id === id)?.name || 'photo.jpg', {type:'image/jpeg'}));
      }
      // Re-check after downloads in case the receipt changed.
      if (files.length > window.receipterPhotoCapacity()) throw new Error('Not enough room in this receipt.');
      window.dispatchEvent(new CustomEvent('receipter-inbox-add', {detail:files}));
      selected.clear(); render(); dialog.close();
    } catch (error) { $('inbox-status').textContent = error.message; }
    finally { $('inbox-add').disabled = false; }
  };
  setInterval(() => { if (dialog.open) refresh(); }, 2500);
})();
