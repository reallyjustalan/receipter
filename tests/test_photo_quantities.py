from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pydantic import ValidationError

from receipter.app import _encode_prepared
from receipter.profiles import Profiles
from receipter.receipt import Footer, Header, Item, Photo, Receipt, render_receipt


def photo_bytes():
    buffer = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(buffer, 'PNG')
    return buffer.getvalue()


class PhotoQuantityTests(unittest.TestCase):
    def receipt(self, count, footer=None):
        footer = footer or Footer(id='footer', items=[
            Item(label='Photos', quantity=7, quantity_mode='photos', price='0.10'),
            Item(label='Other', quantity=2, price='1.25')])
        return Receipt(blocks=[Header(id='logo', asset='image'), footer,
                              *[Photo(id=f'p{i}', asset='image', height=32) for i in range(count)]])

    def test_counts_body_sections_not_logo_assets_or_manual_quantity(self):
        for count in range(4):
            with self.subTest(count=count):
                receipt = self.receipt(count)
                prepared, _ = render_receipt(receipt, {'image':photo_bytes()})
                raw = b''.join(p[2] for p in prepared.native_text)
                if count:
                    self.assertIn(f'{count} x Photos'.encode(), raw)
                    self.assertIn(f'${count / 10:.2f}'.encode(), raw)
                else:
                    self.assertNotIn(b'Photos', raw)
                self.assertIn(b'2 x Other', raw)
                self.assertIn(f'${2.50 + count / 10:.2f}'.encode(), raw)
                self.assertEqual(receipt.blocks[1].items[0].quantity, 7)
                self.assertEqual(receipt.blocks[1].items[0].quantity_mode, 'photos')

    def test_all_font_sizes_and_multiple_automatic_items(self):
        for size in ['small', 'normal', 'large']:
            footer = Footer(id='f', font_size=size, items=[
                Item(label='A', quantity_mode='photos', price='0.10'),
                Item(label='B', quantity_mode='photos', price='0.20')])
            prepared, _ = render_receipt(self.receipt(3, footer), {'image':photo_bytes()})
            raw = b''.join(run[2] for run in prepared.native_text)
            for text in [b'3 x A', b'3 x B', b'$0.30', b'$0.60', b'$0.90']:
                self.assertIn(text, raw)

    def test_snapshot_and_copy_count_do_not_recalculate_photo_quantity(self):
        document = self.receipt(2)
        prepared, _ = render_receipt(document, {'image':photo_bytes()})
        single = _encode_prepared(prepared, 1, 16)
        document.blocks = [block for block in document.blocks if block.type != 'photo']
        batch = _encode_prepared(prepared, 1, 16, copies=3)
        self.assertEqual(batch, single * 3)
        self.assertEqual(b''.join(batch).count(b'2 x Photos'), 3)

    def test_profile_retains_mode_and_manual_fallback_without_camera_photos(self):
        with tempfile.TemporaryDirectory() as root:
            store = Profiles(Path(root))
            saved = store.save('Auto quantities', {'blocks':[Footer(id='f', items=[
                Item(label='Photos', quantity=7, quantity_mode='photos', price='0.10')]).model_dump(mode='json')]},
                {}, {})
            restored = Profiles(Path(root)).get(saved['id'])
            item = restored['document']['blocks'][0]['items'][0]
            self.assertEqual(item['quantity_mode'], 'photos')
            self.assertEqual(item['quantity'], 7)
            document = Receipt.model_validate(restored['document'])
            prepared, _ = render_receipt(document, {})
            raw = b''.join(run[2] for run in prepared.native_text)
            self.assertNotIn(b'Photos', raw)
            self.assertIn(b'$0.00', raw)

    def test_old_items_remain_manual_and_bad_modes_rejected(self):
        self.assertEqual(Item(label='Old').quantity_mode, 'manual')
        with self.assertRaises(ValidationError):
            Item(label='Bad', quantity_mode='copies')
        with self.assertRaises(ValidationError):
            Item(label='Bad', quantity=0)
