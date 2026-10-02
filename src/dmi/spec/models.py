"""The product spec, format_version 1: the single truth a factory's documents are rendered from.

Rules (docs/contracts/spec.md):
- every length is in millimetres, with a tolerance where the factory needs one;
- an unknown value is ``None``: a visible gap in every output, never a default;
- ids are stable within a product, so revisions, renders and Haki swipe verdicts point at them;
- the core knows nothing about one client; client-specific vocabulary lives in its profile.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    field_validator,
    model_validator,
)

from .categories import ANCHORS_BY_CATEGORY

FORMAT_VERSION = 1

Id = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)]
Text = Annotated[str, Field(min_length=1)]
# A catalogue handle ("example-cap") or, before the product is on the site, "pre:<client>:<slug>".
ProductId = Annotated[
    str, Field(pattern=r"^(pre:[a-z0-9-]+:[a-z0-9-]+|[a-z0-9][a-z0-9-]*)$", max_length=128)
]
# Who voted: an opaque id ("u-0001"), never a person's name.
OpaqueId = Annotated[str, Field(pattern=r"^[a-z]+-[0-9a-z]+$", max_length=64)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Length(_Model):
    """A measured value in mm. ``mm=None`` (and no range) is a gap.

    ``tol_mm`` is the + tolerance and, unless ``tol_minus_mm`` is set, also the - tolerance.
    An adjustable dimension (a head circumference with a strap) is a range: ``min_mm``/``max_mm``.
    """

    mm: float | None = Field(default=None, ge=0)
    min_mm: float | None = Field(default=None, ge=0)
    max_mm: float | None = Field(default=None, ge=0)
    tol_mm: float | None = Field(default=None, ge=0)
    tol_minus_mm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> Length:
        ranged = self.min_mm is not None or self.max_mm is not None
        if ranged and self.mm is not None:
            raise ValueError("a length is either a value (mm) or a range (min_mm/max_mm), not both")
        if ranged and (self.min_mm is None or self.max_mm is None):
            raise ValueError("a range needs both min_mm and max_mm")
        if ranged and self.min_mm > self.max_mm:
            raise ValueError("min_mm is greater than max_mm")
        if self.tol_minus_mm is not None and self.tol_mm is None:
            raise ValueError("tol_minus_mm needs tol_mm (the + side)")
        return self

    @property
    def known(self) -> bool:
        return self.mm is not None or self.min_mm is not None


class Colour(_Model):
    """A colour the factory can match: a standard reference, or at least a name and a swatch."""

    name: Text
    system: (
        Literal["pantone-tcx", "pantone-tpx", "pantone-c", "madeira", "isacord", "hex", "other"]
        | None
    ) = None
    code: str | None = None


class Fibre(_Model):
    fibre: Text
    percent: float = Field(gt=0, le=100)


class Material(_Model):
    id: Id
    role: Text  # shell, lining, sweatband, strap, brim-board, ...
    description: Text
    composition: list[Fibre] = Field(default_factory=list)
    weight_gsm: float | None = Field(default=None, gt=0)
    thickness: Length | None = None  # leather, brim board, felt
    colour: Colour | None = None
    supplier_ref: str | None = None

    @field_validator("composition")
    @classmethod
    def _sums_to_100(cls, v: list[Fibre]) -> list[Fibre]:
        if v and abs(sum(f.percent for f in v) - 100) > 0.01:
            raise ValueError(f"composition sums to {sum(f.percent for f in v)}%, not 100%")
        return v


ArtworkPoint = Literal[
    "centre",
    "top-edge",
    "bottom-edge",
    "left-edge",
    "right-edge",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
]


class Position(_Model):
    """Where something sits: the offset from an anchor on the product to a point of the item.

    Seen from outside, facing the surface the item is on: +dx is to the viewer's right, +dy is
    up (towards the crown on a hat). ``anchor`` comes from the category's anchor vocabulary
    (``dmi.spec.categories``) or is ``other:<description>``.
    """

    anchor: Text
    to: ArtworkPoint | None = None  # which point of the artwork/label the offset reaches
    dx_mm: float | None = None
    dy_mm: float | None = None
    note: str | None = None


Technique = Literal[
    "flat-embroidery",
    "puff-embroidery",
    "chain-stitch",
    "applique",
    "woven-patch",
    "embroidered-patch",
    "leather-patch",
    "screen-print",
    "heat-transfer",
    "other",
]


class ArtworkElement(_Model):
    """One coloured part of an artwork (a letter, an outline, a fill) and how it is made."""

    name: Text  # "main letter", "outline", "script"
    colour: Colour | None = None
    thread: str | None = None  # e.g. "rayon 40 wt"
    stitch_type: str | None = None  # satin, fill/tatami, run, ...


class Placement(_Model):
    """One piece of artwork on the product."""

    id: Id
    location: Text  # front, left-side, right-side, back, under-brim, inside, ...
    artwork_ref: str | None = None  # a file name or id the factory receives; never the file itself
    technique: Technique | None = None
    width: Length = Field(default_factory=Length)
    height: Length = Field(default_factory=Length)
    position: Position | None = None
    elements: list[ArtworkElement] = Field(default_factory=list)
    stitch_count: int | None = Field(default=None, gt=0)
    density: str | None = None  # stitch density, e.g. "0.4 mm spacing"
    foam_height_mm: float | None = Field(default=None, gt=0)  # puff embroidery
    notes: list[str] = Field(default_factory=list)


class Pom(_Model):
    """A point of measure. ``values`` maps size -> length; one-size products use "OS"."""

    code: Id
    name: Text
    how_to_measure: str | None = None
    values: dict[str, Length] = Field(default_factory=dict)


class Seam(_Model):
    """How one seam or stitch line is made."""

    location: Text  # "panel seams", "brim", "sweatband"
    stitch_type: str | None = None  # lockstitch 301, coverstitch, ...
    spi: float | None = Field(default=None, gt=0)  # stitches per inch
    thread: str | None = None
    rows: int | None = Field(default=None, gt=0)  # e.g. brim stitch rows
    finish: str | None = None  # top-stitched 2 mm both sides, taped, ...


class Construction(_Model):
    structure: str | None = None  # structured, unstructured
    crown: str | None = None  # low, mid, high
    panels: int | None = Field(default=None, gt=0)
    brim: str | None = None  # flat, curved, pre-curved
    closure: str | None = None  # strap-buckle, snapback, fitted, ...
    seams: list[Seam] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Hardware(_Model):
    id: Id
    kind: Text  # clasp, buckle, eyelet, top-button, snap, ...
    description: Text
    quantity: int | None = Field(default=None, gt=0)
    position: Position | None = None
    material: str | None = None
    finish: str | None = None
    colour: Colour | None = None
    size: Length | None = None
    supplier_ref: str | None = None
    requirements: list[str] = Field(default_factory=list)  # e.g. "must not mark the strap"


class Label(_Model):
    id: Id
    kind: Text  # main, care, size, brand-tab, inner, country-of-origin, ...
    position: Position | None = None
    artwork_ref: str | None = None
    material: str | None = None  # woven, printed satin, leather, ...
    attachment: str | None = None  # sewn into seam, four-side stitched, ...
    width: Length = Field(default_factory=Length)
    height: Length = Field(default_factory=Length)
    content: str | None = None  # the text a care or origin label carries


class Trim(_Model):
    id: Id
    kind: Text  # sweatband, taping, piping, drawcord, ...
    description: Text
    material_id: Id | None = None
    width: Length | None = None
    colour: Colour | None = None


class Packaging(_Model):
    unit: str | None = None  # polybag, tissue, box
    folding: str | None = None
    labels: list[str] = Field(default_factory=list)
    carton: str | None = None


class Reference(_Model):
    """An image the factory may match: a shape reference, a mockup, a sample photo."""

    id: Id
    kind: Literal["shape", "mockup", "sample-photo", "flat", "detail", "other"]
    ref: Text  # a file name or id; never the image itself
    caption: str | None = None
    authority: Literal["exact", "approximate"] | None = None  # None: the client didn't say


ChangeArea = Literal[
    "placement-position",
    "placement-size",
    "pom",
    "hardware",
    "label",
    "material",
    "colour",
    "construction",
    "trim",
    "packaging",
    "other",
]

# Which top-level spec field each change area may point at.
_AREA_FIELDS: dict[str, set[str]] = {
    "placement-position": {"placements"},
    "placement-size": {"placements"},
    "pom": {"poms"},
    "hardware": {"hardware"},
    "label": {"labels"},
    "material": {"materials"},
    "colour": {"materials", "placements", "hardware", "labels", "trims"},
    "construction": {"construction"},
    "trim": {"trims"},
    "packaging": {"packaging"},
}
_LIST_FIELDS = {"materials", "placements", "hardware", "labels", "trims", "references", "poms"}

_FIELD_PATH = re.compile(r"^[a-z_]+(\.[a-z0-9_-]+)*$")


def field_path_ok(path: str) -> bool:
    """A change's ``field`` is a dotted path: a top-level field, then ids or attribute names."""
    return bool(_FIELD_PATH.match(path))


class Change(_Model):
    """One numbered revision after a sample: what the sample did, what it should do, and why."""

    n: int = Field(gt=0)
    area: ChangeArea
    field: Text  # a dotted path into the spec, e.g. "poms.brim-length", "placements.front-logo"
    summary: Text
    current: str | None = None  # what the sample had, as stated
    target: str | None = None
    current_value: Length | None = None  # the same, structured, when it is a length
    target_value: Length | None = None
    reason: str | None = None
    image_refs: list[str] = Field(default_factory=list)

    @field_validator("field")
    @classmethod
    def _path(cls, v: str) -> str:
        if not field_path_ok(v):
            raise ValueError(f"field {v!r} is not a dotted spec path like 'poms.brim-length'")
        return v


class SampleRound(_Model):
    """A sample the factory made from ``made_from_spec_version``, and the changes it needed.

    The changes are applied in ``applied_in_spec_version`` (None while they are still open), so
    a render can say what changed since the version the factory last saw.
    """

    n: int = Field(gt=0)
    made_from_spec_version: int = Field(gt=0)
    applied_in_spec_version: int | None = Field(default=None, gt=0)
    received: date | None = None
    changes: list[Change] = Field(default_factory=list)

    @model_validator(mode="after")
    def _numbered(self) -> SampleRound:
        ns = [c.n for c in self.changes]
        if len(ns) != len(set(ns)):
            raise ValueError(f"sample round {self.n}: change numbers repeat")
        if (
            self.applied_in_spec_version is not None
            and self.applied_in_spec_version <= self.made_from_spec_version
        ):
            raise ValueError(
                f"sample round {self.n}: changes applied in v{self.applied_in_spec_version}, "
                f"not after the v{self.made_from_spec_version} the sample was made from"
            )
        return self


class Approval(_Model):
    """A verdict on a spec version (e.g. from Haki swipe). Times are stored in UTC."""

    spec_version: int = Field(gt=0)
    who: OpaqueId
    decision: Literal["keep", "cut", "love"]
    note: str | None = None
    at: AwareDatetime
    source: Text  # where the verdict came from, e.g. "haki-swipe"

    @field_validator("at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return v.astimezone(UTC)


class Product(_Model):
    format_version: Literal[1] = FORMAT_VERSION
    id: ProductId
    client: Id
    category: Literal["headwear", "top", "bottom", "outerwear", "accessory", "other"]
    name: Text
    colourway: Text
    season: str | None = None
    spec_version: int = Field(gt=0)
    sizes: list[Text] = Field(min_length=1)  # one-size products: ["OS"]
    materials: list[Material] = Field(default_factory=list)
    placements: list[Placement] = Field(default_factory=list)
    poms: list[Pom] = Field(default_factory=list)
    construction: Construction = Field(default_factory=Construction)
    hardware: list[Hardware] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    trims: list[Trim] = Field(default_factory=list)
    packaging: Packaging | None = None
    quantities: dict[str, NonNegativeInt] = Field(default_factory=dict)
    references: list[Reference] = Field(default_factory=list)
    sample_rounds: list[SampleRound] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Product:
        for name in ("materials", "placements", "hardware", "labels", "trims", "references"):
            ids = [x.id for x in getattr(self, name)]
            dup = {i for i in ids if ids.count(i) > 1}
            if dup:
                raise ValueError(f"{name}: duplicate ids {sorted(dup)}")
        codes = [p.code for p in self.poms]
        if len(codes) != len(set(codes)):
            raise ValueError("poms: duplicate codes")
        if len(self.sizes) != len(set(self.sizes)):
            raise ValueError("sizes repeat")
        for p in self.poms:
            extra = set(p.values) - set(self.sizes)
            if extra:
                raise ValueError(
                    f"pom {p.code}: sizes {sorted(extra)} are not in sizes {self.sizes}"
                )
        bad_q = set(self.quantities) - set(self.sizes)
        if bad_q:
            raise ValueError(f"quantities: sizes {sorted(bad_q)} are not in sizes {self.sizes}")
        materials = {m.id for m in self.materials}
        for t in self.trims:
            if t.material_id and t.material_id not in materials:
                raise ValueError(f"trim {t.id}: unknown material {t.material_id}")
        self._check_anchors()
        self._check_rounds()
        for a in self.approvals:
            if a.spec_version > self.spec_version:
                raise ValueError(
                    f"approval for spec v{a.spec_version}, newer than v{self.spec_version}"
                )
        return self

    def _check_anchors(self) -> None:
        vocab = ANCHORS_BY_CATEGORY.get(self.category)
        if vocab is None:
            return
        items = [*self.placements, *self.hardware, *self.labels]
        for item in items:
            pos = item.position
            if pos and pos.anchor not in vocab and not pos.anchor.startswith("other:"):
                raise ValueError(
                    f"{item.id}: anchor {pos.anchor!r} is not a {self.category} anchor "
                    f"({', '.join(sorted(vocab))}) or 'other:<description>'"
                )

    def _check_rounds(self) -> None:
        rounds = [r.n for r in self.sample_rounds]
        if rounds != sorted(set(rounds)):
            raise ValueError("sample_rounds: numbers must be unique and ascending")
        for r in self.sample_rounds:
            for v in (r.made_from_spec_version, r.applied_in_spec_version):
                if v is not None and v > self.spec_version:
                    raise ValueError(
                        f"sample round {r.n}: names spec v{v}, newer than v{self.spec_version}"
                    )
            for c in r.changes:
                self._check_change_field(r.n, c)

    def _check_change_field(self, round_n: int, c: Change) -> None:
        where = f"sample round {round_n} change {c.n}"
        head, *rest = c.field.split(".")
        if head not in type(self).model_fields:
            raise ValueError(f"{where}: field {c.field!r} names no spec field {head!r}")
        allowed = _AREA_FIELDS.get(c.area)
        if allowed is not None and head not in allowed:
            raise ValueError(f"{where}: area {c.area!r} cannot point at {head!r}")
        if head in _LIST_FIELDS and rest:
            key = "code" if head == "poms" else "id"
            ids = {getattr(x, key) for x in getattr(self, head)}
            if rest[0] not in ids:
                raise ValueError(f"{where}: {head} has no {rest[0]!r} (field {c.field!r})")

    def pom(self, code: str) -> Pom | None:
        return next((p for p in self.poms if p.code == code), None)
