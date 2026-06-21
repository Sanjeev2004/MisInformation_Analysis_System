"""Server-side helpers for locating the framework-free frontend assets."""

from pathlib import Path


def frontend_root() -> Path:
    root = Path(__file__).resolve().parent
    required = ("index.html", "app.js", "utils.js", "styles.css")
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing frontend assets: {', '.join(missing)}")
    return root
