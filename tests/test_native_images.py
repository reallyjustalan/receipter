from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from receipter.imaging import load_source
from receipter.native_images import convert_heif, is_heif

HEIC = b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic'


class NativeImageTests(unittest.TestCase):
    def test_container_detection(self):
        self.assertTrue(is_heif(HEIC))
        self.assertFalse(is_heif(b'not an image'))
        self.assertFalse(is_heif(HEIC.replace(b'heic', b'avif')))

    def test_native_conversion_uses_bounded_temp_copy_no_shell(self):
        temp_paths = []
        def run(command, **kwargs):
            self.assertEqual(command[0], '/usr/bin/sips')
            if '-g' in command:
                return Mock(returncode=0, stdout=b'pixelWidth: 8000\npixelHeight: 4000\n')
            self.assertIn('--resampleHeightWidthMax', command)
            self.assertIn('4096', command)
            self.assertNotIn('shell', kwargs)
            source, output = Path(command[-3]), Path(command[-1])
            self.assertEqual(source.read_bytes(), HEIC)
            temp_paths.extend([source, output])
            Image.new('RGB', (40, 20), 'red').save(output, 'JPEG')
            return Mock(returncode=0)
        with patch('receipter.native_images.sys.platform', 'darwin'), \
                patch('receipter.native_images.subprocess.run', side_effect=run):
            image = load_source(HEIC)
        self.assertEqual(image.size, (40, 20))
        self.assertTrue(all(not path.exists() for path in temp_paths))

    def test_small_heic_is_not_upscaled(self):
        def run(command, **kwargs):
            if '-g' in command:
                return Mock(returncode=0, stdout=b'pixelWidth: 40\npixelHeight: 20\n')
            self.assertNotIn('--resampleHeightWidthMax', command)
            Image.new('RGB', (40, 20)).save(command[-1], 'JPEG')
            return Mock(returncode=0)
        with patch('receipter.native_images.sys.platform', 'darwin'), \
                patch('receipter.native_images.subprocess.run', side_effect=run):
            image = load_source(HEIC)
        self.assertEqual(image.size, (40, 20))

    def test_non_macos_error_is_actionable(self):
        with patch('receipter.native_images.sys.platform', 'linux'):
            with self.assertRaisesRegex(ValueError, 'server to run on macOS'):
                convert_heif(HEIC, 4096)

    def test_failed_and_timed_out_conversions(self):
        with patch('receipter.native_images.sys.platform', 'darwin'):
            with patch('receipter.native_images.subprocess.run', return_value=Mock(returncode=1)):
                with self.assertRaisesRegex(ValueError, 'could not read'):
                    convert_heif(HEIC, 4096)
            with patch('receipter.native_images.subprocess.run', side_effect=subprocess.TimeoutExpired('sips', 30)):
                with self.assertRaisesRegex(ValueError, 'timed out'):
                    convert_heif(HEIC, 4096)
