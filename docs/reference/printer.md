# Reference: printer, transport and diagnostic API

## Hardware and configuration

Target: Epson TM-U220A, 76 mm paper, ESC/POS-A firmware, black/red ribbon, installed partial cutter, 4 KB receive buffer.

Defaults: vendor `0x04b8`, product `0x0202` (EPSON UB-U03II adapter), interface `0`, OUT `0x01`, IN `0x82`. Environment overrides: `PRINTER_VENDOR_ID`, `PRINTER_PRODUCT_ID`, `PRINTER_OUT_ENDPOINT`. The backend requires interface 0 and an already active USB configuration; it fails rather than resetting an unconfigured device.

`PRINTER_PROFILE` defaults to `TM-U220B`. `TM-U220` selects a private family-profile copy with the reported A-model partial cutter enabled. Both produce the same ASCII/partial-cut commands. Neither changes firmware, DIP switches or the library’s global capability database. `PORT` defaults to 8022. The app binds to loopback.

`GET /api/status` includes `devices` (numeric IDs, display-only descriptor names and `is_target`) and `detection_error` (empty on successful detection). Matching uses IDs only. Missing native USB backends and USB access errors return structured diagnostics instead of an unhandled HTTP 500. Install `libusb` on each server Mac; see [new-Mac troubleshooting](../how-to/operate.md#use-the-same-printer-on-another-mac). Detection is not proof that printing can claim the interface.

## Transport contract

- Normal transfers: up to 1024 bytes per USB write, no artificial sleeps, 5-second write timeout. Image transfer boundaries preserve complete 8-row black/red bands (at most 825 bytes).
- No USB reset or SET_CONFIGURATION; exclusive USB access throughout the job. Status requests use cached detection during printing instead of competing handles.
- A 2 MiB host-memory guard, not a receive-buffer-sized job cap.
- Cancellation checks between writes. Short writes/timeouts latch STOP; uncertain data is never automatically resent.
- No pending-job queue. A concurrent job is rejected.
- Image limits: 400 columns in mode 1, 200 in mode 0, 1024 rows, at most 2048 total band-feed units.
- Image bands select black/red and overprint before advancing. Finishing restores black/default spacing, adds trailing LF lines, then optionally sends `GS V 1` (`1d 56 01`) in its own write.
- With cutting, 8–20 trailing lines; without cutting, 0–20. Eight default-spaced lines are approximately 34 mm of clearance. Partial cuts leave a paper bridge.

## Endpoints

The creator UI does not expose test-bench buttons. These endpoints remain available for explicit diagnostics:

| Endpoint | Effect |
| --- | --- |
| `GET /api/status` | Detection, busy/STOP state and build ID |
| `POST /api/interrupt` | Invalidate in-flight host jobs, block new jobs |
| `POST /api/resume` | Explicitly enable new jobs after power-cycle; reject while busy |
| `POST /api/print-text` | Buffered `0123456789\nHELLO WORLD\n\n\n\n`, 26 ASCII/LF bytes |
| `POST /api/print-cut-test` | Same text plus only the partial-cut command |
| `GET /api/tiny-image-preview` | Black 32×16 frame/bar/diagonal |
| `POST /api/print-tiny-image` | Buffered `TINY IMAGE` text and two mode-0 bands; no cut |
| `POST /api/print-calibration` | Two-color calibration with optional feed/cut |
| `POST /api/print-ascii-diagnostic` | Exact ASCII payload; 1 byte / 100 ms |
| `POST /api/print-tiny-image-packet` | Exact tiny image; 8 bytes / 100 ms |
| `POST /api/print-tiny-image-slow` | Old 1-byte image comparison; previously failed physically |
| `POST /api/preview` | Legacy single-image preview |
| `POST /api/print` | Legacy single-image preparation and printing |

Slow diagnostic writes retain 500 ms timeouts. Tiny-image encoding matches python-escpos’s column encoder; slow fallbacks do not change its byte stream.

Legacy image endpoints accept multipart `image`, `width`, `two_color`, `dither`, `rotation`, `flip_horizontal`, `flip_vertical`, `brightness`, `contrast`, `black_ink`, `red_ink`. `vertical_scale` remains a form field for compatibility but **must be 0.5**; arbitrary preview scales now return 400. Legacy printing additionally accepts `density_mode`, `line_spacing`, `cut`, `feed_lines`. The block-based creator uses the fixed canonical receipt API instead.

Calibration accepts `width` (default 200), `density_mode` (default 1), `line_spacing` (default 16), `cut` (default true), `feed_lines` (default 8). Every print endpoint requires an explicit POST. [Receipt snapshot endpoints](receipt-api.md) are the normal creator workflow.

## Build and job reporting

HTML, JS and CSS are frozen at backend startup and served with `Cache-Control: no-store`. The startup fingerprint covers application/rendering/transport/UI source files. Print requests with a mismatched `X-Receipter-Build` return 409. STOP is never blocked by build mismatch.

Logs include job ID, build ID, byte/part counts and SHA-256, not source image contents. `cut_command_transferred` means USB accepted the command, not that the cutter moved.

## Physical validation status

Buffered printing, plain text and the text-plus-partial-cut command have been physically confirmed on the target setup. Intermittent image corruption was previously observed; complete-band writes are a mitigation, not a confirmed cure. The new multi-section receipt composition and combined image/feed/cut output still need physical validation. Software test success does not establish ribbon fidelity or mechanical correctness.
