import tempfile
import unittest
from pathlib import Path

from PIL import Image

from qr_maker.inspection import ScanCheckError, check_export, check_image
from qr_maker.render import Options, build_design, export_bytes, save_design


class InspectionTests(unittest.TestCase):
    def test_checks_the_actual_bytes_of_every_export_format(self):
        design = build_design(Options(content_type="Text", text="Exact\n内容", transparent=True, gradient="Diagonal"))
        for suffix in (".png", ".jpg", ".webp", ".svg"):
            with self.subTest(format=suffix):
                self.assertTrue(check_export(export_bytes(design, suffix), suffix, design.payload).ok)

    def test_unreadable_and_mismatched_images_fail(self):
        self.assertFalse(check_image(Image.new("RGB", (256, 256), "white"), "example").ok)
        design = build_design(Options())
        self.assertFalse(check_export(export_bytes(design, ".png"), ".png", "different content").ok)

    def test_failed_preflight_does_not_overwrite_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.png"
            path.write_bytes(b"previous export")
            design = build_design(Options(foreground="#ffffff", finder_color="#ffffff"))
            with self.assertRaises(ScanCheckError) as error:
                save_design(design, path, verify=True)
            self.assertTrue(error.exception.data.startswith(b"\x89PNG"))
            self.assertEqual(path.read_bytes(), b"previous export")


if __name__ == "__main__":
    unittest.main()
