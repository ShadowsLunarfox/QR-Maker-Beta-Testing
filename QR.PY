"""Launch the desktop app, or export a QR code from the command line."""

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

DEPENDENCIES = ("qrcode", "PIL", "zxingcpp", "resvg_py", "tkinterdnd2")


def _prepare_dependencies():
    """Use a local environment when the launching Python lacks dependencies."""
    if all(importlib.util.find_spec(name) is not None for name in DEPENDENCIES):
        return None

    directory = Path(__file__).resolve().parent
    environment = directory / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    temp = directory / ".cache" / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ.update(TMP=str(temp), TEMP=str(temp))

    if not python.is_file():
        import venv

        print("Setting up QR Studio...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)

    command = [str(python)]
    probe = ["-c", "import " + ", ".join(DEPENDENCIES)]
    if subprocess.run(command + probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        if subprocess.run(command + ["-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            subprocess.run(command + ["-m", "ensurepip", "--upgrade"], check=True)
        print("Installing QR Studio dependencies...", flush=True)
        subprocess.run(command + ["-m", "pip", "install", "-r", str(directory / "requirements.txt")], check=True)
        subprocess.run(command + probe, check=True)

    if Path(sys.prefix).resolve() == environment.resolve():
        importlib.invalidate_caches()
        return None
    return subprocess.call(command + [str(directory / "QR.PY"), *sys.argv[1:]])


def _report_error(message, desktop):
    print(message, file=sys.stderr)
    if desktop:
        try:
            import tkinter as tk
            from tkinter import messagebox
        except ImportError:
            return
        try:
            root = tk.Tk()
            root.withdraw()
            try:
                messagebox.showerror("QR Studio could not start", message, parent=root)
            finally:
                root.destroy()
        except tk.TclError:
            pass


def main():
    parser = argparse.ArgumentParser(description="QR Studio — a local QR code designer")
    parser.add_argument("url", nargs="?", help="Website URL (omit to open the desktop app)")
    parser.add_argument("-o", "--output", default="my-qr.png", help="PNG, SVG, JPG, or WebP output path")
    parser.add_argument("--size", type=int, default=1024, help="Image size in pixels (256–4096)")
    parser.add_argument("--color", default="#172033", help="QR color, e.g. '#123456'")
    parser.add_argument("--secondary", default="#087c83", help="Second gradient color")
    parser.add_argument("--background", default="#ffffff", help="Background color")
    parser.add_argument("--transparent", action="store_true", help="Transparent background")
    parser.add_argument("--gradient", default="Solid", choices=("Solid", "Horizontal", "Vertical", "Diagonal", "Radial"))
    parser.add_argument("--shape", default="Square", choices=("Square", "Rounded", "Dots", "Diamond"))
    parser.add_argument("--logo", default="", help="Path to a center logo image")
    parser.add_argument("--safe-rendering", action="store_true", help="Use opaque compatibility rendering instead of native glass")
    args = parser.parse_args()
    try:
        result = _prepare_dependencies()
        if result is not None:
            return result
        if args.url is None:
            from qr_maker.app import main as launch
            launch(safe_rendering=args.safe_rendering)
        else:
            from qr_maker.render import Options, build_design, save_design
            design = build_design(Options(url=args.url, size=args.size, foreground=args.color,
                                          finder_color=args.color, secondary=args.secondary,
                                          background=args.background, transparent=args.transparent,
                                          gradient=args.gradient, shape=args.shape, logo_path=args.logo))
            path = save_design(design, args.output)
            print(f"Saved {path.resolve()}")
            for warning in design.warnings:
                print(f"Note: {warning}")
    except ModuleNotFoundError as exc:
        _report_error(f"Missing dependency: {exc.name}. Install Python 3.10 or newer with Tkinter support and try again.", args.url is None)
        return 1
    except subprocess.CalledProcessError as exc:
        _report_error(f"QR Studio setup failed (exit code {exc.returncode}). Check your internet connection and try opening QR.PY again.", args.url is None)
        return 1
    except (ValueError, OSError) as exc:
        _report_error(f"Error: {exc}", args.url is None)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
