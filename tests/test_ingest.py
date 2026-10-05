import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from receipter.ingest import Inbox
from receipter.app import app


def jpeg(color='red'):
    stream = io.BytesIO()
    Image.new('RGB', (40, 60), color).save(stream, 'JPEG')
    return stream.getvalue()


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'camera'
        self.folder.mkdir()
        self.store = Inbox(self.root / 'data')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def settle(self):
        self.store.scan()
        self.store.scan()

    def test_existing_requires_explicit_import_and_duplicates_are_skipped(self):
        (self.folder / 'old.JPG').write_bytes(jpeg())
        self.store.configure(str(self.folder), True)
        self.settle()
        self.assertEqual(self.store.photos(), [])
        self.store.configure(str(self.folder), True, import_existing=True)
        self.settle()
        self.assertEqual(len(self.store.photos()), 1)
        (self.folder / 'duplicate.jpeg').write_bytes(jpeg())
        self.settle()
        self.assertEqual(len(self.store.photos()), 1)
        photo = self.store.photos()[0]
        self.assertEqual((self.store.root / f"{photo['id']}.jpg").read_bytes(), jpeg())
        self.assertTrue((self.folder / 'old.JPG').exists())

    def test_waits_for_stability_and_recovers_from_partial_jpeg(self):
        self.store.configure(str(self.folder), True)
        path = self.folder / 'new.jpg'
        path.write_bytes(jpeg()[:100])
        self.settle()
        self.assertEqual(self.store.photos(), [])
        self.assertTrue(self.store.status()['error'])
        path.write_bytes(jpeg())
        self.store.scan()
        self.assertEqual(self.store.photos(), [])
        self.store.scan()
        self.assertEqual(len(self.store.photos()), 1)
        self.assertEqual(self.store.status()['error'], '')

    def test_pause_restart_and_source_deletion(self):
        self.store.configure(str(self.folder), False)
        source = self.folder / 'new.jpg'
        source.write_bytes(jpeg())
        self.settle()
        self.assertEqual(self.store.photos(), [])
        self.store.configure(str(self.folder), True)
        restarted = Inbox(self.store.root)
        restarted.scan()
        restarted.scan()
        self.assertEqual(len(restarted.photos()), 1)
        source.unlink()
        self.assertEqual(len(restarted.photos()), 1)
        restarted.close()

    def test_ignores_non_jpegs_and_symlinks(self):
        self.store.configure(str(self.folder), True)
        other = self.root / 'other.jpg'
        other.write_bytes(jpeg())
        (self.folder / 'link.jpg').symlink_to(other)
        (self.folder / 'raw.nef').write_bytes(jpeg())
        self.settle()
        self.assertEqual(self.store.photos(), [])

    def test_thumbnail_applies_exif_orientation(self):
        self.store.configure(str(self.folder), True)
        image = Image.new('RGB', (40, 60), 'red')
        exif = Image.Exif()
        exif[274] = 6
        image.save(self.folder / 'rotated.jpg', exif=exif)
        self.settle()
        photo = self.store.photos()[0]
        with Image.open(self.store.root / f"{photo['id']}.thumb.jpg") as thumb:
            self.assertEqual(thumb.size, (60, 40))

    def test_rejects_invalid_folder(self):
        for path in [self.root / 'missing', self.root]:
            with self.assertRaises(ValueError):
                self.store.configure(str(path), True)

    def test_api_and_persistence(self):
        with patch.dict(os.environ, {'RECEIPTER_DATA_DIR': str(self.root / 'api-data')}):
            with TestClient(app) as client:
                response = client.put('/api/inbox/settings', json={'folder': str(self.folder), 'enabled': True})
                self.assertEqual(response.status_code, 200)
                (self.folder / 'photo.jpg').write_bytes(jpeg())
                app.state.inbox.scan()
                app.state.inbox.scan()
                photos = client.get('/api/inbox/photos').json()
                self.assertEqual(len(photos), 1)
                photo_id = photos[0]['id']
                self.assertEqual(client.get(f'/api/inbox/photos/{photo_id}/original').content, jpeg())
                thumbnail = client.get(f'/api/inbox/photos/{photo_id}/thumbnail')
                self.assertEqual(thumbnail.headers['content-type'], 'image/jpeg')
                self.assertEqual(client.get('/api/inbox/photos/nope/original').status_code, 404)
                self.assertEqual(client.get(f'/api/inbox/photos/{photo_id}/bad').status_code, 404)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/inbox').json()['count'], 1)
                self.assertEqual(client.get('/api/inbox').json()['folder'], str(self.folder.resolve()))
