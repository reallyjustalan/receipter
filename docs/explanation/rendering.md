# Explanation: one receipt, one canonical dot map

## Three workspaces, one document

The receipt is an ordered array of typed sections. Each section has a stable ID. Image assets and processing settings are attached to IDs, not list positions, so reordering does not transfer adjustments to another photo.

**Receipt layout** edits structure and content. **Image editor** edits just one image with persistent controls, an enlarged processed section and a live full-receipt context. **Printer preview** removes selection controls and adds explicit finishing/print actions. These are views of one document, not independent layouts or separate renderers.

## Why 0.5 is canonical

The receipt’s layout is 400 logical pixels wide. Image frame sizes and text are specified at layout resolution. Printer output uses **0.5 vertical scale**, matching the mode-1 horizontal density and existing 8-pin feed configuration. The resulting indexed map contains only white, black and red dots.

The browser displays those dots with an approximate 1:2 horizontal-to-vertical pixel aspect, then applies view zoom through CSS dimensions. The PNG transport representation uses 2× nearest-neighbor enlargement in both axes; its bytes are an exact representation of the indexed dots, not a printer-rendering scale setting.

Changing view zoom never makes an API render request, resamples the source image or re-runs dithering. Switching workspace also reuses the same image. This prevents preview zoom from changing quantization, density, receipt length or print bytes. Physical pin shape, ribbon shade and mechanical spacing are not simulated exactly.

## Image preparation

Raster decoding or bounded SVG rasterization → EXIF orientation → white transparency background → rotation/flips → frame fitting/cropping → brightness/contrast → threshold bias → canonical resizing → palette quantization/dithering → channel assignment → deterministic per-channel ink thinning.

SVGs use the same pipeline after rasterization. resvg resolves vector geometry at bounded resolution; untrusted external resources are rejected before rendering. SVG text should be outlined because system font discovery is disabled for predictable resource handling. Output contains raster dots, never arbitrary uploaded printer commands.

Each image is quantized independently, then pasted into a shared indexed receipt canvas. The assembled receipt is **not** quantized a second time. Consequently, moving a photo preserves its dither pattern and ink thinning. Text is rendered at layout resolution and passed through the same canonical sizing path, in black without dithering. Item totals use decimal arithmetic and measured right alignment.

## Why printing uses a snapshot

The preview endpoint validates the whole document, renders once and stores the canonical `PreparedImage` under an opaque token. The browser displays that exact map. The print endpoint retrieves the snapshot and encodes it directly; it does not accept a second copy of the layout or source images.

Snapshots are process-local, bounded to sixteen entries and expire after thirty minutes. Each token is consumed on one print attempt, including uncertain delivery failures. An explicit preview refresh is required before another copy. This prevents accidental reuse and avoids automatic retries after ambiguous USB delivery. STOP retains the transport’s cancellation generation checks.

Client revisions and request cancellation prevent an older render response from replacing newer edits. Printing is disabled during rendering, on validation errors, stale builds, disconnection, STOP or an active job. HTML, JavaScript, CSS and backend code share a startup build fingerprint. Restarting the server requires a refreshed browser before printing.

## Deliberate limits

There is no print queue, persistent asset library or editable project storage. Browser drafts and uploaded files stay in the tab; servers retain only bounded rendered snapshots. Rendering a new preview currently uploads the referenced images again. Requests are limited by file size, total asset size, image pixels, document size, section count, photo count and final row count. At most two receipt renders run concurrently.

The existing USB transport and diagnostic endpoints remain separate from the creator UI. Buffered printing has been physically confirmed on the target setup; complete multi-photo/red-black receipts and this composition path still require physical validation. Software tests establish byte and preview consistency, not mechanical correctness.

For implementation contracts see [receipt API reference](../reference/receipt-api.md). For the separately deferred aesthetic work see [visual direction](visual-direction.md).
