"""The product spec (format_version 1). See docs/contracts/spec.md."""

from __future__ import annotations

import json
from pathlib import Path

from .models import FORMAT_VERSION, Product

__all__ = ["FORMAT_VERSION", "Product", "load", "dump", "json_schema"]


def load(path: str | Path) -> Product:
    return Product.model_validate_json(Path(path).read_text(encoding="utf-8"))


def dump(product: Product) -> str:
    """Canonical JSON: same spec, same bytes (sorted keys, no unset noise, trailing newline)."""
    data = product.model_dump(mode="json", exclude_none=True)
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def json_schema() -> str:
    return json.dumps(Product.model_json_schema(), indent=2, sort_keys=True) + "\n"
