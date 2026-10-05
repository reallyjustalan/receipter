# Explanation: receipt lettering and the printer's built-in font

## What the hardware supplies

The [Epson TM-U220 product specifications](https://epson.com/For-Work/Printers/POS/TM-U220-Receipt-Kitchen-Printer/p/C31C514653) list **7×9 / 9×9** character sizes and fixed-column text. These are impact-printer character matrices, not a modern thermal printer's high-resolution outline font.

The built-in letters live in the printer's firmware. The installed python-escpos profile contains font names, column counts and code pages, **not downloadable glyph bitmaps**. Selecting a firmware font can print native text, but does not make that font available to Pillow or the browser. The library's generic profile metrics are not a captured sample from this particular printer.

## What was making our text unclear

The previous renderer used Pillow's proportional default font at 18 layout pixels, then scaled it vertically by 0.5 and thresholded it. Thin antialiased strokes could disappear during that conversion. Rendering a larger browser preview could not recover the lost dots.

Titles and preview text use bundled fixed-cell bitmap glyphs pasted into the canonical indexed dot map. Other printed text now uses the printer's resident font through python-escpos, including footer totals and details. Normal and Large sizes use native normal and double-width/double-height modes; preview glyphs scale with nearest-neighbor sampling. Rules remain one-row raster artwork. Amounts use fixed-column spacing rather than proportional-font spacing.

The default view is 100% rather than 85%, avoiding initial fractional downscaling. At 100%, a canonical dot occupies one CSS pixel horizontally and two vertically, following the existing graphics-mode preview aspect. Smaller view zooms necessarily discard some screen detail, but never change the receipt's actual dots.

## Approximation, not Epson ROM lettering

The bundled glyphs are public-domain **font8x8** basic Latin and Latin-1 bitmaps, placed in a 9×9 cell with a 12-column advance and 13-row line pitch. This gives 33 cells across a 400-dot canvas, or 30 within the receipt's margins. The eight-row glyph shapes and chosen spacing are an explicit approximation to fixed-cell impact lettering; they are **not a verified copy of Epson's nine-row glyphs**. [Attribution and source revision](../../receipter/fonts/NOTICE.md) are bundled with the data.

The preview shows these approximate rasterized letters. Printing sends title and artwork dots unchanged, but replaces all other text rows with saved firmware-text commands. The snapshot stores both representations; inspection and printing use the same mixed-output encoder. Native glyph shape, width and alignment can differ from the screen. The UI labels this approximation explicitly; physical validation is still needed.

A close, straight-on scan of the printer's default text or an official usable glyph resource would allow a more faithful comparison. No physical output comparison has yet verified this approximation.

## Character coverage

Printable ASCII, Latin-1 and a small original euro glyph are supported. Combining accents are normalized to composed characters. Curly quotes become straight quotes, en/em dashes become `-`/`--`, ellipses become three periods, and tabs become four spaces before measuring and wrapping. Unsupported characters produce a preview error rather than disappearing or printing a replacement box. For other scripts or custom lettering, upload raster artwork or an SVG with outlined text.

This change concerns **receipt artwork only**. It does not restyle the interface, raise the graphics rendering scale or alter the photo-processing pipeline.
