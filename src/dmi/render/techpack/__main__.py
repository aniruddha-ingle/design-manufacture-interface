"""python -m dmi.render.techpack SPEC.json [--decks DECK ...] [--history SPEC.json ...]

Writes techpack.pdf, bom.xlsx and gaps.json under DMI_HOME/renders/<id>/v<spec_version>/.
Gap severity comes from the client profile. --decks resolves pictures from the client's own
decks (copied once into DMI_HOME/assets, never into git); --history adds past specs of the
category so their revisions tighten the checks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dmi.checks import check, history, profile_severity, report_json
from dmi.paths import home
from dmi.spec import load

from . import render_bom, render_pdf


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m dmi.render.techpack")
    ap.add_argument("spec")
    ap.add_argument("--decks", nargs="*", default=[], type=Path)
    ap.add_argument("--history", nargs="*", default=[])
    a = ap.parse_args(argv)
    p = load(a.spec)
    findings = check(p, history(load(h) for h in a.history), profile_severity(p.client))
    images: dict[str, Path] = {}
    for deck in a.decks:
        from dmi.importers.haki_deck import extract_images

        images |= extract_images(deck)
    out = home() / "renders" / p.id.replace(":", "_") / f"v{p.spec_version}"
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "techpack.pdf": render_pdf(p, findings, images.get, root=home()),
        "bom.xlsx": render_bom(p, findings),
        "gaps.json": report_json(p, findings).encode(),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"wrote {out / name} ({len(data) // 1024} KB)")
    print(f"{len(findings)} gaps ({sum(f.severity == 'block' for f in findings)} blocking)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
