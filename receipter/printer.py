from __future__ import annotations

import os
import logging
import threading
from dataclasses import asdict, dataclass

import usb.core
import usb.util
from escpos.printer import Usb

from .profile import MODEL_NAME, PROFILE_NAME, printer_profile


DEFAULT_VENDOR_ID = int(os.getenv("PRINTER_VENDOR_ID", "0x04b8"), 0)
DEFAULT_PRODUCT_ID = int(os.getenv("PRINTER_PRODUCT_ID", "0x0202"), 0)
DEFAULT_INTERFACE = int(os.getenv("PRINTER_INTERFACE", "0"), 0)
DEFAULT_OUT_ENDPOINT = int(os.getenv("PRINTER_OUT_ENDPOINT", "0x01"), 0)

_print_lock = threading.Lock()
_usb_lock = threading.Lock()
_state_lock = threading.Lock()
_stopped = threading.Event()
_generation = 0
_cached_usb_status = {"connected": False, "devices": []}
ASCII_DIAGNOSTIC = b"0123456789\nHELLO WORLD\n\n\n\n"
MAX_JOB_BYTES = 2 * 1024 * 1024  # Memory guard, not a receipt-size/USB-buffer limit.
DEFAULT_CHUNK_SIZE = 1024
BYTE_DELAY_SECONDS = 0.1  # Explicit 1/8-byte diagnostic modes only.
BUFFERED_TIMEOUT_MS = 5_000


class NoResetUsb(Usb):
    """Verified transport: keep the currently configured USB device intact."""

    def _configure_usb(self) -> None:
        # Fail if unconfigured; do not issue SET_CONFIGURATION or USB reset.
        self.device.get_active_configuration()
        usb.util.claim_interface(self.device, DEFAULT_INTERFACE)


class PrintStopped(RuntimeError):
    pass


def print_state() -> dict:
    return {"stopped": _stopped.is_set(), "printing": _print_lock.locked()}


def interrupt() -> dict:
    global _generation
    with _state_lock:
        _generation += 1
        _stopped.set()
    return {"ok": True, "stopped": True, "message":
            "Remaining host data cancelled; new jobs blocked. Switch the printer off "
            "to clear buffered paper feeding, then power on before resuming."}


def resume() -> dict:
    with _state_lock:
        if _print_lock.locked():
            raise RuntimeError("Wait for the interrupted USB write to finish")
        _stopped.clear()
    return {"ok": True, "stopped": False}


def job_token() -> int:
    with _state_lock:
        if _stopped.is_set():
            raise PrintStopped("Printing stopped. Power-cycle the printer, then resume.")
        return _generation


def _check_job(token: int) -> None:
    with _state_lock:
        if _stopped.is_set() or token != _generation:
            raise PrintStopped("Job interrupted; remaining data discarded")


@dataclass(frozen=True)
class UsbDeviceInfo:
    vendor_id: str
    product_id: str
    manufacturer: str
    product: str
    is_target: bool


def _string(device, index: int) -> str:
    if not index:
        return ""
    try:
        return usb.util.get_string(device, index) or ""
    except Exception:
        return "(unavailable)"


def usb_devices() -> list[dict]:
    result = []
    for device in usb.core.find(find_all=True):
        info = UsbDeviceInfo(
            vendor_id=f"0x{device.idVendor:04x}",
            product_id=f"0x{device.idProduct:04x}",
            manufacturer=_string(device, device.iManufacturer),
            product=_string(device, device.iProduct),
            is_target=(
                device.idVendor == DEFAULT_VENDOR_ID
                and device.idProduct == DEFAULT_PRODUCT_ID
            ),
        )
        result.append(asdict(info))
    return result


def target_status() -> dict:
    global _cached_usb_status
    # Descriptor/string queries open USB handles too. Never do them while a
    # print owns the device; serve the last detection snapshot instead.
    cached = not _usb_lock.acquire(blocking=False)
    if not cached:
        try:
            device = usb.core.find(idVendor=DEFAULT_VENDOR_ID, idProduct=DEFAULT_PRODUCT_ID)
            devices = usb_devices()
            message = ''
            if device is None:
                message = (f'No USB printer with IDs {DEFAULT_VENDOR_ID:04x}:{DEFAULT_PRODUCT_ID:04x}. '
                           'Connect and power on the printer on the Mac running the server.')
                epsons = [d for d in devices if d['vendor_id'] == '0x04b8']
                if epsons:
                    message += ' Other Epson USB IDs found: ' + ', '.join(
                        f"{d['vendor_id']}:{d['product_id']}" for d in epsons) + '. Check PRINTER_PRODUCT_ID.'
            _cached_usb_status = {"connected": device is not None, "devices": devices,
                                  "detection_error": message}
        except usb.core.NoBackendError:
            _cached_usb_status = {"connected": False, "devices": [], "detection_error":
                                  'USB backend missing. On the server Mac, run brew install libusb, then restart Receipter.'}
        except usb.core.USBError as exc:
            _cached_usb_status = {"connected": False, "devices": [], "detection_error":
                                  f'USB access failed: {exc}. Close other printer apps and check the cable/adapter.'}
        finally:
            _usb_lock.release()
    return {
        **_cached_usb_status,
        **print_state(),
        "usb_detection_cached": cached,
        "transport": "buffered / up to 1024 bytes / image bands aligned / no delay or reset",
        "default_chunk_size": DEFAULT_CHUNK_SIZE,
        "write_timeout_ms": BUFFERED_TIMEOUT_MS,
        "max_job_bytes": MAX_JOB_BYTES,
        "model": MODEL_NAME,
        "profile": PROFILE_NAME,
        "cutter": "partial (A variant)",
        "vendor_id": f"0x{DEFAULT_VENDOR_ID:04x}",
        "product_id": f"0x{DEFAULT_PRODUCT_ID:04x}",
        "interface": DEFAULT_INTERFACE,
        "out_endpoint": f"0x{DEFAULT_OUT_ENDPOINT:02x}",
    }


def send_raw(data: bytes | list[bytes], timeout_ms: int | None = None, *, token: int | None = None,
             chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
    """Stream a job with USB backpressure; cancellation between bounded writes.

    Default: 1 KiB writes with no sleeps. Explicit 1/8-byte settings retain the
    confirmed diagnostic pacing. Never resend bytes after a partial/error write.
    """
    if chunk_size not in (1, 8, DEFAULT_CHUNK_SIZE):
        raise ValueError("USB write size must be 1024 (buffered), 1 or 8 (diagnostic)")
    delay_seconds = BYTE_DELAY_SECONDS if chunk_size in (1, 8) else 0
    if timeout_ms is None:
        timeout_ms = 500 if delay_seconds else BUFFERED_TIMEOUT_MS
    parts = [data] if isinstance(data, bytes) else data
    if not parts or not any(parts):
        raise ValueError("Refusing to send an empty print job")
    if not all(isinstance(part, bytes) for part in parts):
        raise ValueError("Print job parts must be bytes")
    if sum(map(len, parts)) > MAX_JOB_BYTES:
        raise ValueError(f"Job exceeds the {MAX_JOB_BYTES // 1024 // 1024} MiB host memory limit")
    if token is None:
        token = job_token()
    _check_job(token)
    if not _print_lock.acquire(blocking=False):
        raise RuntimeError("Another print is active; jobs are not queued")

    owns_usb = False
    try:
        while not _usb_lock.acquire(timeout=0.1):
            _check_job(token)
        owns_usb = True
        _check_job(token)
        if DEFAULT_INTERFACE != 0:
            raise ValueError("python-escpos USB backend currently requires interface 0")
        transport = NoResetUsb(
            idVendor=DEFAULT_VENDOR_ID,
            idProduct=DEFAULT_PRODUCT_ID,
            in_ep=0x82,
            out_ep=DEFAULT_OUT_ENDPOINT,
            timeout=timeout_ms,
            profile=printer_profile(),
        )
        try:
            # Retain no-reset/exclusive access while allowing the USB driver
            # to packetize buffered writes and apply device backpressure.
            transport.open()
            device = transport.device
            _check_job(token)
            total = 0
            for part in parts:
                for offset in range(0, len(part), chunk_size):
                    _check_job(token)
                    chunk = part[offset:offset + chunk_size]
                    written = device.write(DEFAULT_OUT_ENDPOINT, chunk, timeout=timeout_ms)
                    if written != len(chunk):
                        raise RuntimeError(f"Short USB write: {written} of {len(chunk)} bytes")
                    total += written
                    if delay_seconds:
                        _stopped.wait(delay_seconds)
            logging.getLogger(__name__).info("USB job: %d bytes in %d parts", total, len(parts))
            _check_job(token)
            return total
        except Exception:
            # A partial graphics command leaves the parser in an unknown state.
            interrupt()
            raise
        finally:
            transport.close()
    finally:
        if owns_usb:
            _usb_lock.release()
        _print_lock.release()
