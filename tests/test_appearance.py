import unittest
import ctypes
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import ImageColor

from qr_maker.appearance import PALETTES, apply_native_material, resolve_theme
from qr_maker.render import _contrast


class AppearanceTests(unittest.TestCase):
    def test_light_and_dark_text_have_readable_contrast(self):
        for mode, palette in PALETTES.items():
            for text, surface in (("ink", "card"), ("muted", "card"), ("ink", "input"),
                                  ("accent_text", "accent"), ("error", "card"), ("warning", "card")):
                with self.subTest(mode=mode, text=text, surface=surface):
                    self.assertGreaterEqual(_contrast(ImageColor.getrgb(palette[text]),
                                                      ImageColor.getrgb(palette[surface])), 4.5)

    def test_unknown_preferences_follow_system_theme(self):
        with patch("qr_maker.appearance.system_theme", return_value="Dark"):
            self.assertEqual(resolve_theme("System"), "Dark")
            self.assertEqual(resolve_theme("invalid"), "Dark")
            self.assertEqual(resolve_theme("Light"), "Light")

    def test_non_windows_systems_do_not_call_native_apis(self):
        with patch("qr_maker.appearance.sys.platform", "linux"):
            self.assertFalse(apply_native_material(None, True))

    def test_native_backdrop_is_initialized_once_when_switching_colors(self):
        user = SimpleNamespace(GetAncestor=Mock(return_value=123))
        dwm = SimpleNamespace(DwmSetWindowAttribute=Mock(return_value=0), DwmExtendFrameIntoClientArea=Mock(return_value=0))
        window = SimpleNamespace(winfo_id=Mock(return_value=456))
        with patch("qr_maker.appearance.sys.platform", "win32"), patch.object(sys, "getwindowsversion", return_value=SimpleNamespace(build=26200), create=True), patch.object(ctypes, "WinDLL", side_effect=lambda name: user if name == "user32" else dwm, create=True):
            for dark in (True, False, True, False):
                self.assertTrue(apply_native_material(window, dark, allow_glass=True))
        dwm.DwmExtendFrameIntoClientArea.assert_called_once()
        attributes = [call.args[1] for call in dwm.DwmSetWindowAttribute.call_args_list]
        self.assertEqual(attributes.count(38), 1)
        self.assertEqual(attributes.count(33), 1)
        self.assertEqual(attributes.count(20), 4)

    def test_compatibility_startup_never_enables_full_client_glass(self):
        user = SimpleNamespace(GetAncestor=Mock(return_value=123))
        dwm = SimpleNamespace(DwmSetWindowAttribute=Mock(return_value=0), DwmExtendFrameIntoClientArea=Mock(return_value=0))
        window = SimpleNamespace(winfo_id=Mock(return_value=456))
        with patch("qr_maker.appearance.sys.platform", "win32"), patch.object(ctypes, "WinDLL", side_effect=lambda name: user if name == "user32" else dwm, create=True):
            for dark in (True, False, True, False):
                self.assertFalse(apply_native_material(window, dark))
        dwm.DwmExtendFrameIntoClientArea.assert_not_called()
        attributes = [call.args[1] for call in dwm.DwmSetWindowAttribute.call_args_list]
        self.assertNotIn(38, attributes)

    def test_returning_to_compatibility_removes_existing_glass(self):
        user = SimpleNamespace(GetAncestor=Mock(return_value=123))
        seen_attributes, margins = [], []

        def attribute(hwnd, number, pointer, length):
            seen_attributes.append((number, ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0]))
            return 0

        def extend(hwnd, pointer):
            margins.append(tuple(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[i] for i in range(4)))
            return 0

        dwm = SimpleNamespace(DwmSetWindowAttribute=Mock(side_effect=attribute), DwmExtendFrameIntoClientArea=Mock(side_effect=extend))
        window = SimpleNamespace(winfo_id=Mock(return_value=456))
        with patch("qr_maker.appearance.sys.platform", "win32"), patch.object(sys, "getwindowsversion", return_value=SimpleNamespace(build=26200), create=True), patch.object(ctypes, "WinDLL", side_effect=lambda name: user if name == "user32" else dwm, create=True):
            self.assertTrue(apply_native_material(window, False, allow_glass=True))
            self.assertFalse(apply_native_material(window, False, allow_glass=False))
            self.assertFalse(apply_native_material(window, True, allow_glass=False))
        self.assertEqual(margins, [(-1, -1, -1, -1), (0, 0, 0, 0)])
        self.assertIn((38, 1), seen_attributes)

    @unittest.skipUnless(sys.platform == "win32", "Windows theme interaction regression")
    def test_visible_theme_clicks_keep_timers_and_input_responsive(self):
        # A separate process gives this freeze regression a hard deadline.
        code = textwrap.dedent('''
            import faulthandler
            from unittest.mock import patch
            from tkinter import ttk
            from qr_maker.app import QRApp

            faulthandler.dump_traceback_later(12, exit=True)
            initial = {'version': 1, 'last': {'theme': 'Dark'}, 'templates': {}}
            with patch('qr_maker.app.save_settings'), patch('qr_maker.app.load_settings', return_value=initial):
                window = QRApp()
                window.title('QR Studio - theme regression test')
                failures, beats = [], []
                window.report_callback_exception = lambda *args: failures.append(str(args[1]))
                def widgets(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from widgets(child)
                modes = {w.cget('value'): w for w in widgets(window) if isinstance(w, ttk.Radiobutton)}
                def heartbeat():
                    beats.append(1)
                    window.after(5, heartbeat)
                def switch(index=0):
                    if index == 18:
                        assert len(beats) >= 18, 'UI timers stopped'
                        assert not window.grab_current(), 'Input remained grabbed'
                        window.url_entry.delete(0, 'end')
                        window.url_entry.insert(0, 'https://example.com/still-responsive')
                        window.after(250, finish)
                        return
                    button = modes[('Dark', 'Light')[index % 2]]
                    button.event_generate('<ButtonPress-1>', x=8, y=8)
                    button.event_generate('<ButtonRelease-1>', x=8, y=8)
                    window.after(35, lambda: switch(index + 1))
                def finish():
                    assert window.theme_name == 'Light', window.theme_name
                    assert window.vars['url'].get() == 'https://example.com/still-responsive'
                    assert not failures, failures
                    window._close()
                window.after(5, heartbeat)
                window.after(50, switch)
                window.mainloop()
                assert len(beats) >= 18
                assert not failures, failures
            faulthandler.cancel_dump_traceback_later()
            print('18 visible theme clicks completed; timers and input stayed responsive')
        ''')
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=16)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("18 visible theme clicks completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
