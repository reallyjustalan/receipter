from __future__ import annotations

from time import perf_counter, monotonic
from collections import OrderedDict
import base64
import asyncio
from pathlib import Path
import hashlib
import logging
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .escpos import PARTIAL_CUT, encode_column_image_parts, encode_tiny_image_test
from .imaging import CANONICAL_SCALE, calibration_image, prepare_image, tiny_test_image
from .receipt import Receipt, render_receipt
from .printer import ASCII_DIAGNOSTIC, DEFAULT_CHUNK_SIZE, PrintStopped, interrupt, job_token, resume, send_raw, target_status

app = FastAPI(title="Receipter · Photo booth")
MAX_UPLOAD = 20 * 1024 * 1024
# Freeze assets with this backend. Editing files must not expose new controls
# against an older running process (which previously ignored the cut fields).
_ROOT = Path(__file__).parent
BUILD_ID = hashlib.sha256(b"".join((_ROOT / name).read_bytes() for name in
    ("app.py", "index.html", "editor.js", "studio.js", "studio.css", "receipt.py", "receipt_font.py", "fonts/receipt-bitmap.json", "escpos.py", "imaging.py", "printer.py"))).hexdigest()[:12]
INDEX_HTML = (_ROOT / "index.html").read_text().replace("__BUILD_ID__", BUILD_ID)
EDITOR_JS = (_ROOT / "editor.js").read_text()
STUDIO_JS = (_ROOT / 'studio.js').read_text()
STUDIO_CSS = (_ROOT / 'studio.css').read_text()
# Process-local, bounded, expiring canonical snapshots. Printing never re-renders.
_snapshots = OrderedDict()
_render_slots = asyncio.Semaphore(2)
SNAPSHOT_TTL = 1800
_log = logging.getLogger("uvicorn.error")


@app.middleware("http")
async def reject_stale_print_controls(request: Request, call_next):
    if (request.method == "POST" and request.url.path.startswith("/api/print")
            and request.headers.get("X-Receipter-Build", BUILD_ID) != BUILD_ID):
        return JSONResponse({"detail": "Server updated. Refresh the page before printing."}, status_code=409)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-store"})


@app.get("/editor.js")
def editor_script() -> Response:
    return Response(EDITOR_JS, media_type="text/javascript", headers={"Cache-Control": "no-store"})


@app.get('/studio.js')
def studio_script() -> Response:
    return Response(STUDIO_JS, media_type='text/javascript', headers={'Cache-Control': 'no-store'})


@app.get('/studio.css')
def studio_styles() -> Response:
    return Response(STUDIO_CSS, media_type='text/css', headers={'Cache-Control': 'no-store'})


@app.post('/api/receipt-preview')
async def receipt_preview(document: str = Form(...), assets: list[UploadFile] = File(default=[])) -> dict:
    if len(document) > 32_000 or len(assets) > 16:
        raise HTTPException(413, 'Receipt document or asset count is too large')
    try:
        receipt = Receipt.model_validate_json(document)
        images = {}
        total = 0
        for asset in assets:
            raw = await asset.read(MAX_UPLOAD + 1)
            total += len(raw)
            if len(raw) > MAX_UPLOAD or total > 60 * 1024 * 1024:
                raise HTTPException(413, 'Limit: 20 MB per image, 60 MB per receipt')
            if not asset.filename or asset.filename in images:
                raise ValueError('Image asset names must be unique')
            images[asset.filename] = raw
        async with _render_slots:
            prepared, blocks = await run_in_threadpool(render_receipt, receipt, images)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    now = monotonic()
    for key, (created, _) in list(_snapshots.items()):
        if now - created > SNAPSHOT_TTL:
            del _snapshots[key]
    token = uuid.uuid4().hex
    _snapshots[token] = (now, prepared)
    while len(_snapshots) > 16:
        _snapshots.popitem(last=False)
    return {'token': token, 'width': prepared.width, 'height': prepared.height,
            'scale': CANONICAL_SCALE, 'blocks': blocks,
            'png': base64.b64encode(prepared.preview_png).decode(), 'build_id': BUILD_ID}


@app.post('/api/print-receipt')
async def print_receipt(snapshot: str = Form(...), cut: bool = Form(True),
                        feed_lines: int = Form(8), copies: int = Form(1, ge=1, le=10)) -> dict:
    token = _token()
    if not 1 <= copies <= 10:
        raise HTTPException(400, 'Choose 1–10 copies')
    if not 0 <= feed_lines <= 20 or (cut and feed_lines < 8):
        raise HTTPException(400, 'Use 8–20 feed lines with cutting, or 0–20 without')
    saved = _snapshots.pop(snapshot, None)
    if saved is None or monotonic() - saved[0] > SNAPSHOT_TTL:
        raise HTTPException(409, 'Preview expired or already printed. Refresh the preview before printing.')
    return await _print_prepared(saved[1], 1, 16, token, cut=cut, feed_lines=feed_lines, copies=copies)


@app.get("/api/status")
def status() -> dict:
    return {**target_status(), "build_id": BUILD_ID}


@app.post("/api/interrupt")
async def stop_printing() -> dict:
    return interrupt()


@app.post("/api/resume")
async def resume_printing() -> dict:
    try:
        return resume()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


def _token() -> int:
    try:
        return job_token()
    except PrintStopped as exc:
        raise HTTPException(409, str(exc)) from exc


def image_adjustments(
    rotation: int = Form(0), flip_horizontal: bool = Form(False),
    flip_vertical: bool = Form(False), brightness: float = Form(1.0),
    contrast: float = Form(1.0), black_ink: float = Form(100),
    red_ink: float = Form(100),
) -> dict:
    # A shared dependency keeps preview and printing on the same editing path.
    return dict(rotation=rotation, flip_horizontal=flip_horizontal,
                flip_vertical=flip_vertical, brightness=brightness,
                contrast=contrast, black_ink=black_ink, red_ink=red_ink)


async def _prepare(image, width, vertical_scale, two_color, dither, adjustments=None):
    if vertical_scale != CANONICAL_SCALE:
        raise HTTPException(400, 'Printer rendering uses canonical vertical_scale=0.5. Zoom the preview visually instead.')
    raw = await image.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Image is larger than 20 MB")
    try:
        return await run_in_threadpool(prepare_image, raw, width, vertical_scale, two_color, dither,
                                       **(adjustments or {}))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _send(job: bytes | list[bytes], token: int, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    started = perf_counter()
    parts = [job] if isinstance(job, bytes) else job
    job_id = uuid.uuid4().hex[:12]
    digest = hashlib.sha256(b"".join(parts)).hexdigest()
    _log.info("Print %s build=%s bytes=%d parts=%d sha256=%s cut_suffix=%s", job_id,
              BUILD_ID, sum(map(len, parts)), len(parts), digest,
              bool(parts and parts[-1].endswith(PARTIAL_CUT)))
    try:
        written = await run_in_threadpool(send_raw, job, token=token, chunk_size=chunk_size)
    except PrintStopped as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        _log.exception("Print %s failed; no automatic resend", job_id)
        raise HTTPException(503, f"Print {job_id} failed: {exc}") from exc
    _log.info("Print %s USB accepted %d bytes (physical output unverified)", job_id, written)
    pacing = "no artificial delay" if chunk_size == DEFAULT_CHUNK_SIZE else "100 ms between writes"
    return {"ok": True, "bytes": written, "usb_chunk_size": chunk_size,
            "job_id": job_id, "build_id": BUILD_ID, "job_sha256": digest,
            "usb_parts": len(parts),
            "transfer_seconds": round(perf_counter() - started, 3),
            "backend": f"No reset; up to {chunk_size} bytes/write; {pacing}; polling excluded",
            "message": "Data sent over USB; physical printing is not confirmed."}


@app.post("/api/print-text")
async def print_text() -> dict:
    return await _text_test(DEFAULT_CHUNK_SIZE)


@app.post("/api/print-ascii-diagnostic")
async def print_ascii_diagnostic() -> dict:
    return await _text_test(1)


async def _text_test(chunk_size: int) -> dict:
    result = await _send(ASCII_DIAGNOSTIC, _token(), chunk_size=chunk_size)
    result.update({
        "expected_text": "0123456789\nHELLO WORLD",
        "writes_hex": [ASCII_DIAGNOSTIC[i:i + chunk_size].hex(" ")
                       for i in range(0, len(ASCII_DIAGNOSTIC), chunk_size)],
        "message": "Plain ASCII and LF only; no setup or cut commands. USB transfer is not confirmation of readable output.",
    })
    return result


@app.post("/api/print-cut-test")
async def print_cut_test() -> dict:
    # Preserve every byte of the confirmed text job; append only the cut.
    result = await _send(ASCII_DIAGNOSTIC + PARTIAL_CUT, _token())
    result["expected_text"] = "0123456789\nHELLO WORLD"
    result["added_command_hex"] = PARTIAL_CUT.hex(" ")
    result["message"] = "Working text plus GS V 1 sent. Confirm that the text is readable and the paper partially cut. No image sent."
    return result


@app.get("/api/tiny-image-preview")
async def tiny_image_preview() -> Response:
    return Response(tiny_test_image().preview_png, media_type="image/png")


@app.post("/api/print-tiny-image")
async def print_tiny_image() -> dict:
    return await _tiny_image(DEFAULT_CHUNK_SIZE)


@app.post("/api/print-tiny-image-slow")
async def print_tiny_image_slow() -> dict:
    return await _tiny_image(1)


@app.post("/api/print-tiny-image-packet")
async def print_tiny_image_packet() -> dict:
    return await _tiny_image(8)


async def _tiny_image(chunk_size: int) -> dict:
    token = _token()
    job = encode_tiny_image_test()
    result = await _send(job, token, chunk_size=chunk_size)
    result["dots"] = [32, 16]
    result["writes_hex"] = [job[i:i + chunk_size].hex(" ") for i in range(0, len(job), chunk_size)]
    result["message"] = "TINY IMAGE text plus a 32x16 black frame/bar/diagonal sent; no cut, color selection or initialization."
    return result


@app.post("/api/preview")
async def preview(
    image: UploadFile = File(...), width: int = Form(400),
    vertical_scale: float = Form(0.5), two_color: bool = Form(True),
    dither: bool = Form(True), adjustments: dict = Depends(image_adjustments),
) -> Response:
    prepared = await _prepare(image, width, vertical_scale, two_color, dither, adjustments)
    return Response(prepared.preview_png, media_type="image/png", headers={
        "X-Dot-Width": str(prepared.width), "X-Dot-Height": str(prepared.height),
    })


@app.post("/api/print")
async def print_image(
    image: UploadFile = File(...), width: int = Form(400),
    vertical_scale: float = Form(0.5), two_color: bool = Form(True),
    dither: bool = Form(True), density_mode: int = Form(1),
    line_spacing: int = Form(16), cut: bool = Form(True),
    feed_lines: int = Form(8), adjustments: dict = Depends(image_adjustments),
) -> dict:
    token = _token()
    prepared = await _prepare(image, width, vertical_scale, two_color, dither, adjustments)
    return await _print_prepared(prepared, density_mode, line_spacing, token,
                                 cut=cut, feed_lines=feed_lines)


async def _print_prepared(prepared, density_mode, line_spacing, token, header=b"", *,
                          cut=True, feed_lines=8, copies=1):
    try:
        if not isinstance(copies, int) or not 1 <= copies <= 10:
            raise ValueError('Choose 1–10 copies')
        if cut and feed_lines < 8:
            raise ValueError("Use at least 8 trailing lines when cutting to clear the print head")
        parts = await run_in_threadpool(encode_column_image_parts, prepared.colors,
                                     density_mode=density_mode, line_spacing=line_spacing,
                                     trailing_lines=feed_lines)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if header:
        parts.insert(0, header)
    if cut:
        parts.append(PARTIAL_CUT)  # Own write, after image bands and clearance feed.
    # Encode once; repeat complete copies under ONE transport lock/generation.
    # Each copy keeps its own feed/cut. STOP/errors discard all remaining copies.
    parts = parts * copies
    _log.info("Image %dx%d density=%s feed_lines=%s cut_requested=%s copies=%s",
              prepared.width, prepared.height, density_mode, feed_lines, cut, copies)
    result = await _send(parts, token)
    result["dots"] = [prepared.width, prepared.height]
    result["feed_lines"] = feed_lines
    result["cut"] = "partial" if cut else "none"
    result["cut_command_transferred"] = bool(cut)
    result["density_mode"] = density_mode
    result["copies"] = copies
    result["message"] = (f"Image and finishing bytes for {copies} {'copy' if copies == 1 else 'copies'} "
                         "accepted by USB; verify every receipt and cut physically.")
    return result


@app.post("/api/print-calibration")
async def print_calibration(
    width: int = Form(200), density_mode: int = Form(1),
    line_spacing: int = Form(16), cut: bool = Form(True), feed_lines: int = Form(8),
) -> dict:
    token = _token()
    try:
        prepared = calibration_image(width)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await _print_prepared(prepared, density_mode, line_spacing, token,
        ASCII_DIAGNOSTIC, cut=cut, feed_lines=feed_lines)


def main() -> None:
    import os
    import uvicorn
    uvicorn.run("receipter.app:app", host="127.0.0.1", port=int(os.getenv("PORT", "8022")))


if __name__ == "__main__":
    main()
