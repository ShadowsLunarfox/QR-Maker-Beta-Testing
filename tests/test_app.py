import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qr_maker.app import QRApp
from qr_maker.appearance import PALETTES
from qr_maker.clipboard import ClipboardBusy
from qr_maker.inspection import ScanCheckError, ScanResult
from PIL import Image
from qr_maker.settings import load_settings, save_settings


class DesktopTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"
        for target, replacement in (
            ("qr_maker.app.load_settings", lambda: load_settings(self.path)),
            ("qr_maker.app.save_settings", lambda data: save_settings(data, self.path)),
        ):
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        try:
            self.window = QRApp()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        self.window.withdraw()
        self.addCleanup(self.window._close)

    def wait_for(self, condition):
        deadline = time.monotonic() + 8
        while not condition() and time.monotonic() < deadline:
            self.window.update()
            time.sleep(.005)
        self.assertTrue(condition(), "Desktop work did not finish")

    def wait_for_preview(self):
        self.wait_for(lambda: self.window.design_serial == self.window.serial)

    def test_save_apply_delete_template_and_preserve_current_url(self):
        window = self.window
        window.vars["url"].set("https://example.com/original")
        window.vars["foreground"].set("#123456")
        window.vars["gradient"].set("Diagonal")
        window.format_var.set("SVG")
        with patch("qr_maker.app.simpledialog.askstring", return_value="Brand"):
            window._save_template()
        self.assertNotIn("url", load_settings(self.path)["templates"]["Brand"]["options"])
        self.assertNotIn("theme", load_settings(self.path)["templates"]["Brand"])
        self.assertNotIn("native_glass", load_settings(self.path)["templates"]["Brand"])
        window.vars["url"].set("https://example.com/new")
        window.vars["foreground"].set("#111111")
        window.format_var.set("PNG")
        window._apply_template()
        self.wait_for_preview()
        self.assertEqual(window.design.options.url, "https://example.com/new")
        self.assertEqual(window.design.options.foreground, "#123456")
        self.assertEqual(window.format_var.get(), "SVG")
        window._delete_template()
        self.assertEqual(load_settings(self.path)["templates"], {})

    def test_last_settings_restore_on_next_open(self):
        self.window.vars["url"].set("https://example.com/remember")
        self.window.vars["shape"].set("Dots")
        self.window.vars["foreground_opacity"].set(85)
        self.window.format_var.set("WebP")
        self.window.preview_surface.set("Charcoal")
        self.window.theme_var.set("Light")
        self.window._close()
        reopened = QRApp()
        reopened.withdraw()
        self.addCleanup(reopened._close)
        self.assertEqual(reopened.vars["url"].get(), "https://example.com/remember")
        self.assertEqual(reopened.vars["shape"].get(), "Dots")
        self.assertEqual(reopened.vars["foreground_opacity"].get(), 85)
        self.assertEqual(reopened.format_var.get(), "WebP")
        self.assertEqual(reopened.preview_surface.get(), "Charcoal")
        self.assertEqual(reopened.theme_var.get(), "Light")
        self.assertEqual(reopened.theme_name, "Light")

    def test_theme_switch_preserves_the_qr_and_updates_controls_and_menus(self):
        self.wait_for_preview()
        design = self.window.design
        preview = self.window.preview.tobytes()
        revision = self.window.serial
        for mode in ("Light", "Dark", "Light"):
            self.window.theme_var.set(mode)
            self.window.update()
            palette = PALETTES[mode]
            style = ttk.Style(self.window)
            self.assertEqual(style.lookup("Card.TFrame", "background"), palette["card"])
            self.assertEqual(style.lookup("TEntry", "foreground"), palette["ink"])
            popdown = self.window.tk.call("ttk::combobox::PopdownWindow", self.window.template_combo)
            self.window._style_popdown(self.window.template_combo)
            self.assertEqual(self.window.tk.call(f"{popdown}.f.l", "cget", "-background"), palette["input"])
            self.assertIs(self.window.design, design)
            self.assertEqual(self.window.serial, revision)
            self.assertEqual(self.window.preview.tobytes(), preview)

    def test_system_mode_follows_system_but_explicit_mode_stays_fixed(self):
        with patch("qr_maker.appearance.system_theme", return_value="Light"):
            self.window.theme_var.set("System")
            self.window._apply_theme(force=True)
            self.assertEqual(self.window.theme_name, "Light")
        with patch("qr_maker.appearance.system_theme", return_value="Dark"):
            self.window._apply_theme()
            self.assertEqual(self.window.theme_name, "Dark")
            self.window.theme_var.set("Light")
            self.window._apply_theme()
            self.assertEqual(self.window.theme_name, "Light")

    def test_theme_clicks_are_deferred_coalesced_and_do_not_reset_tk(self):
        self.window.update()
        original = self.window.theme_name
        target = "Light" if original == "Dark" else "Dark"
        with patch.object(self.window, "_apply_theme", wraps=self.window._apply_theme) as apply, patch.object(self.window.style, "theme_use", side_effect=AssertionError("Do not reset the Tk engine while switching colors")):
            self.window.theme_var.set(target)
            self.window.theme_var.set(original)
            self.window.theme_var.set(target)
            apply.assert_not_called()
            self.assertEqual(self.window.theme_name, original)
            self.window.update()
            apply.assert_called_once()
        self.assertEqual(self.window.theme_name, target)
        self.assertIsNone(self.window.theme_update_pending)

    def test_theme_switch_does_not_create_unopened_popup_windows(self):
        widget = self.window.template_combo
        popup = f"{widget}.popdown"
        self.assertFalse(self.window.tk.getboolean(self.window.tk.call("winfo", "exists", popup)))
        for mode in ("Light", "Dark", "Light"):
            self.window.theme_var.set(mode)
            self.window.update()
            self.assertFalse(self.window.tk.getboolean(self.window.tk.call("winfo", "exists", popup)))
        # The normal postcommand creates and styles the menu when it is used.
        self.window.tk.call(widget.cget("postcommand"))
        self.assertEqual(self.window.tk.call(f"{popup}.f.l", "cget", "-background"), PALETTES["Light"]["input"])
        self.window.theme_var.set("Dark")
        self.window.update()
        self.assertEqual(self.window.tk.call(f"{popup}.f.l", "cget", "-background"), PALETTES["Dark"]["input"])

    def test_material_failure_uses_a_solid_theme_without_fading_the_window(self):
        with patch("qr_maker.app.apply_native_material", return_value=False):
            self.window.theme_var.set("Dark")
            self.window._apply_theme(force=True)
        self.assertFalse(self.window.native_glass)
        self.assertEqual(self.window.cget("background"), PALETTES["Dark"]["background"])
        self.assertEqual(float(self.window.attributes("-alpha")), 1.0)

    def test_compatibility_rendering_is_the_default_for_existing_settings(self):
        self.assertTrue(self.window.compatibility_var.get())
        self.assertFalse(self.window.native_glass)
        for mode in ("Light", "Dark", "Light"):
            self.window.theme_var.set(mode)
            self.window.update()
            self.assertEqual(self.window.cget("background"), PALETTES[mode]["background"])
            self.assertFalse(self.window.native_glass)

    def test_renderer_switch_updates_without_changing_theme_or_design(self):
        self.wait_for_preview()
        original = self.window.design
        with patch("qr_maker.app.apply_native_material", side_effect=lambda window, dark, *, allow_glass: allow_glass) as material:
            self.window.compatibility_var.set(False)
            self.window.update()
            self.assertTrue(self.window.native_glass)
            self.window._use_compatible_rendering()
            self.window.update()
            self.assertFalse(self.window.native_glass)
            self.assertTrue(self.window.compatibility_var.get())
        self.assertIs(self.window.design, original)
        self.assertEqual(material.call_count, 2)
        self.window._store_settings()
        self.assertFalse(load_settings(self.path)["last"]["native_glass"])

    def test_safe_launch_overrides_a_saved_native_glass_preference(self):
        save_settings({"last": {"native_glass": True}, "templates": {}}, self.path)
        reopened = QRApp(safe_rendering=True)
        reopened.withdraw()
        self.addCleanup(reopened._close)
        self.assertTrue(reopened.compatibility_var.get())
        self.assertFalse(reopened.native_glass)

    def test_minimum_window_keeps_preview_actions_and_history_visible(self):
        self.window.geometry("990x730")
        self.window.deiconify()
        self.wait_for_preview()
        self.window.update()
        for button in (self.window.copy_button, self.window.check_button, self.window.export_button,
                       self.window.undo_button, self.window.redo_button):
            self.assertTrue(button.winfo_ismapped(), button.cget("text"))
            bottom = button.winfo_rooty() + button.winfo_height()
            self.assertLessEqual(bottom, self.window.winfo_rooty() + self.window.winfo_height())
        self.assertGreaterEqual(self.window.canvas.winfo_height(), 90)

    def test_rapid_changes_export_only_the_latest_design(self):
        self.wait_for_preview()
        for index in range(20):
            self.window.vars["url"].set(f"https://example.com/{index}")
            self.window.vars["foreground_opacity"].set(80 + index)
            self.window.update()
        self.assertEqual(str(self.window.export_button.cget("state")), "disabled")
        self.wait_for_preview()
        self.assertEqual(self.window.design.options.url, "https://example.com/19")
        self.assertEqual(self.window.design.options.foreground_opacity, 99)
        self.assertEqual(str(self.window.export_button.cget("state")), "normal")

    def test_grouped_edits_can_undo_redo_and_start_a_new_branch(self):
        window = self.window
        window.vars["foreground"].set("#123456")
        window.vars["foreground_opacity"].set(70)
        window.vars["logo_padding"].set(12)
        window._commit_history()
        self.assertEqual(len(window.history.states), 2)
        window._undo()
        self.assertEqual(window.vars["foreground"].get(), "#172033")
        self.assertEqual(window.vars["foreground_opacity"].get(), 100)
        window._redo()
        self.assertEqual(window.vars["foreground"].get(), "#123456")
        self.assertEqual(window.vars["logo_padding"].get(), 12)
        window._undo()
        window.vars["foreground"].set("#112233")
        window._commit_history()
        self.assertFalse(window.history.can_redo)
        self.assertTrue(window.bind_class(f"QRHistory{id(window)}", "<Control-z>"))

    def test_template_and_reset_keep_content_and_wifi_password_is_not_persisted(self):
        window = self.window
        window.vars["content_type"].set("Wi-Fi")
        window.vars["wifi_ssid"].set("Office")
        window.vars["wifi_password"].set("session-secret")
        window.vars["foreground"].set("#123456")
        with patch("qr_maker.app.simpledialog.askstring", return_value="Office look"):
            window._save_template()
        stored = load_settings(self.path)
        self.assertEqual(stored["last"]["options"]["wifi_password"], "")
        self.assertNotIn("wifi_password", stored["templates"]["Office look"]["options"])
        window.vars["wifi_ssid"].set("Another network")
        window._apply_template()
        self.assertEqual(window.vars["wifi_ssid"].get(), "Another network")
        self.assertEqual(window.vars["wifi_password"].get(), "session-secret")
        window._reset()
        self.assertEqual(window.vars["content_type"].get(), "Wi-Fi")
        self.assertEqual(window.vars["wifi_password"].get(), "session-secret")

    def test_logo_drop_accepts_quoted_paths_and_can_be_undone(self):
        path = self.path.parent / "logo image.png"
        Image.new("RGB", (120, 80), "blue").save(path)
        result = self.window._drop_logo(SimpleNamespace(data="{" + str(path) + "}"))
        self.assertEqual(result, "copy")
        self.assertEqual(self.window.vars["logo_path"].get(), str(path.resolve()))
        self.window._undo()
        self.assertEqual(self.window.vars["logo_path"].get(), "")
        self.window._redo()
        self.assertEqual(self.window.vars["logo_path"].get(), str(path.resolve()))

    def test_copy_prepares_full_size_image_and_retries_a_busy_clipboard(self):
        self.wait_for_preview()
        with patch("qr_maker.app.set_image_clipboard", side_effect=[ClipboardBusy("busy"), None]) as clipboard:
            self.window._copy_image()
            self.wait_for(lambda: not self.window.copying)
        self.assertEqual(clipboard.call_count, 2)
        self.assertEqual(clipboard.call_args.args[1][0][:8], b"\x89PNG\r\n\x1a\n")
        import io
        with Image.open(io.BytesIO(clipboard.call_args.args[1][0])) as copied:
            self.assertEqual(copied.size, (self.window.design.options.size,) * 2)
        self.assertIn("Image copied", self.window.status.get())

    def test_copy_discards_an_image_when_the_design_changes_during_preparation(self):
        self.wait_for_preview()
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def prepare(_image):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release copy")
            return b"png", b"dib"

        with patch("qr_maker.app.image_formats", side_effect=prepare), patch("qr_maker.app.set_image_clipboard") as clipboard:
            self.window._copy_image()
            self.wait_for(started.is_set)
            self.window.vars["foreground"].set("#112233")
            self.wait_for_preview()
            release.set()
            self.wait_for(lambda: not self.window.copying)
        clipboard.assert_not_called()

    def test_manual_scan_checks_the_selected_svg_format(self):
        self.wait_for_preview()
        self.window.format_var.set("SVG")
        self.window._check_scan()
        self.wait_for(lambda: not self.window.checking)
        self.assertTrue(self.window.scan_ok)

    def test_scan_result_is_discarded_if_the_selected_format_changes(self):
        self.wait_for_preview()
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def check(*_):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release scan")
            return ScanResult(True, "passed")

        with patch("qr_maker.app.check_export", side_effect=check):
            self.window._check_scan()
            self.wait_for(started.is_set)
            self.window.format_var.set("SVG")
            release.set()
            self.wait_for(lambda: not self.window.checking)
        self.assertIsNone(self.window.scan_ok)
        self.assertEqual(self.window.scan_note.get(), "Scan check: not run")

    def test_failed_export_check_does_not_save_without_user_override(self):
        self.wait_for_preview()
        target = self.path.with_suffix(".png")
        with patch("qr_maker.app.filedialog.asksaveasfilename", return_value=str(target)), patch("qr_maker.app.save_design", side_effect=ScanCheckError("Unreadable design", b"image bytes")), patch("qr_maker.app.messagebox.askyesno", return_value=False):
            self.window._export()
            self.wait_for(lambda: not self.window.exporting)
        self.assertFalse(target.exists())
        self.assertFalse(self.window.scan_ok)

    def test_preview_updates_during_export_and_export_button_recovers(self):
        self.wait_for_preview()
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow_save(*_, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release export")

        with patch("qr_maker.app.save_design", side_effect=slow_save), patch("qr_maker.app.filedialog.asksaveasfilename", return_value=str(self.path.with_suffix(".png"))):
            self.window._export()
            self.wait_for(started.is_set)
            self.window.vars["foreground"].set("#112233")
            self.wait_for_preview()
            self.assertTrue(self.window.exporting)
            self.assertEqual(self.window.design.options.foreground, "#112233")
            self.assertEqual(str(self.window.export_button.cget("state")), "disabled")
            release.set()
            self.wait_for(lambda: not self.window.exporting)
        self.assertEqual(str(self.window.export_button.cget("state")), "normal")


if __name__ == "__main__":
    unittest.main()
