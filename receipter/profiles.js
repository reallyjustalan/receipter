'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let catalogue = {profiles:[], default_id:''}, activeId = '', busy = false;
  const dialog = $('receipt-profiles');
  function controls() {
    for (const element of $('profile-form').elements) element.disabled = busy;
    $('profile-load').disabled = busy || !$('profile-select').value;
    $('profile-new').disabled = busy;
    $('close-profiles').disabled = busy;
  }
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  async function api(path = '', options = {}) {
    const response = await fetch('/api/profiles' + path, options);
    let result;
    try { result = JSON.parse(await response.text()); }
    catch { throw new Error(`Profile server error (HTTP ${response.status}). Check the server terminal.`); }
    if (!response.ok) throw new Error(result.detail || 'Profile request failed');
    return result;
  }
  async function list() {
    catalogue = await api();
    const select = $('profile-select');
    select.replaceChildren(new Option('New profile', ''));
    for (const profile of catalogue.profiles) {
      select.add(new Option(profile.name + (profile.id === catalogue.default_id ? ' (default)' : ''), profile.id));
    }
    select.value = catalogue.profiles.some(p => p.id === activeId) ? activeId : '';
    choose();
  }
  function choose() {
    const id = $('profile-select').value;
    $('profile-name').value = catalogue.profiles.find(p => p.id === id)?.name || '';
    $('profile-default').checked = id ? id === catalogue.default_id : true;
    controls();
  }
  function activate(profile) {
    const files = new Map();
    for (const asset of profile.assets) {
      const data = Uint8Array.from(atob(asset.data), char => char.charCodeAt(0));
      files.set(asset.id, new File([data], asset.name, {type:asset.mime}));
    }
    window.receipterApplyProfile(profile.document, profile.options, files);
    activeId = profile.id;
    $('open-profiles').textContent = `Profile: ${profile.name}`;
  }
  window.receipterInitializeProfile = async () => {
    await list();
    if (catalogue.default_id) activate(await api('/' + encodeURIComponent(catalogue.default_id)));
  };
  $('open-profiles').onclick = async () => {
    dialog.showModal(); busy = true; controls();
    $('profile-status').textContent = 'Loading profiles…';
    try { await list(); $('profile-status').textContent = ''; }
    catch (error) { $('profile-status').textContent = error.message; }
    finally { busy = false; controls(); }
  };
  $('close-profiles').onclick = () => dialog.close();
  $('profile-select').onchange = choose;
  $('profile-new').onclick = () => { $('profile-select').value = ''; choose(); $('profile-name').focus(); };
  $('profile-form').onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    busy = true; controls(); $('profile-status').textContent = 'Saving profile…';
    try {
      const snapshot = window.receipterProfileSnapshot();
      const form = new FormData();
      form.append('name', $('profile-name').value);
      form.append('profile_id', $('profile-select').value);
      form.append('make_default', $('profile-default').checked);
      form.append('document', JSON.stringify(snapshot.document));
      form.append('options', JSON.stringify(snapshot.options));
      for (const [id, file] of snapshot.assets) form.append('assets', file, id);
      const result = await api('', {method:'POST', body:form});
      activeId = result.id;
      $('open-profiles').textContent = `Profile: ${result.name}`;
      await list();
      $('profile-status').textContent = 'Saved on this server. Camera photos were not included.';
    } catch (error) { $('profile-status').textContent = error.message; }
    finally { busy = false; controls(); }
  };
  $('profile-load').onclick = async () => {
    if (busy || !$('profile-select').value) return;
    if (!window.confirm('Replace the current receipt with this profile? Unsaved edits and camera photos will be removed.')) return;
    busy = true; controls(); $('profile-status').textContent = 'Loading profile…';
    try {
      activate(await api('/' + encodeURIComponent($('profile-select').value)));
      dialog.close();
    } catch (error) { $('profile-status').textContent = error.message; }
    finally { busy = false; controls(); }
  };
})();
