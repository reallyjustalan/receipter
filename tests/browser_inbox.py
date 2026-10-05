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
                    errors, prints = [], []
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
                    expect(page.locator('#inbox-status')).to_contain_text('Paused')
                    expect(page.locator('#inbox-enabled')).to_be_checked()
                    expect(page.locator('#inbox-add')).to_be_disabled()
                    expect(page.locator('#inbox-latest')).to_be_disabled()
                    page.locator('#inbox-folder').fill(f'  "{folder}"  ')
                    page.get_by_role('button', name='Save settings').click()
                    expect(page.locator('#inbox-status')).to_contain_text('Watching')
                    expect(page.locator('#inbox-photos label')).to_have_count(0)
                    Image.new('RGB', (80, 60), 'blue').save(folder / 'new.JfIf', 'JPEG')
                    expect(page.locator('#inbox-photos label')).to_have_count(1, timeout=15000)
                    expect(page.locator('#inbox-photos')).to_contain_text('new.JfIf')
                    page.locator('#inbox-enabled').uncheck()
                    page.locator('#inbox-import').click()
                    expect(page.locator('#inbox-enabled')).to_be_checked()
                    expect(page.locator('#inbox-photos label')).to_have_count(2, timeout=15000)
                    page.reload()
                    page.locator('#open-inbox').click()
                    expect(page.locator('#inbox-photos label')).to_have_count(2)
                    page.locator('#inbox-photos input').first.check()
                    page.locator('#inbox-add').click()
                    expect(page.locator('#photo-inbox')).not_to_be_visible()
                    expect(page.locator('#photo-count')).to_have_text('1 / 3')
                    expect(page.locator('#preview-state')).to_contain_text('Up to date')
                    page.locator('#open-inbox').click()
                    page.locator('#inbox-latest').click()
                    expect(page.locator('#photo-inbox')).not_to_be_visible()
                    expect(page.locator('#photo-count')).to_have_text('2 / 3')
                    page.locator('#open-inbox').click()
                    page.locator('#inbox-photos input').first.check()
                    page.locator('#inbox-photos input').last.check()
                    expect(page.locator('#inbox-add')).to_be_disabled()
                    page.locator('#inbox-latest').click()
                    expect(page.locator('#photo-count')).to_have_text('3 / 3')
                    page.locator('#open-inbox').click()
                    expect(page.locator('#inbox-latest')).to_be_disabled()
                    expect(page.locator('#inbox-add')).to_be_disabled()
                    assert not errors, errors
                    assert not prints, prints
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=15)
    print('Folder ingestion, explicit existing import, persistence and add-to-receipt passed; nothing printed.')


if __name__ == '__main__':
    main()
