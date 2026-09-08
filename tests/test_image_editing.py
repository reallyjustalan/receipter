from collections import Counter
from io import BytesIO
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageDraw
from fastapi import UploadFile

from receipter.imaging import BLACK, RED, WHITE, prepare_image
from receipter.escpos import _eight_dot_band


def png(image):
    data = BytesIO()
    image.save(data, 'PNG')
    return data.getvalue()


def swatches():
    image = Image.new('RGB', (32, 32), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 15, 15), fill='black')
    draw.rectangle((16, 0, 31, 15), fill=(210, 0, 0))
    return png(image)


def prepare(raw=None, **edits):
    return prepare_image(raw or swatches(), width=32, vertical_scale=1, dither=False, **edits)


class ImageEditingTests(unittest.TestCase):
    def test_default_preserves_real_black_red_white_channels(self):
        colors = prepare().colors
        self.assertEqual(Counter(colors.tobytes()), {WHITE: 512, BLACK: 256, RED: 256})

    def test_rotation_is_clockwise_and_changes_aspect(self):
        image = prepare(rotation=90).colors
        self.assertEqual(image.getpixel((24, 8)), BLACK)
        self.assertEqual(image.getpixel((24, 24)), RED)
        self.assertEqual(image.getpixel((8, 8)), WHITE)
        raw = png(Image.new('RGB', (32, 16), 'black'))
        self.assertEqual(prepare(raw).colors.size, (32, 16))
        self.assertEqual(prepare(raw, rotation=90).colors.size, (32, 64))
        self.assertEqual(prepare(raw, rotation=180).colors.size, (32, 16))

    def test_flips_are_in_rotated_image_coordinates(self):
        self.assertEqual(prepare(flip_horizontal=True).colors.getpixel((24, 8)), BLACK)
        self.assertEqual(prepare(flip_vertical=True).colors.getpixel((8, 24)), BLACK)
        self.assertEqual(prepare(rotation=90, flip_horizontal=True).colors.getpixel((8, 8)), BLACK)

    def test_ink_controls_remove_dots_without_swapping_colors(self):
        original = prepare().colors.tobytes()
        for kwargs, removed, retained in [({'black_ink': 0}, BLACK, RED), ({'red_ink': 0}, RED, BLACK)]:
            edited = prepare(**kwargs).colors.tobytes()
            self.assertNotIn(removed, edited)
            self.assertEqual(edited.count(retained), original.count(retained))
            for before, after in zip(original, edited):
                self.assertEqual(after, WHITE if before == removed else before)
        self.assertEqual(set(prepare(black_ink=0, red_ink=0).colors.tobytes()), {WHITE})

    def test_half_ink_and_monotonic_thinning_are_deterministic(self):
        raw = png(Image.new('RGB', (32, 32), (210, 0, 0)))
        half = prepare(raw, red_ink=50)
        self.assertEqual(half.colors.tobytes().count(RED), 512)
        self.assertEqual(half.preview_png, prepare(raw, red_ink=50).preview_png)
        fewer = prepare(raw, red_ink=25).colors.tobytes()
        for lower, higher in zip(fewer, half.colors.tobytes()):
            if lower == RED:
                self.assertEqual(higher, RED)

    def test_brightness_can_make_image_lighter_or_darker(self):
        raw = png(Image.new('RGB', (32, 32), (150, 150, 150)))
        dark = prepare(raw, two_color=False, brightness=0.5).colors
        light = prepare(raw, two_color=False, brightness=1.5).colors
        self.assertEqual(set(dark.tobytes()), {BLACK})
        self.assertEqual(set(light.tobytes()), {WHITE})

    def test_contrast_changes_quantized_output(self):
        image = Image.new('RGB', (32, 32))
        image.putdata([(x * 8,) * 3 for y in range(32) for x in range(32)])
        raw = png(image)
        low = prepare_image(raw, 32, 1, False, True, contrast=0.2)
        high = prepare_image(raw, 32, 1, False, True, contrast=2)
        self.assertNotEqual(low.colors.tobytes(), high.colors.tobytes())

    def test_preview_is_exactly_the_printable_palette(self):
        prepared = prepare(rotation=270, black_ink=30, red_ink=65, brightness=1.2)
        preview = Image.open(BytesIO(prepared.preview_png))
        expected = prepared.colors.convert('RGB').resize(preview.size, Image.Resampling.NEAREST)
        self.assertEqual(preview.tobytes(), expected.tobytes())
        self.assertTrue(set(prepared.colors.tobytes()) <= {WHITE, BLACK, RED})
        for y in range(0, prepared.height, 8):
            black = _eight_dot_band(prepared.colors, y, BLACK)
            red = _eight_dot_band(prepared.colors, y, RED)
            self.assertTrue(all(not (b & r) for b, r in zip(black, red)))

    def test_transparency_is_white_and_mono_never_uses_red(self):
        transparent = png(Image.new('RGBA', (32, 32), (0, 0, 0, 0)))
        self.assertEqual(set(prepare(transparent).colors.tobytes()), {WHITE})
        self.assertNotIn(RED, prepare(two_color=False).colors.tobytes())

    def test_invalid_edit_settings_are_rejected(self):
        for edits in [dict(rotation=45), dict(brightness=0), dict(brightness=float('nan')),
                      dict(contrast=3), dict(black_ink=-1), dict(red_ink=101)]:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                prepare(**edits)


class SharedPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_and_print_use_identical_edits(self):
        from receipter import app
        edits = dict(rotation=90, flip_horizontal=True, flip_vertical=False,
                     brightness=1.2, contrast=0.8, black_ink=35, red_ink=70)
        raw = swatches()
        response = await app.preview(UploadFile(file=BytesIO(raw)), 32, 0.5, True, True, edits)
        with patch.object(app, '_print_prepared', new_callable=AsyncMock, return_value={}) as send:
            await app.print_image(UploadFile(file=BytesIO(raw)), 32, 0.5, True, True, 0, 16,
                                  True, 8, edits)
            prepared = send.call_args.args[0]
            self.assertEqual(response.body, prepared.preview_png)
            self.assertEqual(send.call_args.kwargs, {'cut': True, 'feed_lines': 8})

    async def test_both_http_routes_expose_the_same_edit_fields(self):
        from receipter.app import app
        schema = app.openapi()
        for route in ['/api/preview', '/api/print']:
            ref = schema['paths'][route]['post']['requestBody']['content']['multipart/form-data']['schema']['$ref']
            fields = schema['components']['schemas'][ref.split('/')[-1]]['properties']
            for name in ['rotation', 'flip_horizontal', 'flip_vertical', 'brightness',
                         'contrast', 'red_ink', 'black_ink']:
                self.assertIn(name, fields)


if __name__ == '__main__':
    unittest.main()
