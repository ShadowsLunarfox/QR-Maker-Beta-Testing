# QR Maker

Install Python 3.10 or newer with Tkinter support, then double-click `QR.PY` to
open QR Studio. No batch file is needed. If `.py` files open in an editor, run
`py QR.PY` from this folder instead.

When dependencies are missing, the Python launcher creates a local `.venv` and
installs them automatically. This first setup needs an internet connection.
Keep `QR.PY`, `requirements.txt`, and the `qr_maker` folder together.

To export a QR code from the command line:

```powershell
py QR.PY "https://example.com" --output my-qr.png
```

Run `py QR.PY --help` for design and export options.

In the Design tab, use **Save current** under **Your templates** to save a look.
Select a saved template and click **Apply** to reuse its colors, shapes, logo,
and export options while keeping your current content. **Delete** removes it.
Logo files stay at their original locations, so keep them available.

The app remembers your content, design, export format, and preview surface when you
close it. Templates and the last session are stored locally in
`qr-maker-settings.json` beside `QR.PY` and excluded from Git.

Preview updates reuse QR data and small gradient fields. Window resizing is
throttled, and exports run separately so you can continue adjusting the design.

Choose **System**, **Light**, or **Dark** under **Appearance** in the upper-right
corner. The app remembers this preference. System mode follows the Windows app
theme while QR Studio is running. Interface themes never change QR colors or
exported images, and applying a design template keeps your appearance preference.

The interface uses rounded, softly tinted panels and fine glass borders.
**Compatibility rendering** is enabled by default, including for existing
settings that predate this option. It keeps the client area opaque and avoids
full-window native blur, which can display incorrectly on some monitor/driver
combinations. Light/Dark/System modes and the frosted-style colors remain.

To opt into the native
[Desktop Acrylic backdrop](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)
on Windows 11 build 22621 or later, clear **Compatibility rendering** under
Appearance. The choice is saved separately from design templates and undo history.
Press **Ctrl+Shift+F12** to return to compatibility rendering. If the window
cannot be used, launch `py QR.PY --safe-rendering` to override a saved glass
preference. No system-wide graphics settings are changed.

Choose **URL**, **Text**, **Wi-Fi**, **Contact**, **Phone**, or **Email** in the
content selector. Use **Details** or the **Content** tab for multiline text,
Wi-Fi credentials, contact fields, and email subjects/messages. Content formats
follow the [ZXing barcode conventions](https://github.com/zxing/zxing/wiki/Barcode-Contents).
Wi-Fi passwords remain in memory for this session and are omitted from saved
settings and design templates.

Use **Undo / Redo** or **Ctrl+Z / Ctrl+Y** to step through up to 100 edit states.
Continuous slider adjustments and typing are grouped into one step. Presets,
templates, logo selection, and reset can also be undone. Appearance mode is
independent of design history.

On Windows, **Copy image** (**Ctrl+Shift+C**) copies the full selected image size
directly to the clipboard. PNG clipboard data keeps transparency; applications
using the standard bitmap fallback receive a white-backed image instead.

**Check scan** decodes the selected export format and compares the exact content.
Desktop exports run this check before writing the file, including rasterizing
SVG exports. If decoding fails, you can adjust the design or choose to save it
anyway. A successful local check does not replace testing with your phone.

Drop a logo image anywhere in the app, or use **Choose logo**. The Logo tab
offers **Fit**, **Center crop**, **Circle**, and an inner-padding slider. Cropping
does not change the original image file. PNG/SVG/WebP/JPG exports use the same
processed logo.

