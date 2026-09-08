from __future__ import annotations

from PIL import Image

from .imaging import BLACK, RED, tiny_test_image


ESC = b"\x1b"
LF = b"\n"
PARTIAL_CUT = b"\x1dV\x01"  # GS V 1: A/B partial-cut autocutter


def encode_tiny_image_test() -> bytes:
    """Only two single-density 8-pin ESC * bands; no reset, color or cut."""
    colors = tiny_test_image().colors
    job = bytearray(b"TINY IMAGE\n")
    job += ESC + b"3\x10"  # 16 feed units between 8-pin bands
    for y in (0, 8):
        job += ESC + b"*\x00\x20\x00"  # mode 0, 32 dot columns
        job += _eight_dot_band(colors, y, BLACK)
        job += LF  # explicit print + feed, already verified for text
    job += ESC + b"2"  # restore default spacing
    job += LF * 4
    return bytes(job)


def _eight_dot_band(colors: Image.Image, y_start: int, color: int) -> bytes:
    """Pack one byte per x column; bits represent 8 vertical print-head pins."""
    width, height = colors.size
    pixels = colors.load()
    band = bytearray(width)
    for x in range(width):
        value = 0
        for bit in range(8):
            y = y_start + bit
            if y < height and pixels[x, y] == color:
                value |= 0x80 >> bit
        band[x] = value
    return bytes(band)


def encode_column_image(
    colors: Image.Image,
    *,
    density_mode: int = 1,
    line_spacing: int = 16,
    trailing_lines: int = 4,
) -> bytes:
    """Return the same stream as the band-aligned encoder, joined for callers."""
    return b"".join(encode_column_image_parts(colors, density_mode=density_mode,
                                           line_spacing=line_spacing, trailing_lines=trailing_lines))


def encode_column_image_parts(
    colors: Image.Image, *, density_mode: int = 1, line_spacing: int = 16,
    trailing_lines: int = 4,
) -> list[bytes]:
    """Complete 8-row bands, each <=825 bytes, with separate setup/finishing.

    Black and red are overprinted before advancing. Transfer boundaries never
    split an ESC * header from its declared bitmap payload in buffered mode.
    This preserves the encoded bytes; it is not proof against device data loss.
    """
    if colors.mode != "P":
        raise ValueError("Expected an indexed color image")
    if density_mode not in (0, 1):
        raise ValueError("TM-U220 8-dot density mode must be 0 or 1")
    if not 1 <= line_spacing <= 255:
        raise ValueError("Line spacing must be between 1 and 255")
    if not 0 <= trailing_lines <= 20:
        raise ValueError("Trailing lines must be between 0 and 20")

    width, height = colors.size
    if not 1 <= width <= 400 or (density_mode == 0 and width > 200):
        raise ValueError("Use at most 400 columns in mode 1, or 200 in mode 0")
    if not 1 <= height <= 1024:
        raise ValueError("Print height must be between 1 and 1024 dots; crop long images")
    if ((height + 7) // 8) * line_spacing > 2048:
        raise ValueError("Job would feed too much paper; reduce height or band feed units")
    width_header = bytes((width & 0xFF, (width >> 8) & 0xFF))
    command = bytearray()
    command += ESC + b"=\x01"  # select printer before initialization
    command += ESC + b"@"  # initialize
    command += ESC + b"3" + bytes((line_spacing,))

    parts = [bytes(command)]
    for y in range(0, height, 8):
        command = bytearray()
        black = _eight_dot_band(colors, y, BLACK)
        red = _eight_dot_band(colors, y, RED)

        if any(black):
            command += ESC + b"r\x00"
            command += ESC + b"*" + bytes((density_mode,)) + width_header + black
            command += ESC + b"J\x00"  # explicitly print, with no paper feed
        if any(red):
            command += ESC + b"r\x01"
            command += ESC + b"*" + bytes((density_mode,)) + width_header + red
            command += ESC + b"J\x00"

        command += ESC + b"J" + bytes((line_spacing,))
        parts.append(bytes(command))

    command = bytearray()
    command += ESC + b"r\x00"
    command += ESC + b"2"  # restore default line spacing
    command += LF * trailing_lines
    parts.append(bytes(command))
    return parts
