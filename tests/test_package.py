from __future__ import annotations

import json
from pathlib import Path

from dmi.__main__ import main
from dmi.checks import check
from dmi.spec import load
from dmi.swipe import tech_package_item

GOLDEN = Path(__file__).resolve().parent / "golden/example-cap.json"


def test_swipe_item_shape():
    p = load(GOLDEN)
    item = tech_package_item(p, check(p), ["/x/page-1.png"])
    assert item["item_key"] == "dmi:pre:example:six-panel-cap:spec-2"
    assert (item["department"], item["kind"]) == ("design-manufacture", "tech-package")
    assert item["source"] == {"product": p.id, "spec_version": 2, "sample_round": None}
    assert len(item["summary"]) <= 400 and item["images"][0]["label"] == "page 1"
    demo = tech_package_item(p, [], [], demo=True)
    assert demo["title"].startswith("demo · not evaluated")


def test_package_writes_everything(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DMI_HOME", str(tmp_path))
    assert main(["package", str(GOLDEN)]) == 0
    out = tmp_path / "renders/pre_example_six-panel-cap/v2"
    names = {x.name for x in out.iterdir()}
    assert {
        "techpack.pdf",
        "bom.xlsx",
        "gaps.json",
        "brief.pptx",
        "revisions-sample-1.pptx",
    } <= names
    swipe = tmp_path / "swipe/dmi_pre_example_six-panel-cap_spec-2"
    item = json.loads((swipe / "item.json").read_text())
    assert item["images"] and all(Path(i["src"]).exists() for i in item["images"])
