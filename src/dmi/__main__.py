"""python -m dmi package SPEC.json [--decks DECK ...] [--history SPEC ...] [--demo]

The whole package for one spec version under DMI_HOME: Haki-format decks, the tech pack
(PDF, BOM, gaps) and a Haki swipe item with the tech pack's pages.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dmi.checks import check, history, profile_severity, report_json
from dmi.paths import home
from dmi.render.deck import render_brief, render_revisions
from dmi.render.techpack import render_bom, render_pages, render_pdf
from dmi.spec import load
from dmi.swipe import item_key, tech_package_item, write_item


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m dmi package")
    ap.add_argument("cmd", choices=["package"])
    ap.add_argument("spec")
    ap.add_argument("--decks", nargs="*", default=[], type=Path)
    ap.add_argument("--history", nargs="*", default=[])
    ap.add_argument("--demo", action="store_true", help="C-suite demo: label 'not evaluated'")
    a = ap.parse_args(argv)
    p = load(a.spec)
    findings = check(p, history(load(h) for h in a.history), profile_severity(p.client))
    images: dict[str, Path] = {}
    if a.decks:
        from dmi.importers.haki_deck import extract_images

        for deck in a.decks:
            images |= extract_images(deck)
    out = home() / "renders" / p.id.replace(":", "_") / f"v{p.spec_version}"
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "techpack.pdf": render_pdf(p, findings, images.get, root=home()),
        "bom.xlsx": render_bom(p, findings),
        "gaps.json": report_json(p, findings).encode(),
        "brief.pptx": render_brief(p, images.get),
    }
    for r in p.sample_rounds:
        files[f"revisions-sample-{r.n}.pptx"] = render_revisions(p, r, images.get)
    for name, data in files.items():
        (out / name).write_bytes(data)
    swipe = home() / "swipe" / item_key(p).replace(":", "_")
    swipe.mkdir(parents=True, exist_ok=True)
    pages = []
    for i, png in enumerate(render_pages(p, findings, images.get, root=home()), 1):
        (swipe / f"page-{i}.png").write_bytes(png)
        pages.append(str(swipe / f"page-{i}.png"))
    item = write_item(tech_package_item(p, findings, pages, a.demo), swipe)
    print(f"package: {out} ({len(files)} files); swipe item: {item} ({len(pages)} pages)")
    print(f"{len(findings)} gaps ({sum(f.severity == 'block' for f in findings)} blocking)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
