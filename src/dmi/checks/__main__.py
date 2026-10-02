"""python -m dmi.checks SPEC.json [--severity block|warn] [--history SPEC.json ...]

Prints the gap report as JSON. Exit 1 when any finding blocks.
"""

from __future__ import annotations

import argparse
import sys

from dmi.spec import load

from . import check, history, report_json


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m dmi.checks")
    ap.add_argument("spec")
    ap.add_argument("--severity", choices=["block", "warn"], default="block")
    ap.add_argument("--history", nargs="*", default=[], help="past specs of the same category")
    a = ap.parse_args(argv)
    product = load(a.spec)
    findings = check(product, history(load(h) for h in a.history), a.severity)
    sys.stdout.write(report_json(product, findings))
    return 1 if any(f.severity == "block" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
