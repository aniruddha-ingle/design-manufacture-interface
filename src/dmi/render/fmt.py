"""How every renderer writes numbers, so the deck, the PDF and the BOM read the same.

- Lengths of 10 mm and up: cm to 0.1 and inches to 1/8 ("7.5 cm / 3""); under 10 mm: mm to
  0.1 and inches to 0.01 ("0.8 mm / 0.03""), so small parts never round to zero.
- Tolerances carry their unit ("±0.2 cm", "±0.5 mm").
- Positions say direction in words, as seen from outside facing the surface: "4.0 cm
  (1 5/8") to the viewer's left, 3.5 cm (1 3/8") up from <anchor>"; zero is "centred".
- Every function returns None for a gap; callers decide how a gap looks.
"""

from __future__ import annotations

import io
import re
import zipfile

from dmi.spec.models import Length, Position
from dmi.spec.units import inch_fraction, mm_to_cm, mm_to_inch

FIXED_TIME = "2000-01-01T00:00:00Z"


def value(mm: float) -> str:
    if abs(mm) < 10:
        return f'{mm:g} mm / {mm_to_inch(mm):.2f}"'
    return f'{mm_to_cm(mm)} cm / {inch_fraction(mm)}"'


def _tol_unit(mm: float) -> str:
    return f"{mm:g} mm" if mm < 10 else f"{mm_to_cm(mm, 2):g} cm"


def tol(v: Length | None) -> str | None:
    if v is None or v.tol_mm is None:
        return None
    minus = v.tol_minus_mm if v.tol_minus_mm is not None else v.tol_mm
    if minus == v.tol_mm:
        return f"±{_tol_unit(v.tol_mm)}"
    return f"+{_tol_unit(v.tol_mm)} / −{_tol_unit(minus)}"


def length(v: Length | None, with_tol: bool = False) -> str | None:
    if v is None or not v.known:
        return None
    if v.mm is not None:
        s = value(v.mm)
    else:
        lo, hi = value(v.min_mm).split(" / "), value(v.max_mm).split(" / ")
        s = f"{lo[0]}–{hi[0]} / {lo[1]}–{hi[1]} (adjustable)"
    t = tol(v) if with_tol else None
    return f"{s} {t}" if t else s


def _dir(mm: float, pos: str, neg: str) -> str:
    if mm == 0:
        return "centred"
    return f"{value(abs(mm))} {pos if mm > 0 else neg}"


def position(p: Position | None) -> str | None:
    """A complete position in words, or None when anything is missing (a gap)."""
    if p is None or p.to is None or p.dx_mm is None or p.dy_mm is None:
        return None
    across = _dir(p.dx_mm, "to the viewer's right", "to the viewer's left")
    up = _dir(p.dy_mm, "up", "down")
    point, anchor = p.to.replace("-", " "), p.anchor.replace("-", " ")
    if p.dx_mm or p.dy_mm:
        s = f"{point} {across}, {up} from {anchor}"
    else:
        s = f"{point} aligned at {anchor}"
    return s + (f" ({p.note})" if p.note else "")


def fixed_zip(data: bytes) -> bytes:
    """Rewrite an OOXML package (pptx, xlsx) so its bytes depend only on its content: fixed
    entry times, and fixed created/modified dates in docProps/core.xml."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            blob = src.read(name)
            if name == "docProps/core.xml":
                blob = re.sub(
                    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                    rb"\g<1>" + FIXED_TIME.encode() + rb"\g<2>",
                    blob,
                )
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, blob)
    return out.getvalue()
