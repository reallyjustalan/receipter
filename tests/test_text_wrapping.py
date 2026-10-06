from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from receipter.app import _encode_prepared
from receipter.profiles import Profiles
from receipter.receipt import Receipt, Text, render_receipt, wrap_text


class TextWrappingTests(unittest.TestCase):
    def test_whole_word_and_dash_choices(self):
        self.assertEqual(wrap_text('hello elephant', 10, 'word'), ['hello', 'elephant'])
        self.assertEqual(wrap_text('hello elephant', 10, 'hyphenate'), ['hello ele-', 'phant'])
        self.assertEqual(wrap_text('The quick brown fox', 10, 'word'), ['The quick', 'brown fox'])
        self.assertEqual(wrap_text('The quick brown fox', 10, 'hyphenate'), ['The quick', 'brown fox'])

    def test_oversized_word_always_fits_and_dashes_reserve_a_column(self):
        source = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        self.assertEqual(wrap_text(source, 10, 'word'), ['ABCDEFGHIJ', 'KLMNOPQRST', 'UVWXYZ'])
        lines = wrap_text(source, 10, 'hyphenate')
        self.assertEqual(lines, ['ABCDEFGHI-', 'JKLMNOPQR-', 'STUVWXYZ'])
        self.assertEqual(''.join(line.removesuffix('-') for line in lines), source)
        self.assertTrue(all(len(line) <= 10 for line in lines))

    def test_manual_blank_lines_and_unicode_normalization(self):
        for mode in ['word', 'hyphenate']:
            self.assertEqual(wrap_text('one\n\ntwo\n', 10, mode), ['one', '', 'two', ''])
            self.assertEqual(wrap_text('one\r\ntwo', 10, mode), ['one', 'two'])
            self.assertEqual(wrap_text('“hello”', 10, mode), ['"hello"'])
            self.assertEqual(wrap_text('', 10, mode), [''])
            self.assertEqual(wrap_text('one  two', 10, mode), ['one  two'])

    def test_boundary_spaces_existing_dashes_and_one_column_remaining(self):
        self.assertEqual(wrap_text('123456789 rest', 10, 'hyphenate'), ['123456789', 'rest'])
        self.assertEqual(wrap_text('12345678 rest', 10, 'hyphenate'), ['12345678', 'rest'])
        self.assertEqual(wrap_text('123456789-rest', 10, 'hyphenate'), ['123456789-', 'rest'])
        self.assertEqual(wrap_text('12345678-rest', 10, 'hyphenate'), ['12345678-', 'rest'])
        self.assertEqual(wrap_text('1234567890    rest', 10, 'word'), ['1234567890', 'rest'])

    def test_selected_font_controls_wrap_width_and_native_commands_match_preview(self):
        for size, columns in [('small', 40), ('normal', 30), ('large', 15)]:
            source = 'A' * (columns - 5) + ' elephant'
            for mode in ['word', 'hyphenate']:
                with self.subTest(size=size, mode=mode):
                    block = Text(id='t', text=source, font_size=size, wrap_mode=mode)
                    prepared, _ = render_receipt(Receipt(blocks=[block]), {})
                    expected = wrap_text(source, columns, mode)
                    self.assertEqual(len(prepared.native_text), len(expected))
                    for line, (start, end, raw) in zip(expected, prepared.native_text):
                        self.assertIn(line.encode() + b'\n', raw)
                        self.assertEqual(end - start, 26 if size == 'large' else 13)
                    self.assertEqual(block.text, source)

    def test_existing_documents_keep_character_wrapping(self):
        text = 'A' * 25 + ' elephant'
        legacy = Text(id='t', text=text)
        self.assertEqual(legacy.wrap_mode, 'character')
        prepared, _ = render_receipt(Receipt(blocks=[legacy]), {})
        self.assertIn(b'A' * 25 + b' elep\n', prepared.native_text[0][2])
        self.assertIn(b'hant\n', prepared.native_text[1][2])

    def test_profiles_persist_mode_but_queue_snapshot_stays_frozen(self):
        block = Text(id='t', text='A' * 25 + ' elephant', wrap_mode='hyphenate')
        document = Receipt(blocks=[block])
        prepared, _ = render_receipt(document, {})
        original = _encode_prepared(prepared, 1, 16)
        with tempfile.TemporaryDirectory() as root:
            store = Profiles(Path(root))
            saved = store.save('Wrapped text', document.model_dump(mode='json'), {}, {})
            loaded = Profiles(Path(root)).get(saved['id'])
            self.assertEqual(loaded['document']['blocks'][0]['wrap_mode'], 'hyphenate')
            restored, _ = render_receipt(Receipt.model_validate(loaded['document']), {})
            self.assertEqual(_encode_prepared(restored, 1, 16), original)
        block.wrap_mode = 'word'
        block.text = 'Edited later'
        self.assertEqual(_encode_prepared(prepared, 1, 16, copies=2), original * 2)

    def test_invalid_modes_rejected(self):
        with self.assertRaises(ValidationError):
            Text(id='t', wrap_mode='random')
        with self.assertRaises(ValueError):
            wrap_text('text', 1, 'hyphenate')
