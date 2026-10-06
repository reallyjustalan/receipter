# How to edit receipts

## Assemble and reorder sections

Use **Receipt layout** to add headers/logos, photos, footers, text, signatures or spaces. Select a section in the left-hand list or on the receipt to edit it. Drag list entries, or use their up/down buttons (also keyboard accessible). Every section type can move; ordering is not hard-coded. Newly uploaded photos are initially placed before the first footer as a convenience.

A receipt allows at most three photos and sixteen sections. Use **Remove this section** to delete a block. For a photo, click it on the receipt or in the section list, then press **Delete** or **Backspace** (the Mac Delete key). This removes the selected photo section from the draft and updates automatic footer quantities. The shortcut is disabled while typing, inside dialogs, during crop/erase drags, and in Printer preview; it never changes saved queue receipts or removes non-photo sections. To replace an image without losing its adjustments, use **Replace image**. To remove only a header’s logo, use **Remove logo**.

## Prepare an SVG logo

Export a self-contained SVG with a `viewBox` or explicit dimensions. Convert text to paths for predictable typography. Inline vector shapes, gradients, clipping and local `#id` references are supported by the renderer. External images, embedded images, scripts, foreign objects, stylesheets and external references are rejected. Convert stylesheet rules to inline presentation attributes before uploading.

Upload it through a header’s **Upload SVG or image** button. SVGs are rasterized server-side with resvg; the browser does not send an SVG directly to the printer. Transparency becomes white. Logos use the same brightness, threshold, black/red quantization, dithering and ink thinning as photographs.

Use **Fit entire image** for an uncropped logo, or **Crop to fill** for a cropped header image. Try switching dithering off for clean solid artwork.

## Crop and process an individual photo

Select a photo, then open **Image editor** or **Crop & process image**.

In **02 Image editor**, click **Photo 1**, **Photo 2**, **Photo 3** (or **Header / logo**) in the thumbnail switcher to edit another image without leaving this view. You can also click its section in the small **In your receipt** preview. The selected thumbnail is highlighted. Buttons support keyboard Tab/Enter and touch. Crop, tone, colour and eraser edits remain independent for each image; switching does not reset them or apply changes to every photo. The current crop/erase tool stays selected.

- Set **Frame height** in layout mode to change its height on paper.
- Choose **Crop to fill**. **Image zoom** ranges from **0.25× to 4×**. Values below 1 shrink the photo relative to its fill size, leaving white space where it no longer fills the frame. Values above 1 magnify it. Drag the preview in **Move / crop** mode or use horizontal/vertical position sliders to position it. This changes the printed photo; the toolbar's **View** zoom only changes screen magnification. If an axis exactly fits, its position control has no visible effect until zoom or frame dimensions change.
- Choose **Fit entire image** to retain the entire image with white surround. Crop controls are disabled in this mode.
- Rotate clockwise or mirror/flip. Positions are evaluated after orientation changes.
- Adjust brightness and contrast. Increase **Threshold / ink bias** to add ink; 128 is neutral.
- Use Floyd–Steinberg dithering for continuous tones; disable it for solid palette regions.
- Choose automatic black/red assignment, black only, red only, or swap the separated channels.
- Lower black/red ink remaining to remove dots from that channel, not recolor them.

All adjustments are per image, including logos. The enlarged preview and full-receipt context update after a short debounce. A faded image means edits are still being rendered; printing is blocked until the latest result is ready.

### Erase smudges or unwanted details

In **Crop & process image**, find **Clean up image** and switch **Tool** to **Erase**. The large canvas shows the original, uncropped image (with any background removal applied). Choose a brush diameter and click or drag over marks to remove them. PNG and JPEG are recommended; erasing requires a browser-decodable image.

White brush marks become paper-white areas in the receipt, before dithering, even with dark brightness/threshold settings. The full-receipt context shows the processed result. Switch back to **Move / crop** to inspect the enlarged printer-dot preview or reposition the image.

Use **Undo last erase** to remove the latest stroke, or **Reset erasing** to remove all strokes on this image. Crop, rotation, flips, zoom and tone adjustments retain the erasing, attached to the source image. **Reset image adjustments** also retains erasing. Replacing the uploaded image clears its strokes; the original upload is never overwritten. There is a limit of 100 strokes per image and 256 sampled points per stroke; start another stroke if prompted. Erasing, like the rest of the draft, is kept only in the current tab.

### Remove the background and keep people

In **Crop & process image**, click **Remove background** under **Keep people only**. Apple Vision processes the photo locally on the Mac running Receipter—no cloud service, API key or image upload to a third party. Run `uv sync` and restart the server after updating; this feature requires macOS 12 or later. Other platforms can still use the rest of Receipter.

The mask keeps detected people rather than arbitrary foreground objects. Check hair, clothing, small people and crowded group shots in the preview: segmentation is not perfect. If no people are detected, the original stays unchanged and an explanation appears in the event log.

**Restore original background** reverses removal without resetting crop or tone settings. **Reset image adjustments** only resets those adjustments, not the background. Replacing the image discards its saved original. Background removal preserves the working image’s dimensions (up to 4096 pixels on the longest side) and existing transparency; transparent areas are composited onto white before the usual tone/ink processing. Processing runs before cropping and dithering. Printing is blocked while removal is pending.

Originals and processed images live in the current browser tab; [saving a profile](receipt-profiles.md) also persists its current logo assets on the server. Input and output are limited to 20 MB each. High-resolution images are automatically downsampled with Pillow to at most 4096 pixels on the longest side; there is no app-level megapixel rejection. JPEG reduced-resolution decoding saves memory before resizing. Pillow’s decompression-bomb safeguards remain enabled. Inference uses a copy bounded to 2048 pixels on its longest side; the mask is resized to the working image’s dimensions.

## Choose a smaller built-in font

Select an itemised footer or text section and set **Text size → Small (Font B)**. This selects the printer's narrower resident Font B; the installed Epson profile lists 56 columns versus Font A's 42. More text and longer item labels fit on a line. The preview is approximate and keeps the existing line pitch, so this is not a half-height font.

**Normal** remains the default and **Large** keeps its double-width/double-height behavior. Small also applies to captions, signatures and native header text; custom bitmap titles and images are unchanged. Profiles preserve the selection, and saved queue receipts keep their original encoded font choices.

## Create an itemised footer

Add an **Itemised footer**. Enter labels, quantities and non-negative unit prices with up to two decimal places. Add or remove rows. The total is calculated using decimal arithmetic on the server; it is not a free-text total. Long labels wrap rather than overwriting right-aligned costs.

### Automatically count photos

For a footer item, enable **Use photo count as quantity**. Its quantity becomes the number of body photo sections (0–3), and its cost and the footer total update as photos are added or removed. Logos and print copies do not count. With zero body photos, the automatic item is omitted from the printed footer and contributes zero; manual items are unchanged. Disable the checkbox to return to its previous manual quantity.

Save **Profiles → Save current defaults** to make this automatic behavior part of a reusable template. Unlike a captured quantity, the mode is saved: each new receipt counts its own photos. Quantities resolve when the preview is rendered, so adding to queue freezes the matching totals and reprints never change them.

Date, reference and footer text are optional. Empty fields are omitted. Add a separate **Signature** section wherever a blank signing area is needed.

### Insert today's date and time

In the footer, enable **Use current date & time**. The date field becomes automatic and uses the browser's local clock in receipt format, for example `08/09/2026 14:35` (day/month/year, 24-hour time).

The time is captured on each receipt preview refresh, including refreshes caused by edits. It does not tick continuously or change silently at print time. Use **Refresh preview** to update a timestamp after leaving the editor idle. All copies in a batch use the exact previewed time. Disable the option to edit the captured date manually or clear it. This setting is per footer and follows that section when reordered.

## Print multiple copies

1. Open **Printer preview** and wait for an up-to-date receipt.
2. Set **Copies (1–10)** to the number you want; the default is one. The button updates to **Add N copies to queue**. Changing the count does not regenerate the artwork.
3. Choose trailing feed and partial cut. These settings apply **after every copy**. Without cutting, copies remain on one continuous strip; use feed lines if you want space between them.
4. Click **Add N copies to queue**. Wait for confirmation that it was saved on the Mac, then open **Queue** and explicitly **Start / continue queue**. All copies run sequentially as one job.
5. Inspect the paper, then **Confirm & next**. USB acceptance does not verify physical receipts or cuts. Use STOP / Esc to cancel remaining unsent copies; power off to stop buffered data. Saved jobs stay available.

For a failed batch, count actual receipts and use **Reprint / remaining copies** to choose how many to resend. There are no automatic retries. See [queue persistence and recovery](print-queue.md).

## Inspect printer output

The floating bottom toolbar keeps **Refresh preview**, **Download PNG** and **Download raw** accessible. Its **ESC/POS bytes** panel updates when the receipt or copy/feed/cut settings change, without printing anything.

- The byte view shows hexadecimal offsets, 16 hexadecimal bytes per row and a printable ASCII column. Non-printable bytes appear as dots only in the ASCII column; their actual hex values are retained.
- Use the arrows to page through the complete stream, 1024 bytes at a time. The full job is available as `receipt.escpos` through **Download raw**.
- `Prepared — not sent` describes the editor's candidate bytes, not queue activity. Check Queue for sending, awaiting confirmation or interrupted states. USB acceptance does not verify physical output.
- Timestamped event entries report editor preparation and durable queue saves. Old entries are retained up to 40 events; the byte pane/download holds the most recently inspected stream. Queue is the permanent receipt archive until explicit deletion.
- During edits, the prior byte view is marked stale until matching output is ready. Printing is blocked while output inspection is pending or failed. The raw download may still represent the last inspected stream; use the state label to distinguish it from current output.

Receipt text is rasterized, so most raw bytes are graphics payload, not readable text strings. Do not treat incidental ESC bytes inside those payloads as separate commands.

Collapse **ESC/POS bytes** to reclaim screen space. The top printer/workspace controls and bottom toolbar float above the document; their measured heights reserve space for editing and keyboard focus, including on narrow screens.

## Review and export

Use **Printer preview** for a clean proof without selection outlines. **View** changes CSS display dimensions only. The receipt image is not regenerated when you zoom or switch workspaces. Leave the default 100% view selected to inspect text without fractional downscaling; smaller views can hide fine dots on screen.

Receipt lettering is a crisp fixed-cell bitmap approximation, not the printer's firmware font. For an unsupported-character error, use Latin/Latin-1 text or upload outlined artwork. See [receipt typography](../explanation/receipt-typography.md) for exact coverage and limitations.

**Download PNG** exports the processed canonical map (2× nearest-neighbor dot enlargement). It does not save source images, editable blocks, physical pin spacing or trailing feed/cut clearance. Drafts are session-only: keep the tab open if you want to continue editing.

If a receipt exceeds 1024 printer rows, reduce photo frame heights, remove spaces or shorten text. The preview error explains the limit; no silently truncated receipt is printed.

See [model limits](../reference/receipt-api.md) for exact bounds.
