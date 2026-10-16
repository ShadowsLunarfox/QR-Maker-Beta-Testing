"""Decode the final raster or SVG export and compare its exact payload."""

import io
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class ScanResult:
    ok: bool
    message: str


class ScanCheckError(ValueError):
    def __init__(self, message, data):
        super().__init__(message)
        self.data = data


def check_image(image, expected):
    import zxingcpp

    rgba = image.convert("RGBA")
    base = Image.new("RGBA", rgba.size, "white")
    rgb = Image.alpha_composite(base, rgba).convert("RGB")
    result = zxingcpp.read_barcode(rgb, formats=zxingcpp.BarcodeFormat.QRCode)
    if result is None:
        return ScanResult(False, "Could not decode this design. Try darker QR colors, a smaller logo, or a larger image.")
    # Bytes avoid reader display conventions for multiline text and vCards.
    if result.bytes != expected.encode("utf-8"):
        return ScanResult(False, "The decoded content does not match this design. Adjust the design and check again.")
    return ScanResult(True, "Scan check passed: the decoded content matches.")


def check_export(data, suffix, expected):
    if suffix.lower() == ".svg":
        import resvg_py

        data = resvg_py.svg_to_bytes(svg_string=data.decode("utf-8"), skip_system_fonts=True)
    with Image.open(io.BytesIO(data)) as image:
        return check_image(image, expected)
