from base64 import b64decode
from decimal import Decimal
from io import BytesIO
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from pydantic import ValidationError

from receipter import app
from receipter.imaging import BLACK, RED, WHITE, load_source, prepare_image
from receipter.receipt import Footer, Header, ImageEdits, Item, Photo, Receipt, Signature, Text, render_receipt

SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
<rect width="100" height="100" fill="#d20000"/>
<rect x="100" width="100" height="100" fill="black"/></svg>'''


def png(image):
    output = BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


class ReceiptTests(unittest.TestCase):
    def test_svg_preserves_aspect_viewbox_transparency_and_channels(self):
        source = load_source(SVG)
        self.assertEqual(source.width / source.height, 2)
        result = prepare_image(SVG, width=200, dither=False)
        self.assertEqual(result.colors.size, (200, 50))
        self.assertEqual(result.colors.getpixel((20, 20)), RED)
        self.assertEqual(result.colors.getpixel((180, 20)), BLACK)
        transparent = SVG.replace(b'fill="#d20000"', b'fill="none"')
        self.assertEqual(prepare_image(transparent, width=200).colors.getpixel((20, 20)), WHITE)

    def test_svg_and_raster_use_identical_processing(self):
        raster = png(load_source(SVG))
        edits = dict(brightness=.85, contrast=1.2, black_ink=37, red_ink=64,
                     assignment='swap', threshold=140, crop_zoom=1.4, crop_x=.3, frame_height=180)
        for dither in (False, True):
            self.assertEqual(prepare_image(SVG, dither=dither, **edits).preview_png,
                             prepare_image(raster, dither=dither, **edits).preview_png)

    def test_svg_rejects_external_resources_and_entities(self):
        for svg in [b'<svg><image href="file:///etc/passwd"/></svg>',
                    b'<svg><use href="https://example.com/x.svg#id"/></svg>',
                    b'<svg><style>@import "https://example.com/a.css"</style></svg>',
                    b'<svg><rect fill="url(https://example.com/a)"/></svg>',
                    b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
                    b'<html/>', b'<svg>']:
            with self.subTest(svg=svg), self.assertRaises(ValueError):
                load_source(svg)

    def test_crop_position_rotation_and_assignment(self):
        left = prepare_image(SVG, width=100, frame_height=100, crop_x=0, dither=False)
        right = prepare_image(SVG, width=100, frame_height=100, crop_x=1, dither=False)
        self.assertEqual(left.colors.getpixel((50,25)), RED)
        self.assertEqual(right.colors.getpixel((50,25)), BLACK)
        for assignment, expected in [('red', RED), ('black', BLACK)]:
            result = prepare_image(SVG, width=100, assignment=assignment, dither=False)
            self.assertEqual(set(result.colors.tobytes()), {expected})
        contained = prepare_image(SVG, width=100, frame_height=200, fit='contain', dither=False)
        self.assertEqual(contained.colors.getpixel((50,0)), WHITE)
        self.assertNotEqual(prepare_image(SVG, width=100, rotation=90).colors.size, left.colors.size)

    def test_threshold_and_dithering(self):
        raw = png(Image.new('RGB', (100,100), (150,150,150)))
        light = prepare_image(raw, width=100, two_color=False, dither=False, threshold=60)
        dark = prepare_image(raw, width=100, two_color=False, dither=False, threshold=220)
        self.assertEqual(set(light.colors.tobytes()), {WHITE})
        self.assertEqual(set(dark.colors.tobytes()), {BLACK})
        dithered = prepare_image(raw, width=100, two_color=False, dither=True)
        self.assertEqual(set(dithered.colors.tobytes()), {BLACK, WHITE})

    def test_three_photos_footer_and_signature_form_one_receipt(self):
        doc = Receipt(blocks=[Header(id='h', asset='logo'),
                              *[Photo(id=f'p{i}', asset='photo') for i in range(3)],
                              Footer(id='f', items=[Item(label='Prints', quantity=3, price=Decimal('.10'))],
                                     date='2026-09-08', reference='BOOTH-01'), Signature(id='s')])
        prepared, metadata = render_receipt(doc, {'logo':SVG,'photo':SVG})
        self.assertEqual(prepared.width, 400)
        self.assertLessEqual(prepared.height, 1024)
        self.assertEqual([m['id'] for m in metadata], ['h','p0','p1','p2','f','s'])
        preview = Image.open(BytesIO(prepared.preview_png))
        self.assertEqual(preview.tobytes(), prepared.colors.convert('RGB').resize(preview.size, Image.Resampling.NEAREST).tobytes())
        self.assertTrue(set(prepared.colors.tobytes()) <= {WHITE, BLACK, RED})

    def test_reorder_changes_composition_not_individual_processing(self):
        a = Photo(id='a', asset='x', edits=ImageEdits(assignment='black'))
        b = Photo(id='b', asset='x', edits=ImageEdits(assignment='red'))
        original, om = render_receipt(Receipt(blocks=[a,b]), {'x':SVG})
        reordered, rm = render_receipt(Receipt(blocks=[b,a]), {'x':SVG})
        self.assertNotEqual(original.preview_png, reordered.preview_png)
        for first, second in [(om[0],rm[1]),(om[1],rm[0])]:
            def crop(image, meta):
                return image.colors.crop((0,meta['y'],400,meta['y']+meta['height'])).tobytes()
            self.assertEqual(crop(original,first),crop(reordered,second))

    def test_invalid_receipts_are_rejected(self):
        for blocks, assets in [([Photo(id='p',asset='missing')], {}),
                               ([Text(id='same'),Text(id='same')], {}),
                               ([Photo(id=f'p{i}',asset='x') for i in range(4)], {'x':SVG}),
                               ([Photo(id=f'p{i}',asset='x',height=800) for i in range(3)], {'x':SVG})]:
            with self.subTest(blocks=blocks), self.assertRaises(ValueError):
                render_receipt(Receipt(blocks=blocks), assets)
        for data in [{'blocks':[]}, {'blocks':[{'id':'a','type':'unknown'}]},
                     {'blocks':[{'id':'a','type':'text'}], 'zoom':2}]:
            with self.assertRaises(ValidationError):
                Receipt.model_validate(data)
        with self.assertRaises(ValidationError):
            Item(label='Bad price',price='0.001')
        with self.assertRaises(ValidationError):
            ImageEdits(brightness=float('nan'))

    def test_costs_use_decimal_tabulation(self):
        footer = Footer(id='f', items=[Item(label='Photo',price='.10',quantity=3),Item(label='Logo',price='.20')])
        with patch('receipter.receipt.TextCanvas.amount', autospec=True) as amount:
            render_receipt(Receipt(blocks=[footer]), {})
            self.assertEqual(amount.call_args.args[1:], ('TOTAL','$0.50'))


class ReceiptAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app._snapshots.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        app._snapshots.clear()

    async def preview(self):
        return await self.client.post('/api/receipt-preview',
            data={'document':Receipt(blocks=[Header(id='h',asset='logo')]).model_dump_json()},
            files=[('assets',('logo',SVG,'image/svg+xml'))])

    async def test_print_uses_exact_preview_snapshot_without_rerendering(self):
        response = await self.preview()
        self.assertEqual(response.status_code,200,response.text)
        proof = response.json()
        self.assertEqual(proof['scale'],.5)
        with (patch.object(app,'render_receipt',side_effect=AssertionError('No rerender')),
              patch.object(app,'_token',return_value=1),
              patch.object(app,'_print_prepared',new_callable=AsyncMock,return_value={'ok':True}) as send):
            response = await self.client.post('/api/print-receipt',data={'snapshot':proof['token']})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(send.call_args.args[0].preview_png,b64decode(proof['png']))
            self.assertEqual(send.call_args.args[1:4],(1,16,1))
            self.assertEqual(send.call_args.kwargs,{'cut':True,'feed_lines':8})
            response = await self.client.post('/api/print-receipt',data={'snapshot':proof['token']})
            self.assertEqual(response.status_code,409)
            send.assert_awaited_once()

    async def test_missing_expired_and_stale_tokens_never_print(self):
        proof = (await self.preview()).json()
        with patch.object(app,'_token',return_value=1), patch.object(app,'_print_prepared',new_callable=AsyncMock) as send:
            response = await self.client.post('/api/print-receipt',data={'snapshot':proof['token']},headers={'X-Receipter-Build':'stale'})
            self.assertEqual(response.status_code,409)
            with patch.object(app,'monotonic',return_value=app.monotonic()+1801):
                response = await self.client.post('/api/print-receipt',data={'snapshot':proof['token']})
                self.assertEqual(response.status_code,409)
            send.assert_not_called()

    async def test_receipt_validation_and_finishing_errors(self):
        for document in ['invalid','{"blocks":[]}','{"blocks":[{"type":"photo","id":"x","asset":"missing"}]}']:
            response = await self.client.post('/api/receipt-preview',data={'document':document})
            self.assertEqual(response.status_code,400,response.text)
        proof = (await self.preview()).json()
        with patch.object(app,'_token',return_value=1), patch.object(app,'_print_prepared',new_callable=AsyncMock) as send:
            response = await self.client.post('/api/print-receipt',data={'snapshot':proof['token'],'feed_lines':2})
            self.assertEqual(response.status_code,400)
            self.assertIn(proof['token'],app._snapshots)
            send.assert_not_called()

    async def test_legacy_preview_rejects_arbitrary_render_scales(self):
        response = await self.client.post('/api/preview',data={'vertical_scale':1.5},files={'image':('logo.svg',SVG)})
        self.assertEqual(response.status_code,400)

    async def test_snapshot_cache_is_bounded_and_stop_preserves_unattempted_token(self):
        first = (await self.preview()).json()['token']
        for _ in range(16):
            latest = (await self.preview()).json()['token']
        self.assertEqual(len(app._snapshots),16)
        self.assertNotIn(first,app._snapshots)
        with patch.object(app,'_token',side_effect=app.HTTPException(409,'Stopped')):
            response = await self.client.post('/api/print-receipt',data={'snapshot':latest})
            self.assertEqual(response.status_code,409)
            self.assertIn(latest,app._snapshots)

    async def test_frozen_studio_assets(self):
        with patch('pathlib.Path.read_text',side_effect=AssertionError('Live file access')):
            for path in ['/studio.js','/studio.css']:
                response = await self.client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers['cache-control'],'no-store')


if __name__ == '__main__':
    unittest.main()
