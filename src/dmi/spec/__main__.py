"""python -m dmi.spec validate FILE... | schema"""

from __future__ import annotations

import sys

from pydantic import ValidationError

from . import json_schema, load


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("validate", "schema"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if argv[0] == "schema":
        sys.stdout.write(json_schema())
        return 0
    status = 0
    for path in argv[1:]:
        try:
            p = load(path)
            print(f"ok  {path}: {p.id} v{p.spec_version}")
        except (ValidationError, OSError) as e:
            print(f"bad {path}: {e}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
