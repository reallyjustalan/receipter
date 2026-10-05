"""USB discovery portability checks; never access real hardware or print."""
import unittest
from unittest.mock import Mock, patch

from receipter import printer


class PrinterDetectionTests(unittest.TestCase):
    def device(self, vendor=0x04b8, product=0x0202):
        return Mock(idVendor=vendor, idProduct=product, iManufacturer=1, iProduct=2)

    def test_names_do_not_affect_matching(self):
        device = self.device()
        for name in ['EPSON', 'Different name on another Mac', '']:
            with patch.object(printer.usb.core, 'find', side_effect=[device, [device]]) as find, \
                    patch.object(printer.usb.util, 'get_string', return_value=name):
                status = printer.target_status()
            self.assertTrue(status['connected'])
            self.assertTrue(status['devices'][0]['is_target'])
            self.assertEqual(status['detection_error'], '')
            self.assertEqual(find.call_args_list[0].kwargs,
                             dict(idVendor=printer.DEFAULT_VENDOR_ID, idProduct=printer.DEFAULT_PRODUCT_ID))

    def test_unreadable_names_do_not_prevent_detection(self):
        device = self.device()
        with patch.object(printer.usb.core, 'find', side_effect=[device, [device]]), \
                patch.object(printer.usb.util, 'get_string', side_effect=printer.usb.core.USBError('denied')):
            status = printer.target_status()
        self.assertTrue(status['connected'])
        self.assertEqual(status['devices'][0]['product'], '(unavailable)')

    def test_missing_backend_is_actionable_and_recovers(self):
        with patch.object(printer.usb.core, 'find', side_effect=printer.usb.core.NoBackendError()):
            status = printer.target_status()
        self.assertFalse(status['connected'])
        self.assertIn('brew install libusb', status['detection_error'])
        device = self.device()
        with patch.object(printer.usb.core, 'find', side_effect=[device, []]):
            self.assertEqual(printer.target_status()['detection_error'], '')

    def test_other_epson_ids_are_reported_not_automatically_selected(self):
        with patch.object(printer.usb.core, 'find', side_effect=[None, [self.device(product=0x9999)]]), \
                patch.object(printer.usb.util, 'get_string', return_value='EPSON'):
            status = printer.target_status()
        self.assertFalse(status['connected'])
        self.assertIn('0x9999', status['detection_error'])
        self.assertFalse(status['devices'][0]['is_target'])

    def test_usb_access_error_is_actionable(self):
        with patch.object(printer.usb.core, 'find', side_effect=printer.usb.core.USBError('Access denied')):
            status = printer.target_status()
        self.assertFalse(status['connected'])
        self.assertIn('USB access failed', status['detection_error'])
