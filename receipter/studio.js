'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const {defaultEdits, moveBlock, receiptTotal} = ReceiptEditor;
  const build = document.querySelector('meta[name="receipter-build"]').content;
  const uid = () => crypto.randomUUID();
  const escapeHTML = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const names = {header:'Header & logo', photo:'Photo', footer:'Itemised footer', text:'Text', signature:'Signature', spacer:'Breathing room'};
  const icons = {header:'◈', photo:'▧', footer:'≡', text:'T', signature:'〰', spacer:'↕'};
  function newBlock(type) {
    const block = {id:uid(), type};
    if (type === 'header') Object.assign(block, {title:'THE PHOTO BOOTH', subtitle:'A little moment, on paper.', asset:null, height:100, edits:defaultEdits(true)});
    if (type === 'photo') Object.assign(block, {asset:null, height:240, caption:'', edits:defaultEdits()});
    if (type === 'footer') Object.assign(block, {items:[{label:'Memories', quantity:1, price:'0.00'}], currency:'$', date:'', reference:'', text:'THANK YOU FOR THE MEMORIES'});
    if (type === 'text') block.text = 'Your story, in a few words.';
    if (type === 'signature') block.label = 'Signed with love';
    if (type === 'spacer') block.height = 24;
    return block;
  }
  let documentState = {blocks:[newBlock('header'), newBlock('footer'), newBlock('signature')]};
  let selected = documentState.blocks[0].id;
  const assets = new Map();
  let mode = 'layout', zoom = .85, revision = 0, timer, controller, snapshot = null;
  let previewError = '', busy = false, dirty = false, status = null, statusError = '', stoppedLocally = false;
  let finishing = {cut:true, feed_lines:8};
  let uploadTarget = null;
  const selectedBlock = () => documentState.blocks.find(b => b.id === selected);
  const tell = message => { $('message').textContent = message; };

  function renderList() {
    $('sections').innerHTML = documentState.blocks.map((b, i) => `<li draggable="true" data-id="${b.id}" class="${b.id === selected ? 'selected' : ''}"><button class="section-select" data-select="${b.id}" aria-pressed="${b.id === selected}"><span class="section-icon" aria-hidden="true">${icons[b.type]}</span><span class="section-name">${escapeHTML(b.type === 'header' ? b.title || names[b.type] : names[b.type])}<small>${String(i+1).padStart(2,'0')} / ${b.type.toUpperCase()}</small></span></button><div class="move-buttons"><button data-move="-1" data-id="${b.id}" aria-label="Move ${names[b.type]} up" ${i===0?'disabled':''}>↑</button><button data-move="1" data-id="${b.id}" aria-label="Move ${names[b.type]} down" ${i===documentState.blocks.length-1?'disabled':''}>↓</button></div></li>`).join('');
    const count = documentState.blocks.filter(b => b.type === 'photo').length;
    $('photo-count').textContent = `${count} / 3`;
    $('add-photos').disabled = count >= 3 || documentState.blocks.length >= 16;
    document.querySelectorAll('[data-add]').forEach(b => b.disabled = documentState.blocks.length >= 16);
    document.querySelector('[data-mode="image"]').disabled = !selectedBlock()?.asset;
  }

  function selectBlock(id) {
    selected = id;
    if (mode === 'image' && !selectedBlock()?.asset) mode = 'layout';
    renderList(); renderMode(); renderInspector(); paintPreview();
  }
  function setMode(next) {
    if (next === 'image' && !selectedBlock()?.asset) return;
    mode = next; renderMode(); renderInspector(); paintPreview();
  }
  function renderMode() {
    $('workspace').dataset.mode = mode;
    document.querySelectorAll('[data-mode]').forEach(button => {
      if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', button.dataset.mode === mode);
    });
    $('receipt-stage').hidden = mode === 'image';
    $('image-stage').hidden = mode !== 'image';
    $('stage-title').textContent = {layout:'LIVE RECEIPT', image:'INDIVIDUAL IMAGE / LIVE DOTS', final:'FINAL PRINTER PROOF'}[mode];
    $('zoom').disabled = mode === 'image';
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
      panel.innerHTML = `<p class="eyebrow">READY WHEN YOU ARE</p><h2>The final receipt</h2><p class="muted">The full receipt on the left is the exact dot map sent to the printer. Nothing is re-rendered when you print.</p><div class="proof-note">400 columns · 0.5 canonical scale<br>Black + red ribbon · 76 mm paper<br>View zoom never changes print data.<br>Paper clearance below is added after the artwork.</div><hr><h3>Finish the receipt</h3><label class="check"><input id="cut" type="checkbox" ${finishing.cut?'checked':''}>Partial cut after printing</label><label>Trailing feed (lines)<input id="feed-lines" type="number" min="${finishing.cut?8:0}" max="20" value="${finishing.feed_lines}"></label><p class="muted">With cutting, allow at least 8 lines (~34 mm) for the print head to clear. A partial cut leaves a small bridge.</p><button id="print-receipt" class="primary wide" disabled>Print one receipt →</button><p id="print-reasons" role="status"></p><hr><p class="muted">Preview dots are exact; ribbon shade, pin spacing and paper may vary. USB delivery does not confirm physical output.</p><button id="back-editing" class="wide">← Keep editing</button>`;
      $('cut').onchange = () => { finishing.cut = $('cut').checked; if (finishing.cut) finishing.feed_lines = Math.max(8, finishing.feed_lines); renderInspector(); };
      $('feed-lines').oninput = () => { finishing.feed_lines = Number($('feed-lines').value); updatePrint(); };
      $('print-receipt').onclick = printReceipt;
      $('back-editing').onclick = () => setMode('layout');
      updatePrint();
      return;
    }
    if (!b) { panel.innerHTML = '<h2>Start a little story</h2><p class="muted">Add a section to begin your receipt.</p>'; return; }
    if (mode === 'image') {
      const e = b.edits;
      panel.innerHTML = `<p class="eyebrow">JUST THIS IMAGE</p><h2>Make it your own</h2><p class="muted">Independent settings for this ${b.type==='header'?'logo':'photo'}. Preview updates as you edit.</p>${select('Frame fit','fit',e.fit,[['cover','Crop to fill'],['contain','Fit entire image (white surround)']])}<div id="crop-controls">${range('Crop zoom','crop_zoom',e.crop_zoom,1,4,.05)}${range('Horizontal position','crop_x',e.crop_x,0,1,.01)}${range('Vertical position','crop_y',e.crop_y,0,1,.01)}</div>${select('Rotate clockwise','rotation',e.rotation,[[0,'Original'],[90,'90°'],[180,'180°'],[270,'270°']])}${check('Mirror left / right','flip_horizontal',e.flip_horizontal)}${check('Flip top / bottom','flip_vertical',e.flip_vertical)}<hr><h3>Tone & texture</h3>${range('Brightness','brightness',e.brightness,.2,2,.05)}${range('Contrast','contrast',e.contrast,.2,2,.05)}${range('Threshold / ink bias','threshold',e.threshold,1,255)}${check('Floyd–Steinberg dithering','dither',e.dither)}<p class="muted">Turn dithering off for crisp logos. A higher threshold adds ink; 128 is neutral.</p><hr><h3>Ribbon colours</h3>${select('Assign ink','assignment',e.assignment,[['auto','Automatic black + red'],['black','Black only'],['red','Red only'],['swap','Swap black ↔ red']])}${range('Black ink remaining (%)','black_ink',e.black_ink,0,100)}${range('Red ink remaining (%)','red_ink',e.red_ink,0,100)}<button id="reset-image" class="wide">Reset image adjustments</button>`;
      panel.querySelectorAll('[data-edit]').forEach(input => input.oninput = () => {
        const key = input.dataset.edit;
        b.edits[key] = input.type === 'checkbox' ? input.checked : ['fit','assignment'].includes(key) ? input.value : Number(input.value);
        const output = panel.querySelector(`[data-output="${key}"]`);
        if (output) output.textContent = input.value;
        updateCropControls(); changed();
      });
      $('reset-image').onclick = () => { b.edits = defaultEdits(b.type==='header'); renderInspector(); changed(); };
      updateCropControls();
      return;
    }
    let content = `<p class="eyebrow">SECTION ${String(documentState.blocks.indexOf(b)+1).padStart(2,'0')}</p><h2>${names[b.type]}</h2>`;
    if (b.type === 'header') content += field('Heading','title',b.title) + field('Subheading','subtitle',b.subtitle,{max:160,area:true}) + imageLayout(b);
    if (b.type === 'photo') content += field('Caption (optional)','caption',b.caption) + imageLayout(b);
    if (b.type === 'text') content += field('Your text','text',b.text,{area:true,max:600});
    if (b.type === 'signature') content += field('Signature label','label',b.label,{max:80}) + '<p class="muted">A blank signing area and rule are printed above this label.</p>';
    if (b.type === 'spacer') content += field('Space (layout pixels)','height',b.height,{type:'number',min:8,max:200});
    if (b.type === 'footer') {
      content += '<p class="muted">A little tab for the occasion. Prices can be zero — memories are priceless.</p>' + field('Currency symbol','currency',b.currency,{max:4});
      content += b.items.map((item,i) => `<div class="item-row"><label>Item ${i+1}<input data-item="${i}" data-key="label" value="${escapeHTML(item.label)}" maxlength="64"></label><div class="row"><label>Qty<input data-item="${i}" data-key="quantity" type="number" min="1" max="999" value="${item.quantity}"></label><label>Unit price<input data-item="${i}" data-key="price" type="number" min="0" max="999999.99" step="0.01" value="${escapeHTML(item.price)}"></label></div><button class="remove" data-remove-item="${i}">Remove item</button></div>`).join('');
      content += `<button id="add-item" class="wide" ${b.items.length>=12?'disabled':''}>＋ Add item</button><div class="total"><span>TOTAL</span><strong id="total">${escapeHTML(b.currency)}${receiptTotal(b.items).toFixed(2)}</strong></div><hr>` + field('Date (optional)','date',b.date,{max:40}) + field('Reference (optional)','reference',b.reference,{max:64}) + field('Footer message (optional)','text',b.text,{area:true,max:400});
    }
    content += '<hr><button id="delete-section" class="remove">Remove this section</button>';
    panel.innerHTML = content;
    panel.querySelectorAll('[data-field]').forEach(input => input.oninput = () => {
      b[input.dataset.field] = input.type === 'number' ? Number(input.value) : input.value;
      if (b.type === 'footer') updateTotal(b);
      renderList(); changed();
    });
    panel.querySelectorAll('[data-item]').forEach(input => input.oninput = () => {
      b.items[Number(input.dataset.item)][input.dataset.key] = input.dataset.key==='quantity'?Number(input.value):input.value;
      updateTotal(b); changed();
    });
    panel.querySelectorAll('[data-remove-item]').forEach(button => button.onclick = () => { b.items.splice(Number(button.dataset.removeItem),1); renderInspector(); changed(); });
    if ($('add-item')) $('add-item').onclick = () => { b.items.push({label:'New item',quantity:1,price:'0.00'}); renderInspector(); changed(); };
    if ($('replace-asset')) $('replace-asset').onclick = () => { uploadTarget = b.id; $('asset-upload').click(); };
    if ($('edit-image')) $('edit-image').onclick = () => setMode('image');
    if ($('remove-logo')) $('remove-logo').onclick = () => { assets.delete(b.asset); b.asset = null; renderInspector(); renderList(); changed(); };
    $('delete-section').onclick = () => {
      documentState.blocks = documentState.blocks.filter(block => block.id !== b.id);
      if (b.asset) assets.delete(b.asset);
      selected = documentState.blocks[0]?.id;
      renderList(); renderInspector(); changed();
    };
  }
  function updateTotal(b) { if ($('total')) $('total').textContent = `${b.currency}${receiptTotal(b.items).toFixed(2)}`; }
  function updateCropControls() {
    const contain = selectedBlock()?.edits.fit === 'contain';
    document.querySelectorAll('#crop-controls input').forEach(input => input.disabled = contain);
  }
  function changed() {
    dirty = true;
    revision++;
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
    const result = await response.json();
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
  function paintPreview() {
    // Display dots with 1:2 pixel aspect for mode 1. Zoom only changes CSS sizes.
    // Neither this function nor the zoom handler requests or quantizes an image.
    const proof = snapshot;
    if (!proof) return;
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
      const canvas = $('image-canvas');
      canvas.width = proof.width*2;
      canvas.height = section.height*4;
      const context = canvas.getContext('2d');
      context.imageSmoothingEnabled = false;
      context.drawImage(proof.image, 0, section.y*2, proof.width*2, section.height*2, 0, 0, canvas.width, canvas.height);
      $('image-name').textContent = selectedBlock()?.type==='header' ? 'HEADER / LOGO' : 'PHOTO / '+(documentState.blocks.filter(b=>b.type==='photo').findIndex(b=>b.id===selected)+1);
    }
  }

  function printReasons() {
    const invalidFeed = !Number.isInteger(finishing.feed_lines) || finishing.feed_lines < (finishing.cut?8:0) || finishing.feed_lines > 20;
    return ReceiptEditor.printBlockReasons({
      statusKnown: !!status, statusError, buildMatches: status?.build_id === build,
      connected: status?.connected, stopped: stoppedLocally || status?.stopped,
      busy, serverBusy: status?.printing, hasReceipt: documentState.blocks.length > 0,
      previewReady: !!snapshot && snapshot.revision === revision, previewError,
      validationError: invalidFeed ? 'Enter a valid trailing feed: '+(finishing.cut?'8':'0')+'–20 lines.' : '',
    });
  }
  function updatePrint() {
    if (!$('print-receipt')) return;
    const reasons = printReasons();
    $('print-receipt').disabled = reasons.length > 0;
    $('print-receipt').title = reasons.join('\n');
    $('print-reasons').textContent = reasons.join('\n');
  }
  async function refreshStatus() {
    try {
      status = await responseJSON(await fetch('/api/status'));
      statusError = '';
      $('connection').textContent = status.stopped || stoppedLocally ? 'Printer stopped' : status.printing ? 'Printing…' : status.connected ? 'Printer connected' : 'Create now · printer offline';
      $('connection').classList.toggle('online',status.connected && !status.stopped && !stoppedLocally);
      $('resume').hidden = !(status.stopped || stoppedLocally);
      $('resume').disabled = status.printing || busy;
    } catch(error) { statusError = error.message; $('connection').textContent = 'Printer status unavailable'; $('connection').classList.remove('online'); }
    updatePrint();
  }
  async function printReceipt() {
    if (printReasons().length) return;
    const form = new FormData();
    const printingRevision = revision;
    form.append('snapshot', snapshot.token);
    form.append('cut', finishing.cut);
    form.append('feed_lines', finishing.feed_lines);
    busy = true; updatePrint();
    tell('Sending one receipt. STOP cancels unsent data; power off to stop buffered printing.');
    try {
      const result = await responseJSON(await fetch('/api/print-receipt', {method:'POST',headers:{'X-Receipter-Build':build},body:form}));
      tell(`${result.message}\nJob ${result.job_id} · ${result.bytes} bytes · ${result.cut} cut. Nothing will be resent automatically.`);
    } catch(error) { tell(`Print failed: ${error.message}\nNo automatic retry. Check the printer before another attempt.`); }
    finally {
      busy = false;
      // Tokens are single-use. Never re-enable an uncertain job automatically.
      if (revision === printingRevision) {
        snapshot = null;
        previewError = 'Refresh preview before printing another copy.';
      }
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
    try { const result = await responseJSON(await fetch('/api/resume',{method:'POST'})); stoppedLocally = false; tell(result.message); }
    catch(error) { tell(error.message); }
    await refreshStatus();
  };
  document.addEventListener('keydown', event => { if (event.key === 'Escape') $('stop').click(); });
  document.querySelectorAll('button[data-mode]').forEach(button => button.onclick = () => setMode(button.dataset.mode));
  $('back-layout').onclick = () => setMode('layout');
  $('zoom').onchange = () => { zoom = Number($('zoom').value); paintPreview(); };
  $('refresh-preview').onclick = changed;
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
  $('photo-upload').onchange = () => {
    const files = [...$('photo-upload').files];
    const available = Math.min(3-documentState.blocks.filter(b=>b.type==='photo').length,16-documentState.blocks.length);
    if (files.length > available) tell(`Up to three photos per receipt. Only the first ${available} files were added.`);
    let index = documentState.blocks.findIndex(b=>b.type==='footer');
    if (index < 0) index = documentState.blocks.length;
    for (const file of files.slice(0,available)) {
      if (!validUpload(file)) continue;
      const block = newBlock('photo'); block.asset = uid(); assets.set(block.asset,file);
      documentState.blocks.splice(index++,0,block); selected = block.id;
    }
    $('photo-upload').value = '';
    renderList(); renderInspector(); changed();
  };
  $('asset-upload').onchange = () => {
    const file = $('asset-upload').files[0];
    const block = documentState.blocks.find(b=>b.id===uploadTarget);
    if (file && block && validUpload(file)) {
      if (block.asset) assets.delete(block.asset);
      block.asset = uid(); assets.set(block.asset,file);
      renderList(); renderInspector(); changed();
    }
    $('asset-upload').value = '';
  };
  let cropDrag = null;
  $('image-canvas').onpointerdown = event => {
    const block = selectedBlock();
    if (!block?.edits || block.edits.fit !== 'cover') return;
    cropDrag = {x:event.clientX,y:event.clientY,cx:block.edits.crop_x,cy:block.edits.crop_y,id:block.id};
    $('image-canvas').setPointerCapture(event.pointerId);
  };
  $('image-canvas').onpointermove = event => {
    if (!cropDrag || selected !== cropDrag.id) return;
    const rect = $('image-canvas').getBoundingClientRect();
    const edits = selectedBlock().edits;
    edits.crop_x = Math.round(Math.max(0,Math.min(1,cropDrag.cx-(event.clientX-cropDrag.x)/rect.width))*100)/100;
    edits.crop_y = Math.round(Math.max(0,Math.min(1,cropDrag.cy-(event.clientY-cropDrag.y)/rect.height))*100)/100;
    for (const key of ['crop_x','crop_y']) {
      document.querySelector(`[data-edit="${key}"]`).value = edits[key];
      document.querySelector(`[data-output="${key}"]`).textContent = edits[key];
    }
    changed();
  };
  $('image-canvas').onpointerup = $('image-canvas').onpointercancel = () => { cropDrag = null; };
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  renderList(); renderMode(); renderInspector(); refreshPreview(); refreshStatus();
  setInterval(refreshStatus, 3000);
})();
