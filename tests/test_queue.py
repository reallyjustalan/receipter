import asyncio
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from receipter.app import app
from receipter import printer
from receipter.queue import PrintQueue


class QueueStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = PrintQueue(self.root)

    def add(self, key='a', copies=3):
        return self.queue.add(key, key, [b'band one', b'band two', b'cut'], b'png', copies)

    def test_survives_restart_and_preserves_boundaries(self):
        job = self.add()
        restarted = PrintQueue(self.root)
        self.assertTrue(restarted.listing()['paused'])
        self.assertEqual(restarted.preview(job), b'png')
        self.assertIsNone(restarted.claim())
        restarted.pause(False)
        self.assertEqual(restarted.claim(), (job, [b'band one', b'band two', b'cut'] * 3))

    def test_crashed_transfer_retained_as_uncertain_and_paused(self):
        job = self.add()
        self.queue.pause(False)
        self.queue.claim()
        restarted = PrintQueue(self.root)
        self.assertEqual(restarted.listing()['jobs'][0]['state'], 'interrupted')
        restarted.pause(False)
        self.assertIsNone(restarted.claim())  # Never automatically retry.
        restarted.action(job, 'reprint', 1)
        self.assertTrue(restarted.listing()['paused'])
        restarted.pause(False)
        self.assertEqual(len(restarted.claim()[1]), 3)

    def test_confirm_is_only_way_to_advance_and_history_is_retained(self):
        first = self.add()
        second = self.add('b')
        self.queue.pause(False)
        self.queue.claim()
        with self.assertRaises(ValueError):
            self.queue.action(first, 'confirm')
        self.queue.finish(first, True, 'USB accepted')
        self.assertIsNone(self.queue.claim())
        with self.assertRaises(ValueError):
            self.queue.action(second, 'confirm')
        self.queue.action(first, 'confirm')
        self.assertEqual(self.queue.claim()[0], second)
        self.assertEqual(self.queue.listing()['jobs'][0]['state'], 'confirmed')
        self.assertEqual(self.queue.preview(first), b'png')

    def test_failed_job_and_waiting_jobs_are_retained(self):
        first = self.add()
        self.add('b')
        self.queue.pause(False)
        self.queue.claim()
        self.queue.finish(first, False, 'timeout')
        self.assertTrue(self.queue.listing()['paused'])
        self.assertEqual(len(self.queue.listing()['jobs']), 2)

    def test_reprint_history_creates_new_entry_not_mutates_history(self):
        job = self.add()
        self.queue.pause(False)
        self.queue.claim()
        self.queue.finish(job, True, 'USB accepted')
        self.queue.action(job, 'confirm')
        self.queue.action(job, 'reprint', 2)
        jobs = self.queue.listing()['jobs']
        self.assertEqual([j['state'] for j in jobs], ['confirmed', 'waiting'])
        self.assertNotEqual(jobs[1]['id'], job)
        self.assertEqual(jobs[1]['send_copies'], 2)

    def test_idempotent_add_and_explicit_delete(self):
        job = self.add()
        self.assertEqual(self.add(), job)
        self.assertEqual(len(self.queue.listing()['jobs']), 1)
        self.queue.action(job, 'delete')
        self.assertEqual(self.queue.listing()['jobs'], [])

    def test_cannot_delete_or_resend_during_transfer(self):
        job = self.add()
        self.queue.pause(False)
        self.queue.claim()
        for action in ['delete', 'reprint', 'confirm']:
            with self.assertRaises(ValueError):
                self.queue.action(job, action)


class QueueAPITests(unittest.TestCase):
    def test_save_refresh_restart_confirm_and_reprint_without_usb(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'RECEIPTER_DATA_DIR': root}), \
                patch('receipter.app.send_raw', side_effect=lambda parts, **kw: sum(map(len, parts))) as send:
            printer.resume()
            with TestClient(app) as client:
                preview = client.post('/api/receipt-preview', data={'document': '{"blocks":[{"type":"text","id":"t","text":"Guest A"}]}'}).json()
                form = {'snapshot': preview['token'], 'request_id': 'save-a', 'label': 'Guest A',
                        'copies': '2', 'cut': 'true', 'feed_lines': '8'}
                saved = client.post('/api/queue', data=form)
                self.assertEqual(saved.status_code, 200, saved.text)
                job = saved.json()['id']
                self.assertEqual(client.post('/api/queue', data=form).json()['id'], job)
                self.assertEqual(len(client.get('/api/queue').json()['jobs']), 1)
                self.assertEqual(client.get(f'/api/queue/{job}/preview').status_code, 200)
                self.assertFalse(send.called)
            with TestClient(app) as client:
                state = client.get('/api/queue').json()
                self.assertTrue(state['paused'])
                self.assertEqual(state['jobs'][0]['id'], job)
                self.assertEqual(client.post('/api/queue', data={**form, 'snapshot':'expired'}).json()['id'], job)
                self.assertEqual(client.post('/api/queue/start').status_code, 200)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    state = client.get('/api/queue').json()
                    if state['jobs'][0]['state'] == 'awaiting_confirmation':
                        break
                    time.sleep(0.05)
                self.assertEqual(state['jobs'][0]['state'], 'awaiting_confirmation')
                self.assertEqual(send.call_count, 1)
                self.assertEqual(client.post(f'/api/queue/{job}/action', data={'action':'confirm'}).status_code, 200)
                self.assertEqual(client.post(f'/api/queue/{job}/action', data={'action':'reprint', 'copies':'1'}).status_code, 200)
                state = client.get('/api/queue').json()
                self.assertTrue(state['paused'])
                self.assertEqual([j['state'] for j in state['jobs']], ['confirmed', 'waiting'])
                # STOP retains the entries and Resume alone cannot start sending.
                client.post('/api/interrupt')
                self.assertEqual(client.post('/api/queue/start').status_code, 409)
                client.post('/api/resume')
                self.assertTrue(client.get('/api/queue').json()['paused'])
                self.assertEqual(send.call_count, 1)

    def test_worker_can_save_next_receipt_during_transfer(self):
        async def slow_send(*args, **kwargs):
            await asyncio.sleep(0.5)
            return {'message': 'USB accepted; check paper'}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'RECEIPTER_DATA_DIR': root}), \
                patch('receipter.app._send', side_effect=slow_send):
            printer.resume()
            with TestClient(app) as client:
                q = app.state.queue
                first = q.add('first', 'first', [b'a'], b'png', 1)
                client.post('/api/queue/start')
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and q.listing()['jobs'][0]['state'] != 'sending':
                    time.sleep(0.02)
                self.assertEqual(q.listing()['jobs'][0]['state'], 'sending')
                preview = client.post('/api/receipt-preview', data={'document':'{"blocks":[{"type":"text","id":"b","text":"Next guest"}]}'}).json()
                response = client.post('/api/queue', data={'snapshot':preview['token'], 'request_id':'next'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(q.listing()['jobs']), 2)
                time.sleep(0.6)
                self.assertEqual([j['state'] for j in q.listing()['jobs']], ['awaiting_confirmation','waiting'])
                self.assertEqual(q.listing()['jobs'][0]['id'], first)


if __name__ == '__main__':
    unittest.main()
