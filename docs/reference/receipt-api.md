# Reference: receipt document and API

OpenAPI is served at `/docs`. This reference describes the creator workflow. [Printer reference](printer.md) lists legacy and diagnostic endpoints.

## Document

`{"blocks": [...]}` — 1–16 blocks in print order. Unknown fields and types are rejected. Every block requires a unique `id` of 1–64 ASCII letters, digits, underscores or hyphens. There may be at most three `photo` blocks. Headers with logos are separate from the photo count.

| Type | Fields beyond `id` and `type` |
| --- | --- |
| `header` | `title` (≤100 chars), `subtitle` (≤160), optional `asset`, `height` (32–800, default 100), `edits` (default contain) |
| `photo` | required `asset`, `height` (32–800, default 240), `edits` (default cover), `caption` (≤100) |
| `footer` | `items` (0–12), `currency` (≤4, default `$`), `date` (≤40), `reference` (≤64), `text` (≤400) |
| `text` | `text` (≤600) |
| `signature` | `label` (≤80); renderer adds a blank signing area and rule |
| `spacer` | `height` (8–200, default 24) |

Heights are layout pixels, not printer rows. Layout width is 400 with 16-pixel horizontal margins. Canonical vertical scale is 0.5. The assembled output must fit 1024 rows; otherwise rendering fails rather than clipping. Receipt previews approximate physical pixel aspect in CSS; see [rendering](../explanation/rendering.md).

Text uses a bundled fixed-cell bitmap approximation of impact lettering, not the printer's ROM font. Glyphs occupy a 9×9 cell with 12-dot advance and 13-row line pitch, drawn directly into canonical dots. Printable ASCII, Latin-1 and euro are supported; common smart punctuation is normalized, and unsupported characters return 400. See [typography reference and rationale](../explanation/receipt-typography.md).

An item is `{"label":"Photo strip","quantity":2,"price":"1.50"}`. Labels have 1–64 characters, integer quantities are 1–999 and prices are non-negative decimals with at most eight digits, including at most two fractional digits. Line cost is `quantity × price`; total is the decimal sum. No taxes or automatic date generation are implied.

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
| `crop_zoom` | 1–4; 1 |
| `crop_x`, `crop_y` | 0–1; 0.5. Fraction of available crop travel in oriented source coordinates. |
| `fit` | `cover` or `contain`; cover for photos, contain for headers |

Contain ignores crop zoom and position. Forced black/red first uses monochrome quantization; swap exchanges separated black/red channels. Retention thinning is applied after assignment. All settings are independent per block.

### Upload limits

Raster formats readable by Pillow (including PNG, JPEG, WebP, GIF first frame, BMP) and self-contained SVG are accepted. EXIF orientation is honored. Limits: 20 MiB per upload, 60 MiB combined, 16 uploaded assets, 24 megapixels per decoded raster, 2 MiB per SVG, 32,000 characters in the document JSON. SVGs rasterize to a bounded 1200-pixel box with preserved aspect ratio.

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

`y` and `height` are canonical row coordinates. PNG width/height are 2× the dot dimensions with nearest-neighbor pixels. The PNG is the same palette map used by printing, not a separate aesthetic mockup. Block metadata supports selection overlays and image-editor extraction.

Rendering never prints. Snapshots expire after 1800 seconds or eviction from the 16-entry process-local cache. Restarting clears them.

## `POST /api/print-receipt`

Multipart/form fields: `snapshot` (preview token), `cut` (boolean, default true), `feed_lines` (integer, default 8), `copies` (integer 1–10, default 1).

Send `X-Receipter-Build` with the preview’s build ID. A supplied stale build is rejected with 409. Missing build headers remain accepted for existing non-browser clients.

The snapshot is retrieved, consumed once per batch and encoded once with fixed mode 1 / line spacing 16. No image preparation occurs. The complete encoded copy (setup, image, feed, optional cut) is repeated `copies` times under one transport lock and cancellation generation. Each copy receives its own feed/cut. Without cutting, the result is a continuous strip. The existing 2 MiB job-byte guard applies to the entire batch.

With cutting, feed must be 8–20 lines; without cutting, 0–20. Invalid finishing fields or copy counts are rejected without consuming the snapshot. Missing, evicted, consumed or expired tokens return 409. A token is not restored after an uncertain transport failure.

Response includes `job_id`, `build_id`, `job_sha256`, accepted `bytes`, `dots`, `usb_parts`, `density_mode`, `feed_lines`, `cut`, `cut_command_transferred`, `copies` and a human-readable message. `copies` is the requested count whose full batch was accepted by USB, not a physical count. `bytes`, `usb_parts` and `job_sha256` describe the whole batch; `dots` describes one copy. USB success is not physical confirmation. STOP or an error discards all remaining unsent copies; no completed-copy count is inferred from an uncertain failure.

Validation errors return 400 (or 422 for malformed form types). Oversized documents/uploads return 413. STOP or job conflicts return 409; transport failures may return 503. There is no automatic retry.
