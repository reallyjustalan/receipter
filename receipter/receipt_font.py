"""Crisp, fixed-cell receipt text. Bitmap approximation, NOT Epson ROM data."""
from functools import lru_cache
import json
from pathlib import Path
import unicodedata

from PIL import Image

# 8x8 public-domain glyphs inside a 9x9 cell, with three columns of spacing.
# 400 // 12 = 33 full-width cells; the receipt's margins leave 30 usable cells.
CELL_WIDTH = 9
CELL_HEIGHT = 9
ADVANCE = 12
LINE_ROWS = 13
_ROWS = json.loads((Path(__file__).parent / 'fonts/receipt-bitmap.json').read_text())
# Original supplemental euro glyph; the upstream Latin-1 table predates it.
_ROWS[str(ord('€'))] = [0x3c, 0x66, 0x0f, 0x06, 0x0f, 0x66, 0x3c, 0x00]
_ALIASES = str.maketrans({'‘': "'", '’': "'", '“': '"', '”': '"',
                          '–': '-', '—': '--', '…': '...', '\t': '    '})


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFC', text.replace('\r\n', '\n')).translate(_ALIASES)
    for char in text:
        if char != '\n' and str(ord(char)) not in _ROWS:
            raise ValueError(f'Receipt font does not support {char!r} (U+{ord(char):04X}). '
                             'Use basic Latin/Latin-1 text or upload outlined artwork.')
    return text


def text_width(text: str) -> int:
    """Width including the final cell, but excluding its trailing spacing."""
    return max(0, (len(text) - 1) * ADVANCE + CELL_WIDTH)


@lru_cache(maxsize=256)
def glyph(char: str) -> Image.Image:
    mask = Image.new('1', (CELL_WIDTH, CELL_HEIGHT), 0)
    for y, row in enumerate(_ROWS[str(ord(char))]):
        for x in range(8):
            if row & (1 << x):
                mask.putpixel((x, y), 255)
    return mask


def draw_text(image: Image.Image, x: int, y: int, text: str, ink: int = 1) -> None:
    """Paste exact glyph masks into the final indexed dot map, without filtering."""
    for char in text:
        image.paste(ink, (x, y), glyph(char))
        x += ADVANCE
