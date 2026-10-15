"""Launch the desktop app, or export a QR code from the command line."""

import argparse
import sys


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
    args = parser.parse_args()
    try:
        if args.url is None:
            from qr_maker.app import main as launch
            launch()
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
        print(f"Missing dependency: {exc.name}. Run: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
