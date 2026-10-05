import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from receipter.app import app
from receipter.profiles import Profiles


DOCUMENT = {'blocks':[
    {'type':'header', 'id':'header', 'title':'MY BOOTH', 'asset':'logo'},
    {'type':'footer', 'id':'footer', 'text':'SEE YOU SOON', 'date':'old timestamp'},
    {'type':'signature', 'id':'signature', 'label':'Your autograph'},
]}
OPTIONS = {'automatic_dates':['footer'], 'finishing':{'copies':2, 'cut':True, 'feed_lines':10}}


def logo():
    data = io.BytesIO()
    Image.new('RGB', (40, 20), 'red').save(data, 'PNG')
    return data.getvalue()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Profiles(self.root / 'profiles')
        self.assets = {'logo':dict(name='logo.png', mime='image/png', data=logo())}

    def test_persists_logo_text_options_and_default_across_restart(self):
        saved = self.store.save('Event booth', DOCUMENT, OPTIONS, self.assets)
        restarted = Profiles(self.root / 'profiles')
        self.assertEqual(restarted.listing()['default_id'], saved['id'])
        profile = restarted.get(saved['id'])
        self.assertEqual(profile['document']['blocks'][0]['title'], 'MY BOOTH')
        self.assertEqual(profile['document']['blocks'][1]['date'], '')
        self.assertEqual(profile['options'], OPTIONS)
        import base64
        self.assertEqual(base64.b64decode(profile['assets'][0]['data']), logo())

    def test_overwrite_and_switch_defaults(self):
        first = self.store.save('First', DOCUMENT, OPTIONS, self.assets)
        second = self.store.save('Second', DOCUMENT, OPTIONS, self.assets, make_default=False)
        self.assertEqual(self.store.listing()['default_id'], first['id'])
        self.store.save('Renamed', DOCUMENT, OPTIONS, self.assets, second['id'], True)
        self.assertEqual(self.store.listing()['default_id'], second['id'])
        self.assertEqual(len(self.store.listing()['profiles']), 2)
        self.store.save('Renamed', DOCUMENT, OPTIONS, self.assets, second['id'], False)
        self.assertEqual(self.store.listing()['default_id'], '')
        with self.assertRaises(KeyError):
            self.store.get('missing')

    def test_invalid_save_does_not_replace_existing_profile(self):
        saved = self.store.save('Good', DOCUMENT, OPTIONS, self.assets)
        cases = [('', DOCUMENT, OPTIONS, self.assets),
                 ('Bad', DOCUMENT, OPTIONS, {}),
                 ('Bad', DOCUMENT, OPTIONS, {'logo':dict(name='x', mime='image/png', data=b'broken')}),
                 ('Bad', {'blocks':[{'id':'photo','type':'photo','asset':'camera'}]}, {}, {}),
                 ('Bad', DOCUMENT, {'automatic_dates':['header']}, self.assets),
                 ('Bad', DOCUMENT, {'finishing':{'cut':True,'feed_lines':0}}, self.assets)]
        for args in cases:
            with self.assertRaises(ValueError):
                self.store.save(*args, profile_id=saved['id'])
            self.assertEqual(self.store.get(saved['id'])['name'], 'Good')

    def test_svg_logo_and_external_resource_rejection(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20" fill="red"/></svg>'
        assets = {'logo':dict(name='brand.svg', mime='image/svg+xml', data=svg)}
        saved = self.store.save('SVG', DOCUMENT, {}, assets)
        self.assertEqual(self.store.get(saved['id'])['assets'][0]['mime'], 'image/svg+xml')
        assets['logo']['data'] = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>'
        with self.assertRaises(ValueError):
            self.store.save('Unsafe', DOCUMENT, {}, assets)

    def test_api_persistence_validation_and_missing_profiles(self):
        with patch.dict(os.environ, {'RECEIPTER_DATA_DIR': str(self.root / 'app')}):
            with TestClient(app) as client, patch('receipter.app.send_raw') as send:
                data = {'name':'API booth', 'document':json.dumps(DOCUMENT), 'options':json.dumps(OPTIONS)}
                response = client.post('/api/profiles', data=data, files=[('assets', ('logo', logo(), 'image/png'))])
                self.assertEqual(response.status_code, 200, response.text)
                profile_id = response.json()['id']
                self.assertEqual(client.get('/api/profiles').json()['default_id'], profile_id)
                self.assertEqual(client.get('/api/profiles/nope').status_code, 404)
                self.assertEqual(client.post('/api/profiles', data={**data, 'document':'not-json'}).status_code, 400)
                self.assertEqual(client.post('/api/profiles', data=data).status_code, 400)
                with patch('receipter.profiles.MAX_ASSET', 4):
                    self.assertEqual(client.post('/api/profiles', data=data, files=[('assets', ('logo', logo(), 'image/png'))]).status_code, 413)
                send.assert_not_called()
            with TestClient(app) as client:
                self.assertEqual(client.get(f'/api/profiles/{profile_id}').json()['name'], 'API booth')
