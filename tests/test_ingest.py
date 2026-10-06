import io
import os
from pathlib import Path
import tempfile
import subprocess
import sys
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

    def test_disappearing_file_does_not_block_other_imports(self):
        self.store.configure(str(self.folder), True)
        missing = self.folder / 'a-missing.jpg'
        valid = self.folder / 'b-valid.jpg'
        valid.write_bytes(jpeg())
        with patch.object(self.store, 'files', return_value=[missing, valid]):
            self.settle()
        self.assertEqual(len(self.store.photos()), 1)
        self.assertEqual(self.store.status()['error'], '')

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

    def test_all_jpeg_extensions_case_insensitive(self):
        self.store.configure(str(self.folder), True)
        extensions = ['jpg', 'JPG', 'JPEG', 'JpE', 'jfif', 'JIF', 'jFi']
        for index, extension in enumerate(extensions):
            (self.folder / f'photo-{index}.{extension}').write_bytes(jpeg((index * 35, 50, 100)))
        self.settle()
        self.assertEqual(len(self.store.photos()), len(extensions))
        self.assertEqual(self.store.status()['error'], '')

    @unittest.skipUnless(sys.platform == 'darwin', 'Uses macOS HEIC conversion')
    def test_real_heic_auto_ingestion_and_api_preserve_original(self):
        png = self.root / 'source.png'
        Image.new('RGB', (800, 600), 'red').save(png)
        heic = self.folder / 'camera.HEIC'
        result = subprocess.run(['/usr/bin/sips', '-s', 'format', 'heic', str(png), '--out', str(heic)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = heic.read_bytes()
        with patch.dict(os.environ, {'RECEIPTER_DATA_DIR': str(self.root / 'heic-api')}):
            with TestClient(app) as client:
                response = client.put('/api/inbox/settings', json={'folder': str(self.folder), 'enabled': True, 'import_existing': True})
                self.assertEqual(response.status_code, 200)
                with patch('receipter.imaging.WORKING_IMAGE_EDGE', 200):
                    app.state.inbox.scan()
                    app.state.inbox.scan()
                self.assertEqual(app.state.inbox.status()['error'], '')
                photos = client.get('/api/inbox/photos').json()
                self.assertEqual(len(photos), 1)
                photo_id = photos[0]['id']
                saved_original = client.get(f'/api/inbox/photos/{photo_id}/original')
                self.assertEqual(saved_original.headers['content-type'], 'image/heic')
                self.assertEqual(saved_original.content, original)
                working = client.get(f'/api/inbox/photos/{photo_id}/working')
                self.assertEqual(working.headers['content-type'], 'image/jpeg')
                with Image.open(io.BytesIO(working.content)) as image:
                    self.assertEqual(image.format, 'JPEG')
                    self.assertLessEqual(max(image.size), 200)
                self.assertEqual(heic.read_bytes(), original)

    def test_camera_jpg_with_mpo_metadata_is_a_valid_jpeg(self):
        self.store.configure(str(self.folder), True)
        stream = io.BytesIO()
        Image.new('RGB', (40, 60), 'red').save(stream, 'MPO', save_all=True,
            append_images=[Image.new('RGB', (40, 60), 'blue')])
        raw = stream.getvalue()
        self.assertTrue(raw.startswith(b'\xff\xd8\xff'))
        with Image.open(io.BytesIO(raw)) as source:
            self.assertEqual(source.format, 'MPO')
        source_path = self.folder / 'CAMERA.JPG'
        source_path.write_bytes(raw)
        self.settle()
        self.assertEqual(self.store.status()['error'], '')
        photos = self.store.photos()
        self.assertEqual(len(photos), 1)
        photo_id = photos[0]['id']
        self.assertEqual((self.store.root / f'{photo_id}.jpg').read_bytes(), raw)
        self.assertEqual(source_path.read_bytes(), raw)
        with Image.open(self.store.root / f'{photo_id}.working.jpg') as working:
            self.assertEqual(working.format, 'JPEG')
            r, g, b = working.getpixel((20, 30))
            self.assertGreater(r, 200)  # The first/main frame, not the blue secondary picture.
            self.assertLess(b, 50)
        self.settle()
        self.assertEqual(len(self.store.photos()), 1)  # Stable deduplication.

    def test_supported_extension_still_requires_jpeg_content(self):
        self.store.configure(str(self.folder), True)
        Image.new('RGB', (40, 60)).save(self.folder / 'not-jpeg.jfif', 'PNG')
        self.settle()
        self.assertEqual(self.store.photos(), [])
        self.assertIn('Not a JPEG: detected PNG content', self.store.status()['error'])
        self.assertIn('filename extension', self.store.status()['error'])

    def test_pasted_folder_paths_and_import_while_resuming(self):
        (self.folder / 'existing.jpe').write_bytes(jpeg())
        for quote in ('"', "'"):
            status = self.store.configure(f'  {quote}{self.folder}{quote}  ', False)
            self.assertEqual(status['folder'], str(self.folder.resolve()))
        self.store.configure(str(self.folder), True, import_existing=True)
        self.settle()
        self.assertEqual(len(self.store.photos()), 1)

    def test_working_copy_downsamples_and_keeps_original(self):
        stream = io.BytesIO()
        Image.new('RGB', (800, 600), 'blue').save(stream, 'JPEG')
        raw = stream.getvalue()
        self.store.configure(str(self.folder), True)
        (self.folder / 'large.jpg').write_bytes(raw)
        with patch('receipter.imaging.WORKING_IMAGE_EDGE', 200):
            self.settle()
        photo = self.store.photos()[0]
        self.assertEqual((self.store.root / f"{photo['id']}.jpg").read_bytes(), raw)
        with Image.open(self.store.root / f"{photo['id']}.working.jpg") as working:
            self.assertEqual(working.size, (200, 150))
        self.assertEqual((self.folder / 'large.jpg').read_bytes(), raw)

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
                working_path = app.state.inbox.root / f'{photo_id}.working.jpg'
                self.assertTrue(working_path.exists())
                working_path.unlink()  # Older catalogues generate a working copy on demand.
                working = client.get(f'/api/inbox/photos/{photo_id}/working')
                self.assertEqual(working.status_code, 200)
                self.assertEqual(working.headers['content-type'], 'image/jpeg')
                self.assertTrue(working_path.exists())
                with Image.open(io.BytesIO(working.content)) as image:
                    self.assertEqual(image.size, (40, 60))
                self.assertEqual(client.get('/api/inbox/photos/nope/original').status_code, 404)
                self.assertEqual(client.get(f'/api/inbox/photos/{photo_id}/bad').status_code, 404)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/inbox').json()['count'], 1)
                self.assertEqual(client.get('/api/inbox').json()['folder'], str(self.folder.resolve()))
