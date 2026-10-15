"""QR geometry shared by the Pillow and vector SVG exporters."""

from __future__ import annotations

import base64
import io
import ipaddress
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

import qrcode
from PIL import Image, ImageColor, ImageDraw, ImageOps
from qrcode.exceptions import DataOverflowError
from qrcode.util import pattern_position


SHAPES = ("Square", "Rounded", "Dots", "Diamond")
GRADIENTS = ("Solid", "Horizontal", "Vertical", "Diagonal", "Radial")
PRESETS = {
    "Classic": ("#172033", "#172033", "#ffffff", "Solid", "Square"),
    "Ocean": ("#123b83", "#087c83", "#ffffff", "Diagonal", "Rounded"),
    "Violet": ("#492b89", "#963b82", "#ffffff", "Vertical", "Rounded"),
    "Ember": ("#78204c", "#a54a16", "#fffaf5", "Diagonal", "Dots"),
    "Forest": ("#143d35", "#34723b", "#f9fcf8", "Radial", "Rounded"),
    "Midnight": ("#132039", "#3a4d76", "#edf2ff", "Horizontal", "Diamond"),
}


@dataclass(frozen=True)
class Options:
    url: str = "https://example.com"
    size: int = 1024
    border: int = 4
    foreground: str = "#172033"
    secondary: str = "#087c83"
    background: str = "#ffffff"
    gradient: str = "Solid"
    shape: str = "Square"
    foreground_opacity: int = 100
    background_opacity: int = 100
    transparent: bool = False
    finder_color: str = "#172033"
    finder_style: str = "Square"
    rotation: int = 0
    logo_path: str = ""
    logo_size: int = 18
    logo_opacity: int = 100
    logo_plate: bool = True
    plate_color: str = "#ffffff"
    plate_style: str = "Rounded"


@dataclass(frozen=True)
class Shape:
    kind: str
    box: tuple[float, float, float, float]
    radius: float = 0


@dataclass
class Design:
    options: Options
    matrix: list[list[bool]]
    version: int
    modules: list[Shape]
    structure: list[Shape]
    logo: Image.Image | None
    logo_box: tuple[float, float, float, float] | None
    warnings: list[str]

    @property
    def cells(self) -> int:
        return len(self.matrix) + 2 * self.options.border


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Enter a URL to create your QR code.")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("The URL contains spaces. Use %20 for spaces in a link.")
    if "://" not in value:
        has_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
        host_port = re.match(r"^[^/?#:]+:\d+(?:[/?#]|$)", value)
        if has_scheme and not host_port:
            raise ValueError("Use an http:// or https:// website URL.")
        value = "https://" + value
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port
        if parts.scheme.lower() not in ("http", "https") or not hostname:
            raise ValueError
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            encoded = hostname.encode("idna").decode("ascii").rstrip(".")
            if len(encoded) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in encoded.split(".")
            ):
                raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Enter a valid website URL, such as https://example.com.") from exc
    return value


def _color(value: str) -> tuple[int, int, int]:
    try:
        rgb = ImageColor.getrgb(value)
        if len(rgb) != 3:
            raise ValueError
        return rgb
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid color: {value!r}. Use a color like #123456.") from exc


def _contrast(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    def luminance(rgb):
        channels = [v / 255 for v in rgb]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
    x, y = sorted((luminance(a), luminance(b)))
    return (y + .05) / (x + .05)


def build_design(options: Options) -> Design:
    opts = replace(options, url=normalize_url(options.url))
    for name, low, high in (
        ("size", 256, 4096), ("border", 4, 12), ("foreground_opacity", 10, 100),
        ("background_opacity", 0, 100), ("logo_size", 8, 24), ("logo_opacity", 0, 100),
    ):
        value = getattr(opts, name)
        if not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{name.replace('_', ' ').capitalize()} must be {low}–{high}.")
    if opts.gradient not in GRADIENTS or opts.shape not in SHAPES:
        raise ValueError("Choose a supported gradient and module shape.")
    if opts.finder_style not in ("Square", "Rounded") or opts.plate_style not in ("Square", "Rounded", "Circle"):
        raise ValueError("Choose a supported corner or logo plate style.")
    if opts.rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180, or 270 degrees.")
    colors = {key: _color(getattr(opts, key)) for key in (
        "foreground", "secondary", "background", "finder_color", "plate_color"
    )}
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=0)
    try:
        qr.add_data(opts.url)
        qr.make(fit=True)
    except (DataOverflowError, ValueError) as exc:
        raise ValueError("This URL is too long for a QR code. Try a shorter link.") from exc
    matrix = qr.get_matrix()
    n, border = len(matrix), opts.border
    cell = opts.size / (n + 2 * border)
    modules, structure = [], []
    finders = ((0, 0), (n - 7, 0), (0, n - 7))
    align = pattern_position(qr.version)

    def protected(x, y):
        return (
            x in (6, 8) or y in (6, 8)
            or any(abs(x - cx) <= 2 and abs(y - cy) <= 2 for cx in align for cy in align)
            or (qr.version >= 7 and ((x >= n - 11 and y < 6) or (y >= n - 11 and x < 6)))
        )

    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if not dark or any(fx <= x < fx + 7 and fy <= y < fy + 7 for fx, fy in finders):
                continue
            box = ((x + border) * cell, (y + border) * cell,
                   (x + border + 1) * cell, (y + border + 1) * cell)
            if protected(x, y):
                structure.append(Shape("Square", box))
            else:
                modules.append(Shape(opts.shape, box, cell * .27))
    # A ring is a single path with a hole, so transparent backgrounds stay transparent.
    for fx, fy in finders:
        x, y = (fx + border) * cell, (fy + border) * cell
        radius = cell * .8 if opts.finder_style == "Rounded" else 0
        structure.append(Shape("Ring", (x, y, x + 7 * cell, y + 7 * cell), radius))
        structure.append(Shape("Rounded" if radius else "Square",
                               (x + 2 * cell, y + 2 * cell, x + 5 * cell, y + 5 * cell),
                               cell * .4 if radius else 0))

    logo, logo_box = None, None
    if opts.logo_path:
        try:
            with Image.open(opts.logo_path) as source:
                source.load()
                logo = ImageOps.exif_transpose(source).convert("RGBA")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError("The logo could not be opened. Choose a PNG, JPG, or WebP image.") from exc
        # Limit the entire occluded area, including its plate, to the requested fraction.
        side = n * cell * opts.logo_size / 100
        start = (opts.size - side) / 2
        logo_box = (start, start, start + side, start + side)
        padding = (.16 if opts.plate_style == "Circle" else .13) if opts.logo_plate else 0
        fitted = max(1, round(side * (1 - 2 * padding)))
        logo.thumbnail((fitted, fitted), Image.Resampling.LANCZOS)
        if opts.logo_opacity != 100:
            logo.putalpha(logo.getchannel("A").point(lambda a: round(a * opts.logo_opacity / 100)))

    bg = colors["background"]
    warnings = []
    check_colors = [colors["foreground"], colors["finder_color"]]
    if opts.gradient != "Solid":
        check_colors.extend(tuple(round(a + (b - a) * t / 8) for a, b in zip(colors["foreground"], colors["secondary"])) for t in range(9))
    alpha = opts.foreground_opacity / 100
    if any(_contrast(tuple(round(v * alpha + w * (1 - alpha)) for v, w in zip(c, bg)), bg) < 3 for c in check_colors):
        warnings.append("Low contrast: use darker QR colors or a lighter background.")
    if opts.transparent or opts.background_opacity < 100:
        warnings.append("Transparency needs a light, plain surface behind the QR code.")
    if opts.foreground_opacity < 80:
        warnings.append("Low QR opacity can make scanning harder.")
    if opts.logo_path and opts.logo_size > 20:
        warnings.append("A smaller logo is easier to scan. Try 18–20% if needed.")
    if cell < 4:
        warnings.append("This link is dense at this size. Export a larger image.")
    return Design(opts, matrix, qr.version, modules, structure, logo, logo_box, warnings)


def _draw_shape(draw: ImageDraw.ImageDraw, shape: Shape, scale: float, fill=255):
    box = tuple(round(v * scale) for v in shape.box)
    x0, y0, x1, y1 = box
    box = (x0, y0, x1 - 1, y1 - 1)
    radius = round(shape.radius * scale)
    if shape.kind == "Ring":
        cell = (x1 - x0) / 7
        draw.rounded_rectangle(box, radius=radius, fill=fill)
        inner = (round(x0 + cell), round(y0 + cell), round(x1 - cell) - 1, round(y1 - cell) - 1)
        draw.rounded_rectangle(inner, radius=round(radius * .6), fill=0)
    elif shape.kind == "Dots":
        draw.ellipse(box, fill=fill)
    elif shape.kind == "Diamond":
        draw.polygon((((x0 + x1 - 1) / 2, y0), (x1 - 1, (y0 + y1 - 1) / 2),
                      ((x0 + x1 - 1) / 2, y1 - 1), (x0, (y0 + y1 - 1) / 2)), fill=fill)
    elif shape.kind in ("Rounded", "Circle"):
        draw.rounded_rectangle(box, radius=min(x1 - x0, y1 - y0) // 2 if shape.kind == "Circle" else radius, fill=fill)
    else:
        draw.rectangle(box, fill=fill)


def _gradient(design: Design, side: int) -> Image.Image:
    opts = design.options
    a, b = _color(opts.foreground), _color(opts.secondary)
    if opts.gradient == "Solid":
        return Image.new("RGBA", (side, side), (*a, 255))
    # A small color field is resized smoothly; QR edges use separate full-resolution masks.
    field_side = min(256, side)
    pixels = []
    for y in range(field_side):
        for x in range(field_side):
            u, v = x / (field_side - 1), y / (field_side - 1)
            t = {"Horizontal": u, "Vertical": v, "Diagonal": (u + v) / 2,
                 "Radial": min(1, math.hypot(u - .5, v - .5) * 2)}[opts.gradient]
            pixels.append(tuple(round(s + (e - s) * t) for s, e in zip(a, b)) + (255,))
    result = Image.new("RGBA", (field_side, field_side))
    result.putdata(pixels)
    return result.resize((side, side), Image.Resampling.BILINEAR)


def render_image(design: Design, size: int | None = None) -> Image.Image:
    """Return an RGBA image. Optional size is useful for a fast UI preview."""
    opts = design.options
    side = size or opts.size
    # Supersampling at small sizes keeps curves clean without excessive 4K memory usage.
    scale_factor = 2 if side <= 1536 else 1
    work = side * scale_factor
    scale = work / opts.size
    opacity = round(255 * opts.foreground_opacity / 100)
    bg_alpha = 0 if opts.transparent else round(255 * opts.background_opacity / 100)
    image = Image.new("RGBA", (work, work), (*_color(opts.background), bg_alpha))
    for shapes, is_structure in ((design.modules, False), (design.structure, True)):
        layer = (Image.new("RGBA", (work, work), (*_color(opts.finder_color), 255))
                 if is_structure else _gradient(design, work))
        mask = Image.new("L", (work, work), 0)
        draw = ImageDraw.Draw(mask)
        for shape in shapes:
            _draw_shape(draw, shape, scale)
        if opacity != 255:
            mask = mask.point(lambda a: round(a * opacity / 255))
        layer.putalpha(mask)
        image = Image.alpha_composite(image, layer)
    if design.logo is not None and design.logo_box:
        if opts.logo_plate:
            plate_mask = Image.new("L", (work, work), 0)
            _draw_shape(ImageDraw.Draw(plate_mask), Shape(opts.plate_style, design.logo_box,
                                                        (design.logo_box[2] - design.logo_box[0]) * .17), scale)
            plate = Image.new("RGBA", (work, work), (*_color(opts.plate_color), 255))
            plate.putalpha(plate_mask)
            image = Image.alpha_composite(image, plate)
        logo = design.logo.resize((max(1, round(design.logo.width * scale)),
                                   max(1, round(design.logo.height * scale))), Image.Resampling.LANCZOS)
        image.alpha_composite(logo, ((work - logo.width) // 2, (work - logo.height) // 2))
    if opts.rotation:
        image = image.rotate(-opts.rotation)
    if work != side:
        image = image.resize((side, side), Image.Resampling.LANCZOS)
    return image


def _svg_shape(shape: Shape) -> str:
    x, y, right, bottom = shape.box
    w, h = right - x, bottom - y
    f = lambda v: f"{v:.4f}".rstrip("0").rstrip(".")
    if shape.kind == "Ring":
        cell = w / 7
        def rounded_path(a, b, width, height, r):
            return (f"M{f(a+r)} {f(b)}h{f(width-2*r)}q{f(r)} 0 {f(r)} {f(r)}v{f(height-2*r)}"
                    f"q0 {f(r)} {f(-r)} {f(r)}h{f(-width+2*r)}q{f(-r)} 0 {f(-r)} {f(-r)}"
                    f"v{f(-height+2*r)}q0 {f(-r)} {f(r)} {f(-r)}z")
        path = rounded_path(x, y, w, h, shape.radius)
        path += rounded_path(x + cell, y + cell, w - 2 * cell, h - 2 * cell, shape.radius * .6)
        return f'<path d="{path}" fill-rule="evenodd"/>'
    if shape.kind == "Dots":
        return f'<ellipse cx="{f(x+w/2)}" cy="{f(y+h/2)}" rx="{f(w/2)}" ry="{f(h/2)}"/>'
    if shape.kind == "Diamond":
        return f'<polygon points="{f(x+w/2)},{f(y)} {f(right)},{f(y+h/2)} {f(x+w/2)},{f(bottom)} {f(x)},{f(y+h/2)}"/>'
    r = min(w, h) / 2 if shape.kind == "Circle" else shape.radius if shape.kind == "Rounded" else 0
    return f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(r)}"/>'


def render_svg(design: Design) -> str:
    """Export real vector QR shapes and an embedded PNG logo, with no external links."""
    opts = design.options
    color = lambda value: "#%02x%02x%02x" % _color(value)
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{opts.size}" height="{opts.size}" viewBox="0 0 {opts.size} {opts.size}">',
              f'<title>QR code for {escape(opts.url)}</title>']
    fill = color(opts.foreground)
    if opts.gradient != "Solid":
        stops = f'<stop stop-color="{fill}"/><stop offset="1" stop-color="{color(opts.secondary)}"/>'
        if opts.gradient == "Radial":
            grad = f'<radialGradient id="ink" cx=".5" cy=".5" r=".5" gradientUnits="objectBoundingBox">{stops}</radialGradient>'
        else:
            x2, y2 = {"Horizontal": (1, 0), "Vertical": (0, 1), "Diagonal": (1, 1)}[opts.gradient]
            grad = f'<linearGradient id="ink" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{x2*opts.size}" y2="{y2*opts.size}">{stops}</linearGradient>'
        # Radial coordinates also use the whole artboard, independent of module extents.
        if opts.gradient == "Radial":
            grad = f'<radialGradient id="ink" gradientUnits="userSpaceOnUse" cx="{opts.size/2}" cy="{opts.size/2}" r="{opts.size/2}">{stops}</radialGradient>'
        pieces.append(f'<defs>{grad}</defs>')
        fill = "url(#ink)"
    if not opts.transparent and opts.background_opacity:
        pieces.append(f'<rect width="100%" height="100%" fill="{color(opts.background)}" fill-opacity="{opts.background_opacity/100}"/>')
    pieces.append(f'<g transform="rotate({opts.rotation} {opts.size/2} {opts.size/2})">')
    for shapes, ink in ((design.modules, fill), (design.structure, color(opts.finder_color))):
        pieces.append(f'<g fill="{ink}" fill-opacity="{opts.foreground_opacity/100}">')
        pieces.extend(_svg_shape(shape) for shape in shapes)
        pieces.append('</g>')
    if design.logo is not None and design.logo_box:
        if opts.logo_plate:
            pieces.append(f'<g fill="{color(opts.plate_color)}">')
            pieces.append(_svg_shape(Shape(opts.plate_style, design.logo_box,
                                           (design.logo_box[2] - design.logo_box[0]) * .17)))
            pieces.append('</g>')
        buffer = io.BytesIO()
        design.logo.save(buffer, format="PNG")
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        x, y = (opts.size - design.logo.width) / 2, (opts.size - design.logo.height) / 2
        pieces.append(f'<image x="{x}" y="{y}" width="{design.logo.width}" height="{design.logo.height}" href="data:image/png;base64,{data}"/>')
    pieces.extend(('</g>', '</svg>'))
    return '\n'.join(pieces)


def save_design(design: Design, destination: str | Path) -> Path:
    path = Path(destination)
    suffix = path.suffix.lower()
    if suffix not in (".png", ".svg", ".jpg", ".jpeg", ".webp"):
        raise ValueError("Choose a PNG, SVG, JPG, or WebP filename.")
    if suffix == ".svg":
        path.write_text(render_svg(design), encoding="utf-8")
    else:
        image = render_image(design)
        if suffix in (".jpg", ".jpeg"):
            base = Image.new("RGBA", image.size, "white")
            image = Image.alpha_composite(base, image).convert("RGB")
            image.save(path, quality=98, subsampling=0)
        elif suffix == ".webp":
            image.save(path, lossless=True)
        else:
            image.save(path)
    return path
