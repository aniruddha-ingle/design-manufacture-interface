"""Lengths are stored in millimetres; conversion happens only when rendering.

A tech pack is read by people working in cm or inches. Storing one unit avoids drift between
the two, and every conversion goes through here so it is tested once.
"""

from __future__ import annotations

MM_PER_CM = 10.0
MM_PER_INCH = 25.4


def cm_to_mm(cm: float) -> float:
    return round(cm * MM_PER_CM, 3)


def inch_to_mm(inch: float) -> float:
    return round(inch * MM_PER_INCH, 3)


def mm_to_cm(mm: float, places: int = 1) -> float:
    return round(mm / MM_PER_CM, places)


def mm_to_inch(mm: float, places: int = 2) -> float:
    return round(mm / MM_PER_INCH, places)


def inch_fraction(mm: float, denominator: int = 8) -> str:
    """Render mm as inches to the nearest 1/denominator, the way factories write it ("2 5/8")."""
    if mm < 0:
        return "-" + inch_fraction(-mm, denominator)
    eighths = round(mm / MM_PER_INCH * denominator)
    whole, rest = divmod(eighths, denominator)
    if rest == 0:
        return f"{whole}"
    num, den = rest, denominator
    while num % 2 == 0 and den % 2 == 0:
        num, den = num // 2, den // 2
    return f"{whole} {num}/{den}" if whole else f"{num}/{den}"
