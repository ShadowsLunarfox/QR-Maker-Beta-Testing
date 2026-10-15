import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

from qr_maker.render import (
    GRADIENTS, PRESETS, SHAPES, Options, build_design, normalize_url,
    render_image, render_svg, save_design,
)

try:
    import zxingcpp
except ImportError:
    zxingcpp = None
try:
    import resvg_py
except ImportError:
    resvg_py = None


class QRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.logo = cls.directory / "logo.png"
        image = Image.new("RGBA", (180, 120), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 175, 115), radius=24, fill="#087f8c")
        draw.text((72, 50), "QR", fill="white")
        image.save(cls.logo)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def decode(self, image, expected):
        base = Image.new("RGBA", image.size, "white")
        rgb = Image.alpha_composite(base, image.convert("RGBA")).convert("RGB")
        result = zxingcpp.read_barcode(rgb)
        self.assertIsNotNone(result, "Exported QR could not be decoded")
        self.assertEqual(result.text, expected)

    def test_url_normalization_and_validation(self):
        self.assertEqual(normalize_url("  example.com/a?x=1&y=2  "), "https://example.com/a?x=1&y=2")
        self.assertEqual(normalize_url("localhost:8080/test"), "https://localhost:8080/test")
        self.assertEqual(normalize_url("http://[::1]:8080"), "http://[::1]:8080")
        for url in ("", "https://", "javascript:alert(1)", "ftp://example.com", "a b.com", "https://bad..com", "https://example.com:99999", "https://-bad.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)

    def test_square_render_matches_every_matrix_cell(self):
        design = build_design(Options(size=768))
        image = render_image(design)
        step = image.width / design.cells
        for y, row in enumerate(design.matrix):
            for x, dark in enumerate(row):
                point = (round((x + design.options.border + .5) * step),
                         round((y + design.options.border + .5) * step))
                color = image.getpixel(point)
                self.assertEqual(color[:3], (23, 32, 51) if dark else (255, 255, 255), (x, y))

    def test_transparency_and_opacity(self):
        image = render_image(build_design(Options(transparent=True, foreground_opacity=65, size=512)))
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.size, (512, 512))
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertGreater(image.getchannel("A").histogram()[166], 0)
        bg = render_image(build_design(Options(background_opacity=50, size=256)))
        self.assertEqual(bg.getpixel((0, 0))[3], 128)

    def test_exports_and_self_contained_svg(self):
        design = build_design(Options(url="example.com/?a=1&b=2", size=512, logo_path=str(self.logo), transparent=True))
        for extension in ("png", "jpg", "webp", "svg"):
            path = self.directory / f"test.{extension}"
            save_design(design, path)
            if extension == "svg":
                root = ET.fromstring(path.read_text("utf-8"))
                self.assertEqual(root.attrib["viewBox"], "0 0 512 512")
                image = root.find(".//{http://www.w3.org/2000/svg}image")
                self.assertTrue(image.attrib["href"].startswith("data:image/png;base64,"))
            else:
                with Image.open(path) as image:
                    self.assertEqual(image.size, (512, 512))
                    if extension == "jpg":
                        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                    else:
                        self.assertEqual(image.getpixel((0, 0))[3], 0)
        with self.assertRaises(ValueError):
            save_design(design, self.directory / "bad.txt")

    def test_invalid_designs_and_useful_warnings(self):
        for change in (dict(size=40), dict(border=0), dict(gradient="Nope"), dict(foreground="bad-color"), dict(logo_path="missing.png"), dict(logo_size=50), dict(rotation=45)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_design(replace(Options(), **change))
        with self.assertRaisesRegex(ValueError, "too long"):
            build_design(Options(url="https://example.com/" + "a" * 5000))
        warnings = build_design(Options(foreground="#ffffff", transparent=True)).warnings
        self.assertTrue(any("contrast" in warning for warning in warnings))
        self.assertTrue(any("Transparency" in warning for warning in warnings))

    @unittest.skipUnless(zxingcpp, "Install requirements-dev.txt for scanner tests")
    def test_presets_are_scannable(self):
        for name, (a, b, bg, gradient, shape) in PRESETS.items():
            with self.subTest(preset=name):
                opts = Options(foreground=a, secondary=b, background=bg, gradient=gradient,
                               shape=shape, finder_color=a, finder_style="Rounded", size=768)
                design = build_design(opts)
                self.decode(render_image(design), design.options.url)

    @unittest.skipUnless(zxingcpp, "Install requirements-dev.txt for scanner tests")
    def test_effects_logos_rotation_and_dense_links_scan(self):
        variants = [replace(Options(), shape=shape, size=512) for shape in SHAPES]
        variants += [replace(Options(), gradient=effect, size=512) for effect in GRADIENTS]
        variants += [Options(logo_path=str(self.logo), plate_style=plate, rotation=rotation,
                             shape="Rounded", gradient="Diagonal", transparent=True, size=768)
                     for plate in ("Square", "Rounded", "Circle") for rotation in (0, 90, 180, 270)]
        variants += [Options(url="https://example.com/" + "details/" * 70 + "?name=caf%C3%A9", size=1536,
                             gradient="Radial", shape="Dots", logo_path=str(self.logo))]
        for options in variants:
            with self.subTest(options=options):
                design = build_design(options)
                self.decode(render_image(design), design.options.url)

    @unittest.skipUnless(zxingcpp and resvg_py, "Install requirements-dev.txt for SVG scanner tests")
    def test_svg_exports_scan_after_vector_rasterization(self):
        import io
        for effect in GRADIENTS:
            with self.subTest(effect=effect):
                design = build_design(Options(url="https://example.com/?a=1&b=2", gradient=effect,
                                              shape="Rounded", finder_style="Rounded", rotation=90,
                                              transparent=True, logo_path=str(self.logo), size=768))
                data = resvg_py.svg_to_bytes(svg_string=render_svg(design))
                self.decode(Image.open(io.BytesIO(data)), design.options.url)


if __name__ == "__main__":
    unittest.main()
