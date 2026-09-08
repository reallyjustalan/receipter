# Receipt bitmap glyphs

`receipt-bitmap.json` contains the printable basic Latin and Latin-1 glyph rows from Daniel Hepper's **font8x8** project, based on Marcel Sondaar's / IBM public-domain VGA fonts.

- Source: https://github.com/dhepper/font8x8
- Revision: `8e279d2d864e79128e96188a6b9526cfa3fbfef9`
- Files: `font8x8_basic.h`, `font8x8_ext_latin.h`
- Upstream license declaration: **Public Domain**
- Authors credited upstream: Daniel Hepper, Marcel Sondaar, International Business Machines.

The data was converted to JSON without changing glyph bits. Keys are Unicode code points; each glyph is eight row bytes, least-significant bit at the left. Control characters were excluded. No network access or system-font lookup occurs at runtime.

These are **not Epson ROM glyphs**. Receipter uses them within a fixed 9×9 cell as a dot-matrix approximation, not an exact reproduction of the TM-U220 firmware font. See [receipt typography](../../docs/explanation/receipt-typography.md).
