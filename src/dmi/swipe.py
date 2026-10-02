"""Haki swipe items (product-in-picture's private page, deck item v2): what the CEO and COO
vote on. An item is written under DMI_HOME/swipe/<item>/ (item.json and page images), never
into git; product-in-picture's lead puts it into the private page.

Only reviewed work becomes an item (factory-reviewer PASS), except a C-suite demo, which is
labelled "demo · not evaluated" and is never approval to send anything to a manufacturer.
"""

from __future__ import annotations

import json
from pathlib import Path

from dmi.checks import Finding
from dmi.spec.models import Product

DEPARTMENT = "design-manufacture"


def item_key(p: Product, sample_round: int | None = None) -> str:
    key = f"dmi:{p.id}:spec-{p.spec_version}"
    return key + (f":round-{sample_round}" if sample_round else "")


def tech_package_item(
    p: Product, findings: list[Finding], pages: list[str], demo: bool = False
) -> dict:
    changes = sum(len(r.changes) for r in p.sample_rounds)
    blocking = sum(f.severity == "block" for f in findings)
    summary = (
        f"Complete tech pack v{p.spec_version}: every sample change so far ({changes}) stated "
        f"up front, measurements, artwork, BOM and construction; {len(findings)} open gaps "
        f"({blocking} blocking) listed for the factory. Keep = send it with the deck; "
        f"cut = hold; love = make this the standard for every product."
    )
    item = {
        "item_key": item_key(p),
        "department": DEPARTMENT,
        "kind": "tech-package",
        "source": {"product": p.id, "spec_version": p.spec_version, "sample_round": None},
        "title": ("demo · not evaluated · " if demo else "")
        + f"{p.name}: tech pack v{p.spec_version}",
        "summary": summary[:400],
        "images": [{"src": src, "label": f"page {i}"} for i, src in enumerate(pages, 1)],
        "links": [],
    }
    return item


def write_item(item: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "item.json"
    path.write_text(json.dumps(item, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path
