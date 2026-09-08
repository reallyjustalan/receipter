# How to edit receipts

## Assemble and reorder sections

Use **Receipt layout** to add headers/logos, photos, footers, text, signatures or spaces. Select a section in the left-hand list or on the receipt to edit it. Drag list entries, or use their up/down buttons (also keyboard accessible). Every section type can move; ordering is not hard-coded. Newly uploaded photos are initially placed before the first footer as a convenience.

A receipt allows at most three photos and sixteen sections. Use **Remove this section** to delete a block. To replace an image without losing its adjustments, use **Replace image**. To remove only a header’s logo, use **Remove logo**.

## Prepare an SVG logo

Export a self-contained SVG with a `viewBox` or explicit dimensions. Convert text to paths for predictable typography. Inline vector shapes, gradients, clipping and local `#id` references are supported by the renderer. External images, embedded images, scripts, foreign objects, stylesheets and external references are rejected. Convert stylesheet rules to inline presentation attributes before uploading.

Upload it through a header’s **Upload SVG or image** button. SVGs are rasterized server-side with resvg; the browser does not send an SVG directly to the printer. Transparency becomes white. Logos use the same brightness, threshold, black/red quantization, dithering and ink thinning as photographs.

Use **Fit entire image** for an uncropped logo, or **Crop to fill** for a cropped header image. Try switching dithering off for clean solid artwork.

## Crop and process an individual photo

Select a photo, then open **Image editor** or **Crop & process image**.

- Set **Frame height** in layout mode to change its height on paper.
- Choose **Crop to fill**. **Crop zoom** magnifies within the fixed frame. Drag the preview or use horizontal/vertical position sliders to choose the visible region. If an axis has no excess image area, that position control has no visible effect until zoom or frame dimensions change.
- Choose **Fit entire image** to retain the entire image with white surround. Crop controls are disabled in this mode.
- Rotate clockwise or mirror/flip. Positions are evaluated after orientation changes.
- Adjust brightness and contrast. Increase **Threshold / ink bias** to add ink; 128 is neutral.
- Use Floyd–Steinberg dithering for continuous tones; disable it for solid palette regions.
- Choose automatic black/red assignment, black only, red only, or swap the separated channels.
- Lower black/red ink remaining to remove dots from that channel, not recolor them.

All adjustments are per image, including logos. The enlarged preview and full-receipt context update after a short debounce. A faded image means edits are still being rendered; printing is blocked until the latest result is ready.

## Create an itemised footer

Add an **Itemised footer**. Enter labels, quantities and non-negative unit prices with up to two decimal places. Add or remove rows. The total is calculated using decimal arithmetic on the server; it is not a free-text total. Long labels wrap rather than overwriting right-aligned costs.

Date, reference and footer text are optional. Empty fields are omitted. Dates are supplied explicitly, not regenerated at print time. Add a separate **Signature** section wherever a blank signing area is needed.

## Review and export

Use **Printer preview** for a clean proof without selection outlines. **View** changes CSS display dimensions only. The receipt image is not regenerated when you zoom or switch workspaces. Leave the default 100% view selected to inspect text without fractional downscaling; smaller views can hide fine dots on screen.

Receipt lettering is a crisp fixed-cell bitmap approximation, not the printer's firmware font. For an unsupported-character error, use Latin/Latin-1 text or upload outlined artwork. See [receipt typography](../explanation/receipt-typography.md) for exact coverage and limitations.

**Download PNG** exports the processed canonical map (2× nearest-neighbor dot enlargement). It does not save source images, editable blocks, physical pin spacing or trailing feed/cut clearance. Drafts are session-only: keep the tab open if you want to continue editing.

If a receipt exceeds 1024 printer rows, reduce photo frame heights, remove spaces or shorten text. The preview error explains the limit; no silently truncated receipt is printed.

See [model limits](../reference/receipt-api.md) for exact bounds.
