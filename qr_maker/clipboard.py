"""Publish an image in Windows PNG and standard DIB clipboard formats."""

import io
import sys

from PIL import Image


class ClipboardBusy(OSError):
    pass


def image_formats(image):
    png = io.BytesIO()
    image.save(png, format="PNG")
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    flat = Image.alpha_composite(white, rgba).convert("RGB")
    bitmap = io.BytesIO()
    flat.save(bitmap, format="BMP")
    return png.getvalue(), bitmap.getvalue()[14:]


def set_image_clipboard(owner, formats):
    if sys.platform != "win32":
        raise OSError("Image clipboard copy is currently supported on Windows.")
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes = (wintypes.HWND,)
    user.OpenClipboard.restype = wintypes.BOOL
    user.EmptyClipboard.restype = wintypes.BOOL
    user.CloseClipboard.restype = wintypes.BOOL
    user.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user.SetClipboardData.restype = wintypes.HANDLE
    user.RegisterClipboardFormatW.argtypes = (wintypes.LPCWSTR,)
    user.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    kernel.GlobalFree.argtypes = (wintypes.HGLOBAL,)
    kernel.GlobalFree.restype = wintypes.HGLOBAL

    png_format = user.RegisterClipboardFormatW("PNG")
    if not png_format:
        raise ctypes.WinError(ctypes.get_last_error())
    allocated = []
    opened = False
    try:
        # Allocate before clearing the clipboard. Ownership moves to Windows
        # only after each successful SetClipboardData call.
        for format_id, data in ((png_format, formats[0]), (8, formats[1])):
            handle = kernel.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            allocated.append([format_id, handle])
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                ctypes.memmove(pointer, data, len(data))
            finally:
                kernel.GlobalUnlock(handle)
        if not user.OpenClipboard(owner):
            raise ClipboardBusy("The clipboard is busy. Try copying again.")
        opened = True
        if not user.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        for record in allocated:
            if not user.SetClipboardData(record[0], record[1]):
                raise ctypes.WinError(ctypes.get_last_error())
            record[1] = None
    finally:
        if opened:
            user.CloseClipboard()
        for _, handle in allocated:
            if handle:
                kernel.GlobalFree(handle)
