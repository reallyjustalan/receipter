import unittest

from receipter.app import _encode_prepared
from receipter.escpos import encode_native_text
from receipter.receipt import Receipt, Text, Header, Footer, Item, Photo, Signature, render_receipt
from pydantic import ValidationError


class NativeTextTests(unittest.TestCase):
    def test_standard_text_uses_library_text_not_bitmap(self):
        prepared, _ = render_receipt(Receipt(blocks=[Text(id='t', text='Hello world')]), {})
        raw = b''.join(_encode_prepared(prepared, 1, 16, cut=False, feed_lines=0))
        self.assertIn(b'Hello world\n', raw)
        self.assertNotIn(b'\x1b*', raw)
        self.assertIn(1, prepared.colors.tobytes())  # preview still has glyphs

    def test_mixed_order_and_copies(self):
        prepared, _ = render_receipt(Receipt(blocks=[Text(id='a', text='FIRST'),
            Header(id='h', title='Artwork'), Text(id='b', text='LAST')]), {})
        single = _encode_prepared(prepared, 1, 16)
        raw = b''.join(single)
        self.assertLess(raw.index(b'FIRST\n'), raw.index(b'\x1b*'))
        self.assertLess(raw.index(b'\x1b*'), raw.index(b'LAST\n'))
        self.assertEqual(_encode_prepared(prepared, 1, 16, copies=2), single * 2)

    def test_wrapping_and_blank_lines(self):
        prepared, _ = render_receipt(Receipt(blocks=[Text(id='t', text='A' * 31 + '\n\nB')]), {})
        self.assertEqual(len(prepared.native_text), 4)
        for run, expected in zip(prepared.native_text, [b'A' * 30, b'A', b'', b'B']):
            self.assertIn(expected + b'\n', run[2])

    def test_footer_details_use_native_text_but_keep_rules(self):
        prepared, _ = render_receipt(Receipt(blocks=[Footer(id='f',
            items=[Item(label='Print', quantity=2, price='1.25')],
            date='2026-09-08', reference='ABC', text='THANK YOU')]), {})
        raw = b''.join(_encode_prepared(prepared, 1, 16))
        for expected in [b'2 x Print', b'$2.50', b'TOTAL', b'2026-09-08', b'REF: ABC', b'THANK YOU']:
            self.assertIn(expected, raw)
        self.assertIn(b'\x1b*', raw)  # rules still print as artwork

    def test_subtitle_caption_signature_native_title_unchanged(self):
        prepared, _ = render_receipt(Receipt(blocks=[Header(id='h', title='TITLE', subtitle='Subtitle'),
            Signature(id='s', label='Sign here')]), {})
        raw = b''.join(_encode_prepared(prepared, 1, 16))
        self.assertNotIn(b'TITLE', raw)
        self.assertIn(b'Subtitle\n', raw)
        self.assertIn(b'Sign here\n', raw)
        from io import BytesIO
        from PIL import Image
        image = BytesIO()
        Image.new('RGB', (32, 32), 'white').save(image, 'PNG')
        prepared, _ = render_receipt(Receipt(blocks=[Photo(id='p', asset='x', caption='Caption')]),
                                     {'x': image.getvalue()})
        self.assertIn(b'Caption\n', b''.join(_encode_prepared(prepared, 1, 16)))
        self.assertGreater(prepared.native_text[0][0], 100)

    def test_large_text_wraps_and_reserves_double_height(self):
        normal, _ = render_receipt(Receipt(blocks=[Text(id='t', text='A' * 20)]), {})
        large, _ = render_receipt(Receipt(blocks=[Text(id='t', text='A' * 20, font_size='large')]), {})
        self.assertEqual(len(normal.native_text), 1)
        self.assertEqual(len(large.native_text), 2)
        self.assertGreater(large.height, normal.height)
        for start, end, raw in large.native_text:
            self.assertEqual(end - start, 26)
            self.assertIn(b'\x1b!0', raw)  # ESC ! double width + height
            self.assertIn(b'\x1b34', raw)  # 52 feed units per line
            self.assertIn(b'\x1b!\x00', raw)  # size reset
        for size in ['normal', 'large']:
            title, _ = render_receipt(Receipt(blocks=[Header(id='h', title='TITLE', font_size=size)]), {})
            if size == 'normal':
                title_normal = title
            else:
                self.assertEqual(title.preview_png, title_normal.preview_png)
        with self.assertRaises(ValidationError):
            Text(id='t', font_size='huge')

    def test_header_title_font_selection_and_size(self):
        for size, pitch in [('normal', 13), ('large', 26)]:
            for font in ['custom', 'native']:
                with self.subTest(size=size, font=font):
                    header = Header(id='h', title='TITLE', subtitle='Subtitle',
                                    title_font=font, font_size=size)
                    restored = Receipt.model_validate_json(Receipt(blocks=[header]).model_dump_json())
                    prepared, _ = render_receipt(restored, {})
                    runs = prepared.native_text
                    self.assertEqual(len(runs), 2 if font == 'native' else 1)
                    raw = b''.join(_encode_prepared(prepared, 1, 16))
                    self.assertEqual(b'TITLE\n' in raw, font == 'native')
                    self.assertIn(b'Subtitle\n', raw)
                    for start, end, commands in runs:
                        self.assertEqual(end - start, pitch)
                        self.assertIn(b'\x1ba\x01', commands)  # centered native header text
                    if size == 'large' and font == 'native':
                        self.assertIn(b'\x1b!0', runs[0][2])
        self.assertEqual(Header(id='h').title_font, 'custom')
        with self.assertRaises(ValidationError):
            Header(id='h', title_font='unknown')

    def test_footer_ascii_quantity_marker_at_both_sizes(self):
        for size in ['normal', 'large']:
            prepared, _ = render_receipt(Receipt(blocks=[Footer(id='f', font_size=size,
                items=[Item(label='Photo', quantity=3, price='0.10')])]), {})
            raw = b''.join(commands for _, _, commands in prepared.native_text)
            self.assertIn(b'3 x Photo', raw)
            self.assertIn(b'$0.30', raw)
            # ASCII-only receipt must never switch to a non-default code page.
            pages = [raw[i + 2] for i in range(len(raw) - 2) if raw[i:i+2] == b'\x1bt']
            self.assertTrue(all(page == 0 for page in pages))

    def test_controls_rejected(self):
        for text in ['bad\x1b@', 'bad\x00', 'bad\r', 'bad\x7f']:
            with self.assertRaises(ValueError):
                encode_native_text([text])
