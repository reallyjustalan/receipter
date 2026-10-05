"""Real folder-to-browser regression; isolates storage and never prints."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as temp, socket.socket() as sock:
        folder = Path(temp) / 'camera'
        folder.mkdir()
        Image.new('RGB', (40, 60), 'red').save(folder / 'existing.jpg')
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, RECEIPTER_DATA_DIR=str(Path(temp) / 'data'))
        with open(Path(temp) / 'server.log', 'w') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'receipter.app:app', '--port', str(port)],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        with urlopen(base + '/api/inbox') as response:
                            json.load(response)
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Server did not start')
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    page = browser.new_page()
                    errors, prints, working_requests = [], [], []
                    page.on('request', lambda request: working_requests.append(request.url) if request.url.endswith('/working') else None)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def reject_print(route):
                        prints.append(route.request.url)
                        route.fulfill(status=503, json={'detail': 'Printing disabled in test'})
                    page.route('**/api/print*', reject_print)
                    status_mode = ['server-error']
                    def mock_status(route):
                        if status_mode[0] == 'server-error':
                            route.fulfill(status=500, content_type='text/plain', body='Internal Server Error')
                        else:
                            route.fulfill(json={'connected': False, 'stopped': False, 'printing': False,
                                                'detection_error': 'USB backend missing. Run brew install libusb.'})
                    page.route('**/api/status', mock_status)
                    page.goto(base)
                    page.locator('[data-mode="final"]').click()
                    expect(page.locator('#print-reasons')).to_contain_text('non-JSON response (HTTP 500)')
                    status_mode[0] = 'usb-error'
                    expect(page.locator('#print-reasons')).to_contain_text('brew install libusb', timeout=10000)
                    expect(page.locator('#print-receipt')).to_be_disabled()
                    page.locator('#open-inbox').click()
                    expect(page.locator('#inbox-status')).to_contain_text('Choose a camera folder')
                    expect(page.locator('#inbox-enabled')).to_be_checked()
                    expect(page.locator('#inbox-add')).to_be_disabled()
                    expect(page.locator('#inbox-latest')).to_be_disabled()
                    page.locator('#inbox-folder').fill(f'  "{folder}"  ')
                    page.get_by_role('button', name='Save settings').click()
                    expect(page.locator('#inbox-status')).to_contain_text('Watching')
                    expect(page.locator('#inbox-photos label')).to_have_count(1, timeout=15000)
                    expect(page.locator('#inbox-existing')).not_to_be_checked()
                    page.locator('#close-inbox').click()
                    page.locator('[data-mode="layout"]').click()
                    Image.new('RGB', (80, 60), 'blue').save(folder / 'new.JPG', 'JPEG')
                    expect(page.locator('.tray-photo')).to_have_count(2, timeout=15000)
                    expect(page.locator('#tray-photos')).to_contain_text('new.JPG')
                    expect(page.locator('#photo-count')).to_have_text('0 / 3')
                    photo_count = 2
                    if sys.platform == 'darwin':
                        png = Path(temp) / 'heic-source.png'
                        Image.new('RGB', (80, 60), 'green').save(png)
                        result = subprocess.run(['/usr/bin/sips', '-s', 'format', 'heic', str(png), '--out', str(folder / 'phone.HEIC')], capture_output=True, timeout=30)
                        assert result.returncode == 0, result.stderr
                        photo_count = 3
                        expect(page.locator('.tray-photo')).to_have_count(photo_count, timeout=15000)
                        expect(page.locator('#tray-photos')).to_contain_text('phone.HEIC')
                    page.reload()
                    expect(page.locator('.tray-photo')).to_have_count(photo_count)
                    # Failed downloads do not mutate the receipt; a retry can succeed.
                    page.route('**/api/inbox/photos/*/working', lambda route: route.fulfill(status=503))
                    page.locator('.tray-photo button').first.click()
                    expect(page.locator('#tray-status')).to_contain_text('Could not load photo')
                    expect(page.locator('#photo-count')).to_have_text('0 / 3')
                    page.unroute('**/api/inbox/photos/*/working')
                    page.locator('.tray-photo').first.drag_to(page.locator('#section-overlays button').first, source_position={'x': 10, 'y': 10})
                    expect(page.locator('#photo-count')).to_have_text('1 / 3')
                    expect(page.locator('#sections li').first).to_contain_text('PHOTO')
                    expect(page.locator('#preview-state')).to_contain_text('Up to date')
                    page.locator('#open-inbox').click()
                    page.locator('#inbox-enabled').uncheck()
                    page.locator('#inbox-import').click()
                    expect(page.locator('#inbox-enabled')).to_be_checked()
                    page.locator('#inbox-photos input').first.check()
                    page.locator('#inbox-add').click()
                    expect(page.locator('#photo-inbox')).not_to_be_visible()
                    expect(page.locator('#photo-count')).to_have_text('2 / 3')
                    page.locator('#open-inbox').click()
                    page.locator('#inbox-photos input').first.check()
                    page.locator('#inbox-photos input').last.check()
                    expect(page.locator('#inbox-add')).to_be_disabled()
                    page.locator('#inbox-latest').click()
                    expect(page.locator('#photo-count')).to_have_text('3 / 3')
                    assert len(working_requests) == 2, working_requests  # One failed request, one successful cached copy.
                    page.locator('#open-inbox').click()
                    expect(page.locator('#inbox-latest')).to_be_disabled()
                    expect(page.locator('#inbox-add')).to_be_disabled()
                    page.locator('#close-inbox').click()
                    expect(page.locator('.tray-photo button').first).to_be_disabled()
                    page.locator('.tray-photo').first.drag_to(page.locator('#receipt-stage'), source_position={'x': 10, 'y': 10})
                    expect(page.locator('#tray-status')).to_contain_text('room for 0')
                    expect(page.locator('#photo-count')).to_have_text('3 / 3')
                    # Desktop image drop works independently of the camera catalogue.
                    desktop = browser.new_page()
                    desktop.route('**/api/status', mock_status)
                    desktop.route('**/api/print*', reject_print)
                    desktop.goto(base)
                    desktop.evaluate('''async () => {
                      const canvas = document.createElement('canvas'); canvas.width = 80; canvas.height = 60;
                      const blob = await new Promise(resolve => canvas.toBlob(resolve));
                      const transfer = new DataTransfer();
                      transfer.items.add(new File([blob], 'desktop.png', {type: 'image/png'}));
                      document.getElementById('receipt-stage').dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: transfer}));
                    }''')
                    expect(desktop.locator('#photo-count')).to_have_text('1 / 3')
                    expect(desktop.locator('#preview-state')).to_contain_text('Up to date')
                    desktop.close()
                    assert not errors, errors
                    assert not prints, prints
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=15)
    print('Automatic inbox population, background tray updates, drag/drop insertion, desktop file drop, failed-load retry, persistence and capacity guards passed; nothing printed.')


if __name__ == '__main__':
    main()
