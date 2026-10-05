'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('photo-inbox');
  const selected = new Set();
  const cache = new Map();
  const dragType = 'application/x-receipter-photo';
  let photos = [], limit = 100, refreshing = null, adding = false, saving = false;
  let actionMessage = '';

  function message(text) {
    actionMessage = text;
    $('inbox-status').textContent = text;
    $('tray-status').textContent = text;
  }
  function showStatus(status) {
    const text = status.folder
      ? `${status.enabled ? 'Watching' : 'Paused'} · ${status.count} saved photos${status.error ? ' · ' + status.error : ''}`
      : 'Choose a camera folder to get started.';
    if (!adding && !actionMessage) {
      $('inbox-status').textContent = text;
      $('tray-status').textContent = text;
    }
    $('open-inbox').textContent = status.count ? `Photo inbox (${status.count})` : 'Photo inbox';
  }
  function settingsBusy(busy) {
    for (const input of $('inbox-settings').elements) input.disabled = busy;
  }
  function applySettings(status) {
    $('inbox-folder').value = status.folder;
    $('inbox-enabled').checked = status.enabled || !status.folder;
    $('inbox-existing').checked = !status.folder;
  }
  function updateActions() {
    const capacity = window.receipterPhotoCapacity();
    $('inbox-add').disabled = adding || !selected.size || selected.size > capacity;
    $('inbox-add').textContent = selected.size ? `Add ${selected.size} selected to receipt` : 'Add selected to receipt';
    $('inbox-latest').disabled = adding || !photos.length || capacity < 1;
    for (const button of $('tray-photos').querySelectorAll('button')) button.disabled = adding || capacity < 1;
  }
  async function api(path = '', options = {}) {
    const response = await fetch('/api/inbox' + path, options);
    let result;
    try { result = JSON.parse(await response.text()); }
    catch { throw new Error(`Inbox server error (HTTP ${response.status}). Check the server terminal.`); }
    if (!response.ok) throw new Error(result.detail || 'Inbox request failed');
    return result;
  }
  function thumbnail(photo) {
    const image = document.createElement('img');
    image.src = `/api/inbox/photos/${photo.id}/thumbnail`;
    image.alt = photo.name; image.loading = 'lazy'; image.draggable = false;
    return image;
  }
  function draggable(element, photo) {
    element.draggable = true;
    element.addEventListener('dragstart', event => {
      event.dataTransfer.setData(dragType, photo.id);
      event.dataTransfer.effectAllowed = 'copy';
    });
  }
  function render() {
    const grid = $('inbox-photos');
    grid.replaceChildren();
    for (const photo of photos) {
      const label = document.createElement('label');
      const check = document.createElement('input');
      check.type = 'checkbox'; check.checked = selected.has(photo.id);
      check.onchange = () => {
        if (check.checked) selected.add(photo.id); else selected.delete(photo.id);
        updateActions();
      };
      const name = document.createElement('span'); name.textContent = photo.name;
      label.append(check, thumbnail(photo), name); grid.append(label);
    }
    const tray = $('tray-photos');
    tray.replaceChildren();
    for (const photo of photos.slice(0, 12)) {
      const card = document.createElement('div');
      card.className = 'tray-photo'; card.dataset.photoId = photo.id;
      draggable(card, photo);
      const name = document.createElement('span'); name.textContent = photo.name;
      const add = document.createElement('button'); add.textContent = 'Add';
      add.setAttribute('aria-label', `Add ${photo.name} to receipt`);
      add.onclick = () => addPhotos([photo.id]);
      card.append(thumbnail(photo), name, add); tray.append(card);
    }
    updateActions();
  }
  function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      try {
        const status = await api();
        showStatus(status);
        const incoming = [];
        const pageLimit = dialog.open ? limit : 100;
        for (let offset = 0; offset < pageLimit; offset += 100) {
          const page = await api('/photos?offset=' + offset);
          incoming.push(...page);
          if (page.length < 100) break;
        }
        // Keep selected older photos when the dialog is closed or new shots arrive.
        const retained = photos.filter(photo => selected.has(photo.id) && !incoming.some(p => p.id === photo.id));
        incoming.push(...retained);
        if (JSON.stringify(incoming) !== JSON.stringify(photos)) { photos = incoming; render(); }
        $('inbox-more').hidden = photos.length >= status.count;
        updateActions();
      } catch (error) { message(error.message); }
      finally { refreshing = null; }
    })();
    return refreshing;
  }
  async function openInbox() {
    if (dialog.open) return;
    dialog.showModal(); settingsBusy(true);
    try {
      // Never let background polling overwrite unsaved folder edits.
      const status = await api(); applySettings(status); showStatus(status);
      await refresh();
    } catch (error) { message(error.message); }
    finally { if (!saving) settingsBusy(false); }
  }
  async function save(importExisting = false) {
    if (saving) return;
    saving = true; settingsBusy(true); actionMessage = '';
    try {
      const status = await api('/settings', {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({folder: $('inbox-folder').value, enabled: importExisting || $('inbox-enabled').checked,
                              import_existing: importExisting || $('inbox-existing').checked})
      });
      applySettings(status); showStatus(status);
      await refresh();
    } catch (error) { message(error.message); }
    finally { saving = false; settingsBusy(false); }
  }
  async function workingFile(id) {
    if (cache.has(id)) return cache.get(id);
    const response = await fetch(`/api/inbox/photos/${id}/working`);
    if (!response.ok) throw new Error(`Could not load photo (HTTP ${response.status}). Try again.`);
    const file = new File([await response.blob()], photos.find(p => p.id === id)?.name || 'photo.jpg', {type:'image/jpeg'});
    cache.set(id, file);
    // Bounded cache avoids repeat downloads without retaining the whole catalogue.
    while (cache.size > 12) cache.delete(cache.keys().next().value);
    return file;
  }
  async function addPhotos(ids, beforeId = null) {
    if (adding) return;
    if (!ids.length) { message('Select photos first.'); return; }
    if (ids.length > window.receipterPhotoCapacity()) {
      message(`This receipt has room for ${window.receipterPhotoCapacity()} more photos.`); return;
    }
    adding = true; updateActions(); message('Loading photos…');
    try {
      // Download selections concurrently, preserving selection order. Add only if all succeed.
      const files = await Promise.all(ids.map(workingFile));
      if (files.length > window.receipterPhotoCapacity()) throw new Error('Not enough room in this receipt.');
      window.dispatchEvent(new CustomEvent('receipter-inbox-add', {detail:{files, beforeId}}));
      selected.clear(); render(); dialog.close();
      message(`Added ${files.length} ${files.length === 1 ? 'photo' : 'photos'} to receipt.`);
    } catch (error) { message(error.message); }
    finally { adding = false; updateActions(); }
  }
  $('open-inbox').onclick = openInbox;
  $('tray-settings').onclick = openInbox;
  $('close-inbox').onclick = () => dialog.close();
  $('inbox-settings').onsubmit = event => { event.preventDefault(); save(); };
  $('inbox-import').onclick = () => save(true);
  $('inbox-more').onclick = async () => { limit += 100; await refresh(); await refresh(); };
  $('inbox-add').onclick = () => addPhotos([...selected]);
  $('inbox-latest').onclick = () => addPhotos(photos.length ? [photos[0].id] : []);
  window.addEventListener('receipter-receipt-changed', updateActions);
  window.addEventListener('receipter-inbox-drop', event => addPhotos([event.detail.id], event.detail.beforeId));
  refresh();
  setInterval(() => {
    if (!document.hidden) { if (!adding) actionMessage = ''; refresh(); }
  }, 2500);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
