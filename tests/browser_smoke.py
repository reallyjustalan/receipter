"""Real-browser workflow regression; runs an isolated server, mocks USB status/printing.

Run: uv run playwright install chromium && uv run python tests/browser_smoke.py
"""
from io import BytesIO
from datetime import datetime, timezone
import re
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 70"><rect x="3" y="3" width="174" height="64" rx="10" fill="none" stroke="black" stroke-width="4"/><circle cx="90" cy="35" r="22" fill="#d20000"/><circle cx="90" cy="35" r="12" fill="white"/></svg>'


def photo():
    image = Image.new('RGB',(720,480),'#eee5ce')
    draw = ImageDraw.Draw(image)
    for y in range(480):
        draw.line((0,y,720,y),fill=(230-int(y*.18),215-int(y*.2),190-int(y*.18)))
    draw.ellipse((445,45,565,165),fill='#d24332')
    draw.polygon([(0,365),(200,150),(360,355),(510,235),(720,410),(720,480),(0,480)],fill='#414b47')
    draw.polygon([(0,440),(285,335),(445,445),(610,365),(720,410),(720,480),(0,480)],fill='#b24b3b')
    output = BytesIO(); image.save(output,'PNG'); return output.getvalue()


def assert_uncovered(page, selector):
    control = page.locator(selector)
    control.scroll_into_view_if_needed()
    assert control.evaluate('''element => {
      const r = element.getBoundingClientRect();
      const top = document.getElementById('top-bar').getBoundingClientRect().bottom;
      const bottom = document.getElementById('bottom-bar').getBoundingClientRect().top;
      const hit = document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
      return r.top >= top && r.bottom <= bottom && (hit === element || element.contains(hit));
    }'''), f'{selector} is covered by a floating bar'


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with open('/tmp/receipter-browser-server.log','w') as log:
        server = subprocess.Popen([sys.executable,'-m','uvicorn','receipter.app:app','--port',str(port)],cwd=ROOT,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    with urlopen(base+'/api/status') as response: status = json.load(response)
                    break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('Test server failed to start')
            status.update(connected=True,stopped=False,printing=False)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1,timezone_id='UTC')
                page.clock.set_fixed_time(datetime(2026,9,8,14,35,tzinfo=timezone.utc))
                batch_plan = {}
                errors, renders, prints = [], [], []
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:renders.append(request) if request.url.endswith('/api/receipt-preview') else None)
                page.route('**/api/status',lambda route:route.fulfill(json=status))
                def mock_print(route):
                    prints.append(route.request.post_data)
                    route.fulfill(json={'message':'Mock USB accepted the receipt.', 'job_id':'test-only',
                                        'bytes':batch_plan['bytes'],'job_sha256':batch_plan['sha256'],'cut':'partial'})
                page.route('**/api/print-receipt',mock_print)
                page.goto(base)
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                expect(page.locator('#zoom')).to_have_value('1')
                assert page.locator('#receipt-image').evaluate('(image) => image.getBoundingClientRect().width') == 400
                expect(page.locator('#output-status')).to_have_text('Prepared — not sent')
                expect(page.locator('#raw-output')).to_contain_text('00000000  1b 3d 01 1b 40')
                assert not prints
                # SVG logo and three independently editable photo blocks.
                # File chooser target is set by the upload button.
                with page.expect_file_chooser() as chooser:
                    page.get_by_role('button',name='Upload SVG or image').click()
                chooser.value.set_files({'name':'logo.svg','mimeType':'image/svg+xml','buffer':SVG})
                expect(page.get_by_role('button',name='Crop & process image')).to_be_visible()
                page.locator('#photo-upload').set_input_files([{'name':f'photo{i}.png','mimeType':'image/png','buffer':photo()} for i in range(3)])
                expect(page.locator('#photo-count')).to_have_text('3 / 3')
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                expect(page.locator('#sections li')).to_have_count(6)
                expect(page.locator('#add-photos')).to_be_disabled()
                selected = page.locator('#sections li.selected').get_attribute('data-id')
                page.get_by_role('button',name='Crop & process image').click()
                expect(page.locator('#workspace')).to_have_attribute('data-mode','image')
                expect(page.locator('#context-image')).to_be_visible()
                # People-only processing is explicit and reversible; errors keep the original.
                original_preview = page.locator('#receipt-image').get_attribute('src')
                page.route('**/api/remove-background', lambda route: route.fulfill(
                    status=400, json={'detail':'No people detected'}))
                page.locator('#remove-background').click()
                expect(page.locator('#message')).to_contain_text('No people detected')
                expect(page.locator('#remove-background')).to_be_enabled()
                assert page.locator('#receipt-image').get_attribute('src') == original_preview
                page.unroute('**/api/remove-background')
                cutout = BytesIO()
                Image.new('RGBA', (720,480), (0,0,0,0)).save(cutout, 'PNG')
                page.route('**/api/remove-background', lambda route: route.fulfill(
                    content_type='image/png', body=cutout.getvalue()))
                page.locator('#remove-background').click()
                expect(page.locator('#restore-background')).to_be_visible()
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert page.locator('#receipt-image').get_attribute('src') != original_preview
                page.locator('#restore-background').click()
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert page.locator('#receipt-image').get_attribute('src') == original_preview
                # Zoom below one changes the print, not only the editor view.
                page.locator('[data-edit="crop_zoom"]').fill('0.5')
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                zoomed_preview = page.locator('#receipt-image').get_attribute('src')
                assert zoomed_preview != original_preview
                # Erase source-image marks, retain them across tone resets, then undo.
                page.locator('#image-tool').select_option('erase')
                page.wait_for_function("document.getElementById('image-canvas').width > 1")
                page.locator('#eraser-size').fill('20')
                canvas = page.locator('#image-canvas')
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                page.mouse.move(box['x']+box['width']*.3, box['y']+box['height']*.6)
                page.mouse.down()
                page.mouse.move(box['x']+box['width']*.7, box['y']+box['height']*.6, steps=10)
                page.mouse.up()
                expect(page.locator('#undo-erasing')).to_be_enabled()
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert page.locator('#receipt-image').get_attribute('src') != zoomed_preview
                last_doc = json.loads(renders[-1].post_data_buffer.split(b'\r\n\r\n', 1)[1].split(b'\r\n--', 1)[0])
                erased = next(b for b in last_doc['blocks'] if b['id'] == selected)
                assert len(erased['edits']['eraser_strokes']) == 1
                page.locator('#reset-image').click()
                expect(page.locator('#undo-erasing')).to_be_enabled()
                page.locator('[data-edit="crop_zoom"]').fill('0.5')
                page.locator('#undo-erasing').click()
                expect(page.locator('#undo-erasing')).to_be_disabled()
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert page.locator('#receipt-image').get_attribute('src') == zoomed_preview
                # A single click also erases; reset restores it.
                canvas.scroll_into_view_if_needed()
                canvas.click(position={'x':box['width']*.5, 'y':box['height']*.5})
                expect(page.locator('#reset-erasing')).to_be_enabled()
                page.locator('#reset-erasing').click()
                expect(page.locator('#reset-erasing')).to_be_disabled()
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert page.locator('#receipt-image').get_attribute('src') == zoomed_preview
                page.locator('#image-tool').select_option('crop')
                page.locator('[data-edit="crop_zoom"]').fill('1.8')
                page.locator('[data-edit="crop_x"]').fill('0.2')
                page.locator('[data-edit="threshold"]').fill('155')
                page.locator('[data-edit="assignment"]').select_option('red')
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert page.locator('#context-image').get_attribute('src') == page.locator('#receipt-image').get_attribute('src')
                page.screenshot(path='/tmp/receipter-image-editor.png',full_page=True)
                page.locator('#back-layout').click()
                # Reordering retains edits on the same block, not its old position.
                page.locator(f'[data-move="-1"][data-id="{selected}"]').click()
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                page.get_by_role('button',name='Crop & process image').click()
                expect(page.locator('[data-edit="crop_zoom"]')).to_have_value('1.8')
                expect(page.locator('[data-edit="assignment"]')).to_have_value('red')
                page.locator('#back-layout').click()
                # A different photo still has defaults.
                page.locator('#sections li').filter(has=page.locator('.section-name',has_text='Photo')).first.locator('.section-select').click()
                page.get_by_role('button',name='Crop & process image').click()
                expect(page.locator('[data-edit="crop_zoom"]')).to_have_value('1')
                expect(page.locator('[data-edit="assignment"]')).to_have_value('auto')
                page.locator('#back-layout').click()
                # Itemised costs and optional footer fields update the complete proof.
                page.locator('#sections .section-select').filter(has_text='Itemised footer').click()
                page.locator('[data-item="0"][data-key="price"]').fill('0.10')
                page.locator('[data-item="0"][data-key="quantity"]').fill('3')
                page.locator('[data-field="reference"]').fill('BOOTH-001')
                expect(page.locator('#total')).to_have_text('$0.30')
                page.locator('#automatic-date').check()
                expect(page.locator('[data-field="date"]')).to_be_disabled()
                expect(page.locator('[data-field="date"]')).to_have_value('08/09/2026 14:35')
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                page.clock.set_fixed_time(datetime(2026,9,9,0,5,tzinfo=timezone.utc))
                page.locator('#refresh-preview').click()
                expect(page.locator('[data-field="date"]')).to_have_value('09/09/2026 00:05')
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                payload = renders[-1].post_data_buffer
                document = json.loads(re.search(rb'name="document"\r\n\r\n(.*?)\r\n--',payload,re.S).group(1))
                assert next(b['date'] for b in document['blocks'] if b['type']=='footer') == '09/09/2026 00:05'
                page.locator('#automatic-date').uncheck()
                expect(page.locator('[data-field="date"]')).to_be_enabled()
                page.locator('[data-field="date"]').fill('08/09/2026 14:35')
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                assert_uncovered(page, '[data-field="currency"]')
                assert_uncovered(page, '#delete-section')
                count = len(renders)
                src = page.locator('#receipt-image').get_attribute('src')
                page.locator('#zoom').select_option('1.5')
                page.wait_for_timeout(250)
                assert len(renders) == count, 'Zoom must not regenerate printer output'
                assert page.locator('#receipt-image').get_attribute('src') == src
                page.locator('#zoom').select_option('0.65')
                page.screenshot(path='/tmp/receipter-layout.png',full_page=True)
                page.get_by_role('button',name='03 Printer preview').click()
                expect(page.locator('#print-receipt')).to_be_enabled()
                assert page.locator('#receipt-image').get_attribute('src') == src
                expect(page.locator('#copies')).to_have_value('1')
                for invalid in ['', '0', '11', '1.5']:
                    page.locator('#copies').fill(invalid)
                    expect(page.locator('#print-receipt')).to_be_disabled()
                    expect(page.locator('#print-reasons')).to_contain_text('whole number of copies')
                with page.expect_response(lambda response: response.url.endswith('/api/receipt-output') and response.status == 200) as encoded:
                    page.locator('#copies').fill('3')
                batch_plan = encoded.value.json()
                expect(page.locator('#print-receipt')).to_have_text('Print 3 copies →')
                expect(page.locator('#print-receipt')).to_be_enabled()
                assert len(renders) == count, 'Copy count must not regenerate the preview'
                assert batch_plan['copies'] == 3
                expect(page.locator('#output-status')).to_have_text('Prepared — not sent')
                page.locator('#output-next').click()
                expect(page.locator('#raw-output')).to_contain_text('00000400')
                page.locator('#output-prev').click()
                downloaded_sha = page.locator('#download-raw').evaluate('''async link => {
                  const bytes = await (await fetch(link.href)).arrayBuffer();
                  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
                }''')
                assert downloaded_sha == batch_plan['sha256']
                page.locator('#back-editing').click()
                page.get_by_role('button',name='03 Printer preview').click()
                expect(page.locator('#copies')).to_have_value('3')
                page.locator('#print-receipt').click()
                expect(page.locator('#message')).to_contain_text('Mock USB accepted')
                expect(page.locator('#message')).to_contain_text(batch_plan['sha256'])
                expect(page.locator('#output-status')).to_have_text('USB accepted')
                expect(page.locator('#print-receipt')).to_be_disabled()
                assert len(prints) == 1 and 'snapshot' in prints[0]
                assert 'name="copies"\r\n\r\n3\r\n' in prints[0]
                page.locator('#refresh-preview').click()
                expect(page.locator('#print-receipt')).to_be_disabled()
                expect(page.locator('#print-receipt')).to_be_enabled()
                # Narrow screens keep the complete paper and all controls reachable.
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_role('button',name='01 Receipt layout').click()
                assert_uncovered(page, '[data-field="currency"]')
                assert_uncovered(page, '#delete-section')
                assert page.locator('#top-bar').evaluate('el => el.getBoundingClientRect().top') == 0
                assert page.locator('#bottom-bar').evaluate('el => el.getBoundingClientRect().bottom') == 844
                expanded_height = page.locator('#bottom-bar').bounding_box()['height']
                page.locator('#output-details summary').click()
                page.wait_for_timeout(100)
                assert page.locator('#bottom-bar').bounding_box()['height'] < expanded_height
                assert_uncovered(page, '#delete-section')
                page.locator('#output-details summary').click()
                page.screenshot(path='/tmp/receipter-mobile.png',full_page=True)
                page.screenshot(path='/tmp/receipter-mobile-viewport.png')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflows'
                page.set_viewport_size({'width':320,'height':568})
                page.wait_for_timeout(100)
                assert_uncovered(page, '[data-field="currency"]')
                assert_uncovered(page, '#delete-section')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Small-screen page overflows'
                assert not errors, errors
                browser.close()
                print('Browser workflow passed: SVG + 3 photos, independent edits, reorder, totals, zoom isolation, snapshot printing, copy counts, automatic local dates, raw-byte log/download and unobstructed floating bars. No USB writes.')
        finally:
            server.terminate(); server.wait(timeout=10)


if __name__ == '__main__':
    main()
