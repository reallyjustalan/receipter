from io import BytesIO
import os
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from receipter.background import BackgroundUnavailable, _person_mask, remove_background
from receipter.app import app


def png(image):
    output = BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


class BackgroundTests(unittest.TestCase):
    def test_mask_preserves_framing_color_and_existing_alpha(self):
        source = Image.new('RGBA', (8, 4), (210, 30, 20, 128))
        mask = Image.new('L', source.size, 0)
        mask.paste(255, (0, 0, 4, 4))
        with patch('receipter.background._person_mask', return_value=mask):
            result = Image.open(BytesIO(remove_background(png(source))))
        self.assertEqual(result.size, source.size)
        self.assertEqual(result.getpixel((0, 0)), (210, 30, 20, 128))
        self.assertEqual(result.getpixel((7, 3)), (210, 30, 20, 0))

    def test_empty_mask_is_not_returned_as_a_blank_image(self):
        with patch('receipter.background._person_mask', return_value=Image.new('L', (2, 2), 4)):
            with self.assertRaisesRegex(ValueError, 'No people detected'):
                remove_background(png(Image.new('RGB', (8, 4))))

    def test_invalid_image_never_reaches_vision(self):
        with patch('receipter.background._person_mask') as native:
            with self.assertRaises(ValueError):
                remove_background(b'not an image')
            native.assert_not_called()

    def test_exif_orientation_applied_before_segmentation(self):
        source = Image.new('RGB', (8, 4))
        exif = Image.Exif(); exif[274] = 6
        data = BytesIO(); source.save(data, 'JPEG', exif=exif)
        with patch('receipter.background._person_mask', return_value=Image.new('L', (4, 8), 255)) as native:
            result = Image.open(BytesIO(remove_background(data.getvalue())))
        self.assertEqual(native.call_args.args[0].size, (4, 8))
        self.assertEqual(result.size, (4, 8))

    def test_other_platform_has_actionable_error(self):
        with patch('receipter.background.sys.platform', 'linux'):
            with self.assertRaisesRegex(BackgroundUnavailable, 'requires a Mac'):
                _person_mask(Image.new('RGBA', (8, 4)))

    @unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('RECEIPTER_TEST_VISION'),
                         'Opt-in native Vision integration test')
    def test_native_blank_photo_has_no_people(self):
        with self.assertRaisesRegex(ValueError, 'No people detected'):
            remove_background(png(Image.new('RGB', (320, 240), 'white')))


class BackgroundAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_returns_uncached_png_without_printing(self):
        raw = png(Image.new('RGBA', (8, 4), (0, 0, 0, 0)))
        with patch('receipter.app.remove_background', return_value=raw) as native:
            response = self.client.post('/api/remove-background', files={'image': ('photo.png', raw)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, raw)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        native.assert_called_once_with(raw)

    def test_failure_statuses(self):
        for error, status in [(ValueError('No people detected'), 400),
                              (BackgroundUnavailable('requires a Mac'), 503)]:
            with self.subTest(status=status), patch('receipter.app.remove_background', side_effect=error):
                response = self.client.post('/api/remove-background', files={'image': ('photo.png', b'image')})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()['detail'], str(error))

    def test_upload_and_output_limits(self):
        with patch('receipter.app.MAX_UPLOAD', 4), patch('receipter.app.remove_background') as native:
            response = self.client.post('/api/remove-background', files={'image': ('photo.png', b'12345')})
            self.assertEqual(response.status_code, 413)
            native.assert_not_called()
            native.return_value = b'12345'
            response = self.client.post('/api/remove-background', files={'image': ('photo.png', b'1234')})
            self.assertEqual(response.status_code, 413)


if __name__ == '__main__':
    unittest.main()
