"""Completeness checks: what a factory would have to ask about before making the product.

Two sources (the north star: revision rounds per product, towards zero):
- **standard**: what a complete tech pack of the category states (``dmi.spec.categories``);
- **revision-history**: every field that needed a sample revision, in this product or in
  past products of the same category, is checked strictly on every new product.

Each finding names the spec field, why a factory needs it, and its severity. Severity comes
from the client profile: "block" (the default, for clients whose factories need a complete
pack) or "warn" (Haki: the factory relationship fills gaps; the report is still produced).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Literal

from dmi.spec.categories import POMS_BY_CATEGORY
from dmi.spec.models import Change, Length, Position, Product

Severity = Literal["block", "warn"]
Source = Literal["standard", "revision-history"]

EMBROIDERY = {"flat-embroidery", "puff-embroidery", "chain-stitch", "embroidered-patch"}


@dataclass(frozen=True)
class Finding:
    code: str  # stable, e.g. "pom-missing"
    field: str  # dotted spec path, e.g. "poms.brim-length"
    message: str
    why: str  # why the factory needs it
    source: Source
    severity: Severity


@dataclass(frozen=True)
class Learned:
    """A revision-derived check: a kind of field that once needed a sample revision."""

    area: str  # the change area
    key: str  # pom code, hardware kind, label kind, or "*" for every placement


def learn(changes: Iterable[tuple[Product, Change]]) -> set[Learned]:
    """Turn past changes into checks for future products of the same category."""
    out: set[Learned] = set()
    for product, c in changes:
        head, *rest = c.field.split(".")
        ref = rest[0] if rest else "*"
        if c.area == "pom":
            out.add(Learned("pom", ref))
        elif c.area in ("placement-position", "placement-size"):
            out.add(Learned(c.area, "*"))
        elif c.area == "hardware":
            hw = next((h for h in product.hardware if h.id == ref), None)
            out.add(Learned("hardware", hw.kind if hw else "*"))
        elif c.area == "label":
            lb = next((x for x in product.labels if x.id == ref), None)
            out.add(Learned("label", lb.kind if lb else "*"))
        elif c.area in ("material", "colour", "construction", "trim", "packaging"):
            out.add(Learned(c.area, "*"))
    return out


def history(products: Iterable[Product]) -> set[Learned]:
    return learn((p, c) for p in products for r in p.sample_rounds for c in r.changes)


class _Run:
    def __init__(self, product: Product, learned: set[Learned], severity: Severity):
        self.p, self.learned, self.severity = product, learned, severity
        self.findings: list[Finding] = []

    def gap(self, code: str, field: str, message: str, why: str, learned: bool = False) -> None:
        source: Source = "revision-history" if learned else "standard"
        self.findings.append(Finding(code, field, message, why, source, self.severity))

    def was_revised(self, area: str, key: str = "*") -> bool:
        return Learned(area, key) in self.learned or Learned(area, "*") in self.learned

    def length(self, field: str, v: Length | None, what: str, tol: bool, learned: bool) -> None:
        if v is None or not v.known:
            self.gap(
                "length-missing",
                field,
                f"{what}: no measurement",
                "the factory cannot make or check it",
                learned,
            )
        elif tol and v.tol_mm is None:
            self.gap(
                "tolerance-missing",
                field,
                f"{what}: no tolerance",
                "QC cannot pass or fail the sample",
                learned,
            )

    def position(self, field: str, pos: Position | None, what: str, learned: bool) -> None:
        if pos is None:
            self.gap(
                "position-missing",
                field,
                f"{what}: no measured position",
                "placed by eye, it moves sample to sample",
                learned,
            )
            return
        if pos.to is None:
            self.gap(
                "position-point-missing",
                field + ".position",
                f"{what}: offset doesn't say which point of the item",
                "centre and edge differ by half the item",
                learned,
            )
        if pos.dx_mm is None or pos.dy_mm is None:
            self.gap(
                "position-offset-missing",
                field + ".position",
                f"{what}: offset not measured in both directions",
                "placed by eye, it moves sample to sample",
                learned,
            )


def check(
    product: Product, learned: set[Learned] | None = None, severity: Severity = "block"
) -> list[Finding]:
    """All gaps in ``product``; ``learned`` adds revision-derived checks (see ``history``)."""
    learned = (learned or set()) | history([product])
    r = _Run(product, learned, severity)
    p = product

    for d in POMS_BY_CATEGORY.get(p.category, ()):
        pom, hit = p.pom(d.code), r.was_revised("pom", d.code)
        for size in p.sizes:
            v = pom.values.get(size) if pom else None
            r.length(f"poms.{d.code}", v, f"{d.name} ({size})", d.needs_tolerance, hit)
            if v is not None and d.ranged and v.mm is not None:
                r.gap(
                    "range-expected",
                    f"poms.{d.code}",
                    f"{d.name}: one value for an adjustable measurement",
                    "state the tightest and loosest setting",
                    hit,
                )

    for pl in p.placements:
        f, what = f"placements.{pl.id}", f"artwork '{pl.id}'"
        hit_pos, hit_size = r.was_revised("placement-position"), r.was_revised("placement-size")
        if pl.technique is None:
            r.gap(
                "technique-missing",
                f,
                f"{what}: no technique",
                "embroidery, print and patch are made differently",
            )
        if not pl.artwork_ref:
            r.gap(
                "artwork-missing",
                f,
                f"{what}: no artwork file",
                "the factory needs the vector to digitise or screen",
            )
        r.length(f + ".width", pl.width, f"{what} width", True, hit_size)
        r.length(f + ".height", pl.height, f"{what} height", True, hit_size)
        r.position(f, pl.position, what, hit_pos)
        if not pl.elements:
            r.gap(
                "colours-missing",
                f,
                f"{what}: no colours per element",
                "thread or ink is bought and matched per element",
            )
        for e in pl.elements:
            if e.colour is None or not e.colour.code:
                r.gap(
                    "colour-ref-missing",
                    f + ".elements",
                    f"{what}, {e.name}: no colour reference",
                    "a name alone is matched by eye",
                    r.was_revised("colour"),
                )
            if pl.technique in EMBROIDERY and not e.thread:
                r.gap(
                    "thread-missing",
                    f + ".elements",
                    f"{what}, {e.name}: no thread",
                    "thread type and weight change the look",
                )
        if pl.technique == "puff-embroidery" and pl.foam_height_mm is None:
            r.gap("foam-missing", f, f"{what}: no foam height", "puff height is set by the foam")

    for m in p.materials:
        f, hit = f"materials.{m.id}", r.was_revised("material")
        if not m.composition:
            r.gap(
                "composition-missing",
                f,
                f"material '{m.id}': no composition",
                "needed to source it and for the care label",
                hit,
            )
        if m.colour is None or not m.colour.code:
            r.gap(
                "colour-ref-missing",
                f,
                f"material '{m.id}': no colour reference",
                "dyed to a reference, not a name",
                r.was_revised("colour"),
            )
        if m.role == "shell" and m.weight_gsm is None:
            r.gap(
                "weight-missing",
                f,
                "shell fabric: no weight (gsm)",
                "weight changes drape and structure",
                hit,
            )
        if not m.supplier_ref:
            r.gap(
                "supplier-missing",
                f,
                f"material '{m.id}': no supplier reference",
                "the factory may source a near match",
                hit,
            )

    for h in p.hardware:
        f, hit = f"hardware.{h.id}", r.was_revised("hardware", h.kind)
        for attr, why in (
            ("material", "different metals wear differently"),
            ("finish", "finish is part of the look"),
        ):
            if getattr(h, attr) is None:
                r.gap(f"hardware-{attr}-missing", f, f"{h.kind} '{h.id}': no {attr}", why, hit)
        if h.size is None:
            r.gap(
                "length-missing",
                f,
                f"{h.kind} '{h.id}': no size",
                "hardware is bought by size",
                hit,
            )
        if hit and not h.requirements:
            r.gap(
                "hardware-requirements-missing",
                f,
                f"{h.kind} '{h.id}': no requirements",
                "this kind of part needed a revision before; say what it must and must not do",
                True,
            )

    kinds = {lb.kind for lb in p.labels}
    for kind, why in (
        ("care", "required to sell in most markets"),
        ("inner", "the brand label inside"),
    ):
        if kind not in kinds:
            r.gap("label-missing", "labels", f"no {kind} label", why, r.was_revised("label", kind))
    for lb in p.labels:
        f, hit = f"labels.{lb.id}", r.was_revised("label", lb.kind)
        r.position(f, lb.position, f"{lb.kind} label '{lb.id}'", hit)
        for attr in ("material", "attachment"):
            if getattr(lb, attr) is None:
                r.gap(
                    f"label-{attr}-missing",
                    f,
                    f"{lb.kind} label '{lb.id}': no {attr}",
                    "labels are bought and sewn by spec",
                    hit,
                )

    c, hit = p.construction, r.was_revised("construction")
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

    if p.packaging is None:
        r.gap(
            "packaging-missing",
            "packaging",
            "no packaging spec",
            "the factory packs to spec",
            r.was_revised("packaging"),
        )
    if not p.quantities:
        r.gap(
            "quantities-missing",
            "quantities",
            "no quantities",
            "the factory plans materials by quantity",
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
