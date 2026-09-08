import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from receipter import printer
from receipter.escpos import PARTIAL_CUT, encode_column_image, encode_column_image_parts, encode_tiny_image_test
from receipter.imaging import BLACK, calibration_image, tiny_test_image
from receipter.profile import PROFILE_NAME, printer_profile


class EncodingTests(unittest.TestCase):
    def test_working_ascii_payload_is_unchanged(self):
        self.assertEqual(printer.ASCII_DIAGNOSTIC, b'0123456789\nHELLO WORLD\n\n\n\n')
        self.assertTrue(all(v == 10 or 32 <= v <= 126 for v in printer.ASCII_DIAGNOSTIC))

    def test_cut_matches_library_partial_cut(self):
        from escpos.printer import Dummy
        p = Dummy(profile=printer_profile())
        p.cut(mode='PART')
        self.assertTrue(p.output.endswith(PARTIAL_CUT))
        self.assertEqual(PARTIAL_CUT, b'\x1dV\x01')

    def test_tiny_image_has_exactly_two_decodable_8_pin_bands(self):
        job = encode_tiny_image_test()
        image = tiny_test_image().colors
        prefix = b'TINY IMAGE\n\x1b3\x10'
        self.assertTrue(job.startswith(prefix))
        offset = len(prefix)
        for y in (0, 8):
            self.assertEqual(job[offset:offset + 5], b'\x1b*\x00\x20\x00')
            offset += 5
            for x, value in enumerate(job[offset:offset + 32]):
                for bit in range(8):
                    self.assertEqual(bool(value & (128 >> bit)), image.getpixel((x, y + bit)) == BLACK)
            offset += 32
            self.assertEqual(job[offset:offset + 1], b'\n')
            offset += 1
        self.assertEqual(job[offset:], b'\x1b2\n\n\n\n')
        self.assertLess(len(job), 128)
        self.assertEqual(image.size, (32, 16))
        self.assertEqual(set(image.tobytes()), {0, 1})
        self.assertTrue(tiny_test_image().preview_png.startswith(b'\x89PNG'))

    def test_tiny_image_matches_library_byte_for_byte(self):
        from escpos.printer import Dummy
        p = Dummy(profile=printer_profile())
        p.image(tiny_test_image().colors.convert('RGB'), impl='bitImageColumn',
                high_density_vertical=False, high_density_horizontal=False)
        self.assertEqual(encode_tiny_image_test(), b'TINY IMAGE\n' + p.output + b'\n' * 4)

    def test_full_calibration_encoding_and_guards(self):
        image = calibration_image(200).colors
        job = encode_column_image(image)
        self.assertTrue(job.startswith(b'\x1b=\x01\x1b@'))
        self.assertIn(b'\x1b*\x01\xc8\x00', job)
        self.assertEqual(job.count(b'\x1bJ\x10'), 16)
        with self.assertRaises(ValueError):
            encode_column_image(image, line_spacing=255)
        with self.assertRaises(ValueError):
            encode_column_image(calibration_image(400).colors, density_mode=0)

    def test_band_parts_have_complete_headers_payloads_and_feed(self):
        image = calibration_image(400).colors
        parts = encode_column_image_parts(image, trailing_lines=8)
        self.assertEqual(len(parts), 18)  # setup, 16 bands, footer
        self.assertEqual(b''.join(parts), encode_column_image(image, trailing_lines=8))
        for part in parts[1:-1]:
            self.assertLessEqual(len(part), 825)
            offset = 0
            while part[offset:offset + 2] == b'\x1br':
                self.assertIn(part[offset + 2], (0, 1))
                offset += 3
                self.assertEqual(part[offset:offset + 3], b'\x1b*\x01')
                width = int.from_bytes(part[offset + 3:offset + 5], 'little')
                self.assertEqual(width, 400)
                offset += 5 + width
                self.assertEqual(part[offset:offset + 3], b'\x1bJ\x00')
                offset += 3
            self.assertEqual(part[offset:], b'\x1bJ\x10')

    def test_profile_is_private_and_supports_only_column_graphics(self):
        from escpos.capabilities import get_profile
        profile = printer_profile()
        self.assertEqual(profile.name, PROFILE_NAME)
        self.assertEqual(profile.media['width']['pixels'], 400)
        self.assertTrue(profile.supports('bitImageColumn'))
        self.assertFalse(profile.supports('bitImageRaster'))
        self.assertTrue(profile.supports('paperPartCut'))
        self.assertFalse(get_profile('TM-U220').supports('paperPartCut'))


class TransportTests(unittest.TestCase):
    def setUp(self):
        printer.resume()
        # Simulate USB only: these tests must never use real hardware or paper.
        self.find = self.enterContext(patch('receipter.printer.usb.core.find'))
        self.dispose = self.enterContext(patch('receipter.printer.usb.util.dispose_resources'))
        self.claim = self.enterContext(patch('receipter.printer.usb.util.claim_interface'))
        self.wait = self.enterContext(patch('receipter.printer._stopped.wait', return_value=False))
        self.device = self.find.return_value = Mock()
        self.device.write.side_effect = lambda endpoint, data, timeout: len(data)

    def tearDown(self):
        printer.resume()

    def test_default_transport_is_buffered_without_reset_or_pacing(self):
        for job in (printer.ASCII_DIAGNOSTIC, printer.ASCII_DIAGNOSTIC + PARTIAL_CUT,
                    encode_tiny_image_test()):
            self.device.reset_mock()
            written = printer.send_raw(job)
            parts = [call.args[1] for call in self.device.write.call_args_list]
            self.assertEqual(written, len(job))
            self.assertEqual(b''.join(parts), job)
            self.assertTrue(all(1 <= len(part) <= 1024 for part in parts))
            self.assertEqual(len(parts), 1)
            self.assertTrue(all(c.kwargs['timeout'] == 5000 for c in self.device.write.call_args_list))
            self.device.reset.assert_not_called()
            self.device.set_configuration.assert_not_called()
            self.device.get_active_configuration.assert_called_once()
        self.wait.assert_not_called()
        self.assertEqual(self.claim.call_count, 3)
        self.assertEqual(self.dispose.call_count, 3)

    def test_packet_experiment_changes_only_write_boundaries(self):
        job = encode_tiny_image_test()
        self.assertEqual(printer.send_raw(job, chunk_size=8), len(job))
        writes = self.device.write.call_args_list
        self.assertEqual(b''.join(c.args[1] for c in writes), job)
        self.assertTrue(all(1 <= len(c.args[1]) <= 8 for c in writes))
        self.device.reset.assert_not_called()
        self.device.set_configuration.assert_not_called()
        self.assertTrue(all(c.args == (0.1,) for c in self.wait.call_args_list))

    def test_invalid_write_size_rejected_before_usb(self):
        for size in (0, 2, 256):
            with self.assertRaises(ValueError):
                printer.send_raw(b'ABC', chunk_size=size)
        self.find.assert_not_called()

    def test_packet_experiment_remains_cancellable(self):
        def write(endpoint, data, timeout):
            printer.interrupt()
            return len(data)
        self.device.write.side_effect = write
        with self.assertRaises(printer.PrintStopped):
            printer.send_raw(encode_tiny_image_test(), chunk_size=8)
        self.assertEqual(self.device.write.call_count, 1)
        self.assertEqual(len(self.device.write.call_args.args[1]), 8)
        self.assertFalse(printer._usb_lock.locked())

    def test_no_reset_path_is_used_even_for_parts(self):
        printer.send_raw([b'ABC', b'\n'])
        self.assertEqual(b''.join(c.args[1] for c in self.device.write.call_args_list), b'ABC\n')
        self.device.reset.assert_not_called()

    def test_image_bands_and_finishing_are_separate_complete_writes(self):
        parts = encode_column_image_parts(calibration_image(400).colors, trailing_lines=8) + [PARTIAL_CUT]
        printer.send_raw(parts)
        self.assertEqual([c.args[1] for c in self.device.write.call_args_list], parts)
        self.wait.assert_not_called()

    def test_oversize_and_empty_rejected_before_usb(self):
        for data in (b'', [], b'x' * (printer.MAX_JOB_BYTES + 1)):
            with self.assertRaises(ValueError):
                printer.send_raw(data)
        self.find.assert_not_called()

    def test_full_calibration_is_no_longer_rejected_at_512_bytes(self):
        job = encode_column_image(calibration_image(200).colors)
        self.assertGreater(len(job), 512)
        self.assertEqual(printer.send_raw(job), len(job))
        self.assertEqual(b''.join(c.args[1] for c in self.device.write.call_args_list), job)
        self.wait.assert_not_called()

    def test_long_receipt_streams_in_order_without_sleeps(self):
        job = b'RECEIPT LINE 0123456789\n' * 1000 + PARTIAL_CUT
        self.assertEqual(printer.send_raw(job), len(job))
        chunks = [c.args[1] for c in self.device.write.call_args_list]
        self.assertEqual(b''.join(chunks), job)
        self.assertTrue(all(len(c) == 1024 for c in chunks[:-1]))
        self.wait.assert_not_called()

    def test_explicit_slow_text_fallback_is_preserved(self):
        printer.send_raw(printer.ASCII_DIAGNOSTIC, chunk_size=1)
        self.assertEqual(self.device.write.call_count, len(printer.ASCII_DIAGNOSTIC))
        self.assertTrue(all(c.args == (0.1,) for c in self.wait.call_args_list))
        self.assertTrue(all(c.kwargs['timeout'] == 500 for c in self.device.write.call_args_list))

    def test_buffered_stop_discards_remaining_blocks_and_cut(self):
        def write(endpoint, data, timeout):
            printer.interrupt()
            return len(data)
        self.device.write.side_effect = write
        with self.assertRaises(printer.PrintStopped):
            printer.send_raw(b'x' * 4096 + PARTIAL_CUT)
        self.device.write.assert_called_once_with(printer.DEFAULT_OUT_ENDPOINT, b'x' * 1024, timeout=5000)
        self.assertFalse(printer._usb_lock.locked())

    def test_usb_timeout_latches_stop_without_resending_uncertain_bytes(self):
        self.device.write.side_effect = printer.usb.core.USBTimeoutError('partial transfer unknown')
        with self.assertRaises(printer.usb.core.USBTimeoutError):
            printer.send_raw(b'x' * 4096)
        self.assertEqual(self.device.write.call_count, 1)
        self.assertTrue(printer.print_state()['stopped'])

    def test_stop_discards_remaining_bytes_and_cut(self):
        count = 0
        def write(endpoint, data, timeout):
            nonlocal count
            count += len(data)
            if count == len(printer.ASCII_DIAGNOSTIC):
                printer.interrupt()
            return len(data)
        self.device.write.side_effect = write
        with self.assertRaises(printer.PrintStopped):
            printer.send_raw(printer.ASCII_DIAGNOSTIC + PARTIAL_CUT, chunk_size=1)
        sent = b''.join(c.args[1] for c in self.device.write.call_args_list)
        self.assertEqual(sent, printer.ASCII_DIAGNOSTIC)
        self.assertTrue(printer.print_state()['stopped'])
        self.assertFalse(printer._usb_lock.locked())

    def test_short_write_latches_stop_without_retry(self):
        self.device.write.side_effect = lambda *a, **kw: 0
        with self.assertRaises(RuntimeError):
            printer.send_raw(b'ABC')
        self.assertEqual(self.device.write.call_count, 1)
        self.assertTrue(printer.print_state()['stopped'])

    def test_old_requests_stay_cancelled_after_resume(self):
        token = printer.job_token()
        printer.interrupt()
        printer.resume()
        with self.assertRaises(printer.PrintStopped):
            printer.send_raw(b'old', token=token)
        self.find.assert_not_called()

    def test_status_does_not_access_usb_during_print(self):
        def write(endpoint, data, timeout):
            self.find.reset_mock()
            state = printer.target_status()
            self.assertTrue(state['printing'])
            self.assertTrue(state['usb_detection_cached'])
            self.find.assert_not_called()
            return len(data)
        self.device.write.side_effect = write
        printer.send_raw(b'Hello\n')

    def test_no_queue_and_stop_does_not_wait_for_usb(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def write(endpoint, data, timeout):
            entered.set()
            release.wait(2)
            return len(data)
        self.device.write.side_effect = write
        def send():
            try:
                printer.send_raw(b'AB')
            except printer.PrintStopped as exc:
                errors.append(exc)
        worker = threading.Thread(target=send)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(RuntimeError):
                printer.send_raw(b'queued')
            printer.interrupt()
            with self.assertRaises(RuntimeError):
                printer.resume()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.device.write.call_count, 1)


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_cut_adds_only_three_bytes_and_never_sends_image(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            await app.print_cut_test()
            send.assert_awaited_once()
            self.assertEqual(send.call_args.args[0], printer.ASCII_DIAGNOSTIC + PARTIAL_CUT)
            self.assertEqual(send.call_args.kwargs, {})

    async def test_tiny_image_endpoint_does_not_cut(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            result = await app.print_tiny_image()
            send.assert_awaited_once()
            self.assertEqual(send.call_args.args[0], encode_tiny_image_test())
            self.assertEqual(result['dots'], [32, 16])
            self.assertEqual(send.call_args.kwargs, {'chunk_size': 1024})

    async def test_packet_endpoint_uses_identical_job_and_explicit_write_size(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            await app.print_tiny_image_packet()
            self.assertEqual(send.call_args.args[0], encode_tiny_image_test())
            self.assertEqual(send.call_args.kwargs, {'chunk_size': 8})

    async def test_uploaded_images_use_buffered_default(self):
        from receipter import app
        prepared = tiny_test_image()
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            await app._print_prepared(prepared, 0, 16, printer.job_token())
            self.assertEqual(b''.join(send.call_args.args[0]), encode_column_image(prepared.colors, density_mode=0, trailing_lines=8) + PARTIAL_CUT)
            self.assertEqual(send.call_args.args[0][-1], PARTIAL_CUT)
            self.assertEqual(send.call_args.kwargs, {})

    async def test_image_finishes_with_clearance_feed_then_one_cut(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            result = await app._print_prepared(tiny_test_image(), 0, 16, printer.job_token(), feed_lines=10)
            self.assertTrue(b''.join(send.call_args.args[0]).endswith(b'\x1br\x00\x1b2' + b'\n' * 10 + PARTIAL_CUT))
            self.assertEqual(send.call_args.args[0][-1], PARTIAL_CUT)
            self.assertTrue(result['cut_command_transferred'])
            self.assertEqual(result['cut'], 'partial')
            self.assertEqual(result['feed_lines'], 10)

    async def test_image_cut_can_be_disabled_without_extra_feed(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            result = await app._print_prepared(tiny_test_image(), 0, 16, printer.job_token(), cut=False, feed_lines=0)
            self.assertEqual(b''.join(send.call_args.args[0]), encode_column_image(tiny_test_image().colors, density_mode=0, trailing_lines=0))
            self.assertEqual(result['cut'], 'none')

    async def test_invalid_clearance_rejected_before_send(self):
        from fastapi import HTTPException
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock) as send:
            for cut, feed in [(True, 0), (True, 7), (True, 21), (False, -1)]:
                with self.assertRaises(HTTPException) as error:
                    await app._print_prepared(tiny_test_image(), 0, 16, printer.job_token(), cut=cut, feed_lines=feed)
                self.assertEqual(error.exception.status_code, 400)
            send.assert_not_called()

    async def test_slow_comparison_is_explicit_only(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            await app.print_tiny_image_slow()
            self.assertEqual(send.call_args.kwargs, {'chunk_size': 1})

    async def test_text_endpoint_uses_exact_working_bytes(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            await app.print_text()
            self.assertEqual(send.call_args.args[0], printer.ASCII_DIAGNOSTIC)
            self.assertEqual(send.call_args.kwargs, {'chunk_size': 1024})

    async def test_ascii_diagnostic_retains_single_byte_fallback(self):
        from receipter import app
        with patch.object(app, '_send', new_callable=AsyncMock, return_value={}) as send:
            await app.print_ascii_diagnostic()
            self.assertEqual(send.call_args.args[0], printer.ASCII_DIAGNOSTIC)
            self.assertEqual(send.call_args.kwargs, {'chunk_size': 1})

    async def test_oversize_is_client_error(self):
        from fastapi import HTTPException
        from receipter import app
        with self.assertRaises(HTTPException) as error:
            await app._send(b'x' * (printer.MAX_JOB_BYTES + 1), printer.job_token())
        self.assertEqual(error.exception.status_code, 400)


if __name__ == '__main__':
    unittest.main()
