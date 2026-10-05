# Explanation: receipt previews and mixed printer output

Text elements, footer items/totals/details, captions, subtitles and signature labels print using `python-escpos.text()` and the printer's resident Font A, not bitmap glyphs. Their wrapped lines and encoded commands are saved with the preview snapshot and interleaved with raster sections in document order. Titles default to the custom bitmap font; the header's Title font selector can switch them to the built-in printer font. Custom titles, rules and artwork retain the raster path. Each text-bearing section offers Normal or Large (native double width and height); the header size setting affects its subtitle and any built-in title, leaving custom titles unchanged. Preview glyphs and line pitch scale with the selection and wrapping is recalculated before saving. The screen uses approximate bitmap glyphs; native font shape, width and alignment may differ. Native text uses black ink and explicit line spacing, with alignment and size reset after each run; hardware validation is still required.

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

Each image is quantized independently, then pasted into a shared indexed receipt canvas. The assembled receipt is **not** quantized a second time. Consequently, moving a photo preserves its dither pattern and ink thinning. Text uses fixed-cell bitmap glyphs drawn directly into canonical black dots without resizing or thresholding. This avoids losing thin strokes during vertical downsampling. The letters approximate impact-printer typography; they are not Epson ROM glyphs. Item totals use decimal arithmetic and fixed-pitch right alignment. See [receipt typography](receipt-typography.md) for provenance, character coverage and fidelity limits.

## Why printing uses a snapshot

The preview endpoint validates the whole document, renders once and stores the canonical `PreparedImage` under an opaque token. The browser displays that map as a preview. The print endpoint retrieves the snapshot and encodes it directly, replacing native-text rows with their saved commands; it does not accept a second copy of the layout or source images.

Snapshots are process-local, bounded to sixteen entries and expire after thirty minutes. Each token is consumed on one print attempt (a batch of 1–10 copies), including uncertain delivery failures. The canonical image is encoded once and its complete setup/image/feed/cut parts are repeated under one transport lock. Copy count never triggers rendering, and finishing is applied per copy. This is one bounded job, not a queue of future jobs. STOP and errors discard all remaining unsent copies. An explicit preview refresh is required before another batch. This prevents accidental reuse and avoids automatic retries after ambiguous USB delivery. STOP retains the transport’s cancellation generation checks.

The output inspector uses that same snapshot and the same job encoder to expose complete raw bytes without USB access. Finishing changes re-encode bytes, not images. Independent output request revisions prevent a late response for an old copy count or cut setting from being shown as current. The client blocks printing until both the image snapshot and byte inspection match current settings. It logs submission and USB acceptance separately and compares the reported job SHA-256 with the inspected stream; it does not invent live per-byte acknowledgement.

Automatic footer dates are resolved from the browser's local clock before preview rendering. They remain literal text in the immutable snapshot, so inspecting output, printing or making multiple copies cannot silently change the date. The automatic option updates on preview refresh rather than continuously invalidating a reviewed receipt.

Client revisions and request cancellation prevent an older render response from replacing newer edits. Printing is disabled during rendering, on validation errors, stale builds, disconnection, STOP or an active job. HTML, JavaScript, CSS and backend code share a startup build fingerprint. Restarting the server requires a refreshed browser before printing.

## Deliberate limits

There is no print queue or full customer-receipt project storage. Named profiles persist reusable default documents and their logo assets on the server; camera shots and unsaved browser drafts stay in the tab. Servers also retain bounded rendered snapshots. Rendering a new preview currently uploads the referenced images again. Raster sources are downsampled to a 4096-pixel working edge (JPEG decoder reduction where supported); original megapixels are not capped by the app, though Pillow’s decompression-bomb protections remain enabled. Requests are limited by file size, total asset size, document size, section count, photo count and final row count. At most two receipt renders run concurrently.

The existing USB transport and diagnostic endpoints remain separate from the creator UI. Buffered printing has been physically confirmed on the target setup; complete multi-photo/red-black receipts and this composition path still require physical validation. Software tests establish byte and preview consistency, not mechanical correctness.

For implementation contracts see [receipt API reference](../reference/receipt-api.md).
