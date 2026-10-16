import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from qr_maker.render import Options
from qr_maker.settings import load_settings, options_from_snapshot, save_settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"

    def test_missing_or_invalid_file_uses_defaults(self):
        expected = {"version": 1, "last": {}, "templates": {}}
        self.assertEqual(load_settings(self.path), expected)
        for value in ("broken json", "[]", '{"last": [], "templates": false}'):
            self.path.write_text(value, encoding="utf-8")
            self.assertEqual(load_settings(self.path), expected)

    def test_settings_and_unicode_templates_survive_round_trip(self):
        snapshot = {"options": asdict(Options(gradient="Radial", logo_size=20)), "format": "SVG", "surface": "White"}
        data = {"version": 1, "last": snapshot, "templates": {"品牌模板": snapshot}}
        save_settings(data, self.path)
        self.assertEqual(load_settings(self.path), data)
        self.assertEqual(options_from_snapshot(load_settings(self.path)["last"]).gradient, "Radial")

    def test_wrong_option_types_and_unknown_fields_do_not_break_startup(self):
        options = options_from_snapshot({"options": {"size": "bad", "transparent": "yes", "foreground": "#123456", "unknown": 1}})
        self.assertEqual(options.size, Options().size)
        self.assertFalse(options.transparent)
        self.assertEqual(options.foreground, "#123456")

    def test_failed_save_preserves_previous_file_and_removes_temporary_file(self):
        self.path.write_text('{"version": 1}', encoding="utf-8")
        with patch.object(Path, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                save_settings({"version": 1, "last": {}}, self.path)
        self.assertEqual(self.path.read_text("utf-8"), '{"version": 1}')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
