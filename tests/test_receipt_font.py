"""Canonical dot masks, not screenshot smoothing or an Epson ROM equivalence test."""
import unittest
from unittest.mock import patch

from PIL import Image

from receipter.imaging import BLACK, WHITE
from receipter.receipt import Receipt, Text, TextCanvas, render_receipt
from receipter.receipt_font import ADVANCE, CELL_HEIGHT, CELL_WIDTH, draw_text, glyph, normalize, text_width


class ReceiptFontTests(unittest.TestCase):
    def test_fixed_pitch_including_narrow_letters_and_figures(self):
        self.assertEqual(text_width('iii'), text_width('WWW'))
        self.assertEqual(text_width('111.00'), text_width('888.88'))
        self.assertEqual(text_width('AA'), ADVANCE + CELL_WIDTH)
        self.assertEqual(text_width(''), 0)

    def test_known_glyph_bits_are_not_smoothed_mirrored_or_resampled(self):
        # Upstream F, low bit is the left-hand column.
        rows = [0x7f, 0x46, 0x16, 0x1e, 0x16, 0x06, 0x0f, 0]
        mask = glyph('F')
        self.assertEqual(mask.size, (CELL_WIDTH, CELL_HEIGHT))
        for y, row in enumerate(rows):
            for x in range(8):
                self.assertEqual(bool(mask.getpixel((x, y))), bool(row & (1 << x)))
        self.assertFalse(any(mask.getpixel((x, 8)) for x in range(CELL_WIDTH)))

    def test_text_is_drawn_directly_into_the_canonical_map(self):
        canvas = TextCanvas()
        canvas.line('Fg')
        with patch('receipter.receipt.prepare_image', side_effect=AssertionError('Do not resample text')):
            dots = canvas.prepared()
            render_receipt(Receipt(blocks=[Text(id='text', text='Fg')]), {})
        self.assertEqual(dots.mode, 'P')
        self.assertEqual(set(dots.tobytes()), {BLACK, WHITE})
        expected = Image.new('P', dots.size, WHITE)
        draw_text(expected, 0, 4, 'Fg')  # Eight layout pixels -> four canonical rows.
        self.assertEqual(dots.tobytes(), expected.tobytes())
        # Descenders occupy their original eighth row, rather than being lost.
        self.assertTrue(any(dots.getpixel((ADVANCE+x, 11)) == BLACK for x in range(8)))

    def test_wrapping_centering_and_right_aligned_amounts(self):
        canvas = TextCanvas()
        canvas.line('A' * 31)
        self.assertEqual(canvas.y, 8 + 2 * 26)  # Thirty cells fit inside the margins.
        centered = TextCanvas()
        centered.line('A', center=True)
        expected = Image.new('P', centered.prepared().size, WHITE)
        draw_text(expected, (expected.width - CELL_WIDTH)//2, 4, 'A')
        self.assertEqual(centered.prepared().tobytes(), expected.tobytes())
        totals = TextCanvas()
        totals.amount('Total', '$12.00')
        right = Image.new('P', totals.prepared().size, WHITE)
        draw_text(right, 0, 4, 'Total')
        draw_text(right, right.width-text_width('$12.00'), 4, '$12.00')
        self.assertEqual(totals.prepared().tobytes(), right.tobytes())

    def test_long_labels_and_multiline_labels_never_overwrite_amounts(self):
        for label in ['A'*64, 'Photo\nstrip']:
            canvas = TextCanvas()
            canvas.amount(label, '$10.00')
            self.assertGreater(canvas.y, 34)
        with self.assertRaises(ValueError):
            TextCanvas().amount('Item', '1'*40)
        with self.assertRaises(ValueError):
            TextCanvas().amount('Item', '$1\n00')

    def test_supported_unicode_and_explicit_unsupported_error(self):
        self.assertEqual(normalize('Cafe\u0301 “today”…\r\n£2 × 3 — €6'), 'Café "today"...\n£2 × 3 -- €6')
        canvas = TextCanvas()
        canvas.line('Café £2 × 3 €6')
        self.assertIn(BLACK, canvas.prepared().tobytes())
        for text in ['你好', '\x1b', '♥']:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'does not support'):
                TextCanvas().line(text)

    def test_rule_is_one_canonical_row(self):
        canvas = TextCanvas()
        canvas.rule()
        dots = canvas.prepared()
        self.assertEqual(dots.tobytes().count(BLACK), dots.width)


if __name__ == '__main__':
    unittest.main()
