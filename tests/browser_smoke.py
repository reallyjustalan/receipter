"""Real-browser workflow regression; runs an isolated server, mocks USB status/printing.

Run: uv run playwright install chromium && uv run python tests/browser_smoke.py
"""
from io import BytesIO
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
                page = browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
                errors, renders, prints = [], [], []
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:renders.append(request) if request.url.endswith('/api/receipt-preview') else None)
                page.route('**/api/status',lambda route:route.fulfill(json=status))
                def mock_print(route):
                    prints.append(route.request.post_data)
                    route.fulfill(json={'message':'Mock USB accepted the receipt.', 'job_id':'test-only','bytes':123,'cut':'partial'})
                page.route('**/api/print-receipt',mock_print)
                page.goto(base)
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
                expect(page.locator('#zoom')).to_have_value('1')
                assert page.locator('#receipt-image').evaluate('(image) => image.getBoundingClientRect().width') == 400
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
                expect(page.locator('#preview-state')).to_contain_text('Up to date')
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
                page.locator('#print-receipt').click()
                expect(page.locator('#message')).to_contain_text('Mock USB accepted')
                expect(page.locator('#print-receipt')).to_be_disabled()
                assert len(prints) == 1 and 'snapshot' in prints[0]
                page.locator('#refresh-preview').click()
                expect(page.locator('#print-receipt')).to_be_disabled()
                expect(page.locator('#print-receipt')).to_be_enabled()
                # Narrow screens keep the complete paper and all controls reachable.
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_role('button',name='01 Receipt layout').click()
                page.screenshot(path='/tmp/receipter-mobile.png',full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflows'
                assert not errors, errors
                browser.close()
                print('Browser workflow passed: SVG + 3 photos, independent edits, reorder, totals, zoom isolation, snapshot printing and mobile layout. No USB writes.')
        finally:
            server.terminate(); server.wait(timeout=10)


if __name__ == '__main__':
    main()
