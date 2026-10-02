from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmi.spec import dump, json_schema, load
from dmi.spec.categories import HEADWEAR_POMS
from dmi.spec.models import Product, field_path_ok
from dmi.spec.units import cm_to_mm, inch_fraction, inch_to_mm, mm_to_cm, mm_to_inch

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests/golden/example-cap.json"
SCHEMA = ROOT / "docs/contracts/spec.schema.json"


def golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_golden_hat_validates():
    p = load(GOLDEN)
    assert p.format_version == 1
    assert p.category == "headwear"
    assert p.pom("brim-length").values["OS"].mm == 75
    assert p.sample_rounds[0].changes[0].field == "poms.brim-length"


def test_dump_is_deterministic_and_round_trips():
    p = load(GOLDEN)
    a, b = dump(p), dump(Product.model_validate_json(dump(p)))
    assert a == b
    assert a.endswith("\n")


def test_committed_schema_matches_models():
    assert SCHEMA.read_text() == json_schema(), (
        "regenerate: uv run python -m dmi.spec schema > docs/contracts/spec.schema.json"
    )


def test_missing_values_are_gaps_not_defaults():
    d = golden()
    d["poms"][0]["values"]["OS"] = {}
    d["placements"][0]["width"] = {}
    p = Product.model_validate(d)
    assert p.poms[0].values["OS"].mm is None
    assert p.placements[0].width.mm is None


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["materials"].append(dict(d["materials"][0])), "duplicate ids"),
        (lambda d: d["poms"].append(dict(d["poms"][0])), "duplicate codes"),
        (lambda d: d["poms"][0]["values"].update({"M": {"mm": 1}}), "not in sizes"),
        (lambda d: d["quantities"].update({"XL": 5}), "not in sizes"),
        (
            lambda d: d["materials"][0]["composition"].append({"fibre": "elastane", "percent": 3}),
            "sums to",
        ),
        (lambda d: d["trims"][0].update({"material_id": "nope"}), "unknown material"),
        (lambda d: d["approvals"][0].update({"spec_version": 9}), "newer than"),
        (
            lambda d: d["sample_rounds"][0]["changes"].append(
                dict(d["sample_rounds"][0]["changes"][0])
            ),
            "repeat",
        ),
        (
            lambda d: d["sample_rounds"].insert(0, {"n": 2, "made_from_spec_version": 1}),
            "ascending",
        ),
        (lambda d: d.update({"id": "Not A Handle"}), "pattern"),
        (lambda d: d.update({"surprise": 1}), "Extra inputs"),
        (lambda d: d["poms"][0]["values"]["OS"].update({"mm": -1}), "greater than or equal"),
        (lambda d: d["quantities"].update({"OS": -1}), "greater than or equal"),
        (lambda d: d["poms"][4]["values"]["OS"].update({"mm": 560}), "either a value"),
        (lambda d: d["poms"][4]["values"]["OS"].pop("max_mm"), "needs both"),
        (lambda d: d["poms"][4]["values"]["OS"].update({"min_mm": 700}), "greater than max"),
        (
            lambda d: d["placements"][0]["position"].update({"anchor": "somewhere"}),
            "not a headwear anchor",
        ),
        (
            lambda d: d["sample_rounds"][0]["changes"][0].update({"field": "Nonsense path!!"}),
            "dotted spec path",
        ),
        (
            lambda d: d["sample_rounds"][0]["changes"][0].update({"field": "poms.does-not-exist"}),
            "has no",
        ),
        (
            lambda d: d["sample_rounds"][0]["changes"][0].update({"field": "nothing.here"}),
            "names no spec field",
        ),
        (
            lambda d: d["sample_rounds"][0]["changes"][0].update({"area": "label"}),
            "cannot point at",
        ),
        (lambda d: d["sample_rounds"][0].update({"applied_in_spec_version": 1}), "not after"),
        (
            lambda d: d["sample_rounds"][0].update(
                {"made_from_spec_version": 7, "applied_in_spec_version": None}
            ),
            "newer than",
        ),
        (lambda d: d["approvals"][0].update({"at": "2026-09-05T12:00:00"}), "timezone"),
        (lambda d: d["approvals"][0].update({"who": "Real Person"}), "pattern"),
        (lambda d: d["approvals"][0].pop("source"), "Field required"),
        (lambda d: d.pop("sizes"), "Field required"),
        (lambda d: d.update({"name": ""}), "at least 1"),
    ],
)
def test_invalid_specs_are_refused(mutate, message):
    d = golden()
    mutate(d)
    with pytest.raises(ValidationError, match=message):
        Product.model_validate(d)


@pytest.mark.parametrize("pid", ["example-cap", "pre:example:cap-01", "example-trackpants-2"])
def test_product_ids(pid):
    d = golden()
    d["id"] = pid
    assert Product.model_validate(d).id == pid


def test_units():
    assert cm_to_mm(4.2) == 42
    assert inch_to_mm(1) == 25.4
    assert mm_to_cm(57) == 5.7
    assert mm_to_inch(25.4) == 1.0
    assert inch_fraction(66.675) == "2 5/8"
    assert inch_fraction(12.7) == "1/2"
    assert inch_fraction(50.8) == "2"
    for mm in (0, 1, 42, 57, 540):
        assert abs(cm_to_mm(mm_to_cm(mm, 3)) - mm) < 1e-6


def test_headwear_poms_cover_the_golden_hat():
    codes = {p.code for p in HEADWEAR_POMS}
    assert {p.code for p in load(GOLDEN).poms} <= codes


@pytest.mark.parametrize(
    "path, ok",
    [
        ("poms.brim-length", True),
        ("hardware.buckle", True),
        ("placements.front-logo.width", True),
        ("Poms..x", False),
        ("", False),
    ],
)
def test_field_paths(path, ok):
    assert field_path_ok(path) is ok


def test_times_are_stored_in_utc():
    d = golden()
    d["approvals"][0]["at"] = "2026-09-05T14:00:00+02:00"
    a, b = Product.model_validate(d), load(GOLDEN)
    assert dump(a) == dump(b)


def test_other_anchor_is_allowed():
    d = golden()
    d["placements"][1]["position"]["anchor"] = "other:centre of the left side panel"
    assert Product.model_validate(d).placements[1].position.anchor.startswith("other:")


def test_change_may_point_at_a_whole_list_or_an_attribute():
    d = golden()
    d["sample_rounds"][0]["changes"][0]["field"] = "poms.brim-length.values"
    d["sample_rounds"][0]["changes"][1].update(
        {"area": "construction", "field": "construction.seams"}
    )
    Product.model_validate(d)


def test_ranged_pom_and_asymmetric_tolerance():
    p = load(GOLDEN)
    hc = p.pom("head-circumference").values["OS"]
    assert (hc.min_mm, hc.max_mm, hc.known) == (540, 600, True)
    assert p.pom("strap-length").values["OS"].tol_minus_mm == 1
