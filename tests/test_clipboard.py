import ctypes
import io
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from qr_maker.clipboard import ClipboardBusy, image_formats, set_image_clipboard


class ClipboardTests(unittest.TestCase):
    def test_png_keeps_alpha_and_dib_supplies_a_standard_white_backed_bitmap(self):
        image = Image.new("RGBA", (12, 10), (0, 0, 0, 0))
        image.putpixel((5, 5), (12, 34, 56, 255))
        png, dib = image_formats(image)
        with Image.open(io.BytesIO(png)) as result:
            self.assertEqual(result.getpixel((0, 0))[3], 0)
            self.assertEqual(result.getpixel((5, 5)), (12, 34, 56, 255))
        header = struct.pack("<2sIHHI", b"BM", len(dib) + 14, 0, 0, 54)
        with Image.open(io.BytesIO(header + dib)) as result:
            self.assertEqual(result.size, image.size)
            self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(result.getpixel((5, 5)), (12, 34, 56))

    def native_api(self, opened):
        buffers = {}

        def allocate(flags, size):
            handle = len(buffers) + 1
            buffers[handle] = ctypes.create_string_buffer(size)
            return handle

        kernel = SimpleNamespace(GlobalAlloc=Mock(side_effect=allocate),
                                 GlobalLock=Mock(side_effect=lambda handle: ctypes.addressof(buffers[handle])),
                                 GlobalUnlock=Mock(), GlobalFree=Mock())
        user = SimpleNamespace(OpenClipboard=Mock(return_value=opened), EmptyClipboard=Mock(return_value=True),
                               CloseClipboard=Mock(), RegisterClipboardFormatW=Mock(return_value=50000),
                               SetClipboardData=Mock(side_effect=lambda format_id, handle: handle))
        return kernel, user, buffers

    def test_clipboard_memory_is_transferred_without_freeing_windows_owned_data(self):
        kernel, user, buffers = self.native_api(True)
        with patch("qr_maker.clipboard.sys.platform", "win32"), patch.object(ctypes, "WinDLL", side_effect=lambda name, **_: user if name == "user32" else kernel, create=True):
            set_image_clipboard(123, (b"png data", b"dib data"))
        user.OpenClipboard.assert_called_once_with(123)
        self.assertEqual(user.SetClipboardData.call_args_list[0].args[0], 50000)
        self.assertEqual(user.SetClipboardData.call_args_list[1].args[0], 8)
        self.assertEqual(buffers[1].raw, b"png data")
        self.assertEqual(buffers[2].raw, b"dib data")
        kernel.GlobalFree.assert_not_called()
        user.CloseClipboard.assert_called_once()

    def test_busy_clipboard_frees_our_buffers_without_clearing_existing_content(self):
        kernel, user, _ = self.native_api(False)
        with patch("qr_maker.clipboard.sys.platform", "win32"), patch.object(ctypes, "WinDLL", side_effect=lambda name, **_: user if name == "user32" else kernel, create=True):
            with self.assertRaises(ClipboardBusy):
                set_image_clipboard(123, (b"png", b"dib"))
        self.assertEqual(kernel.GlobalFree.call_count, 2)
        user.EmptyClipboard.assert_not_called()
        user.CloseClipboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
