"""Where client data and outputs live: outside git, under DMI_HOME (default ~/.dmi).

Every reader and writer goes through here, so DMI_HOME can become an object store later.
"""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("DMI_HOME", "~/.dmi")).expanduser()


def spec_path(product_id: str, version: int) -> Path:
    safe = product_id.replace(":", "_")
    return home() / "specs" / safe / f"spec-v{version}.json"


def write_atomic(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path
