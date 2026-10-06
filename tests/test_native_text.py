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

    def test_small_uses_font_b_without_double_size_and_resets_font(self):
        raw = encode_native_text(['Small text'], font_size='small')
        self.assertIn(b'\x1bM\x01', raw)  # ESC M 1 selects resident Font B.
        self.assertIn(b'\x1b!\x00', raw)  # Explicit normal (not doubled) size.
        self.assertNotIn(b'\x1b!0', raw)
        self.assertIn(b'\x1b3\x1a', raw)  # Existing 26 feed units / 13 preview rows.
        self.assertLess(raw.index(b'\x1bM\x01'), raw.index(b'Small text\n'))
        self.assertGreater(raw.rindex(b'\x1bM\x00'), raw.index(b'Small text\n'))

    def test_small_wraps_at_40_columns_with_same_line_pitch(self):
        normal, _ = render_receipt(Receipt(blocks=[Text(id='t', text='A' * 40)]), {})
        small, _ = render_receipt(Receipt(blocks=[Text(id='t', text='A' * 40, font_size='small')]), {})
        self.assertEqual(len(normal.native_text), 2)
        self.assertEqual(len(small.native_text), 1)
        self.assertLess(small.height, normal.height)
        self.assertEqual(small.native_text[0][1] - small.native_text[0][0], 13)
        wrapped, _ = render_receipt(Receipt(blocks=[Text(id='t', text='A' * 41, font_size='small')]), {})
        self.assertEqual(len(wrapped.native_text), 2)
        self.assertIn(b'A' * 40 + b'\n', wrapped.native_text[0][2])
        self.assertIn(b'A\n', wrapped.native_text[1][2])

    def test_small_footer_fits_more_items_on_one_line_and_preserves_totals(self):
        footer = Footer(id='f', font_size='small', items=[Item(label='A' * 25, price='1.25')],
                        date='08/09/2026', reference='Guest', text='THANK YOU')
        restored = Receipt.model_validate_json(Receipt(blocks=[footer]).model_dump_json())
        self.assertEqual(restored.blocks[0].font_size, 'small')
        small, _ = render_receipt(restored, {})
        normal, _ = render_receipt(Receipt(blocks=[footer.model_copy(update={'font_size':'normal'})]), {})
        self.assertLess(small.height, normal.height)
        item_run = small.native_text[0][2]
        self.assertIn(b'1 x ' + b'A' * 25, item_run)
        self.assertIn(b'$1.25\n', item_run)
        self.assertEqual(len(item_run.split(b'1 x ', 1)[1].split(b'\n', 1)[0]) + 4, 40)
        for _, _, raw in small.native_text:
            self.assertIn(b'\x1bM\x01', raw)
        stream = b''.join(_encode_prepared(small, 1, 16))
        for text in [b'TOTAL', b'$1.25', b'08/09/2026', b'REF: Guest', b'THANK YOU']:
            self.assertIn(text, stream)

    def test_small_does_not_shrink_custom_header_artwork(self):
        normal, _ = render_receipt(Receipt(blocks=[Header(id='h', title='ARTWORK')]), {})
        small, _ = render_receipt(Receipt(blocks=[Header(id='h', title='ARTWORK', font_size='small')]), {})
        self.assertEqual(normal.preview_png, small.preview_png)
        small_native, _ = render_receipt(Receipt(blocks=[Header(id='h', title='TITLE',
                                                               subtitle='Subtitle', title_font='native', font_size='small')]), {})
        self.assertEqual(len(small_native.native_text), 2)
        for _, _, raw in small_native.native_text:
            self.assertIn(b'\x1bM\x01', raw)
            self.assertIn(b'\x1ba\x01', raw)

    def test_small_selection_does_not_leak_to_next_normal_or_large_section(self):
        prepared, _ = render_receipt(Receipt(blocks=[Text(id='s', text='SMALL', font_size='small'),
            Text(id='n', text='NORMAL'), Text(id='l', text='LARGE', font_size='large')]), {})
        small, normal, large = [run[2] for run in prepared.native_text]
        self.assertIn(b'\x1bM\x01', small)
        self.assertNotIn(b'\x1bM\x01', normal)
        self.assertNotIn(b'\x1bM\x01', large)
        self.assertIn(b'\x1b!0', large)

    def test_controls_rejected(self):
        for text in ['bad\x1b@', 'bad\x00', 'bad\r', 'bad\x7f']:
            with self.assertRaises(ValueError):
                encode_native_text([text])
