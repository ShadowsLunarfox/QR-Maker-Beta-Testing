"""Local design templates and the last desktop session."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile

from .render import Options

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "qr-maker-settings.json"
FORMATS = ("PNG", "SVG", "WebP", "JPG")
SURFACES = ("Checkerboard", "White", "Charcoal")


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    last = data.get("last", {})
    templates = data.get("templates", {})
    return {
        "version": 1,
        "last": last if isinstance(last, dict) else {},
        "templates": {name: value for name, value in templates.items()
                      if isinstance(name, str) and name.strip() and isinstance(value, dict)}
                     if isinstance(templates, dict) else {},
    }


def options_from_snapshot(snapshot: dict) -> Options:
    defaults = asdict(Options())
    values = snapshot.get("options", {})
    if isinstance(values, dict):
        defaults.update({name: value for name, value in values.items()
                         if name in defaults and type(value) is type(defaults[name])})
    return Options(**defaults)


def save_settings(data: dict, path: Path = SETTINGS_PATH):
    """Replace the file only after the complete JSON has been written."""
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=".qr-settings-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
