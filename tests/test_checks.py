from __future__ import annotations

import json
from pathlib import Path

from dmi.checks import Learned, check, history, report
from dmi.spec import load
from dmi.spec.models import Product

GOLDEN = Path(__file__).resolve().parent / "golden/example-cap.json"


def golden() -> dict:
    return json.loads(GOLDEN.read_text())


def codes(findings) -> set[tuple[str, str]]:
    return {(f.code, f.field) for f in findings}


def test_golden_cap_is_complete():
    assert check(load(GOLDEN)) == []


def test_deck_style_spec_is_full_of_gaps():
    """A spec as thin as a picture deck: a shape, a technique, a four-line construction."""
    thin = Product.model_validate(
        {
            "id": "pre:example:thin-cap",
            "client": "example",
            "category": "headwear",
            "name": "Thin cap",
            "colourway": "navy",
            "spec_version": 1,
            "sizes": ["OS"],
            "placements": [{"id": "front", "location": "front", "technique": "puff-embroidery"}],
            "construction": {"structure": "unstructured", "crown": "mid"},
            "references": [{"id": "shape-1", "kind": "shape", "ref": "REF-1"}],
        }
    )
    found = codes(check(thin))
    for expected in [
        ("length-missing", "poms.brim-length"),
        ("length-missing", "poms.front-panel-height"),
        ("position-missing", "placements.front"),
        ("length-missing", "placements.front.width"),
        ("foam-missing", "placements.front"),
        ("label-missing", "labels"),
        ("seams-missing", "construction.seams"),
        ("construction-missing", "construction.brim"),
        ("reference-authority-missing", "references.shape-1"),
        ("quantities-missing", "quantities"),
    ]:
        assert expected in found, expected
    assert all(f.severity == "block" for f in check(thin))
    assert {f.severity for f in check(thin, severity="warn")} == {"warn"}


def test_ranged_pom_given_one_value():
    d = golden()
    d["poms"][4]["values"]["OS"] = {"mm": 560, "tol_mm": 5}
    assert ("range-expected", "poms.head-circumference") in codes(check(Product.model_validate(d)))


def test_missing_tolerance():
    d = golden()
    d["poms"][2]["values"]["OS"].pop("tol_mm")
    assert ("tolerance-missing", "poms.brim-length") in codes(check(Product.model_validate(d)))


def test_revision_history_marks_and_tightens_checks():
    past = load(GOLDEN)  # its sample round revised the brim length and the buckle (a clasp)
    learned = history([past])
    assert Learned("pom", "brim-length") in learned
    assert Learned("hardware", "clasp") in learned

    d = golden()
    d["id"] = "pre:example:next-cap"
    d["sample_rounds"], d["approvals"], d["spec_version"] = [], [], 1
    d["poms"][2]["values"]["OS"] = {}  # brim length missing again
    d["hardware"][0]["requirements"] = []  # a clasp with no requirements
    nxt = Product.model_validate(d)

    plain = {(f.code, f.field): f.source for f in check(nxt)}
    assert ("hardware-requirements-missing", "hardware.buckle") not in plain
    assert plain[("length-missing", "poms.brim-length")] == "standard"

    strict = {(f.code, f.field): f.source for f in check(nxt, learned)}
    assert strict[("length-missing", "poms.brim-length")] == "revision-history"
    assert strict[("hardware-requirements-missing", "hardware.buckle")] == "revision-history"


def test_report_counts():
    d = golden()
    d["poms"][2]["values"]["OS"] = {}
    p = Product.model_validate(d)
    rep = report(p, check(p, severity="warn"))
    assert (rep["blocking"], rep["warnings"]) == (0, 1)
    assert rep["from_revision_history"] == 1  # the golden cap's own round revised the brim
