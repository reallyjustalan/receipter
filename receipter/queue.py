"""Durable operator-confirmed queue. Saved bytes preserve USB band boundaries."""
import base64
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid


class PrintQueue:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'queue.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE, label TEXT,
                    created REAL, state TEXT, copies INTEGER, send_copies INTEGER,
                    parts TEXT, preview BLOB, detail TEXT);
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, paused INTEGER);
                INSERT OR IGNORE INTO settings VALUES (1, 1);
            ''')
            db.execute('UPDATE settings SET paused=1')
            db.execute("UPDATE jobs SET state='interrupted', detail='Server stopped during sending. Check paper before reprinting.' WHERE state='sending'")

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path)
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA fullfsync=ON')
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def add(self, request_id, label, parts, preview, copies):
        with self.connect() as db:
            old = db.execute('SELECT id FROM jobs WHERE request_id=?', (request_id,)).fetchone()
            if old:
                return old['id']
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (job_id, request_id, label, time.time(), 'waiting', copies, copies,
                        json.dumps([base64.b64encode(p).decode() for p in parts]), preview, 'Saved; not sent.'))
            return job_id

    def listing(self):
        with self.connect() as db:
            return {'paused': bool(db.execute('SELECT paused FROM settings').fetchone()[0]),
                    'path': str(self.path), 'jobs': [dict(r) for r in db.execute(
                        'SELECT id,label,created,state,copies,send_copies,detail FROM jobs ORDER BY created,rowid')]}

    def pause(self, paused=True):
        with self.connect() as db:
            db.execute('UPDATE settings SET paused=?', (int(paused),))

    def claim(self):
        with self.connect() as db:
            if db.execute('SELECT paused FROM settings').fetchone()[0]:
                return None
            row = db.execute("SELECT * FROM jobs WHERE state!='confirmed' ORDER BY created,rowid LIMIT 1").fetchone()
            if row is None or row['state'] != 'waiting':
                return None
            db.execute("UPDATE jobs SET state='sending',detail='Sending; physical output unverified.' WHERE id=?", (row['id'],))
            return row['id'], [base64.b64decode(p) for p in json.loads(row['parts'])] * row['send_copies']

    def finish(self, job_id, success, detail):
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,detail=? WHERE id=?',
                       ('awaiting_confirmation' if success else 'interrupted', detail, job_id))
            if not success:
                db.execute('UPDATE settings SET paused=1')

    def action(self, job_id, action, copies=None):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise ValueError('Receipt not found.')
            if row['state'] == 'sending':
                raise ValueError('Wait for the active USB transfer to finish; use STOP if needed.')
            head = db.execute("SELECT id FROM jobs WHERE state!='confirmed' ORDER BY created,rowid LIMIT 1").fetchone()
            if action == 'confirm':
                if row['state'] not in ('awaiting_confirmation', 'interrupted') or not head or head['id'] != job_id:
                    raise ValueError('Only the current sent/interrupted receipt can be confirmed.')
                db.execute("UPDATE jobs SET state='confirmed',detail='Operator confirmed output.' WHERE id=?", (job_id,))
            elif action == 'reprint':
                if row['state'] not in ('awaiting_confirmation', 'interrupted', 'confirmed'):
                    raise ValueError('Receipt is already waiting.')
                if copies is None:
                    copies = row['copies']
                if not 1 <= copies <= 10:
                    raise ValueError('Choose 1–10 copies.')
                if row['state'] == 'confirmed':
                    # Create a new queue entry, preserving confirmed history.
                    new_id = uuid.uuid4().hex
                    db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (new_id, new_id, row['label'], time.time(), 'waiting', row['copies'], copies,
                                row['parts'], row['preview'], 'Reprint requested by operator.'))
                else:
                    db.execute("UPDATE jobs SET state='waiting',send_copies=?,detail='Reprint requested by operator.' WHERE id=?", (copies, job_id))
                # Reprinting always requires an explicit Start/continue.
                db.execute('UPDATE settings SET paused=1')
            elif action == 'delete':
                db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            else:
                raise ValueError('Unknown queue action.')

    def preview(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT preview FROM jobs WHERE id=?', (job_id,)).fetchone()
            return bytes(row[0]) if row else None
