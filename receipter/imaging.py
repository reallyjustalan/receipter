from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageEnhance, ImageOps
from defusedxml import ElementTree
import resvg_py
import re

CANONICAL_SCALE = 0.5
WORKING_IMAGE_EDGE = 4096


def load_source(raw: bytes, raster_width: int = 1200) -> Image.Image:
    """Decode into a bounded working copy; never resolve external SVG resources.

    JPEG draft decoding reduces memory before loading the full-resolution pixels.
    Pillow's decompression-bomb protections remain enabled for pathological inputs.
    """
    try:
        raw = raw.removeprefix(b'\xef\xbb\xbf')
        if raw.lstrip().startswith(b'<'):
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('SVG exceeds 2 MB')
            root = ElementTree.fromstring(raw)
            if root.tag.split('}')[-1] != 'svg':
                raise ValueError('Expected an SVG root')
            for node in root.iter():
                if node.tag.split('}')[-1] in ('image', 'feImage', 'foreignObject', 'script', 'style'):
                    raise ValueError('SVG must use self-contained vector shapes (no images, scripts or stylesheets)')
                for key, value in node.attrib.items():
                    if key.split('}')[-1] == 'href' and not value.startswith('#'):
                        raise ValueError('External SVG references are not allowed')
                    if '@import' in value or any(not ref.strip(' \"\'').startswith('#')
                                                for ref in re.findall(r'url\((.*?)\)', value, re.I)):
                        raise ValueError('External SVG resources are not allowed')
            # A bounded square render also bounds pathological SVG aspect ratios.
            raw = resvg_py.svg_to_bytes(svg_string=ElementTree.tostring(root, encoding='unicode'),
                                       width=raster_width, height=raster_width,
                                       skip_system_fonts=True)
        with Image.open(BytesIO(raw)) as source:
            # draft() is a decoder hint (JPEG/MPO); thumbnail handles other formats
            # and JPEG dimensions that cannot be reached by decoder scaling alone.
            scale = min(1, WORKING_IMAGE_EDGE / max(source.size))
            target = tuple(max(1, round(side * scale)) for side in source.size)
            source.draft(None, target)
            source.thumbnail((WORKING_IMAGE_EDGE, WORKING_IMAGE_EDGE), Image.Resampling.LANCZOS)
            return ImageOps.exif_transpose(source).convert('RGBA')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('The uploaded file is not a readable raster image or SVG') from exc


WHITE = 0
BLACK = 1
RED = 2

# Ordered thinning removes dots without converting black ink to red or vice versa.
_BAYER_8 = (
    (0, 48, 12, 60, 3, 51, 15, 63), (32, 16, 44, 28, 35, 19, 47, 31),
    (8, 56, 4, 52, 11, 59, 7, 55), (40, 24, 36, 20, 43, 27, 39, 23),
    (2, 50, 14, 62, 1, 49, 13, 61), (34, 18, 46, 30, 33, 17, 45, 29),
    (10, 58, 6, 54, 9, 57, 5, 53), (42, 26, 38, 22, 41, 25, 37, 21),
)


@dataclass(frozen=True)
class PreparedImage:
    colors: Image.Image
    preview_png: bytes
    # (start row, end row, native commands); preview glyphs are not printed here.
    native_text: tuple[tuple[int, int, bytes], ...] = ()

    @property
    def width(self) -> int:
        return self.colors.width

    @property
    def height(self) -> int:
        return self.colors.height


def _palette() -> Image.Image:
    palette = Image.new("P", (1, 1))
    # Remaining entries must be present, but are deliberately also white.
    palette.putpalette([255, 255, 255, 0, 0, 0, 210, 0, 0] + [255, 255, 255] * 253)
    return palette


def prepare_image(
    raw: bytes,
    width: int = 400,
    vertical_scale: float = 0.5,
    two_color: bool = True,
    dither: bool = True,
    *,
    rotation: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
    brightness: float = 1.0,
    contrast: float = 1.0,
    black_ink: float = 100,
    red_ink: float = 100,
    threshold: int = 128,
    assignment: str = 'auto',
    crop_zoom: float = 1,
    crop_x: float = 0.5,
    crop_y: float = 0.5,
    frame_height: int | None = None,
    fit: str = 'cover',
    eraser_strokes: list[dict] | None = None,
) -> PreparedImage:
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180 or 270 degrees clockwise")
    if not 0.2 <= brightness <= 2.0 or not 0.2 <= contrast <= 2.0:
        raise ValueError("Brightness and contrast must be between 0.2 and 2.0")
    if not 0 <= black_ink <= 100 or not 0 <= red_ink <= 100:
        raise ValueError("Ink amounts must be between 0 and 100 percent")
    if not raw:
        raise ValueError("Choose an image first")
    if not 32 <= width <= 576:
        raise ValueError("Width must be between 32 and 576 dots")
    if not 0.1 <= vertical_scale <= 2.0:
        raise ValueError("Vertical scale must be between 0.1 and 2.0")

    if not 1 <= threshold <= 255 or assignment not in ('auto', 'black', 'red', 'swap'):
        raise ValueError('Invalid threshold or ink assignment')
    if not .25 <= crop_zoom <= 4 or not 0 <= crop_x <= 1 or not 0 <= crop_y <= 1:
        raise ValueError('Invalid crop position or zoom')
    if fit not in ('cover', 'contain') or (frame_height is not None and not 32 <= frame_height <= 800):
        raise ValueError('Invalid image frame')
    source = load_source(raw)

    background = Image.new("RGBA", source.size, "white")
    background.alpha_composite(source)
    source = background.convert("RGB")
    coverage = Image.new('L', source.size, 255)
    if eraser_strokes:
        draw = ImageDraw.Draw(coverage)
        for stroke in eraser_strokes:
            radius = stroke['radius'] * max(source.size)
            points = [(x * source.width, y * source.height) for x, y in stroke['points']]
            if len(points) > 1:
                draw.line(points, fill=0, width=max(1, round(radius * 2)))
            for x, y in points:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=0)

    def frame(image, fill):
        if rotation:
            image = image.rotate(-rotation, expand=True)
        if flip_horizontal:
            image = ImageOps.mirror(image)
        if flip_vertical:
            image = ImageOps.flip(image)
        if frame_height is None:
            return image
        target = (width, frame_height)
        if fit == 'contain' or crop_zoom < 1:
            if fit == 'contain':
                fitted = ImageOps.contain(image, target, Image.Resampling.LANCZOS)
                x, y = .5, .5
            else:
                scale = max(width / image.width, frame_height / image.height) * crop_zoom
                fitted = image.resize((max(1, round(image.width * scale)),
                                       max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
                x, y = crop_x, crop_y
            result = Image.new(image.mode, target, fill)
            result.paste(fitted, (round((width - fitted.width) * x),
                                  round((frame_height - fitted.height) * y)))
            return result
        ratio = width / frame_height
        cw = min(image.width, image.height * ratio) / crop_zoom
        ch = cw / ratio
        left = (image.width - cw) * crop_x
        top = (image.height - ch) * crop_y
        return image.resize(target, Image.Resampling.LANCZOS,
                            box=(left, top, left + cw, top + ch))

    source = frame(source, 'white')
    coverage = frame(coverage, 0)
    source = ImageEnhance.Brightness(source).enhance(brightness)
    source = ImageEnhance.Contrast(source).enhance(contrast)

    if threshold != 128:
        source = source.point([max(0, min(255, i + 128 - threshold)) for i in range(256)] * 3)
    # Erased pixels and zoom-out padding stay paper-white even with dark tones.
    source = Image.composite(source, Image.new('RGB', source.size, 'white'), coverage)
    if assignment in ('black', 'red'):
        two_color = False

    height = max(1, round(source.height * width / source.width * vertical_scale))
    if height > 1024:
        raise ValueError("Prepared image exceeds 1024 rows; crop it or reduce vertical scale")
    resized = source.resize((width, height), Image.Resampling.LANCZOS)
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE

    if two_color:
        colors = resized.quantize(palette=_palette(), dither=dither_mode)
    else:
        mono = resized.convert("L").convert("1", dither=dither_mode)
        colors = Image.new("P", mono.size, WHITE)
        colors.putpalette(_palette().getpalette())
        # In mode 1, white=255 and black=0.
        for y in range(mono.height):
            for x in range(mono.width):
                colors.putpixel((x, y), WHITE if mono.getpixel((x, y)) else BLACK)

    # Work on final indexed dots: keep the ribbon channels independent. Using
    # the same deterministic mask for preview and print avoids random differences.
    pixels = colors.load()
    for y in range(colors.height):
        for x in range(colors.width):
            color = pixels[x, y]
            if color not in (BLACK, RED):
                pixels[x, y] = WHITE
                continue
            if assignment == 'swap':
                color = RED if color == BLACK else BLACK
            elif assignment == 'red':
                color = RED
            pixels[x, y] = color
            amount = black_ink if color == BLACK else red_ink
            if (_BAYER_8[y % 8][x % 8] + 0.5) * 100 / 64 >= amount:
                pixels[x, y] = WHITE

    return PreparedImage(colors=colors, preview_png=_preview(colors))


def tiny_test_image() -> PreparedImage:
    """Two 8-pin bands: small black frame, solid bar, and diagonal."""
    image = Image.new("P", (32, 16), WHITE)
    image.putpalette(_palette().getpalette())
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 31, 15), outline=BLACK)
    draw.rectangle((4, 4, 8, 11), fill=BLACK)
    draw.line((14, 3, 27, 12), fill=BLACK)
    return PreparedImage(image, _preview(image))


def calibration_image(width: int = 400) -> PreparedImage:
    if not 100 <= width <= 576:
        raise ValueError("Calibration width must be between 100 and 576 dots")

    height = 128
    image = Image.new("P", (width, height), WHITE)
    image.putpalette(_palette().getpalette())
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, width - 1, height - 1), outline=BLACK)
    draw.rectangle((3, 3, width // 2 - 2, 30), fill=BLACK)
    draw.rectangle((width // 2 + 1, 3, width - 4, 30), fill=RED)

    for x in range(0, width, 10):
        tick = 16 if x % 50 == 0 else 8
        draw.line((x, 38, x, 38 + tick), fill=BLACK)

    for y in range(64, 96, 4):
        draw.line((4, y, width - 5, y), fill=BLACK if (y // 4) % 2 else RED)

    cell = 8
    for y in range(100, 124, cell):
        for x in range(4, width - 4, cell):
            if (x // cell + y // cell) % 2 == 0:
                draw.rectangle((x, y, min(x + cell - 1, width - 5), min(y + cell - 1, 123)), fill=BLACK)
            else:
                draw.rectangle((x, y, min(x + cell - 1, width - 5), min(y + cell - 1, 123)), fill=RED)

    return PreparedImage(colors=image, preview_png=_preview(image))


def _preview(colors: Image.Image) -> bytes:
    rgb = colors.convert("RGB")
    # Dot-matrix pixels need enlargement to remain visible in a browser.
    preview = rgb.resize((rgb.width * 2, rgb.height * 2), Image.Resampling.NEAREST)
    output = BytesIO()
    preview.save(output, "PNG")
    return output.getvalue()
