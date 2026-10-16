"""Fluent-inspired surfaces and optional Windows 11 desktop acrylic."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

THEMES = ("System", "Light", "Dark")
PALETTES = {
    "Light": {
        "background": "#e7eef8", "card": "#f4f7fc", "input": "#ffffff",
        "ink": "#17243b", "muted": "#586a82", "accent": "#2563d9",
        "accent_hover": "#1c53bc", "accent_text": "#ffffff",
        "line": "#d2dceb", "edge": "#ffffff", "shadow": "#ccd7e7",
        "hover": "#e5edfa", "selected": "#dce8fd", "disabled": "#b9c9e1",
        "disabled_ink": "#52647c", "stage": "#e7edf6",
        "warning": "#8a5700", "error": "#b22d3e",
    },
    "Dark": {
        "background": "#111a2b", "card": "#202b3d", "input": "#172234",
        "ink": "#eef3fc", "muted": "#b0bfd4", "accent": "#8ab8ff",
        "accent_hover": "#a7caff", "accent_text": "#112544",
        "line": "#3d4c62", "edge": "#485970", "shadow": "#0a111e",
        "hover": "#303e55", "selected": "#354c70", "disabled": "#3a4c65",
        "disabled_ink": "#a4b3c9", "stage": "#152032",
        "warning": "#f6cc7b", "error": "#ff9eaa",
    },
}


def system_theme() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return "Light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "Dark"
        except OSError:
            pass
    return "Light"


def resolve_theme(mode: str) -> str:
    return mode if mode in PALETTES else system_theme()


def apply_native_material(window: tk.Tk, dark: bool, *, allow_glass: bool = False) -> bool:
    """Style the window frame; full-client acrylic is explicitly opt-in."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        dwm = ctypes.WinDLL("dwmapi")
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(window.winfo_id(), 2)
        if not hwnd:
            return False
        dwm.DwmSetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD)
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long

        def attribute(number, value):
            value = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, number, ctypes.byref(value), ctypes.sizeof(value))

        cached = getattr(window, "_native_material_state", None)
        if cached is not None and cached[0] == hwnd:
            if cached[1] != dark:
                attribute(20, int(dark))
            if cached[3] == allow_glass:
                window._native_material_state = (hwnd, dark, cached[2], allow_glass)
                return cached[2]
        else:
            attribute(20, int(dark))  # DWMWA_USE_IMMERSIVE_DARK_MODE
            attribute(33, 2)  # DWMWCP_ROUND

        if not allow_glass and not (cached and cached[0] == hwnd and cached[2]):
            # Leave the normal opaque client area alone on startup. In
            # particular, do not extend a transparent frame across GDI widgets.
            window._native_material_state = (hwnd, dark, False, False)
            return False

        class Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

        dwm.DwmExtendFrameIntoClientArea.argtypes = (wintypes.HWND, ctypes.POINTER(Margins))
        dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        if not allow_glass:
            attribute(38, 1)  # DWMSBT_NONE
            dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(Margins(0, 0, 0, 0)))
            window._native_material_state = (hwnd, dark, False, False)
            return False
        if sys.getwindowsversion().build < 22621:
            window._native_material_state = (hwnd, dark, False, True)
            return False
        # DWMSBT_TRANSIENTWINDOW selects Desktop Acrylic. Pure-black shell
        # pixels expose it; content surfaces and QR images remain opaque.
        if attribute(38, 3) == 0:
            margins = Margins(-1, -1, -1, -1)
            if dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins)) == 0:
                window._native_material_state = (hwnd, dark, True, True)
                return True
        attribute(38, 1)
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(Margins(0, 0, 0, 0)))
        window._native_material_state = (hwnd, dark, False, True)
    except (AttributeError, OSError, tk.TclError):
        pass
    return False


class GlassCard(tk.Canvas):
    """Rounded, softly tinted content surface with a fine glass edge."""

    def __init__(self, parent, palette, shell, padding=18, **kwargs):
        super().__init__(parent, background=shell, highlightthickness=0, bd=0, **kwargs)
        self.palette = palette
        self.padding = padding
        self.body = ttk.Frame(self, style="Card.TFrame")
        self._body_window = self.create_window(padding, padding, window=self.body, anchor="nw")
        self._surface_size = None
        self.bind("<Configure>", self._resize)

    def set_palette(self, palette, shell):
        self.palette = palette
        self.configure(background=shell)
        self._surface_size = None
        self._resize()

    def _rounded(self, x, y, right, bottom, radius, **kwargs):
        self.create_polygon(x + radius, y, right - radius, y, right, y,
                            right, y + radius, right, bottom - radius, right, bottom,
                            right - radius, bottom, x + radius, bottom, x, bottom,
                            x, bottom - radius, x, y + radius, x, y,
                            smooth=True, splinesteps=20, tags="surface", **kwargs)

    def _resize(self, _event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 4 or height < 4:
            return
        if self._surface_size == (width, height):
            return
        self._surface_size = (width, height)
        self.delete("surface")
        self._rounded(2, 4, width - 2, height - 1, 18, fill=self.palette["shadow"], outline="")
        self._rounded(1, 1, width - 2, height - 4, 18, fill=self.palette["card"], outline=self.palette["edge"], width=1)
        self.tag_lower("surface")
        self.itemconfigure(self._body_window, width=max(1, width - self.padding * 2),
                           height=max(1, height - self.padding * 2 - 3))
