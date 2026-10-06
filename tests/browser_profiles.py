"""Profile save/load and real server restart regression; never prints."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as temp, socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, RECEIPTER_DATA_DIR=str(Path(temp) / 'data'))
        with open(Path(temp) / 'server.log', 'w') as log:
            def start():
                server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'receipter.app:app', '--port', str(port)],
                                          cwd=ROOT, env=env, stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        with urlopen(base + '/api/profiles'):
                            return server
                    except OSError:
                        time.sleep(.1)
                server.terminate()
                raise RuntimeError('Server did not start')
            server = start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    page = browser.new_page()
                    errors, prints = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.route('**/api/status', lambda route: route.fulfill(json={'connected':False, 'stopped':False, 'printing':False}))
                    def reject_print(route):
                        prints.append(route.request.url)
                        route.fulfill(status=503, json={'detail':'Printing disabled'})
                    page.route('**/api/print*', reject_print)
                    page.goto(base)
                    page.locator('[data-field="title"]').fill('ALAN PHOTO BOOTH')
                    page.locator('[data-field="subtitle"]').fill('Welcome to the party')
                    page.get_by_role('button', name='Upload SVG or image').click()
                    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 40"><rect width="80" height="40" fill="red"/></svg>'
                    page.locator('#asset-upload').set_input_files({'name':'brand.svg','mimeType':'image/svg+xml','buffer':svg})
                    page.locator('[data-add="text"]').click()
                    page.locator('[data-field="text"]').fill('DEFAULT GREETING')
                    expect(page.locator('[data-field="wrap_mode"]')).to_have_value('word')
                    page.locator('[data-field="wrap_mode"]').select_option('hyphenate')
                    expect(page.locator('[data-field="font_size"]')).to_have_value('normal')
                    page.locator('[data-field="font_size"]').select_option('small')
                    page.locator('#sections .section-select').filter(has_text='Itemised footer').click()
                    page.locator('[data-field="text"]').fill('COME BACK SOON')
                    page.locator('[data-field="font_size"]').select_option('small')
                    page.locator('[data-photo-quantity="0"]').check()
                    expect(page.locator('[data-item="0"][data-key="quantity"]')).to_be_disabled()
                    expect(page.locator('[data-item="0"][data-key="quantity"]')).to_have_value('0')
                    page.locator('#automatic-date').check()
                    # Camera shots must not become profile defaults.
                    page.locator('#photo-upload').set_input_files({'name':'camera.svg','mimeType':'image/svg+xml','buffer':svg})
                    expect(page.locator('#photo-count')).to_have_text('1 / 3')
                    page.locator('button[data-mode="final"]').click()
                    page.locator('#copies').fill('2')
                    page.locator('#feed-lines').fill('10')
                    page.locator('#open-profiles').click()
                    page.locator('#profile-name').fill('Party booth')
                    page.get_by_role('button', name='Save current defaults').click()
                    expect(page.locator('#profile-status')).to_contain_text('Saved on this server')
                    profile_id = page.locator('#profile-select').input_value()
                    page.locator('#close-profiles').click()
                    # Stop the server and reopen the same persistent storage.
                    server.terminate(); server.wait(timeout=15)
                    server = start()
                    page.reload()
                    expect(page.locator('#open-profiles')).to_have_text('Profile: Party booth')
                    expect(page.locator('#photo-count')).to_have_text('0 / 3')
                    expect(page.locator('[data-field="title"]')).to_have_value('ALAN PHOTO BOOTH')
                    expect(page.locator('[data-field="subtitle"]')).to_have_value('Welcome to the party')
                    expect(page.locator('#preview-state')).to_contain_text('Up to date')
                    page.locator('#sections .section-select').filter(has_text='Text').click()
                    expect(page.locator('[data-field="text"]')).to_have_value('DEFAULT GREETING')
                    expect(page.locator('[data-field="wrap_mode"]')).to_have_value('hyphenate')
                    expect(page.locator('[data-field="font_size"]')).to_have_value('small')
                    page.locator('#sections .section-select').filter(has_text='Itemised footer').click()
                    expect(page.locator('[data-field="text"]')).to_have_value('COME BACK SOON')
                    expect(page.locator('[data-field="font_size"]')).to_have_value('small')
                    expect(page.locator('#automatic-date')).to_be_checked()
                    expect(page.locator('[data-photo-quantity="0"]')).to_be_checked()
                    expect(page.locator('[data-item="0"][data-key="quantity"]')).to_be_disabled()
                    expect(page.locator('[data-item="0"][data-key="quantity"]')).to_have_value('0')
                    expect(page.locator('[data-field="date"]')).not_to_have_value('')
                    page.locator('button[data-mode="final"]').click()
                    expect(page.locator('#copies')).to_have_value('2')
                    expect(page.locator('#feed-lines')).to_have_value('10')
                    # A second named profile need not replace the startup default.
                    page.locator('#open-profiles').click()
                    page.locator('#profile-new').click()
                    page.locator('#profile-name').fill('Other event')
                    page.locator('#profile-default').uncheck()
                    page.get_by_role('button', name='Save current defaults').click()
                    expect(page.locator('#profile-status')).to_contain_text('Saved on this server')
                    expect(page.locator('#profile-select option')).to_have_count(3)
                    page.locator('#profile-select').select_option(profile_id)
                    page.once('dialog', lambda dialog: dialog.dismiss())
                    page.locator('#profile-load').click()
                    expect(page.locator('#receipt-profiles')).to_be_visible()
                    page.once('dialog', lambda dialog: dialog.accept())
                    page.locator('#profile-load').click()
                    expect(page.locator('#receipt-profiles')).not_to_be_visible()
                    expect(page.locator('#open-profiles')).to_have_text('Profile: Party booth')
                    assert not errors, errors
                    assert not prints, prints
                    browser.close()
            finally:
                server.terminate(); server.wait(timeout=15)
    print('Named profiles, logo/text restoration, automatic dates, finishing options, camera exclusion and server restart passed; nothing printed.')


if __name__ == '__main__':
    main()
