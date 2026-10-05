"""Local JPEG inbox. Camera transfer is handled by external tethering software."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from .imaging import load_source

MAX_IMAGE = 20 * 1024 * 1024
JPEG_EXTENSIONS = {'.jpg', '.jpeg', '.jpe', '.jfif', '.jif', '.jfi'}


class Inbox:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pending = {}
        self.error = ''
        self.stop_event = threading.Event()
        self.thread = None
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, folder TEXT, enabled INTEGER);
                INSERT OR IGNORE INTO settings VALUES (1, '', 0);
                CREATE TABLE IF NOT EXISTS seen (path TEXT PRIMARY KEY, signature TEXT);
                CREATE TABLE IF NOT EXISTS photos (
                    id TEXT PRIMARY KEY, digest TEXT UNIQUE, name TEXT, imported REAL, size INTEGER);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'inbox.sqlite3')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def signature(path):
        st = path.stat()
        return json.dumps([st.st_size, st.st_mtime_ns])

    @staticmethod
    def files(folder):
        return sorted(p for p in folder.iterdir() if not p.is_symlink() and p.is_file()
                      and p.suffix.lower() in JPEG_EXTENSIONS)

    def configure(self, folder: str, enabled: bool, import_existing: bool = False):
        # Finder/terminal paths are often pasted with surrounding quotes or spaces.
        folder = folder.strip()
        if len(folder) >= 2 and folder[0] == folder[-1] and folder[0] in ('"', "'"):
            folder = folder[1:-1]
        path = Path(folder).expanduser().resolve() if folder else None
        if enabled and path is None:
            raise ValueError('Choose a folder first.')
        if path is not None and not path.is_dir():
            raise ValueError('Folder does not exist or is not a directory.')
        if path is not None and (path.is_relative_to(self.root.resolve()) or self.root.resolve().is_relative_to(path)):
            raise ValueError('Choose a camera inbox outside Receipter storage.')
        with self.lock, self.connect() as db:
            old_folder = db.execute('SELECT folder FROM settings WHERE id=1').fetchone()[0]
            # Baseline a newly selected folder, so existing files require explicit import.
            if path is not None and str(path) != old_folder:
                for file in self.files(path):
                    db.execute('INSERT OR REPLACE INTO seen VALUES (?, ?)', (str(file), self.signature(file)))
            if import_existing and path is not None:
                for file in self.files(path):
                    db.execute('DELETE FROM seen WHERE path=?', (str(file),))
            db.execute('UPDATE settings SET folder=?, enabled=? WHERE id=1',
                       (str(path) if path else '', int(enabled)))
            self.pending.clear()
            self.error = ''
        return self.status()

    def status(self):
        with self.lock, self.connect() as db:
            folder, enabled = db.execute('SELECT folder, enabled FROM settings WHERE id=1').fetchone()
            count = db.execute('SELECT COUNT(*) FROM photos').fetchone()[0]
            return dict(folder=folder, enabled=bool(enabled), count=count, error=self.error)

    def photos(self, limit=100, offset=0):
        with self.lock, self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                'SELECT id,name,imported,size FROM photos ORDER BY imported DESC,id DESC LIMIT ? OFFSET ?',
                (limit, offset))]

    def scan(self):
        with self.lock, self.connect() as db:
            folder, enabled = db.execute('SELECT folder,enabled FROM settings WHERE id=1').fetchone()
            if not enabled:
                return
            files = self.files(Path(folder))
            present = set()
            self.error = ''
            for path in files:
                key = str(path)
                present.add(key)
                try:
                    sig = self.signature(path)
                except FileNotFoundError:
                    self.pending.pop(key, None)
                    continue  # Transfers may be renamed/deleted between listing and stat.
                except OSError as exc:
                    self.error = f'{path.name}: {exc}'
                    continue
                row = db.execute('SELECT signature FROM seen WHERE path=?', (key,)).fetchone()
                if row and row[0] == sig:
                    continue
                if self.pending.get(key) != sig:
                    self.pending[key] = sig
                    continue  # Require two scans with unchanged size/mtime.
                try:
                    if path.stat().st_size > MAX_IMAGE:
                        raise ValueError('JPEG exceeds 20 MB')
                    with path.open('rb') as source:
                        raw = source.read(MAX_IMAGE + 1)
                    if len(raw) > MAX_IMAGE:
                        raise ValueError('JPEG exceeds 20 MB')
                    if self.signature(path) != sig:
                        self.pending.pop(key, None)
                        continue
                    digest = hashlib.sha256(raw).hexdigest()
                    if not db.execute('SELECT 1 FROM photos WHERE digest=?', (digest,)).fetchone():
                        with Image.open(io.BytesIO(raw)) as image:
                            if image.format != 'JPEG':
                                raise ValueError('Not a JPEG')
                        working = load_source(raw).convert('RGB')
                        thumb = working.copy()
                        thumb.thumbnail((320, 320), Image.Resampling.LANCZOS)
                        photo_id = uuid.uuid4().hex
                        original = self.root / f'{photo_id}.jpg'
                        thumbnail = self.root / f'{photo_id}.thumb.jpg'
                        working_path = self.root / f'{photo_id}.working.jpg'
                        try:
                            original.write_bytes(raw)
                            working.save(working_path, 'JPEG', quality=90, optimize=True)
                            thumb.save(thumbnail, 'JPEG', quality=85)
                            db.execute('INSERT INTO photos VALUES (?,?,?,?,?)',
                                       (photo_id, digest, path.name, time.time(), len(raw)))
                        except Exception:
                            original.unlink(missing_ok=True)
                            thumbnail.unlink(missing_ok=True)
                            working_path.unlink(missing_ok=True)
                            raise
                    db.execute('INSERT OR REPLACE INTO seen VALUES (?,?)', (key, sig))
                    self.pending.pop(key, None)
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    # Retry invalid/incomplete images: a paused transfer may resume later.
                    self.error = f'{path.name}: {exc}'
            self.pending = {key: sig for key, sig in self.pending.items() if key in present}

    def start(self):
        def run():
            while not self.stop_event.is_set():
                try:
                    self.scan()
                except Exception as exc:
                    with self.lock:
                        self.error = str(exc)
                self.stop_event.wait(2)
        self.thread = threading.Thread(target=run, name='jpeg-inbox', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()


class FolderSettings(BaseModel):
    folder: str
    enabled: bool = True
    import_existing: bool = False


router = APIRouter(prefix='/api/inbox')


def inbox(request: Request) -> Inbox:
    return request.app.state.inbox


@router.get('')
def status(request: Request):
    return inbox(request).status()


@router.put('/settings')
def configure(settings: FolderSettings, request: Request):
    try:
        return inbox(request).configure(**settings.model_dump())
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/photos')
def photos(request: Request, offset: int = 0):
    return inbox(request).photos(offset=max(0, offset))


@router.get('/photos/{photo_id}/{kind}')
def image(photo_id: str, kind: str, request: Request):
    store = inbox(request)
    if kind not in ('original', 'thumbnail', 'working'):
        raise HTTPException(404)
    with store.lock, store.connect() as db:
        row = db.execute('SELECT name FROM photos WHERE id=?', (photo_id,)).fetchone()
    if row is None:
        raise HTTPException(404)
    if kind == 'working':
        path = store.root / f'{photo_id}.working.jpg'
        # Existing catalogues predate working copies. Generate one on first use.
        with store.lock:
            if not path.exists():
                try:
                    source = load_source((store.root / f'{photo_id}.jpg').read_bytes()).convert('RGB')
                    source.save(path, 'JPEG', quality=90, optimize=True)
                except (ValueError, OSError) as exc:
                    path.unlink(missing_ok=True)
                    raise HTTPException(400, 'Could not prepare the saved photo') from exc
    else:
        path = store.root / (f'{photo_id}.jpg' if kind == 'original' else f'{photo_id}.thumb.jpg')
    return FileResponse(path, media_type='image/jpeg', filename=row[0] if kind != 'thumbnail' else None)


def storage_path():
    return Path(os.getenv('RECEIPTER_DATA_DIR', str(Path.home() / '.receipter'))).expanduser() / 'inbox'
