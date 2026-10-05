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

    def test_zoom_out_leaves_white_padding_and_moves_inside_frame(self):
        raw = png(Image.new('RGB', (64, 64), 'black'))
        for zoom in (.25, .5, 1):
            result = prepare_image(raw, width=64, vertical_scale=1, frame_height=64,
                                   crop_zoom=zoom, dither=False).colors
            self.assertEqual(result.size, (64, 64))
            self.assertEqual(result.tobytes().count(BLACK), round(64*zoom)**2)
        result = prepare_image(raw, width=64, vertical_scale=1, frame_height=64,
                               crop_zoom=.5, crop_x=0, crop_y=1, dither=False,
                               brightness=.2, threshold=255).colors
        self.assertEqual(result.getpixel((0, 63)), BLACK)
        self.assertEqual(result.getpixel((63, 0)), WHITE)

    def test_eraser_stays_white_under_dark_tone_and_ink_assignment(self):
        raw = png(Image.new('RGB', (64, 64), 'black'))
        strokes = [{'radius':.1, 'points':[(.25,.5), (.75,.5)]}]
        for assignment in ('auto', 'black', 'red', 'swap'):
            result = prepare_image(raw, width=64, vertical_scale=1, dither=False,
                                   brightness=.2, threshold=255, assignment=assignment,
                                   eraser_strokes=strokes).colors
            self.assertEqual(result.getpixel((32,32)), WHITE)
            self.assertNotEqual(result.getpixel((0,0)), WHITE)
        self.assertEqual(Image.open(BytesIO(raw)).getpixel((32,32)), (0,0,0))

    def test_eraser_tracks_rotation_flip_crop_and_zoom(self):
        raw = png(Image.new('RGB', (64, 32), 'black'))
        strokes = [{'radius':.08, 'points':[(.25,.25)]}]
        result = prepare_image(raw, width=32, vertical_scale=1, frame_height=64,
                               rotation=90, dither=False, eraser_strokes=strokes).colors
        self.assertEqual(result.getpixel((24,16)), WHITE)
        self.assertEqual(result.getpixel((8,48)), BLACK)
        result = prepare_image(raw, width=32, vertical_scale=1, frame_height=64,
                               rotation=90, flip_horizontal=True, dither=False,
                               eraser_strokes=strokes).colors
        self.assertEqual(result.getpixel((8,16)), WHITE)
        result = prepare_image(raw, width=64, vertical_scale=1, frame_height=32,
                               crop_zoom=.5, dither=False, eraser_strokes=strokes).colors
        self.assertEqual(result.getpixel((24,12)), WHITE)
        self.assertEqual(result.getpixel((40,20)), BLACK)
        result = prepare_image(raw, width=64, vertical_scale=1, frame_height=32,
                               crop_zoom=2, crop_x=0, crop_y=0, dither=False,
                               eraser_strokes=strokes).colors
        self.assertEqual(result.getpixel((32,16)), WHITE)

    def test_eraser_and_zoom_model_limits(self):
        from receipter.receipt import ImageEdits
        from pydantic import ValidationError
        for zoom in (.25, .5, 1, 4):
            self.assertEqual(ImageEdits(crop_zoom=zoom).crop_zoom, zoom)
        for values in [dict(crop_zoom=.2), dict(crop_zoom=4.1),
                       dict(eraser_strokes=[{'radius':.1, 'points':[]}]),
                       dict(eraser_strokes=[{'radius':.1, 'points':[(1.1,0)]}]),
                       dict(eraser_strokes=[{'radius':float('nan'), 'points':[(0,0)]}]),
                       dict(eraser_strokes=[{'radius':.1, 'points':[(0,0)]*257}]),
                       dict(eraser_strokes=[{'radius':.1, 'points':[(0,0)]}]*101)]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ImageEdits(**values)

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
