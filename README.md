# TM-U220 Image Lab

Local USB text/image tests for the user's Epson TM-U220A impact printer: 76 mm paper, ESC/POS-A firmware, installed partial cutter, and a 4 KB receive buffer.

## Run

```bash
uv sync
uv run main.py
```

Open <http://localhost:8022>. Nothing prints automatically. Run one server process, without multiple workers.

## Normal printing: buffered transfers

The tiny-write pacing and 512-byte limit were troubleshooting restrictions, **not hardware limits**. Normal text, cut, image-upload and calibration jobs now use:

- **Up to 1 KiB host USB writes, with no artificial sleeps.** Image jobs now send complete 8-row black/red bands (at most 825 bytes) as separate writes, followed by separate feed and cut writes; the encoded byte stream is unchanged. The USB driver packetizes them and applies backpressure when the printer's receive buffer fills. A receipt can be much larger than that buffer; it is streamed in order.
- The existing USB configuration: **no USB reset or SET_CONFIGURATION**.
- Exclusive USB access throughout the job. Browser status queries return cached detection rather than opening competing handles.
- Cancellation checks between writes. Each buffered write has a **5-second timeout**. A short write or error stops the job; no automatic retransmission of bytes whose delivery is uncertain.
- A **2 MiB host-memory guard**, replacing the old 512-byte cap. Full calibration is enabled again. Existing image rendering/feed limits are separate: up to 400 columns in mode 1, 200 in mode 0, 1024 prepared rows, and a bounded paper feed.

There is deliberately **no pending-job queue**: a second concurrent request is rejected. Buffering bytes within one receipt does not require accumulating more jobs behind it. This avoids surprise receipts printing after STOP.

The user has now **physically confirmed buffered printing works**. The no-reset/exclusive transport remains unchanged while adding image editing and finishing controls. API success means USB accepted the data, not that the output was readable or mechanically complete.

## Print controls

Normal buffered endpoints:

- `POST /api/print-text`: `0123456789\nHELLO WORLD\n\n\n\n` — 26 bytes of ASCII/LF.
- `POST /api/print-cut-test`: the same text plus only `GS V 1` (`1d 56 01`) for a partial cut.
- `POST /api/print-tiny-image`: `TINY IMAGE` and a 32×16-dot black frame/bar/slash, no cut. Two `ESC *` mode-0 8-pin bands, explicit LF, band spacing `ESC 3 16`, then default spacing `ESC 2`. Its bitmap bytes match python-escpos's column encoder exactly.
- `POST /api/print`: uploaded image using the same edits as the preview, followed by clearance feed and optional partial cut (on by default).
- `POST /api/print-calibration`: full two-color calibration, also followed by clearance feed and partial cut by default.

Each test is independent and requires an explicit click. Tiny-image preview: `GET /api/tiny-image-preview`. The UI still exposes STOP and the slower diagnostic fallbacks.

## Image editor and finishing

Choose an image under **Edit & print**. Controls update the preview automatically:

- Clockwise rotation: 0/90/180/270°, plus horizontal/vertical flips. Camera EXIF orientation is applied first; sizing happens after rotation.
- Brightness and contrast: 20–200%, applied before palette quantization.
- Independent **black/red ink remaining**: 0–100%. These deterministically remove a proportion of each channel's dots to white, rather than recoloring them. 0% removes that ink; 100% preserves it. Dots always remain white, black or red, with existing ribbon-selection commands unchanged.
- Existing width, vertical scale, black/red versus monochrome, and dithering controls. Each horizontal density remembers its own width and vertical scale, so 400 → 200 → 400 works without losing custom settings. Defaults are 400/0.5 for double density and 200/1.0 for single density.

Preview and print call the exact same preparation function. Printing is disabled while edits are awaiting a fresh preview, and stale preview responses cannot overwrite newer edits. Whenever Print is disabled, the exact blocking reasons appear below it and in a hover/keyboard-focus tooltip (including preview errors, missing images, invalid settings, active jobs, STOP, disconnection and stale builds). Preview colors approximate the ribbon shades; the displayed pixels are the actual indexed dots, not a simulation of physical dot shape/spacing.

Shared multipart fields for `/api/preview` and `/api/print`: `rotation`, `flip_horizontal`, `flip_vertical`, `brightness`, `contrast`, `black_ink`, `red_ink`, plus the existing sizing/color fields.

Image/calibration finishing fields: `cut=true`, `feed_lines=8` by default. After the last band, the encoder restores black and default line spacing, feeds **eight lines (~34 mm)**, then sends the verified `GS V 1` partial-cut command. Feed is adjustable up to 20 lines; cutting requires at least eight. With cutting disabled, 0–20 lines are allowed. Increase clearance if the image edge is still too close to the cutter. This new combined image/feed/cut sequence still needs physical validation; partial cutting intentionally leaves a small paper bridge. Text/tiny diagnostic jobs retain their original finishing behavior.

## Garbled characters, cutting, and deployment diagnostics

The reported image contains printer-font characters between valid bitmap bands. This is consistent with bitmap bytes being interpreted as text after command framing is lost, not ordinary quantization/dithering. The underlying reason (transport delivery, command handling, or device state) is **not established**. Complete-band host writes are a controlled mitigation, not a physically confirmed cure. No tiny-byte pacing or automatic retries have been reintroduced. If garbage returns, STOP and power-cycle to clear an uncertain parser state before another job.

Logs showed the last reported image jobs ran on the older backend, before image cutting was added, even though the live-served page could already expose new controls. HTML and editor JavaScript are now snapshotted at backend startup, with no browser caching and a matching build ID. Updated browsers block printing after a server update until refreshed; stale build headers are rejected server-side too. STOP is never blocked by version mismatch.

API results and `receipter.log` now include job IDs, build IDs, byte counts, part counts and SHA-256 fingerprints (not uploaded image contents). Image results report the density, feed lines, requested cut and `cut_command_transferred`. That flag confirms USB accepted the cut command, **not that the physical cutter moved**. Cutting remains the previously verified `GS V 1`, in its own final write after clearance feed.

## Physically confirmed slow fallbacks

Under Advanced:

- `POST /api/print-ascii-diagnostic`: exact working ASCII payload, **1 byte per 100 ms**.
- `POST /api/print-tiny-image-packet`: exact working tiny image, **8 bytes per 100 ms**.
- `POST /api/print-tiny-image-slow`: old 1-byte image comparison, which previously failed.

Diagnostic modes retain 500 ms write timeouts. All modes avoid USB resets and competing status probes. The early troubleshooting changed several variables together; the specific cause of the original garbage output was not isolated. Larger/two-color image fidelity needs separate physical validation.

## Emergency stop

Click **STOP**, press **Esc** in the page, or run:

```bash
curl -X POST http://localhost:8022/api/interrupt
```

STOP immediately invalidates in-flight requests and blocks new jobs. It discards remaining unsent blocks, including later feed/cut commands. An in-progress USB write cannot be retracted and may take up to its timeout to return before resources can be released.

**Already-buffered data may continue printing. Switch the printer OFF to stop that, then ON without holding FEED to clear its command parser and return to normal mode.** Afterwards explicitly Resume:

```bash
curl -X POST http://localhost:8022/api/resume
```

A timeout/partial write also latches STOP. No automatic retries or fallback printing occurs. STOP is process-local (a server restart resets it) and cannot cancel other applications' jobs.

## USB/profile configuration

Defaults: vendor `0x04b8`, product `0x0202` (EPSON UB-U03II adapter), interface `0`, OUT `0x01`, IN `0x82`.

Override `PRINTER_VENDOR_ID`, `PRINTER_PRODUCT_ID`, or `PRINTER_OUT_ENDPOINT` before starting if necessary. This backend requires interface 0 and an already active USB configuration; it fails rather than resetting an unconfigured device.

The library profile defaults to `TM-U220B`. `PRINTER_PROFILE=TM-U220` selects a private family-profile copy with the reported A-model partial cutter enabled. Both profiles produce the same ASCII/partial-cut commands. This does not change firmware or DIP switches; the library's global capability database is not modified.

## Tests

```bash
uv run python -m unittest discover -s tests -v
node tests/test_editor.js
```

Tests mock USB and consume no paper. Coverage includes ordered long-receipt streaming without sleeps, retained slow modes, default routing, no reset, exact image packing, STOP before subsequent blocks/cuts, status isolation, and no retries after short writes/timeouts.
