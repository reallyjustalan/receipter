"""HEIC/HEIF conversion using the server Mac's built-in image tools."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HEIF_EXTENSIONS = {'.heic', '.heif'}
_HEIF_BRANDS = {b'heic', b'heix', b'hevc', b'hevx', b'heim', b'heis', b'hevm', b'hevs', b'mif1', b'msf1'}


def is_heif(raw: bytes) -> bool:
    if len(raw) < 16 or raw[4:8] != b'ftyp':
        return False
    size = int.from_bytes(raw[:4], 'big')
    brands = {raw[8:12]} | {raw[i:i + 4] for i in range(16, min(size, len(raw), 256), 4)}
    # AVIF uses the same container but is not HEIC.
    return bool(brands & _HEIF_BRANDS) and not brands & {b'avif', b'avis'}


def convert_heif(raw: bytes, max_edge: int) -> bytes:
    if sys.platform != 'darwin':
        raise ValueError('HEIC/HEIF conversion requires the Receipter server to run on macOS. Export this photo as JPEG on other systems.')
    with tempfile.TemporaryDirectory(prefix='receipter-heic-') as temp:
        source = Path(temp) / 'source.heic'
        output = Path(temp) / 'working.jpg'
        source.write_bytes(raw)
        try:
            query = subprocess.run(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(source)],
                                   capture_output=True, timeout=10, check=False)
            dimensions = [int(value) for value in re.findall(rb'pixel(?:Width|Height):\s*(\d+)', query.stdout)] if not query.returncode else []
            if len(dimensions) != 2 or min(dimensions) < 1:
                raise ValueError('macOS could not read this HEIC/HEIF photo. The transfer may be incomplete.')
            # sips -Z upscales small inputs too, so only request resampling when needed.
            resize = ['--resampleHeightWidthMax', str(max_edge)] if max(dimensions) > max_edge else []
            result = subprocess.run(
                ['/usr/bin/sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '90',
                 *resize, str(source), '--out', str(output)],
                capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('HEIC conversion timed out. Try exporting this photo as JPEG.') from exc
        except OSError as exc:
            raise ValueError('macOS image conversion is unavailable. Try exporting this photo as JPEG.') from exc
        if result.returncode or not output.is_file() or not output.stat().st_size:
            raise ValueError('macOS could not decode this HEIC/HEIF photo. The transfer may be incomplete; try a JPEG export if it persists.')
        if output.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Converted HEIC image exceeds 20 MB. Try a JPEG export.')
        return output.read_bytes()
