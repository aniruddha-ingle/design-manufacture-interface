"""python -m dmi.render.deck SPEC.json [--decks DECK ...]

Haki's brief deck and one revision deck per sample round, written under
DMI_HOME/renders/<id>/v<spec_version>/. With --decks, pictures are taken from the client's
original decks (copied once into DMI_HOME/assets, never into git); otherwise they show as
labelled frames.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dmi.paths import home
from dmi.spec import load

from . import render_brief, render_revisions


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m dmi.render.deck")
    ap.add_argument("spec")
    ap.add_argument("--decks", nargs="*", default=[], type=Path)
    a = ap.parse_args(argv)
    images: dict[str, Path] = {}
    if a.decks:
        from dmi.importers.haki_deck import extract_images

        for deck in a.decks:
            images |= extract_images(deck)
    p = load(a.spec)
    out = home() / "renders" / p.id.replace(":", "_") / f"v{p.spec_version}"
    out.mkdir(parents=True, exist_ok=True)
    files = {"brief.pptx": render_brief(p, images.get)}
    for r in p.sample_rounds:
        files[f"revisions-sample-{r.n}.pptx"] = render_revisions(p, r, images.get)
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"wrote {out / name} ({len(data) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
