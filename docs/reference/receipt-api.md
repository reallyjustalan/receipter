# Reference: receipt document and API

OpenAPI is served at `/docs`. This reference describes the creator workflow. [Printer reference](printer.md) lists legacy and diagnostic endpoints.

## Document

`{"blocks": [...]}` — 1–16 blocks in print order. Unknown fields and types are rejected. Every block requires a unique `id` of 1–64 ASCII letters, digits, underscores or hyphens. There may be at most three `photo` blocks. Headers with logos are separate from the photo count.

| Type | Fields beyond `id` and `type` |
| --- | --- |
| `header` | `title` (≤100 chars), `title_font` (`custom` default / `native`), `subtitle` (≤160), optional `asset`, `height` (32–800, default 100), `edits` (default contain) |
| `photo` | required `asset`, `height` (32–800, default 240), `edits` (default cover), `caption` (≤100) |
| `footer` | `items` (0–12), `currency` (≤4, default `$`), `date` (≤40), `reference` (≤64), `text` (≤400) |
| `text` | `text` (≤600) |
| `signature` | `label` (≤80); renderer adds a blank signing area and rule |
| `spacer` | `height` (8–200, default 24) |

All blocks except `spacer` accept `font_size`: `normal` (default) or `large` (double width and height). For headers this affects the subtitle and, when `title_font` is `native`, the title. Custom bitmap titles retain their original appearance. Photo size affects only the caption. Large text wraps sooner and counts toward the receipt height limit.

Heights are layout pixels, not printer rows. Layout width is 400 with 16-pixel horizontal margins. Canonical vertical scale is 0.5. The assembled output must fit 1024 rows; otherwise rendering fails rather than clipping. Receipt previews approximate physical pixel aspect in CSS; see [rendering](../explanation/rendering.md).

Titles default to bundled bitmap lettering; set `title_font: "native"` to use the built-in printer font instead. All other text prints through python-escpos using the printer's resident Font A, with native double-size mode for `large`. The preview uses approximate bitmap glyphs with 12-dot advance and 13-row line pitch (both doubled for large text); physical glyph width and alignment may differ. Printable ASCII, Latin-1 and euro are supported; common smart punctuation is normalized, and unsupported characters return 400. See [typography reference and rationale](../explanation/receipt-typography.md).

An item is `{"label":"Photo strip","quantity":2,"price":"1.50"}`. Labels have 1–64 characters, integer quantities are 1–999 and prices are non-negative decimals with at most eight digits, including at most two fractional digits. Line cost is `quantity × price`; total is the decimal sum. Printed item labels use the ASCII separator `x` (e.g. `2 x Photo strip`) to avoid device-dependent multiplication-symbol code pages. No taxes or server-side date generation are implied. The UI's per-footer automatic-date option resolves the browser's local clock to a `DD/MM/YYYY HH:mm` string before sending the preview document. The `date` API field remains a plain string; there is no `automatic_date` document field. Printing never recalculates it.

### Image edits

| Field | Values / default |
| --- | --- |
| `rotation` | 0, 90, 180, 270 clockwise; default 0 |
| `flip_horizontal`, `flip_vertical` | boolean; false |
| `brightness`, `contrast` | 0.2–2; 1 |
| `threshold` | integer 1–255; 128 (neutral). Higher adds ink bias. |
| `dither` | boolean; true = Floyd–Steinberg, false = no dithering |
| `assignment` | `auto`, `black`, `red`, `swap`; `auto` |
| `black_ink`, `red_ink` | 0–100 percent retained; 100 |
| `crop_zoom` | 0.25–4; 1. Below 1 shrinks relative to cover size, with white padding. |
| `crop_x`, `crop_y` | 0–1; 0.5. Fraction of available crop travel in oriented source coordinates. |
| `fit` | `cover` or `contain`; cover for photos, contain for headers |
| `eraser_strokes` | Up to 100 strokes; default `[]`. Each has `radius` (0.001–0.25 of the source's longest side) and `points` (1–256 `[x,y]` pairs, each coordinate 0–1). |

Eraser points refer to the EXIF-oriented source before rotation, flips or cropping. The eraser mask follows those transforms and makes erased regions white after tone/threshold adjustments and before dithering. Zoom-out padding also stays white under tone adjustments. Erasing is non-destructive; strokes are stored separately from uploaded bytes. With zoom below 1, position controls align the image within any spare frame space (0 = left/top, 1 = right/bottom); on overflowing axes they select the crop.

Contain ignores crop zoom and position. Forced black/red first uses monochrome quantization; swap exchanges separated black/red channels. Retention thinning is applied after assignment. All settings are independent per block.

### Upload limits

Raster formats readable by Pillow (including PNG, JPEG, WebP, GIF first frame, BMP) and self-contained SVG are accepted. On a macOS server, HEIC/HEIF is also decoded through the native `sips` converter into a bounded JPEG working copy. EXIF orientation is honored. Limits: 20 MiB per upload, 60 MiB combined, 16 uploaded assets, 2 MiB per SVG, 2,000,000 characters in the document JSON (including eraser strokes). SVGs rasterize to a bounded 1200-pixel box with preserved aspect ratio. Raster images are automatically downsampled to a working copy of at most 4096 pixels on the longest side before processing, without upscaling. JPEGs use decoder-level reduction where supported; other formats may require full decoding before resizing. The former 24-megapixel app limit is removed; Pillow’s decompression-bomb protection remains enabled.

SVG external references, image elements (including embedded raster data), stylesheets, scripts, foreign objects and entity declarations are rejected. Local `#id` references and inline vector attributes are allowed. Outline text; system font discovery is disabled.

## `POST /api/receipt-preview`

Multipart fields:

- `document`: JSON receipt document.
- `assets`: repeated file uploads. Each upload’s **filename is its asset ID**, matching the block’s `asset`. Filenames are keys only, never filesystem paths. Duplicate filenames and missing referenced assets fail validation.

Response JSON:

```json
{
  "token": "opaque-single-use-snapshot-token",
  "width": 400,
  "height": 622,
  "scale": 0.5,
  "blocks": [{"id":"header","y":8,"height":54}],
  "png": "base64-encoded-png",
  "build_id": "startup-fingerprint"
}
```

`y` and `height` are canonical row coordinates. PNG width/height are 2× the dot dimensions with nearest-neighbor pixels. The PNG contains the raster artwork plus approximate native-text glyphs. Printing replaces those text rows with the snapshot's saved native commands. Block metadata supports selection overlays and image-editor extraction.

Rendering never prints. Snapshots expire after 1800 seconds or eviction from the 16-entry process-local cache. Restarting clears them.

## `POST /api/receipt-output`

Non-printing, non-consuming byte inspection. Form fields: `snapshot`, `cut` (default true), `feed_lines` (default 8), `copies` (1–10, default 1), with the same finishing validation as printing.

Uses the **same encoder** as the print route on the stored canonical image. Response JSON contains:

- `snapshot`, `build_id`
- `bytes`: full batch byte count
- `parts`: number of encoder/transport parts
- `copies`, `cut` (boolean), `feed_lines`
- `sha256`: SHA-256 of all parts joined in transfer order
- `raw_base64`: the complete binary ESC/POS batch, including each copy's setup, graphics, feed and optional cut
- `state`: `prepared_not_sent`

Inspection does not acquire a printer job token, open USB, consume the snapshot, extend its expiry or send data. It works while the printer is offline or STOPPED. Missing/expired snapshots return 409. Invalid settings return 400 or 422. Browser formatting/pagination does not modify the bytes. The app freezes `/output-log.js` with its other assets at startup.

## `POST /api/print-receipt`

Multipart/form fields: `snapshot` (preview token), `cut` (boolean, default true), `feed_lines` (integer, default 8), `copies` (integer 1–10, default 1).

Send `X-Receipter-Build` with the preview’s build ID. A supplied stale build is rejected with 409. Missing build headers remain accepted for existing non-browser clients.

The snapshot is retrieved, consumed once per batch and encoded once with fixed mode 1 / line spacing 16. No image preparation occurs. The complete encoded copy (setup, image, feed, optional cut) is repeated `copies` times under one transport lock and cancellation generation. Each copy receives its own feed/cut. Without cutting, the result is a continuous strip. The existing 2 MiB job-byte guard applies to the entire batch.

With cutting, feed must be 8–20 lines; without cutting, 0–20. Invalid finishing fields or copy counts are rejected without consuming the snapshot. Missing, evicted, consumed or expired tokens return 409. A token is not restored after an uncertain transport failure.

Response includes `job_id`, `build_id`, `job_sha256`, accepted `bytes`, `dots`, `usb_parts`, `density_mode`, `feed_lines`, `cut`, `cut_command_transferred`, `copies` and a human-readable message. `copies` is the requested count whose full batch was accepted by USB, not a physical count. `bytes`, `usb_parts` and `job_sha256` describe the whole batch; `dots` describes one copy. USB success is not physical confirmation. STOP or an error discards all remaining unsent copies; no completed-copy count is inferred from an uncertain failure.

Validation errors return 400 (or 422 for malformed form types). Oversized documents/uploads return 413. STOP or job conflicts return 409; transport failures may return 503. There is no automatic retry.

## Saved default profiles

These endpoints never access the printer. Profiles live in a separate SQLite database under the server data directory; see [saving and moving profiles](../how-to/receipt-profiles.md).

- `GET /api/profiles`: `{default_id, profiles:[{id,name,updated}]}`. An empty `default_id` means built-in startup defaults.
- `GET /api/profiles/{id}`: `{id,name,document,options,assets}`. Each asset is `{id,name,mime,data}` with base64-encoded bytes. Missing profiles return 404.
- `POST /api/profiles`: multipart fields `name` (trimmed, 1–80 characters), `document` (receipt JSON), `options` (JSON, default `{}`), `profile_id` (omit/empty to create, existing ID to overwrite), `make_default` (boolean, default true), and repeated `assets` uploads whose filenames are the document's asset IDs. Returns `{id,name}`.

`options` contains `automatic_dates` (footer block IDs, default `[]`) and `finishing` (`cut`, `feed_lines`, `copies`, with the normal print-setting defaults/limits). Captured automatic timestamps are cleared in the saved document. Manual dates/references are retained. Saving with `make_default=false` clears the startup default only if the saved profile was the current default.

Profile documents use the receipt schema but reject camera photo blocks and duplicate section IDs. Upload exactly the referenced header logos; unreadable images and externally referencing SVGs fail validation. Limits: 16 logo assets, 20 MiB per logo, 60 MiB total, 2,000,000 document characters and 32,000 option characters. Invalid data returns 400/422, oversized requests 413, and unknown overwrite IDs 404. Document/options/logo updates are transactional; invalid saves do not replace a previous profile.
