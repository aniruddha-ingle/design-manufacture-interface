"""Per-category vocabularies: the points of measure a complete spec states, and the anchors
positions are measured from.

The completeness checks (checks-headwear) read these; a category adds its POMs and anchors here
and never forks the core model. A client profile may map its own words onto these, never add
meanings. Sources: common headwear tech-pack practice; refined as clients' revision history
shows what else factories need.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PomDef:
    code: str
    name: str
    how_to_measure: str
    needs_tolerance: bool = True
    ranged: bool = False  # adjustable: stated as min_mm/max_mm


HEADWEAR_POMS: tuple[PomDef, ...] = (
    PomDef(
        "crown-height",
        "Crown height",
        "Vertical height with the cap standing on a flat surface: table to the top of the button.",
    ),
    PomDef(
        "front-panel-height",
        "Front panel height",
        "Along the centre front seam, following the curve, from the brim seam to the top button.",
    ),
    PomDef(
        "brim-length",
        "Brim length",
        "From the brim seam at centre front to the brim's front edge, measured flat.",
    ),
    PomDef("brim-width", "Brim width", "Across the brim at its widest point, measured flat."),
    PomDef(
        "head-circumference",
        "Head circumference",
        "Inside the sweatband: min at the tightest closure setting, max at the loosest.",
        ranged=True,
    ),
    PomDef(
        "back-opening-width",
        "Back opening width",
        "Across the back opening at its widest, above the closure.",
    ),
    PomDef(
        "back-opening-height",
        "Back opening height",
        "From the sweatband edge to the top of the back opening's arch, at centre back.",
    ),
    PomDef("strap-length", "Strap length", "Closure strap, full length, flat."),
    PomDef(
        "eyelet-position",
        "Eyelet position",
        "From the top button down each panel seam to the eyelet centre.",
        needs_tolerance=False,
    ),
)

HEADWEAR_ANCHORS: frozenset[str] = frozenset(
    {
        "centre-front-seam",  # the seam between the two front panels
        "brim-seam-centre-front",  # where the brim meets the crown, at centre front
        "brim-seam-left-side-seam",  # brim seam at the left side seam (as worn)
        "brim-seam-right-side-seam",
        "top-button",
        "centre-back",  # centre back, at the sweatband edge
        "back-opening-top",  # top of the back opening's arch
        "sweatband-seam-centre-back",  # inside, the sweatband seam at centre back
        "closure-strap-end",
    }
)

POMS_BY_CATEGORY: dict[str, tuple[PomDef, ...]] = {"headwear": HEADWEAR_POMS}
ANCHORS_BY_CATEGORY: dict[str, frozenset[str]] = {"headwear": HEADWEAR_ANCHORS}
