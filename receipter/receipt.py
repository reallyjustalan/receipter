"""Validated, ordered receipt composition in canonical printer-dot coordinates."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from .imaging import BLACK, CANONICAL_SCALE, PreparedImage, _palette, _preview, prepare_image
from .receipt_font import LINE_ROWS, draw_text, normalize, text_width

WIDTH = 400
MARGIN = 16
MAX_ROWS = 1024


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


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
    crop_zoom: float = Field(1, ge=1, le=4)
    crop_x: float = Field(.5, ge=0, le=1)
    crop_y: float = Field(.5, ge=0, le=1)
    fit: Literal['cover', 'contain'] = 'cover'


class Block(Model):
    id: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')


class Photo(Block):
    type: Literal['photo'] = 'photo'
    asset: str = Field(min_length=1, max_length=64)
    height: int = Field(240, ge=32, le=800)
    edits: ImageEdits = Field(default_factory=ImageEdits)
    caption: str = Field('', max_length=100)


class Header(Block):
    type: Literal['header'] = 'header'
    title: str = Field('THE PHOTO BOOTH', max_length=100)
    subtitle: str = Field('', max_length=160)
    asset: str | None = Field(None, min_length=1, max_length=64)
    height: int = Field(100, ge=32, le=800)
    edits: ImageEdits = Field(default_factory=lambda: ImageEdits(fit='contain'))


class Item(Model):
    label: str = Field(min_length=1, max_length=64)
    quantity: int = Field(1, ge=1, le=999)
    price: Decimal = Field(Decimal('0.00'), ge=0, max_digits=8, decimal_places=2)


class Footer(Block):
    type: Literal['footer'] = 'footer'
    items: list[Item] = Field(default_factory=list, max_length=12)
    currency: str = Field('$', max_length=4)
    date: str = Field('', max_length=40)
    reference: str = Field('', max_length=64)
    text: str = Field('THANK YOU', max_length=400)


class Text(Block):
    type: Literal['text'] = 'text'
    text: str = Field('Receipt text', max_length=600)


class Signature(Block):
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
    def __init__(self):
        self.image = Image.new('P', (WIDTH - 2 * MARGIN, MAX_ROWS), 0)
        self.image.putpalette(_palette().getpalette())
        self.draw = ImageDraw.Draw(self.image)
        self.y = 8

    def line(self, text: str, *, center=False):
        for paragraph in normalize(text).split('\n'):
            pending = ''
            for char in paragraph:
                if text_width(pending + char) > self.image.width:
                    self._line(pending, center)
                    pending = ''
                pending += char
            self._line(pending, center)

    def _line(self, text, center):
        x = (self.image.width - text_width(text)) // 2 if center else 0
        draw_text(self.image, x, round(self.y * CANONICAL_SCALE), text, BLACK)
        self.y += round(LINE_ROWS / CANONICAL_SCALE)
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
        aw = text_width(amount)
        if '\n' in amount or aw > self.image.width:
            raise ValueError('Receipt amount is too wide or contains a newline')
        if '\n' in label or text_width(label) + aw + 20 > self.image.width:
            self.line(label)
            label = ''
        row = round(self.y * CANONICAL_SCALE)
        draw_text(self.image, 0, row, label, BLACK)
        draw_text(self.image, self.image.width - aw, row, amount, BLACK)
        self.y += round(LINE_ROWS / CANONICAL_SCALE)
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
    if sum(block.type == 'photo' for block in document.blocks) > 3:
        raise ValueError('A receipt supports up to three photos')
    pieces = []
    metadata = []
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
        text = TextCanvas()
        if isinstance(block, Header):
            if block.title:
                text.line(block.title, center=True)
            if block.subtitle:
                text.line(block.subtitle, center=True)
            text.rule()
        elif isinstance(block, Photo) and block.caption:
            text.line(block.caption, center=True)
        elif isinstance(block, Footer):
            text.rule()
            total = Decimal('0.00')
            for item in block.items:
                cost = item.price * item.quantity
                total += cost
                text.amount(f'{item.quantity} × {item.label}', f'{block.currency}{cost:.2f}')
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
    return PreparedImage(colors, _preview(colors)), metadata
