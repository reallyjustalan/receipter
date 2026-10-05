"""Local, people-only masks from Apple Vision. Native imports stay macOS-only."""
from io import BytesIO
import sys

from PIL import Image, ImageChops

from .imaging import load_source


class BackgroundUnavailable(RuntimeError):
    pass


def _person_mask(source: Image.Image) -> Image.Image:
    if sys.platform != 'darwin':
        raise BackgroundUnavailable('People background removal requires a Mac running macOS 12 or later.')
    try:
        import Vision
        import Quartz
        from Foundation import NSData, NSMutableData, NSAutoreleasePool
    except ImportError as exc:
        raise BackgroundUnavailable('Apple Vision is not installed. Run uv sync on the Mac and restart Receipter.') from exc
    if not hasattr(Vision, 'VNGeneratePersonSegmentationRequest'):
        raise BackgroundUnavailable('People background removal requires macOS 12 or later.')

    pool = NSAutoreleasePool.alloc().init()
    try:
        # Bound inference cost without changing the returned photo's dimensions.
        sample = source.copy()
        sample.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        data = BytesIO()
        sample.convert('RGB').save(data, 'PNG')
        raw = data.getvalue()
        request = Vision.VNGeneratePersonSegmentationRequest.alloc().initWithCompletionHandler_(None)
        request.setQualityLevel_(Vision.VNGeneratePersonSegmentationRequestQualityLevelAccurate)
        request.setOutputPixelFormat_(Quartz.kCVPixelFormatType_OneComponent8)
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
            NSData.dataWithBytes_length_(raw, len(raw)), None)
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise BackgroundUnavailable('Apple Vision could not process this image. Try another photo.')
        results = request.results()
        if not results:
            raise ValueError('No people detected. The original image has been kept.')
        mask = Quartz.CIImage.imageWithCVPixelBuffer_(results[0].pixelBuffer())
        context = Quartz.CIContext.contextWithOptions_({})
        cg_image = context.createCGImage_fromRect_(mask, mask.extent())
        output = NSMutableData.data()
        destination = Quartz.CGImageDestinationCreateWithData(output, 'public.png', 1, None)
        Quartz.CGImageDestinationAddImage(destination, cg_image, None)
        if not Quartz.CGImageDestinationFinalize(destination):
            raise BackgroundUnavailable('Apple Vision could not encode the person mask.')
        return Image.open(BytesIO(bytes(output))).convert('L')
    except (ValueError, BackgroundUnavailable):
        raise
    except Exception as exc:
        raise BackgroundUnavailable('Apple Vision failed. Try another photo or restart Receipter.') from exc
    finally:
        del pool


def remove_background(raw: bytes) -> bytes:
    source = load_source(raw)  # Shared image limits and EXIF orientation handling.
    mask = _person_mask(source)
    if mask.getextrema()[1] < 128:
        raise ValueError('No people detected. The original image has been kept.')
    mask = mask.resize(source.size, Image.Resampling.LANCZOS)
    # Preserve existing transparency, soft hair edges, and the original framing.
    source.putalpha(ImageChops.multiply(source.getchannel('A'), mask))
    output = BytesIO()
    source.save(output, 'PNG')
    return output.getvalue()
