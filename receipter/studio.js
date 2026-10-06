'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const {defaultEdits, moveBlock, receiptTotal, itemQuantity, formatReceiptDate} = ReceiptEditor;
  const build = document.querySelector('meta[name="receipter-build"]').content;
  const uid = () => crypto.randomUUID();
  const escapeHTML = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const names = {header:'Header & logo', photo:'Photo', footer:'Itemised footer', text:'Text', signature:'Signature', spacer:'Spacer'};
  const icons = {header:'◈', photo:'▧', footer:'≡', text:'T', signature:'〰', spacer:'↕'};
  function newBlock(type) {
    const block = {id:uid(), type};
    if (type === 'header') Object.assign(block, {title:'THE PHOTO BOOTH', subtitle:'', asset:null, height:100, edits:defaultEdits(true)});
    if (type === 'photo') Object.assign(block, {asset:null, height:240, caption:'', edits:defaultEdits()});
    if (type === 'footer') Object.assign(block, {items:[{label:'Photo strip', quantity:1, price:'0.00'}], currency:'$', date:'', reference:'', text:'THANK YOU'});
    if (type === 'text') Object.assign(block, {text:'Receipt text', wrap_mode:'word'});
    if (type === 'signature') block.label = 'Signature';
    if (type === 'spacer') block.height = 24;
    return block;
  }
  let documentState = {blocks:[newBlock('header'), newBlock('footer'), newBlock('signature')]};
  let selected = documentState.blocks[0].id;
  const assets = new Map();
  const originalImages = new Map();
  const editorThumbnails = new Map();
  const backgroundJobs = new Set();
  let imageTool = 'crop', brushSize = 3, eraseSource = null, eraseDrag = null;
  const automaticDates = new Set();
  let lastEditingMode = 'layout';
  let mode = 'layout', zoom = Number($('zoom').value), revision = 0, timer, controller, snapshot = null;
  let previewError = '', busy = false, dirty = false, status = null, statusError = '', stoppedLocally = false;
  let finishing = {cut:true, feed_lines:8, copies:1};
  let uploadTarget = null;
  const selectedBlock = () => documentState.blocks.find(b => b.id === selected);
  const photoCount = () => documentState.blocks.filter(b => b.type === 'photo').length;
  const tell = message => {
    const entry = document.createElement('div');
    entry.textContent = `[${new Date().toLocaleTimeString('en-GB')}] ${message}`;
    $('message').append(entry);
    while ($('message').children.length > 40) $('message').firstChild.remove();
    $('message').scrollTop = $('message').scrollHeight;
  };
  const outputLog = new ReceiptOutputLog(build, updatePrint, tell);
  // Reserve the bars' actual wrapped heights, including mobile and log collapse.
  const resizeBars = new ResizeObserver(() => {
    document.documentElement.style.setProperty('--top-bar-height', `${$('top-bar').offsetHeight}px`);
    document.documentElement.style.setProperty('--bottom-bar-height', `${$('bottom-bar').offsetHeight}px`);
  });
  resizeBars.observe($('top-bar')); resizeBars.observe($('bottom-bar'));

  function renderList() {
    $('sections').innerHTML = documentState.blocks.map((b, i) => `<li draggable="true" data-id="${b.id}" class="${b.id === selected ? 'selected' : ''}"><button class="section-select" data-select="${b.id}" aria-pressed="${b.id === selected}"><span class="section-icon" aria-hidden="true">${icons[b.type]}</span><span class="section-name">${escapeHTML(b.type === 'header' ? b.title || names[b.type] : names[b.type])}<small>${String(i+1).padStart(2,'0')} / ${b.type.toUpperCase()}</small></span></button><div class="move-buttons"><button data-move="-1" data-id="${b.id}" aria-label="Move ${names[b.type]} up" ${i===0?'disabled':''}>↑</button><button data-move="1" data-id="${b.id}" aria-label="Move ${names[b.type]} down" ${i===documentState.blocks.length-1?'disabled':''}>↓</button></div></li>`).join('');
    const count = documentState.blocks.filter(b => b.type === 'photo').length;
    $('photo-count').textContent = `${count} / 3`;
    $('add-photos').disabled = count >= 3 || documentState.blocks.length >= 16;
    document.querySelectorAll('[data-add]').forEach(b => b.disabled = documentState.blocks.length >= 16);
    document.querySelector('[data-mode="image"]').disabled = !selectedBlock()?.asset;
    renderImageSwitcher();
  }

  function imageLabel(block) {
    return block?.type === 'header' ? 'Header / logo' : `Photo ${documentState.blocks.filter(b => b.type === 'photo').findIndex(b => b.id === block?.id) + 1}`;
  }
  function renderImageSwitcher() {
    const editable = documentState.blocks.filter(b => (b.type === 'photo' || b.type === 'header') && assets.has(b.asset));
    const used = new Set(editable.map(b => assets.get(b.asset)));
    for (const [file, url] of editorThumbnails) {
      if (!used.has(file)) { URL.revokeObjectURL(url); editorThumbnails.delete(file); }
    }
    const picker = $('image-switcher');
    picker.replaceChildren();
    for (const block of editable) {
      const file = assets.get(block.asset);
      if (!editorThumbnails.has(file)) editorThumbnails.set(file, URL.createObjectURL(file));
      const button = document.createElement('button');
      button.type = 'button'; button.dataset.imageSelect = block.id;
      button.setAttribute('aria-pressed', String(block.id === selected));
      button.setAttribute('aria-label', `Edit ${imageLabel(block)}`);
      const image = document.createElement('img');
      image.src = editorThumbnails.get(file); image.alt = ''; image.onerror = () => { image.hidden = true; };
      const label = document.createElement('span'); label.textContent = imageLabel(block);
      button.append(image, label); picker.append(button);
    }
  }
  function selectBlock(id) {
    cropDrag = null; eraseDrag = null;
    selected = id;
    if (mode === 'image' && !selectedBlock()?.asset) mode = 'layout';
    renderList(); renderMode(); renderInspector(); paintPreview();
  }
  function setMode(next) {
    if (next === 'image' && !selectedBlock()?.asset) return;
    const queueSwitch = next === 'queue' || mode === 'queue';
    if (next === 'queue' && mode !== 'queue') lastEditingMode = mode;
    mode = next; renderMode();
    if (mode !== 'queue') { renderInspector(); paintPreview(); }
    if (queueSwitch) window.scrollTo(0, 0);
  }
  function renderMode() {
    const queueView = mode === 'queue';
    $('workspace').dataset.mode = mode;
    $('workspace').hidden = queueView;
    $('print-queue').hidden = !queueView;
    $('bottom-bar').hidden = queueView;
    document.body.classList.toggle('queue-view', queueView);
    document.querySelectorAll('[data-mode]').forEach(button => {
      if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', button.dataset.mode === mode);
    });
    $('receipt-stage').hidden = mode === 'image';
    $('image-stage').hidden = mode !== 'image';
    $('stage-title').textContent = {layout:'LIVE RECEIPT', image:'INDIVIDUAL IMAGE / LIVE DOTS', final:'FINAL PRINTER PROOF', queue:'SAVED PRINT QUEUE'}[mode];
    $('zoom').disabled = mode === 'image' || queueView;
    window.dispatchEvent(new Event('receipter-mode-changed'));
  }

  function field(label, key, value, {type='text', min, max, step, area=false} = {}) {
    const attrs = `${min!==undefined?` min="${min}"`:''}${max!==undefined?` max="${max}"`:''}${step?` step="${step}"`:''}`;
    return `<label>${label}${area ? `<textarea data-field="${key}" maxlength="${max||400}">${escapeHTML(value)}</textarea>` : `<input data-field="${key}" type="${type}" value="${escapeHTML(value)}" ${type==='text'?`maxlength="${max||100}"`:attrs}>`}</label>`;
  }
  function range(label, key, value, min, max, step=1) {
    return `<label><span class="control-label">${label}<output data-output="${key}">${value}</output></span><input data-edit="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${value}"></label>`;
  }
  function check(label, key, value) {
    return `<label class="check"><input data-edit="${key}" type="checkbox" ${value?'checked':''}>${label}</label>`;
  }
  function select(label, key, value, options) {
    return `<label>${label}<select data-edit="${key}">${options.map(([v,l]) => `<option value="${v}" ${String(v)===String(value)?'selected':''}>${l}</option>`).join('')}</select></label>`;
  }
  function imageLayout(b) {
    return `<hr><h3>${b.type==='header'?'Logo':'Photo'} frame</h3><button class="wide" id="replace-asset">${b.asset?'Replace image':'Upload SVG or image'}</button>${b.asset?'<button id="edit-image" class="primary wide">Crop & process image →</button>':''}${b.type==='header'&&b.asset?'<button id="remove-logo" class="remove">Remove logo</button>':''}${field('Frame height (layout pixels)', 'height', b.height, {type:'number', min:32, max:800})}<p class="muted">This changes the section’s size on paper, not the printer scale.</p>`;
  }
  function renderInspector() {
    const panel = $('inspector-content');
    const b = selectedBlock();
    if (mode === 'final') {
      panel.innerHTML = `<p class="eyebrow">PRINT SETTINGS</p><h2>The final receipt</h2><p class="muted">The receipt on the left previews the saved artwork and native text. Add to queue saves this exact receipt on the Mac. You can edit the next one while it prints; built-in printer lettering is approximate on screen.</p><div class="proof-note">400 columns · 0.5 canonical scale<br>Black + red ribbon · 76 mm paper<br>View zoom never changes print data.<br>Paper clearance below is added after the artwork.</div><hr><h3>Print & finish</h3><label>Copies (1–10)<input id="copies" type="number" min="1" max="10" step="1" value="${finishing.copies}"></label><p class="muted">Each copy gets the selected feed/cut. STOP cancels all remaining unsent copies but keeps the saved receipt for reprinting.</p><label class="check"><input id="cut" type="checkbox" ${finishing.cut?'checked':''}>Partial cut after printing</label><label>Trailing feed (lines)<input id="feed-lines" type="number" min="${finishing.cut?8:0}" max="20" value="${finishing.feed_lines}"></label><p class="muted">With cutting, allow at least 8 lines (~34 mm) for the print head to clear. A partial cut leaves a small bridge.</p><button id="print-receipt" class="primary wide" disabled>Add to queue →</button><p id="print-reasons" role="status"></p><hr><p class="muted">Custom titles and artwork print as images. Built-in titles and other text use the printer’s font and selected size; preview glyph shapes and alignment may differ. Ribbon shade and pin spacing may vary. USB delivery does not confirm physical output.</p><button id="back-editing" class="wide">← Keep editing</button>`;
      $('cut').onchange = () => { finishing.cut = $('cut').checked; if (finishing.cut) finishing.feed_lines = Math.max(8, finishing.feed_lines); renderInspector(); };
      $('feed-lines').oninput = () => { finishing.feed_lines = Number($('feed-lines').value); updatePrint(); };
      $('copies').oninput = () => { finishing.copies = Number($('copies').value); updatePrint(); };
      $('print-receipt').onclick = printReceipt;
      $('back-editing').onclick = () => setMode('layout');
      updatePrint();
      return;
    }
    if (!b) { panel.innerHTML = '<h2>Empty receipt</h2><p class="muted">Add a section to begin your receipt.</p>'; return; }
    if (mode === 'image') {
      const e = b.edits;
      panel.innerHTML = `<p class="eyebrow">JUST THIS IMAGE</p><h2>Image settings</h2><p class="muted">Independent settings for this ${b.type==='header'?'logo':'photo'}. Preview updates as you edit.</p>${select('Frame fit','fit',e.fit,[['cover','Crop to fill'],['contain','Fit entire image (white surround)']])}<div id="crop-controls">${range('Image zoom','crop_zoom',e.crop_zoom,.25,4,.05)}${range('Horizontal position','crop_x',e.crop_x,0,1,.01)}${range('Vertical position','crop_y',e.crop_y,0,1,.01)}</div>${select('Rotate clockwise','rotation',e.rotation,[[0,'Original'],[90,'90°'],[180,'180°'],[270,'270°']])}${check('Mirror left / right','flip_horizontal',e.flip_horizontal)}${check('Flip top / bottom','flip_vertical',e.flip_vertical)}<hr><h3>Tone & texture</h3>${range('Brightness','brightness',e.brightness,.2,2,.05)}${range('Contrast','contrast',e.contrast,.2,2,.05)}${range('Threshold / ink bias','threshold',e.threshold,1,255)}${check('Floyd–Steinberg dithering','dither',e.dither)}<p class="muted">Turn dithering off for crisp logos. A higher threshold adds ink; 128 is neutral.</p><hr><h3>Ribbon colours</h3>${select('Assign ink','assignment',e.assignment,[['auto','Automatic black + red'],['black','Black only'],['red','Red only'],['swap','Swap black ↔ red']])}${range('Black ink remaining (%)','black_ink',e.black_ink,0,100)}${range('Red ink remaining (%)','red_ink',e.red_ink,0,100)}<button id="reset-image" class="wide">Reset image adjustments</button>`;
      panel.insertAdjacentHTML('beforeend', `<hr><h3>Clean up image</h3><label>Tool<select id="image-tool"><option value="crop" ${imageTool==='crop'?'selected':''}>Move / crop</option><option value="erase" ${imageTool==='erase'?'selected':''}>Erase</option></select></label><label>Brush diameter (% of image)<input id="eraser-size" type="range" min="1" max="20" step="1" value="${brushSize}"><output id="eraser-size-value">${brushSize}%</output></label><button id="undo-erasing" ${e.eraser_strokes?.length?'':'disabled'}>Undo last erase</button><button id="reset-erasing" ${e.eraser_strokes?.length?'':'disabled'}>Reset erasing</button><p class="muted">Erase on the original image; the receipt context shows the printed result. Erasing follows the image through crop, zoom and rotation. Up to 100 strokes per image.</p>`);
      $('image-tool').onchange = () => { imageTool = $('image-tool').value; paintPreview(); };
      $('eraser-size').oninput = () => { brushSize = Number($('eraser-size').value); $('eraser-size-value').textContent = `${brushSize}%`; };
      $('undo-erasing').onclick = () => { b.edits.eraser_strokes.pop(); renderInspector(); paintPreview(); changed(); };
      $('reset-erasing').onclick = () => { b.edits.eraser_strokes = []; renderInspector(); paintPreview(); changed(); };
      panel.insertAdjacentHTML('afterbegin', `<h3>Keep people only</h3><button id="remove-background" class="wide" ${backgroundJobs.has(b.asset)||originalImages.has(b.asset)?'disabled':''}>${backgroundJobs.has(b.asset)?'Removing background…':'Remove background'}</button>${originalImages.has(b.asset)?'<button id="restore-background" class="wide">Restore original background</button>':''}<p class="muted">Apple Vision keeps people, not other objects. Processed locally on the Mac; removed areas print white. Check the preview for missed people or edges.</p><hr>`);
      $('remove-background').onclick = () => removePeopleBackground(b);
      if ($('restore-background')) $('restore-background').onclick = () => {
        assets.set(b.asset, originalImages.get(b.asset));
        originalImages.delete(b.asset);
        renderImageSwitcher(); renderInspector(); changed();
      };
      panel.querySelectorAll('[data-edit]').forEach(input => input.oninput = () => {
        const key = input.dataset.edit;
        b.edits[key] = input.type === 'checkbox' ? input.checked : ['fit','assignment'].includes(key) ? input.value : Number(input.value);
        const output = panel.querySelector(`[data-output="${key}"]`);
        if (output) output.textContent = input.value;
        updateCropControls(); changed();
      });
      $('reset-image').onclick = () => { b.edits = {...defaultEdits(b.type==='header'), eraser_strokes:b.edits.eraser_strokes || []}; renderInspector(); changed(); };
      updateCropControls();
      return;
    }
    let content = `<p class="eyebrow">SECTION ${String(documentState.blocks.indexOf(b)+1).padStart(2,'0')}</p><h2>${names[b.type]}</h2>`;
    if (b.type === 'header') {
      content += field('Heading','title',b.title)
        + select('Title font', 'title_font', b.title_font || 'custom',
          [['custom','Custom bitmap font'], ['native','Built-in printer font']]).replace('data-edit=', 'data-field=')
        + field('Subheading','subtitle',b.subtitle,{max:160,area:true}) + imageLayout(b);
    }
    if (b.type === 'photo') content += field('Caption (optional)','caption',b.caption) + '<p class="muted">Select a photo, then press Delete or Backspace to remove it (not while typing).</p>' + imageLayout(b);
    if (b.type === 'text') {
      content += field('Your text','text',b.text,{area:true,max:600})
        + select('Text wrapping', 'wrap_mode', b.wrap_mode || 'character',
          [['word','Whole words — move to next line'], ['hyphenate','Split words with a dash'],
            ['character','Character wrap (existing)']]).replace('data-edit=', 'data-field=')
        + '<p class="muted">Manual line breaks are kept. Dash wrapping marks words continued onto the next line, not dictionary syllables. Whole-word mode splits a word only if it is wider than a full line.</p>';
    }
    if (b.type === 'signature') content += field('Signature label','label',b.label,{max:80}) + '<p class="muted">A blank signing area and rule are printed above this label.</p>';
    if (b.type === 'spacer') content += field('Space (layout pixels)','height',b.height,{type:'number',min:8,max:200});
    if (b.type === 'footer') {
      content += '<p class="muted">Line items, totals and receipt details.</p>' + field('Currency symbol','currency',b.currency,{max:4});
      content += b.items.map((item,i) => `<div class="item-row"><label>Item ${i+1}<input data-item="${i}" data-key="label" value="${escapeHTML(item.label)}" maxlength="64"></label><div class="row"><label>Qty<input data-item="${i}" data-key="quantity" type="number" min="${item.quantity_mode==='photos'?0:1}" max="999" value="${itemQuantity(item, photoCount())}" ${item.quantity_mode==='photos'?'disabled':''}></label><label>Unit price<input data-item="${i}" data-key="price" type="number" min="0" max="999999.99" step="0.01" value="${escapeHTML(item.price)}"></label></div><label class="check"><input type="checkbox" data-photo-quantity="${i}" ${item.quantity_mode==='photos'?'checked':''}>Use photo count as quantity</label><button class="remove" data-remove-item="${i}">Remove item</button></div>`).join('');
      content += `<p class="muted">Automatic quantity counts body photos, not logos or print copies. With no photos, that item is omitted from the printed footer. Save a profile to reuse this setting.</p><button id="add-item" class="wide" ${b.items.length>=12?'disabled':''}>＋ Add item</button><div class="total"><span>TOTAL</span><strong id="total">${escapeHTML(b.currency)}${receiptTotal(b.items, photoCount()).toFixed(2)}</strong></div><hr>` + field('Date / time (optional)','date',b.date,{max:40}) + `<label class="check"><input id="automatic-date" type="checkbox" ${automaticDates.has(b.id)?'checked':''}>Use current date & time</label><p class="muted">Local time: DD/MM/YYYY HH:mm. Captured on each preview refresh; all copies use the previewed timestamp.</p>` + field('Reference (optional)','reference',b.reference,{max:64}) + field('Footer message (optional)','text',b.text,{area:true,max:400});
    }
    if (b.type !== 'spacer') {
      const label = b.type === 'header' ? 'Native text size (subtitle & built-in title)' : 'Text size';
      content += select(label, 'font_size', b.font_size || 'normal',
        [['small','Small (Font B)'], ['normal','Normal'], ['large','Large (double width & height)']]).replace('data-edit=', 'data-field=');
      content += '<p class="muted">Small uses narrower Font B; Normal and Large use Font A. Large text wraps sooner; preview lettering is approximate. ' + (b.type === 'header' ? 'Custom titles keep their original appearance.' : '') + '</p>';
    }
    content += '<hr><button id="delete-section" class="remove">Remove this section</button>';
    panel.innerHTML = content;
    panel.querySelectorAll('[data-field]').forEach(input => input.oninput = () => {
      b[input.dataset.field] = input.type === 'number' ? Number(input.value) : input.value;
      if (b.type === 'footer') updateTotal(b);
      renderList(); changed();
    });
    if ($('automatic-date')) {
      panel.querySelector('[data-field="date"]').disabled = automaticDates.has(b.id);
      $('automatic-date').onchange = () => {
        if ($('automatic-date').checked) { automaticDates.add(b.id); b.date = formatReceiptDate(); }
        else automaticDates.delete(b.id);
        renderInspector(); changed();
      };
    }
    panel.querySelectorAll('[data-item]').forEach(input => input.oninput = () => {
      b.items[Number(input.dataset.item)][input.dataset.key] = input.dataset.key==='quantity'?Number(input.value):input.value;
      updateTotal(b); changed();
    });
    panel.querySelectorAll('[data-photo-quantity]').forEach(input => input.onchange = () => {
      b.items[Number(input.dataset.photoQuantity)].quantity_mode = input.checked ? 'photos' : 'manual';
      renderInspector(); changed();
    });
    panel.querySelectorAll('[data-remove-item]').forEach(button => button.onclick = () => { b.items.splice(Number(button.dataset.removeItem),1); renderInspector(); changed(); });
    if ($('add-item')) $('add-item').onclick = () => { b.items.push({label:'New item',quantity:1,price:'0.00'}); renderInspector(); changed(); };
    if ($('replace-asset')) $('replace-asset').onclick = () => { uploadTarget = b.id; $('asset-upload').click(); };
    if ($('edit-image')) $('edit-image').onclick = () => setMode('image');
    if ($('remove-logo')) $('remove-logo').onclick = () => { assets.delete(b.asset); originalImages.delete(b.asset); b.asset = null; renderInspector(); renderList(); changed(); };
    $('delete-section').onclick = removeSelectedSection;
  }
  function removeSelectedSection() {
    const block = selectedBlock();
    if (!block) return;
    documentState.blocks = documentState.blocks.filter(b => b.id !== block.id);
    if (block.asset) { assets.delete(block.asset); originalImages.delete(block.asset); }
    automaticDates.delete(block.id);
    selected = documentState.blocks[0]?.id;
    cropDrag = null; eraseDrag = null; eraseSource = null;
    if (mode === 'image') mode = 'layout';
    renderList(); renderMode(); renderInspector(); changed();
  }
  async function removePeopleBackground(block) {
    const id = block.asset, file = assets.get(id);
    if (!file || backgroundJobs.has(id) || originalImages.has(id)) return;
    backgroundJobs.add(id);
    renderInspector(); updatePrint();
    tell('Removing background locally with Apple Vision…');
    const form = new FormData();
    form.append('image', file, 'photo');
    try {
      const response = await fetch('/api/remove-background', {method:'POST', body:form});
      if (!response.ok) await responseJSON(response);
      const result = await response.blob();
      // A replaced image or deleted section must never receive a late result.
      if (block.asset !== id || assets.get(id) !== file || !documentState.blocks.includes(block)) return;
      originalImages.set(id, file);
      assets.set(id, result);
      renderImageSwitcher(); changed();
      tell('Background removed. Check the people and edges in the preview; restore the original if needed.');
    } catch (error) {
      tell(`Background removal failed: ${error.message}. Original image unchanged.`);
    } finally {
      backgroundJobs.delete(id);
      renderInspector(); updatePrint();
    }
  }
  function updateTotal(b) {
    if ($('total')) $('total').textContent = `${b.currency}${receiptTotal(b.items, photoCount()).toFixed(2)}`;
    document.querySelectorAll('[data-item][data-key="quantity"]').forEach(input => {
      const item = b.items[Number(input.dataset.item)];
      if (item.quantity_mode === 'photos') input.value = itemQuantity(item, photoCount());
    });
  }
  function updateCropControls() {
    const contain = selectedBlock()?.edits.fit === 'contain';
    document.querySelectorAll('#crop-controls input').forEach(input => input.disabled = contain);
  }
  function changed() {
    window.dispatchEvent(new Event('receipter-receipt-changed'));
    dirty = true;
    revision++;
    if (selectedBlock()?.type === 'footer') updateTotal(selectedBlock());
    snapshot = null;
    previewError = '';
    controller?.abort();
    clearTimeout(timer);
    $('paper').classList.add('stale');
    $('image-canvas').style.opacity = '.5';
    $('context-paper').style.opacity = '.5';
    $('download').removeAttribute('href');
    $('download').setAttribute('aria-disabled','true');
    $('preview-state').classList.remove('error');
    $('preview-state').textContent = 'Updating your receipt…';
    updatePrint();
    timer = setTimeout(refreshPreview, 120);
  }
  async function responseJSON(response) {
    let result;
    try {
      result = JSON.parse(await response.text());
    } catch {
      throw new Error(`Server returned a non-JSON response (HTTP ${response.status}). Check the server terminal for errors, then restart Receipter and refresh this page.`);
    }
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result));
    return result;
  }
  async function refreshPreview() {
    clearTimeout(timer);
    const version = ++revision;
    snapshot = null;
    controller?.abort();
    controller = new AbortController();
    updatePrint();
    const timestamp = formatReceiptDate();
    for (const block of documentState.blocks) {
      if (block.type === 'footer' && automaticDates.has(block.id)) block.date = timestamp;
    }
    const dateInput = document.querySelector('[data-field="date"]');
    if (dateInput && automaticDates.has(selected)) dateInput.value = selectedBlock().date;
    const form = new FormData();
    form.append('document', JSON.stringify(documentState));
    for (const [id, file] of assets) form.append('assets', file, id);
    try {
      const result = await responseJSON(await fetch('/api/receipt-preview', {method:'POST',body:form,signal:controller.signal}));
      if (version !== revision) return;
      if (result.build_id !== build) throw new Error('Server updated. Refresh this page before printing.');
      const image = new Image();
      image.src = `data:image/png;base64,${result.png}`;
      await image.decode();
      if (version !== revision) return;
      snapshot = {...result, image, revision:version};
      previewError = '';
      $('receipt-image').src = image.src;
      $('paper').classList.remove('stale');
      $('image-canvas').style.opacity = '1';
      $('context-paper').style.opacity = '1';
      $('preview-state').classList.remove('error');
      $('preview-state').textContent = 'Up to date · your complete receipt, in printer dots';
      $('dot-count').textContent = `${result.width} × ${result.height} DOTS`;
      $('download').href = image.src;
      $('download').setAttribute('aria-disabled','false');
      paintPreview();
    } catch(error) {
      if (version !== revision || error.name === 'AbortError') return;
      previewError = error.message;
      $('preview-state').textContent = previewError;
      $('preview-state').classList.add('error');
    } finally { if (version === revision) updatePrint(); }
  }
  function loadEditorSource() {
    const file = assets.get(selectedBlock()?.asset);
    if (!file) return;
    if (eraseSource?.file !== file) {
      const image = new Image(), url = URL.createObjectURL(file);
      const source = eraseSource = {file, image, ready:false};
      image.src = url;
      image.decode().then(() => {
        source.ready = true;
        if (eraseSource === source && mode === 'image' && imageTool === 'erase') paintEraseCanvas();
      }).catch(() => { source.failed = true; if (imageTool === 'erase') tell('Cannot open this image for erasing. Try a PNG or JPEG.'); })
        .finally(() => URL.revokeObjectURL(url));
    }
  }
  function paintEraseCanvas() {
    const block = selectedBlock();
    loadEditorSource();
    const canvas = $('image-canvas');
    canvas.style.cursor = 'crosshair';
    canvas.style.opacity = '1';
    $('image-help').textContent = 'Erase on the original image. White marks remove ink; the receipt context shows your crop and print result.';
    if (!eraseSource?.ready) {
      canvas.width = 1; canvas.height = 1;
      $('image-help').textContent = eraseSource?.failed ? 'Cannot open this image for erasing. Try a PNG or JPEG.' : 'Loading original image…';
      return;
    }
    const image = eraseSource.image;
    const scale = Math.min(1, 2048 / Math.max(image.naturalWidth, image.naturalHeight));
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext('2d');
    context.fillStyle = 'white'; context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    context.strokeStyle = context.fillStyle = 'white';
    context.lineCap = context.lineJoin = 'round';
    for (const stroke of block.edits.eraser_strokes || []) {
      const radius = stroke.radius * Math.max(canvas.width, canvas.height);
      context.lineWidth = radius * 2;
      context.beginPath();
      stroke.points.forEach(([x,y], i) => context[i?'lineTo':'moveTo'](x*canvas.width, y*canvas.height));
      context.stroke();
      const [x,y] = stroke.points[0];
      context.beginPath(); context.arc(x*canvas.width, y*canvas.height, radius, 0, Math.PI*2); context.fill();
    }
  }
  function paintPreview() {
    if (mode === 'image') {
      $('image-name').textContent = `${imageTool === 'erase' ? 'ERASER / ' : ''}${imageLabel(selectedBlock()).toUpperCase()}`;
      loadEditorSource();
    }
    if (mode === 'image' && imageTool === 'erase') paintEraseCanvas();
    else {
      $('image-canvas').style.cursor = 'move';
      $('image-help').textContent = 'Drag to position the crop. Zoom below 1 leaves white space inside the frame.';
    }
    // Display dots with 1:2 pixel aspect for mode 1. Zoom only changes CSS sizes.
    // Neither this function nor the zoom handler requests or quantizes an image.
    const proof = snapshot;
    if (!proof) {
      $('context-overlays').replaceChildren();
      if (mode === 'image' && imageTool !== 'erase') {
        // Do not show the previous photo while a newly selected one is rendering.
        $('image-canvas').getContext('2d').clearRect(0, 0, $('image-canvas').width, $('image-canvas').height);
        $('image-help').textContent = 'Updating the selected image…';
      }
      return;
    }
    $('paper').style.width = `${proof.width * zoom}px`;
    $('receipt-image').style.width = `${proof.width * zoom}px`;
    $('receipt-image').style.height = `${proof.height * 2 * zoom}px`;
    $('section-overlays').innerHTML = proof.blocks.map(b => `<button class="section-overlay ${b.id===selected?'selected':''}" data-select="${b.id}" aria-label="Edit ${names[documentState.blocks.find(s=>s.id===b.id)?.type] || 'section'}" style="top:${b.y*2*zoom}px;height:${b.height*2*zoom}px"></button>`).join('');
    if (mode === 'image') {
      const section = proof.blocks.find(b => b.id === selected);
      if (!section) return;
      $('context-image').src = proof.image.src;
      $('context-image').style.height = `${proof.height * 2 * 144 / proof.width}px`;
      $('context-selection').style.top = `${section.y * 2 * 144 / proof.width}px`;
      $('context-selection').style.height = `${section.height * 2 * 144 / proof.width}px`;
      $('context-overlays').replaceChildren();
      for (const part of proof.blocks) {
        const block = documentState.blocks.find(b => b.id === part.id);
        if (!block || !assets.has(block.asset)) continue;
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.imageSelect = block.id;
        button.setAttribute('aria-label', `Edit ${imageLabel(block)}`);
        button.setAttribute('aria-pressed', String(block.id === selected));
        button.style.top = `${part.y * 2 * 144 / proof.width}px`;
        button.style.height = `${part.height * 2 * 144 / proof.width}px`;
        $('context-overlays').append(button);
      }
      if (imageTool === 'erase') return;
      const canvas = $('image-canvas');
      canvas.width = proof.width*2;
      canvas.height = section.height*4;
      const context = canvas.getContext('2d');
      context.imageSmoothingEnabled = false;
      context.drawImage(proof.image, 0, section.y*2, proof.width*2, section.height*2, 0, 0, canvas.width, canvas.height);
    }
  }

  function printReasons() {
    const invalidFeed = !Number.isInteger(finishing.feed_lines) || finishing.feed_lines < (finishing.cut?8:0) || finishing.feed_lines > 20;
    const invalidCopies = !Number.isInteger(finishing.copies) || finishing.copies < 1 || finishing.copies > 10;
    const reasons = ReceiptEditor.printBlockReasons({
      statusKnown: !!status, statusError: status ? '' : statusError, buildMatches: status?.build_id === build,
      connected: true, stopped: false,
      busy, serverBusy: false, hasReceipt: documentState.blocks.length > 0,
      previewReady: !!snapshot && snapshot.revision === revision, previewError,
      validationError: [invalidFeed ? 'Enter a valid trailing feed: '+(finishing.cut?'8':'0')+'–20 lines.' : '',
        invalidCopies ? 'Choose a whole number of copies from 1 to 10.' : ''].filter(Boolean).join('\n'),
    });
    if (eraseDrag) reasons.push('Finish the eraser stroke before printing.');
    if (documentState.blocks.some(b => backgroundJobs.has(b.asset))) reasons.push('Waiting for background removal to finish.');
    if (snapshot && !outputLog.ready(snapshot, finishing)) reasons.push('Waiting for matching printer bytes. Refresh preview if output encoding fails.');
    return reasons;
  }
  function updatePrint() {
    outputLog.update(snapshot, finishing);
    if (!$('print-receipt')) return;
    const reasons = printReasons();
    $('print-receipt').textContent = `Add ${finishing.copies} ${finishing.copies === 1 ? 'copy' : 'copies'} to queue →`;
    $('print-receipt').disabled = reasons.length > 0;
    for (const id of ['copies', 'cut', 'feed-lines']) $(id).disabled = busy;
    $('print-receipt').title = reasons.join('\n');
    $('print-reasons').textContent = reasons.join('\n');
  }
  async function refreshStatus() {
    try {
      status = await responseJSON(await fetch('/api/status'));
      statusError = status.detection_error || '';
      $('connection').title = statusError;
      $('connection').textContent = status.stopped || stoppedLocally ? 'Printer stopped' : status.printing ? 'Printing…' : status.connected ? 'Printer connected' : 'Printer offline';
      $('connection').classList.toggle('online',status.connected && !status.stopped && !stoppedLocally);
      $('resume').hidden = !(status.stopped || stoppedLocally);
      $('resume').disabled = status.printing || busy;
    } catch(error) { statusError = error.message; $('connection').textContent = 'Printer status unavailable'; $('connection').classList.remove('online'); }
    updatePrint();
  }
  async function printReceipt() {
    if (printReasons().length) return;
    const form = new FormData();
    const label = prompt('Queue receipt label (guest name or number):', 'Receipt');
    if (label === null) return;
    // Stable across a lost response: repeating this save cannot create duplicates.
    form.append('request_id', `${snapshot.token}:${finishing.cut}:${finishing.feed_lines}:${finishing.copies}`);
    form.append('label', label.slice(0, 80));
    form.append('snapshot', snapshot.token);
    form.append('cut', finishing.cut);
    form.append('feed_lines', finishing.feed_lines);
    form.append('copies', finishing.copies);
    busy = true; updatePrint();
    try {
      const result = await responseJSON(await fetch('/api/queue', {method:'POST',headers:{'X-Receipter-Build':build},body:form}));
      tell(`Saved receipt ${result.id} on this Mac. Open Queue to start, confirm or reprint. You can keep editing now.`);
      await window.receipterQueueRefresh?.();
    } catch(error) {
      tell(`Queue save could not be confirmed: ${error.message}. Check Queue before leaving; retrying this same preview/settings will not duplicate it.`);
    } finally {
      busy = false;
      updatePrint(); await refreshStatus();
    }
  }
  $('stop').onclick = async () => {
    stoppedLocally = true;
    $('resume').hidden = false;
    updatePrint();
    tell('STOP requested. Switch the printer OFF to stop data already in its buffer.');
    try { const result = await responseJSON(await fetch('/api/interrupt',{method:'POST'})); tell(result.message); }
    catch(error) { tell(`STOP failed: ${error.message}. Switch the printer OFF now.`); }
    await refreshStatus();
  };
  $('resume').onclick = async () => {
    if (!confirm('Have you power-cycled the printer to clear its buffer?')) return;
    try { const result = await responseJSON(await fetch('/api/resume',{method:'POST'})); stoppedLocally = false; tell(result.message || 'Printing enabled.'); }
    catch(error) { tell(error.message); }
    await refreshStatus();
  };
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { $('stop').click(); return; }
    if (!['Delete', 'Backspace'].includes(event.key) || event.defaultPrevented || event.repeat
        || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (event.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')
        || document.querySelector('dialog[open]') || $('workspace').inert || mode === 'final' || mode === 'queue'
        || cropDrag || eraseDrag || selectedBlock()?.type !== 'photo') return;
    event.preventDefault();
    removeSelectedSection();
    tell('Photo removed from this draft. Saved queue receipts are unchanged.');
  });
  document.querySelectorAll('button[data-mode]').forEach(button => button.onclick = () => setMode(button.dataset.mode));
  $('back-layout').onclick = () => setMode('layout');
  $('close-queue').onclick = () => setMode(lastEditingMode);
  $('zoom').onchange = () => { zoom = Number($('zoom').value); paintPreview(); };
  $('refresh-preview').onclick = changed;
  $('new-receipt').onclick = () => {
    if (busy || backgroundJobs.size) { tell('Wait for saving or image processing to finish.'); return; }
    if (!confirm('Start a new receipt? Current unsaved photos will be cleared. Saved queue receipts are unchanged. Text, logo and layout defaults are kept.')) return;
    for (const block of documentState.blocks.filter(b => b.type === 'photo')) {
      assets.delete(block.asset); originalImages.delete(block.asset);
    }
    documentState.blocks = documentState.blocks.filter(b => b.type !== 'photo');
    selected = documentState.blocks[0]?.id;
    mode = 'layout';
    renderMode(); renderList(); renderInspector(); changed();
    tell('Ready for the next guest. Review any guest-specific text before saving.');
  };
  $('sections').onclick = event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.select) selectBlock(button.dataset.select);
    if (button.dataset.move) {
      const index = documentState.blocks.findIndex(b=>b.id===button.dataset.id);
      documentState.blocks = moveBlock(documentState.blocks,button.dataset.id,index+Number(button.dataset.move));
      renderList(); renderInspector(); changed();
      $('sections').querySelector(`[data-id="${button.dataset.id}"] .section-select`)?.focus();
    }
  };
  $('section-overlays').onclick = event => { const id = event.target.dataset.select; if (id) selectBlock(id); };
  for (const element of [$('image-switcher'), $('context-overlays')]) {
    element.onclick = event => {
      const id = event.target.closest('[data-image-select]')?.dataset.imageSelect;
      if (id && id !== selected) {
        selectBlock(id);
        element.querySelector(`[data-image-select="${id}"]`)?.focus({preventScroll:true});
      }
    };
  }
  let dragging = null;
  $('sections').ondragstart = event => { dragging = event.target.closest('li')?.dataset.id; event.dataTransfer.setData('text/plain',dragging||''); event.dataTransfer.effectAllowed = 'move'; };
  $('sections').ondragover = event => { if (!dragging) return; event.preventDefault(); event.target.closest('li')?.classList.add('drag-over'); };
  $('sections').ondragleave = event => event.target.closest('li')?.classList.remove('drag-over');
  $('sections').ondragend = () => { dragging = null; document.querySelectorAll('.drag-over').forEach(el=>el.classList.remove('drag-over')); };
  $('sections').ondrop = event => {
    event.preventDefault();
    const target = event.target.closest('li')?.dataset.id;
    if (dragging && target) {
      documentState.blocks = moveBlock(documentState.blocks,dragging,documentState.blocks.findIndex(b=>b.id===target));
      renderList(); renderInspector(); changed();
    }
    dragging = null;
  };
  document.querySelectorAll('[data-add]').forEach(button => button.onclick = () => {
    if (documentState.blocks.length >= 16) return;
    const block = newBlock(button.dataset.add);
    documentState.blocks.push(block); selected = block.id;
    renderList(); renderInspector(); changed();
  });
  $('add-photos').onclick = () => $('photo-upload').click();
  function validUpload(file) {
    if (file.size > 20*1024*1024) { tell(`${file.name} is larger than 20 MB.`); return false; }
    return true;
  }
  function addPhotoFiles(files, beforeId = null) {
    const available = Math.min(3-documentState.blocks.filter(b=>b.type==='photo').length,16-documentState.blocks.length);
    if (files.length > available) tell(`Up to three photos per receipt. Only the first ${available} files were added.`);
    let index = beforeId ? documentState.blocks.findIndex(b=>b.id===beforeId) : -1;
    if (index < 0) index = documentState.blocks.findIndex(b=>b.type==='footer');
    if (index < 0) index = documentState.blocks.length;
    for (const file of files.slice(0,available)) {
      if (!validUpload(file)) continue;
      const block = newBlock('photo'); block.asset = uid(); assets.set(block.asset,file);
      documentState.blocks.splice(index++,0,block); selected = block.id;
    }
    renderList(); renderInspector(); changed();
  }
  $('photo-upload').onchange = () => {
    addPhotoFiles([...$('photo-upload').files]);
    $('photo-upload').value = '';
  };
  window.addEventListener('receipter-inbox-add', event => {
    addPhotoFiles(event.detail.files, event.detail.beforeId);
    setMode('layout');
  });
  // Accept camera tray photos or desktop files without interfering with section reordering.
  const photoDragType = 'application/x-receipter-photo';
  function photoDropTarget(event) {
    return event.target.closest('#receipt-stage, #sections-panel');
  }
  document.addEventListener('dragover', event => {
    const types = [...event.dataTransfer.types];
    if (!types.includes(photoDragType) && !types.includes('Files')) return;
    event.preventDefault(); // Never navigate away from the draft to a dropped file.
    if (photoDropTarget(event)) {
      event.dataTransfer.dropEffect = 'copy';
      photoDropTarget(event).classList.add('photo-drop-active');
    } else event.dataTransfer.dropEffect = 'none';
  });
  function clearPhotoDrop() {
    document.querySelectorAll('.photo-drop-active').forEach(el => el.classList.remove('photo-drop-active'));
  }
  document.addEventListener('dragleave', event => {
    if (photoDropTarget(event) && !photoDropTarget(event).contains(event.relatedTarget)) clearPhotoDrop();
  });
  document.addEventListener('dragend', clearPhotoDrop);
  document.addEventListener('drop', event => {
    clearPhotoDrop();
    const types = [...event.dataTransfer.types];
    if (!types.includes(photoDragType) && !types.includes('Files')) return;
    event.preventDefault();
    if (!photoDropTarget(event)) return;
    const beforeId = event.target.closest('[data-select]')?.dataset.select || event.target.closest('li[data-id]')?.dataset.id || null;
    if (types.includes(photoDragType)) {
      const id = event.dataTransfer.getData(photoDragType);
      window.dispatchEvent(new CustomEvent('receipter-inbox-drop', {detail:{id, beforeId}}));
    } else {
      const files = [...event.dataTransfer.files].filter(file => file.type.startsWith('image/') || /\.(png|jpe?g|jpe|jfif|jif|jfi|heic|heif|webp|gif|bmp|svg)$/i.test(file.name));
      if (!files.length) { tell('Drop image files to add photos.'); return; }
      addPhotoFiles(files, beforeId); setMode('layout');
    }
  });
  window.receipterPhotoCapacity = () => Math.min(3-documentState.blocks.filter(b=>b.type==='photo').length, 16-documentState.blocks.length);
  $('asset-upload').onchange = () => {
    const file = $('asset-upload').files[0];
    const block = documentState.blocks.find(b=>b.id===uploadTarget);
    if (file && block && validUpload(file)) {
      if (block.asset) { assets.delete(block.asset); originalImages.delete(block.asset); }
      block.asset = uid(); assets.set(block.asset,file);
      block.edits.eraser_strokes = [];
      renderList(); renderInspector(); changed();
    }
    $('asset-upload').value = '';
  };
  let cropDrag = null;
  function erasePoint(event) {
    const rect = $('image-canvas').getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)),
      Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))].map(v => Math.round(v*10000)/10000);
  }
  $('image-canvas').onpointerdown = event => {
    if (event.button !== 0) return;
    const block = selectedBlock();
    if (imageTool === 'erase') {
      if (!block?.edits || !eraseSource?.ready || eraseSource.file !== assets.get(block.asset)) return;
      const strokes = block.edits.eraser_strokes ||= [];
      if (strokes.length >= 100) { tell('Eraser limit: 100 strokes. Undo or reset erasing to continue.'); return; }
      const stroke = {radius:brushSize/200, points:[erasePoint(event)]};
      strokes.push(stroke);
      eraseDrag = {block, stroke};
      $('image-canvas').setPointerCapture(event.pointerId);
      changed(); paintEraseCanvas();
      return;
    }
    if (!snapshot || !block?.edits || block.edits.fit !== 'cover') return;
    cropDrag = {x:event.clientX,y:event.clientY,cx:block.edits.crop_x,cy:block.edits.crop_y,id:block.id};
    $('image-canvas').setPointerCapture(event.pointerId);
  };
  $('image-canvas').onpointermove = event => {
    if (eraseDrag) {
      if (eraseDrag.block !== selectedBlock() || imageTool !== 'erase') return;
      const points = eraseDrag.stroke.points, point = erasePoint(event), last = points[points.length-1];
      if (Math.hypot(point[0]-last[0], point[1]-last[1]) < .001) return;
      if (points.length >= 256) {
        if (!eraseDrag.warned) tell('Finish this stroke and start another to keep erasing.');
        eraseDrag.warned = true; return;
      }
      points.push(point);
      changed(); paintEraseCanvas();
      return;
    }
    if (!cropDrag || selected !== cropDrag.id) return;
    const rect = $('image-canvas').getBoundingClientRect();
    const edits = selectedBlock().edits;
    let directionX = -1, directionY = -1;
    if (edits.crop_zoom < 1 && eraseSource?.ready && eraseSource.file === assets.get(selectedBlock().asset)) {
      let w = eraseSource.image.naturalWidth, h = eraseSource.image.naturalHeight;
      if (edits.rotation % 180) [w,h] = [h,w];
      const height = selectedBlock().height;
      const scale = Math.max(368/w, height/h) * edits.crop_zoom;
      directionX = w*scale < 368 ? 1 : -1;
      directionY = h*scale < height ? 1 : -1;
    }
    edits.crop_x = Math.round(Math.max(0,Math.min(1,cropDrag.cx+directionX*(event.clientX-cropDrag.x)/rect.width))*100)/100;
    edits.crop_y = Math.round(Math.max(0,Math.min(1,cropDrag.cy+directionY*(event.clientY-cropDrag.y)/rect.height))*100)/100;
    for (const key of ['crop_x','crop_y']) {
      document.querySelector(`[data-edit="${key}"]`).value = edits[key];
      document.querySelector(`[data-output="${key}"]`).textContent = edits[key];
    }
    changed();
  };
  $('image-canvas').onpointerup = $('image-canvas').onpointercancel = $('image-canvas').onlostpointercapture = () => {
    cropDrag = null;
    if (eraseDrag) { eraseDrag = null; renderInspector(); changed(); paintPreview(); }
  };
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  function checkProfileIdle() {
    if (busy || backgroundJobs.size) throw new Error('Wait for queue saving or image processing to finish before saving or loading a profile.');
  }
  window.receipterProfileSnapshot = () => {
    checkProfileIdle();
    const blocks = documentState.blocks.filter(block => block.type !== 'photo');
    if (!blocks.length) throw new Error('Add a header, text or another default section before saving a profile.');
    const logos = new Map();
    for (const block of blocks) {
      if (block.type === 'header' && block.asset) {
        const file = assets.get(block.asset);
        if (!file) throw new Error('The logo could not be found. Upload it again before saving.');
        logos.set(block.asset, file);
      }
    }
    return {document:structuredClone({blocks}), assets:logos,
      options:{automatic_dates:blocks.filter(block => automaticDates.has(block.id)).map(block => block.id), finishing:{...finishing}}};
  };
  window.receipterApplyProfile = (document, options, logos) => {
    checkProfileIdle();
    documentState = structuredClone(document);
    assets.clear(); originalImages.clear(); automaticDates.clear();
    for (const [id, file] of logos) assets.set(id, file);
    for (const id of options.automatic_dates) automaticDates.add(id);
    finishing = {...options.finishing};
    selected = documentState.blocks[0]?.id;
    mode = 'layout'; eraseSource = null; eraseDrag = null; cropDrag = null; uploadTarget = null;
    renderList(); renderMode(); renderInspector(); changed();
  };
  renderList(); renderMode(); renderInspector(); refreshStatus();
  window.receipterInitializeProfile().catch(error => {
    tell(`Could not load default profile: ${error.message}. Saved profiles have not been changed.`);
  }).finally(() => {
    $('workspace').inert = false;
    $('open-profiles').disabled = false;
    dirty = false;
    refreshPreview();
  });
  setInterval(refreshStatus, 3000);
})();
