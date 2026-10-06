"""Validated, ordered receipt composition in canonical printer-dot coordinates."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from .imaging import BLACK, CANONICAL_SCALE, PreparedImage, _palette, _preview, prepare_image
from .receipt_font import ADVANCE, LINE_ROWS, draw_text, glyph, normalize, text_width

WIDTH = 400
MARGIN = 16
MAX_ROWS = 1024


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


Unit = Annotated[float, Field(ge=0, le=1)]


class EraserStroke(Model):
    # Source-image coordinates, before crop/rotation; radius / longest side.
    radius: float = Field(ge=.001, le=.25)
    points: list[tuple[Unit, Unit]] = Field(min_length=1, max_length=256)


class ImageEdits(Model):
    rotation: Literal[0, 90, 180, 270] = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    brightness: float = Field(1, ge=.2, le=2)
    contrast: float = Field(1, ge=.2, le=2)
    threshold: int = Field(128, ge=1, le=255)
    dither: bool = True
    assignment: Literal['auto', 'black', 'red', 'swap'] = 'auto'
    black_ink: float = Field(100, ge=0, le=100)
    red_ink: float = Field(100, ge=0, le=100)
    crop_zoom: float = Field(1, ge=.25, le=4)
    crop_x: float = Field(.5, ge=0, le=1)
    crop_y: float = Field(.5, ge=0, le=1)
    fit: Literal['cover', 'contain'] = 'cover'
    eraser_strokes: list[EraserStroke] = Field(default_factory=list, max_length=100)


class Block(Model):
    id: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')


class TextStyle(Block):
    font_size: Literal['small', 'normal', 'large'] = 'normal'


class Photo(TextStyle):
    type: Literal['photo'] = 'photo'
    asset: str = Field(min_length=1, max_length=64)
    height: int = Field(240, ge=32, le=800)
    edits: ImageEdits = Field(default_factory=ImageEdits)
    caption: str = Field('', max_length=100)


class Header(TextStyle):
    type: Literal['header'] = 'header'
    title: str = Field('THE PHOTO BOOTH', max_length=100)
    title_font: Literal['custom', 'native'] = 'custom'
    subtitle: str = Field('', max_length=160)
    asset: str | None = Field(None, min_length=1, max_length=64)
    height: int = Field(100, ge=32, le=800)
    edits: ImageEdits = Field(default_factory=lambda: ImageEdits(fit='contain'))


class Item(Model):
    label: str = Field(min_length=1, max_length=64)
    quantity: int = Field(1, ge=1, le=999)
    quantity_mode: Literal['manual', 'photos'] = 'manual'
    price: Decimal = Field(Decimal('0.00'), ge=0, max_digits=8, decimal_places=2)


class Footer(TextStyle):
    type: Literal['footer'] = 'footer'
    items: list[Item] = Field(default_factory=list, max_length=12)
    currency: str = Field('$', max_length=4)
    date: str = Field('', max_length=40)
    reference: str = Field('', max_length=64)
    text: str = Field('THANK YOU', max_length=400)


class Text(TextStyle):
    type: Literal['text'] = 'text'
    text: str = Field('Receipt text', max_length=600)


class Signature(TextStyle):
    type: Literal['signature'] = 'signature'
    label: str = Field('Signature', max_length=80)


class Spacer(Block):
    type: Literal['spacer'] = 'spacer'
    height: int = Field(24, ge=8, le=200)


Section = Annotated[Header | Photo | Footer | Text | Signature | Spacer, Field(discriminator='type')]


class Receipt(Model):
    blocks: list[Section] = Field(min_length=1, max_length=16)


class TextCanvas:
    """Draw glyphs at printer resolution; keep the section cursor in layout units."""
    def __init__(self, font_size='normal'):
        self.image = Image.new('P', (WIDTH - 2 * MARGIN, MAX_ROWS), 0)
        self.image.putpalette(_palette().getpalette())
        self.draw = ImageDraw.Draw(self.image)
        self.y = 8
        self.font_size = font_size
        self.native = True
        self.runs = []

    @property
    def scale(self):
        return 2 if self.native and self.font_size == 'large' else 1

    @property
    def small(self):
        return self.native and self.font_size == 'small'

    @property
    def advance(self):
        # Profile Font B has 56 columns versus Font A's 42 (3/4 width).
        # Keep the existing A metrics; this remains an approximate ROM preview.
        return 9 if self.small else ADVANCE * self.scale

    @property
    def columns(self):
        return self.image.width // self.advance

    def width(self, text):
        if self.small:
            return max(0, (len(text) - 1) * self.advance + 7)
        return text_width(text) * self.scale

    def glyphs(self, x, row, text):
        if self.small:
            for char in text:
                self.image.paste(BLACK, (x, row), glyph(char).resize((7, 9), Image.Resampling.NEAREST))
                x += self.advance
        elif self.scale == 1:
            draw_text(self.image, x, row, text, BLACK)
        elif text:
            glyphs = Image.new('P', (text_width(text), LINE_ROWS), 0)
            glyphs.putpalette(self.image.getpalette())
            draw_text(glyphs, 0, 0, text, BLACK)
            self.image.paste(glyphs.resize((glyphs.width * 2, glyphs.height * 2),
                                          Image.Resampling.NEAREST), (x, row))

    def record(self, text, row, center=False):
        if self.native:
            from .escpos import encode_native_text
            self.runs.append((row, row + LINE_ROWS * self.scale,
                              encode_native_text([text], font_size=self.font_size,
                                                 center=center, padding=False)))

    def line(self, text: str, *, center=False):
        for paragraph in normalize(text).split('\n'):
            pending = ''
            for char in paragraph:
                if (self.width(pending + char) > self.image.width
                        or (self.small and len(pending + char) > self.columns)):
                    self._line(pending, center)
                    pending = ''
                pending += char
            self._line(pending, center)

    def _line(self, text, center):
        x = (self.image.width - self.width(text)) // 2 if center else 0
        row = round(self.y * CANONICAL_SCALE)
        self.glyphs(x, row, text)
        self.record(text, row, center)
        self.y += round(LINE_ROWS * self.scale / CANONICAL_SCALE)
        if self.y > 2000:
            raise ValueError('Text section is too long')

    def rule(self):
        self.y += 10
        row = round(self.y * CANONICAL_SCALE)
        self.draw.line((0, row, self.image.width - 1, row), fill=BLACK, width=1)
        self.y += 14

    def amount(self, label, amount):
        # Reserve a separate row if the label cannot fit alongside the amount.
        label, amount = normalize(label), normalize(amount)
        aw = self.width(amount)
        if '\n' in amount or aw > self.image.width:
            raise ValueError('Receipt amount is too wide or contains a newline')
        columns = self.columns
        if ('\n' in label or len(label) + len(amount) + 2 > columns):
            self.line(label)
            label = ''
        row = round(self.y * CANONICAL_SCALE)
        self.glyphs(0, row, label)
        self.glyphs(self.image.width - aw, row, amount)
        self.record(label + ' ' * max(0, columns - len(label) - len(amount)) + amount, row)
        self.y += round(LINE_ROWS * self.scale / CANONICAL_SCALE)
        if self.y > 2000:
            raise ValueError('Text section is too long')

    def prepared(self):
        # Already canonical: never resize/threshold these glyphs as an image.
        rows = round((self.y + 8) * CANONICAL_SCALE)
        if rows > MAX_ROWS:
            raise ValueError('Text section is too long')
        return self.image.crop((0, 0, self.image.width, rows))


def render_receipt(document: Receipt, assets: dict[str, bytes]) -> tuple[PreparedImage, list[dict]]:
    ids = [block.id for block in document.blocks]
    if len(set(ids)) != len(ids):
        raise ValueError('Section IDs must be unique')
    photo_count = sum(block.type == 'photo' for block in document.blocks)
    if photo_count > 3:
        raise ValueError('A receipt supports up to three photos')
    pieces = []
    metadata = []
    native_text = []
    y = 8
    for block in document.blocks:
        start = y
        section = []
        if isinstance(block, (Photo, Header)) and block.asset:
            if block.asset not in assets:
                raise ValueError(f'Missing image for section {block.id}')
            section.append(prepare_image(assets[block.asset], WIDTH - 2 * MARGIN,
                                         CANONICAL_SCALE, frame_height=block.height,
                                         **block.edits.model_dump()).colors)
        text = TextCanvas(getattr(block, 'font_size', 'normal'))
        if isinstance(block, Header):
            if block.title:
                text.native = block.title_font == 'native'
                text.line(block.title, center=True)
                text.native = True
            if block.subtitle:
                text.line(block.subtitle, center=True)
            text.rule()
        elif isinstance(block, Photo) and block.caption:
            text.line(block.caption, center=True)
        elif isinstance(block, Footer):
            text.rule()
            total = Decimal('0.00')
            for item in block.items:
                quantity = photo_count if item.quantity_mode == 'photos' else item.quantity
                if quantity == 0:
                    continue  # Automatic photo items are omitted when there are no photos.
                cost = item.price * quantity
                total += cost
                # ASCII avoids printer-dependent code-page mappings for U+00D7.
                text.amount(f'{quantity} x {item.label}', f'{block.currency}{cost:.2f}')
            text.rule()
            text.amount('TOTAL', f'{block.currency}{total:.2f}')
            text.rule()
            if block.date:
                text.line(block.date)
            if block.reference:
                text.line(f'REF: {block.reference}')
            if block.text:
                text.line(block.text, center=True)
        elif isinstance(block, Text):
            text.line(block.text)
        elif isinstance(block, Signature):
            text.y += 72
            text.rule()
            text.line(block.label, center=True)
        elif isinstance(block, Spacer):
            text.y += block.height
        if text.y > 8:
            text_top = y + sum(image.height for image in section)
            native_text.extend((text_top + start, text_top + end, commands)
                               for start, end, commands in text.runs)
            section.append(text.prepared())
        for image in section:
            pieces.append((y, image))
            y += image.height
        y += 8
        metadata.append({'id': block.id, 'y': start, 'height': y - start})
    y += 8
    if y > MAX_ROWS:
        raise ValueError(f'Receipt is {y} rows; maximum is {MAX_ROWS}. Shorten photos, text or spacing.')
    colors = Image.new('P', (WIDTH, y), 0)
    colors.putpalette(_palette().getpalette())
    for top, image in pieces:
        colors.paste(image, (MARGIN, top))
    return PreparedImage(colors, _preview(colors), tuple(native_text)), metadata
