"""Named receipt defaults, persisted atomically alongside the photo inbox."""
from contextlib import contextmanager
import base64
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .imaging import load_source
from .receipt import Receipt

MAX_ASSET = 20 * 1024 * 1024


class Finishing(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cut: bool = True
    feed_lines: int = Field(8, ge=0, le=20)
    copies: int = Field(1, ge=1, le=10)


class Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    automatic_dates: list[str] = Field(default_factory=list, max_length=16)
    finishing: Finishing = Field(default_factory=Finishing)


class Profiles:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'profiles.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY, name TEXT, document TEXT, options TEXT, updated REAL);
                CREATE TABLE IF NOT EXISTS assets (
                    profile_id TEXT, id TEXT, name TEXT, mime TEXT, data BLOB,
                    PRIMARY KEY (profile_id, id));
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, default_id TEXT);
                INSERT OR IGNORE INTO settings VALUES (1, '');
            ''')

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def listing(self):
        with self.connect() as db:
            return {'default_id': db.execute('SELECT default_id FROM settings WHERE id=1').fetchone()[0],
                    'profiles': [dict(id=row[0], name=row[1], updated=row[2]) for row in db.execute(
                        'SELECT id,name,updated FROM profiles ORDER BY name COLLATE NOCASE,id')]}

    def get(self, profile_id):
        with self.connect() as db:
            row = db.execute('SELECT name,document,options FROM profiles WHERE id=?', (profile_id,)).fetchone()
            if row is None:
                raise KeyError(profile_id)
            assets = [dict(id=a[0], name=a[1], mime=a[2], data=base64.b64encode(a[3]).decode())
                      for a in db.execute('SELECT id,name,mime,data FROM assets WHERE profile_id=?', (profile_id,))]
            return dict(id=profile_id, name=row[0], document=json.loads(row[1]), options=json.loads(row[2]), assets=assets)

    def save(self, name, document, options, assets, profile_id='', make_default=True):
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError('Profile name must have 1–80 characters.')
        receipt = Receipt.model_validate(document)
        options = Options.model_validate(options)
        if len({block.id for block in receipt.blocks}) != len(receipt.blocks):
            raise ValueError('Profile section IDs must be unique.')
        if any(block.type == 'photo' for block in receipt.blocks):
            raise ValueError('Default profiles cannot contain camera photos.')
        if options.finishing.cut and options.finishing.feed_lines < 8:
            raise ValueError('Use at least 8 feed lines with cutting.')
        footers = {block.id for block in receipt.blocks if block.type == 'footer'}
        if not set(options.automatic_dates) <= footers:
            raise ValueError('Automatic dates must refer to footer sections.')
        referenced = {block.asset for block in receipt.blocks if block.type == 'header' and block.asset}
        if set(assets) != referenced:
            raise ValueError('Provide exactly the logos referenced by the profile.')
        if sum(len(asset['data']) for asset in assets.values()) > 60 * 1024 * 1024:
            raise ValueError('Profile logos exceed 60 MB.')
        for asset in assets.values():
            if len(asset['data']) > MAX_ASSET:
                raise ValueError('Profile logo exceeds 20 MB.')
            load_source(asset['data'])  # Reject unreadable images and unsafe SVGs before saving.
        # Automatic timestamps are regenerated on load, never baked into a default.
        for block in receipt.blocks:
            if block.id in options.automatic_dates:
                block.date = ''
        with self.connect() as db:
            if profile_id and not db.execute('SELECT 1 FROM profiles WHERE id=?', (profile_id,)).fetchone():
                raise KeyError(profile_id)
            profile_id = profile_id or uuid.uuid4().hex
            db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?)',
                       (profile_id, name, receipt.model_dump_json(), options.model_dump_json(), time.time()))
            db.execute('DELETE FROM assets WHERE profile_id=?', (profile_id,))
            db.executemany('INSERT INTO assets VALUES (?,?,?,?,?)',
                           [(profile_id, key, asset['name'], asset['mime'], asset['data']) for key, asset in assets.items()])
            if make_default:
                db.execute('UPDATE settings SET default_id=? WHERE id=1', (profile_id,))
            else:
                db.execute("UPDATE settings SET default_id='' WHERE id=1 AND default_id=?", (profile_id,))
        return {'id': profile_id, 'name': name}


router = APIRouter(prefix='/api/profiles')


@router.get('')
def listing(request: Request):
    return request.app.state.profiles.listing()


@router.get('/{profile_id}')
def get(profile_id: str, request: Request):
    try:
        return request.app.state.profiles.get(profile_id)
    except KeyError as exc:
        raise HTTPException(404, 'Profile not found') from exc


@router.post('')
async def save(request: Request, name: str = Form(...), document: str = Form(...),
               options: str = Form('{}'), profile_id: str = Form(''), make_default: bool = Form(True),
               assets: list[UploadFile] = File(default=[])):
    if len(document) > 2_000_000 or len(options) > 32_000 or len(assets) > 16:
        raise HTTPException(413, 'Profile document or asset count is too large')
    uploads = {}
    total = 0
    for asset in assets:
        raw = await asset.read(MAX_ASSET + 1)
        total += len(raw)
        if len(raw) > MAX_ASSET or total > 60 * 1024 * 1024:
            raise HTTPException(413, 'Limit: 20 MB per logo, 60 MB per profile')
        if not asset.filename or asset.filename in uploads:
            raise HTTPException(400, 'Logo asset IDs must be unique')
        uploads[asset.filename] = dict(name=asset.filename, mime=asset.content_type or 'application/octet-stream', data=raw)
    try:
        return await run_in_threadpool(request.app.state.profiles.save, name, json.loads(document),
                                       json.loads(options), uploads, profile_id, make_default)
    except KeyError as exc:
        raise HTTPException(404, 'Profile not found') from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
