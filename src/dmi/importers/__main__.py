"""python -m dmi.importers haki --id pre:haki:<slug> --brief DECK [--revision DECK ...]

Reads Haki's decks in place and writes each spec version under DMI_HOME/specs/<id>/.
Prints what was read (counts and field names, never values).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dmi.paths import spec_path, write_atomic
from dmi.spec import dump

from .haki_deck import import_brief, import_revisions


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m dmi.importers")
    ap.add_argument("client", choices=["haki"])
    ap.add_argument("--id", required=True, help="pre:haki:<opaque slug>, never the product name")
    ap.add_argument("--brief", required=True, type=Path)
    ap.add_argument("--revision", nargs="*", default=[], type=Path)
    a = ap.parse_args(argv)
    p = import_brief(a.brief, a.id)
    out = [write_atomic(spec_path(p.id, p.spec_version), dump(p))]
    for deck in a.revision:
        p = import_revisions(deck, p)
        out.append(write_atomic(spec_path(p.id, p.spec_version), dump(p)))
    print(
        f"{p.id} v{p.spec_version}: {len(p.placements)} placements, {len(p.poms)} poms, "
        f"{len(p.materials)} materials, {len(p.hardware)} hardware, {len(p.labels)} labels, "
        f"{len(p.references)} references, {sum(len(r.changes) for r in p.sample_rounds)} changes "
        f"in {len(p.sample_rounds)} round(s); areas "
        f"{sorted({c.area for r in p.sample_rounds for c in r.changes})}"
    )
    for path in out:
        print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
