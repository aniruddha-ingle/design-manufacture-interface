"""Completeness checks: what a factory would have to ask about before making the product.

Two sources (the north star: revision rounds per product, towards zero):
- **standard**: what a complete tech pack of the category states (``dmi.spec.categories``);
- **revision-history**: a kind of field that needed a sample revision, in this product or in
  past products of the same category, is checked *more strictly* on every product (e.g. a
  revised POM must carry a tolerance; a revised hardware kind must state requirements and a
  supplier; a revised label kind must carry its artwork and measured size).

Each finding names the spec field, why a factory needs it, its source and its severity.
Severity comes from the client profile's ``gap_severity``: "block" (the default) or "warn".
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from dmi.spec.categories import POMS_BY_CATEGORY
from dmi.spec.models import Change, Length, Position, Product

Severity = Literal["block", "warn"]
Source = Literal["standard", "revision-history"]

EMBROIDERY = {"flat-embroidery", "puff-embroidery", "chain-stitch", "embroidered-patch"}
POSITIONED_HARDWARE = {"eyelet", "top-button", "snap", "rivet", "grommet"}
PROFILES = Path(__file__).resolve().parents[3] / "profiles"


@dataclass(frozen=True)
class Finding:
    code: str  # stable, e.g. "length-missing"
    field: str  # dotted spec path, e.g. "poms.brim-length"
    message: str
    why: str  # why the factory needs it
    source: Source
    severity: Severity


@dataclass(frozen=True)
class Learned:
    """A revision-derived check: a kind of field that once needed a sample revision."""

    area: str  # the change area
    key: str  # pom code, hardware kind, label kind, or "*"


def learn(changes: Iterable[tuple[Product, Change]]) -> set[Learned]:
    """Turn past changes into checks for future products of the same category."""
    out: set[Learned] = set()
    for product, c in changes:
        head, *rest = c.field.split(".")
        ref = rest[0] if rest else "*"
        if c.area == "pom":
            out.add(Learned("pom", ref))
        elif c.area in ("placement-position", "placement-size"):
            out |= {Learned("placement-position", "*"), Learned("placement-size", "*")}
        elif c.area == "hardware":
            hw = next((h for h in product.hardware if h.id == ref), None)
            out.add(Learned("hardware", hw.kind if hw else "*"))
        elif c.area == "label":
            lb = next((x for x in product.labels if x.id == ref), None)
            out.add(Learned("label", lb.kind if lb and lb.kind != "unspecified" else "*"))
        elif c.area != "other":
            out.add(Learned(c.area, "*"))
    return out


def history(products: Iterable[Product]) -> set[Learned]:
    return learn((p, c) for p in products for r in p.sample_rounds for c in r.changes)


def profile_severity(client: str, profiles: Path = PROFILES) -> Severity:
    path = profiles / client / "profile.json"
    if not path.exists():
        return "block"
    return json.loads(path.read_text(encoding="utf-8")).get("gap_severity", "block")


class _Run:
    def __init__(self, product: Product, learned: set[Learned], severity: Severity):
        self.p, self.learned, self.severity = product, learned, severity
        self.findings: list[Finding] = []

    def gap(self, code: str, field: str, msg: str, why: str, learned: bool = False) -> None:
        source: Source = "revision-history" if learned else "standard"
        self.findings.append(Finding(code, field, msg, why, source, self.severity))

    def hit(self, area: str, key: str = "*") -> bool:
        return Learned(area, key) in self.learned or Learned(area, "*") in self.learned

    def length(self, field: str, v: Length | None, what: str, tol: bool, hit: bool) -> None:
        if v is None or not v.known:
            self.gap(
                "length-missing",
                field,
                f"{what}: no measurement",
                "it can't be made or checked",
                hit,
            )
        elif (tol or hit) and v.tol_mm is None:
            self.gap(
                "tolerance-missing", field, f"{what}: no tolerance", "QC can't pass or fail it", hit
            )

    def position(self, field: str, pos: Position | None, what: str, hit: bool) -> None:
        if pos is None:
            self.gap(
                "position-missing",
                field,
                f"{what}: no measured position",
                "placed by eye, it moves",
                hit,
            )
            return
        if pos.to is None:
            self.gap(
                "position-point-missing",
                field,
                f"{what}: offset to which point?",
                "centre vs edge is half the item",
                hit,
            )
        if pos.dx_mm is None or pos.dy_mm is None:
            self.gap(
                "position-offset-missing",
                field,
                f"{what}: offset not measured both ways",
                "placed by eye, it moves",
                hit,
            )
        if hit and pos.anchor.startswith("other:"):
            self.gap(
                "anchor-standard",
                field,
                f"{what}: measured from a free-text point",
                "this was revised before; use a standard anchor",
                True,
            )

    def colour(self, field: str, colour, what: str, hit: bool) -> None:
        if colour is None or not colour.code:
            self.gap(
                "colour-ref-missing",
                field,
                f"{what}: no colour reference",
                "a name is matched by eye",
                hit,
            )
        elif hit and colour.system is None:
            self.gap(
                "colour-system-missing",
                field,
                f"{what}: which colour system?",
                "this was revised before",
                True,
            )


def check(
    product: Product, learned: set[Learned] | None = None, severity: Severity = "block"
) -> list[Finding]:
    """All gaps in ``product``; ``learned`` adds revision-derived checks (see ``history``)."""
    r = _Run(product, (learned or set()) | history([product]), severity)
    p = product
    _poms(r, p)
    _placements(r, p)
    _materials(r, p)
    _hardware(r, p)
    _labels(r, p)
    _construction(r, p)
    for t in p.trims:
        f, hit = f"trims.{t.id}", r.hit("trim")
        r.length(f + ".width", t.width, f"trim '{t.id}' width", True, hit)
        if t.material_id is None:
            r.colour(f, t.colour, f"trim '{t.id}'", hit or r.hit("colour"))
    pk, hit = p.packaging, r.hit("packaging")
    if pk is None or not (pk.unit and pk.folding):
        r.gap(
            "packaging-missing",
            "packaging",
            "packaging: unit and folding",
            "the factory packs to spec",
            hit,
        )
    elif hit and not pk.carton:
        r.gap(
            "carton-missing",
            "packaging.carton",
            "packaging: carton",
            "this was revised before",
            True,
        )
    if not p.quantities:
        r.gap(
            "quantities-missing", "quantities", "no quantities", "materials are planned by quantity"
        )
    for ref in p.references:
        if ref.authority is None:
            r.gap(
                "reference-authority-missing",
                f"references.{ref.id}",
                f"reference '{ref.id}': exact or approximate?",
                "a mockup copied exactly is a common wrong sample",
            )
    return r.findings


def _poms(r: _Run, p: Product) -> None:
    defs = {d.code: d for d in POMS_BY_CATEGORY.get(p.category, ())}
    learned = {x.key for x in r.learned if x.area == "pom" and x.key != "*"}
    codes = list(defs) + [c for c in [pm.code for pm in p.poms] + sorted(learned) if c not in defs]
    for code in dict.fromkeys(codes):
        d, pm, hit = defs.get(code), p.pom(code), r.hit("pom", code)
        name = d.name if d else (pm.name if pm else code)
        for size in p.sizes:
            v = pm.values.get(size) if pm else None
            r.length(f"poms.{code}", v, f"{name} ({size})", d.needs_tolerance if d else True, hit)
            if v is not None and d and d.ranged and v.mm is not None:
                r.gap(
                    "range-expected",
                    f"poms.{code}",
                    f"{name}: one value for an adjustable measurement",
                    "state tightest and loosest",
                    hit,
                )


def _placements(r: _Run, p: Product) -> None:
    hit_pos, hit_size = r.hit("placement-position"), r.hit("placement-size")
    for pl in p.placements:
        f, what = f"placements.{pl.id}", f"artwork '{pl.id}'"
        if pl.technique is None:
            r.gap(
                "technique-missing",
                f,
                f"{what}: no technique",
                "embroidery, print and patch differ",
            )
        if not pl.artwork_ref:
            r.gap(
                "artwork-missing",
                f,
                f"{what}: no artwork file",
                "the factory digitises or screens the vector",
                hit_size,
            )
        r.length(f + ".width", pl.width, f"{what} width", True, hit_size)
        r.length(f + ".height", pl.height, f"{what} height", True, hit_size)
        r.position(f, pl.position, what, hit_pos)
        if not pl.elements:
            r.gap(
                "colours-missing",
                f,
                f"{what}: no colours per element",
                "thread or ink is matched per element",
            )
        for e in pl.elements:
            r.colour(f + ".elements", e.colour, f"{what}, {e.name}", r.hit("colour"))
            if pl.technique in EMBROIDERY and not e.thread:
                r.gap(
                    "thread-missing",
                    f + ".elements",
                    f"{what}, {e.name}: no thread",
                    "thread type changes the look",
                    r.hit("colour"),
                )
        if pl.technique == "puff-embroidery" and pl.foam_height_mm is None:
            r.gap("foam-missing", f, f"{what}: no foam height", "puff height is set by the foam")
        if pl.technique in EMBROIDERY and hit_size and pl.stitch_count is None:
            r.gap(
                "stitch-count-missing",
                f,
                f"{what}: no stitch count",
                "size was revised before; the count fixes the density",
                True,
            )


def _materials(r: _Run, p: Product) -> None:
    for m in p.materials:
        f, hit = f"materials.{m.id}", r.hit("material")
        if not m.composition:
            r.gap(
                "composition-missing",
                f,
                f"material '{m.id}': no composition",
                "sourcing and the care label",
                hit,
            )
        r.colour(f, m.colour, f"material '{m.id}'", r.hit("colour"))
        if m.role == "shell" and m.weight_gsm is None:
            r.gap(
                "weight-missing",
                f,
                "shell fabric: no weight (gsm)",
                "weight changes drape and structure",
                hit,
            )
        if hit and m.weight_gsm is None and m.thickness is None:
            r.gap(
                "weight-or-thickness-missing",
                f,
                f"material '{m.id}': no weight or thickness",
                "materials were revised before",
                True,
            )
        if not m.supplier_ref:
            r.gap(
                "supplier-missing",
                f,
                f"material '{m.id}': no supplier reference",
                "a near match gets sourced",
                hit,
            )


def _hardware(r: _Run, p: Product) -> None:
    for h in p.hardware:
        f, hit, what = f"hardware.{h.id}", r.hit("hardware", h.kind), f"{h.kind} '{h.id}'"
        for attr, why in (
            ("material", "metals wear differently"),
            ("finish", "finish is part of the look"),
        ):
            if getattr(h, attr) is None:
                r.gap(f"hardware-{attr}-missing", f, f"{what}: no {attr}", why, hit)
        r.length(f + ".size", h.size, f"{what} size", False, hit)
        if h.quantity is None:
            r.gap(
                "quantity-missing",
                f,
                f"{what}: no quantity per piece",
                "hardware is bought by count",
                hit,
            )
        if h.kind in POSITIONED_HARDWARE:
            r.position(f, h.position, what, hit)
        if hit and not h.requirements:
            r.gap(
                "hardware-requirements-missing",
                f,
                f"{what}: no requirements",
                "revised before; say what it must and must not do",
                True,
            )
        if hit and not h.supplier_ref:
            r.gap(
                "supplier-missing",
                f,
                f"{what}: no supplier reference",
                "revised before; name the part",
                True,
            )


def _labels(r: _Run, p: Product) -> None:
    kinds = {lb.kind for lb in p.labels}
    required = {"care": "required to sell in most markets", "inner": "the brand label inside"}
    required |= {
        x.key: "this label was revised before"
        for x in r.learned
        if x.area == "label" and x.key != "*"
    }
    for kind, why in required.items():
        if kind not in kinds:
            r.gap("label-missing", "labels", f"no {kind} label", why, r.hit("label", kind))
    for lb in p.labels:
        f, hit, what = f"labels.{lb.id}", r.hit("label", lb.kind), f"{lb.kind} label '{lb.id}'"
        r.position(f, lb.position, what, hit)
        r.length(f + ".width", lb.width, f"{what} width", hit, hit)
        r.length(f + ".height", lb.height, f"{what} height", hit, hit)
        for attr in ("material", "attachment"):
            if getattr(lb, attr) is None:
                r.gap(
                    f"label-{attr}-missing",
                    f,
                    f"{what}: no {attr}",
                    "labels are bought and sewn by spec",
                    hit,
                )
        if lb.kind == "care" and not lb.content:
            r.gap(
                "care-content-missing",
                f,
                f"{what}: no care text",
                "composition and care are legally required",
            )
        elif lb.kind != "care" and not lb.artwork_ref:
            r.gap(
                "artwork-missing",
                f,
                f"{what}: no artwork file",
                "woven and printed labels are made from it",
                hit,
            )


def _construction(r: _Run, p: Product) -> None:
    c, hit = p.construction, r.hit("construction")
    for attr in (
        ("structure", "crown", "brim", "closure") if p.category == "headwear" else ("closure",)
    ):
        if getattr(c, attr) is None:
            r.gap(
                "construction-missing",
                f"construction.{attr}",
                f"construction: no {attr}",
                "it changes the pattern",
                hit,
            )
    if not c.seams:
        r.gap(
            "seams-missing",
            "construction.seams",
            "no seam or stitch spec",
            "stitch type and SPI change strength and look",
            hit,
        )
    for s in c.seams:
        if s.spi is None:
            r.gap(
                "spi-missing",
                "construction.seams",
                f"seam '{s.location}': no stitches per inch",
                "SPI changes strength and look",
                hit,
            )
        if hit and (s.thread is None or s.stitch_type is None):
            r.gap(
                "seam-detail-missing",
                "construction.seams",
                f"seam '{s.location}': thread and stitch type",
                "construction was revised before",
                True,
            )


def report(product: Product, findings: list[Finding]) -> dict:
    """The gap report as data (JSON-ready): counts first, then every finding."""
    return {
        "product": product.id,
        "spec_version": product.spec_version,
        "blocking": sum(f.severity == "block" for f in findings),
        "warnings": sum(f.severity == "warn" for f in findings),
        "from_revision_history": sum(f.source == "revision-history" for f in findings),
        "findings": [asdict(f) for f in findings],
    }


def report_json(product: Product, findings: list[Finding]) -> str:
    return json.dumps(report(product, findings), indent=2, sort_keys=True) + "\n"
