"""Read Haki's slide decks into the spec: brief deck -> spec v1, revision deck -> a sample round.

The decks are read in place, read-only (python-pptx); nothing is copied. How Haki's decks are
laid out (slide titles, the construction lines, how a change is worded) is data in
``profiles/haki/profile.json``; this module only applies it. What can't be read reliably
stays a gap: the checks report it, it is never guessed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from dmi.spec.models import Product
from dmi.spec.units import MM_PER_CM, MM_PER_INCH

PROFILE = Path(__file__).resolve().parents[3] / "profiles/haki/profile.json"
_LEN = r"(\d+(?:\.\d+)?)\s*(cm|mm|in|inch|inches|\")"
_CALLOUT = re.compile(rf"^\s*{_LEN}\s*$", re.I)
_CURRENT_TARGET = re.compile(rf"current\b.*?{_LEN}.*?\bto\s+{_LEN}", re.I | re.S)
_TITLE = (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)


def load_profile(path: Path = PROFILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def to_mm(value: str, unit: str) -> float:
    v, u = float(value), unit.lower()
    return round(v * (MM_PER_CM if u == "cm" else 1 if u == "mm" else MM_PER_INCH), 3)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "item"


@dataclass
class Slide:
    n: int
    title: str
    texts: list[str] = field(default_factory=list)  # every other text box, in reading order
    pictures: int = 0


def read_slides(path: Path) -> tuple[str, list[Slide]]:
    """The deck's id (content hash, never its name) and its slides' titles, texts, pictures."""
    deck_id = "deck-" + hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    slides = []
    for i, s in enumerate(Presentation(str(path)).slides, 1):
        sl = Slide(i, "")
        shapes = sorted(s.shapes, key=lambda sh: ((sh.top or 0), (sh.left or 0)))
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                sl.pictures += 1
            elif sh.has_text_frame and sh.text_frame.text.strip():
                text = sh.text_frame.text.strip()
                is_title = sh.is_placeholder and sh.placeholder_format.type in _TITLE
                if is_title and not sl.title:
                    sl.title = text
                else:
                    sl.texts.append(text)
        slides.append(sl)
    return deck_id, slides


def _refs(deck_id: str, s: Slide) -> list[str]:
    return [f"{deck_id}#s{s.n}p{k}" for k in range(1, s.pictures + 1)]


def import_brief(path: Path, product_id: str, profile: dict | None = None) -> Product:
    """A brief deck -> spec v1. The title slide names the product; the last ' - ' part is the
    colourway. Every line of the construction slide is kept verbatim in construction.notes."""
    prof = (profile or load_profile())["deck"]
    deck_id, slides = read_slides(path)
    title = slides[0].title or slides[0].texts[0]
    colourway = title.rsplit(" - ", 1)[-1].strip() if " - " in title else "unspecified"
    spec: dict = {
        "id": product_id,
        "client": "haki",
        "category": "headwear",
        "name": title,
        "colourway": colourway.lower(),
        "spec_version": 1,
        "sizes": ["OS"],
        "materials": [],
        "placements": [],
        "hardware": [],
        "labels": [],
        "references": [],
        "construction": {"notes": []},
        "notes": [f"imported from Haki brief deck {deck_id}"],
    }
    for s in slides[1:]:
        t = s.title.strip()
        if re.search(prof["shape_reference_title"], t, re.I):
            for ref in _refs(deck_id, s):
                spec["references"].append({"id": slug(ref), "kind": "shape", "ref": ref})
        elif m := re.search(prof["placement_title"], t, re.I):
            _placement(spec, prof, m, s, deck_id)
        elif re.search(prof["label_title"], t, re.I):
            spec["labels"].append({"id": slug(t), "kind": slug(t.split("(")[0]) or "label"})
            for ref in _refs(deck_id, s):
                spec["references"].append(
                    {"id": slug(ref), "kind": "detail", "ref": ref, "caption": t}
                )
        elif re.search(prof["construction_title"], t, re.I):
            for text in s.texts:
                for line in (x.strip() for x in text.splitlines()):
                    if line:
                        _construction_line(spec, prof, line)
        elif t:
            spec["notes"].append(f"{t}: {' / '.join(s.texts)}" if s.texts else t)
    return Product.model_validate(spec)


def _placement(spec: dict, prof: dict, m: re.Match, s: Slide, deck_id: str) -> None:
    loc_word, kind = m["location"].strip(), m["kind"].strip().title()
    tech = (m["technique"] or "").strip().title()
    technique = prof["techniques"].get(f"{kind}/{tech}" if tech else kind, "other")
    location = prof["locations"].get(loc_word.title(), slug(loc_word))
    pid = slug(f"{location}-{kind}")
    notes = list(s.texts)
    approximate = any(re.search(r"not\s+exact", x, re.I) for x in notes)
    elements = [
        {"name": c.strip().lower(), "colour": {"name": c.strip()}}
        for c in re.split(r"\s*\+\s*|\s*,\s*|\s+and\s+", m["colours"] or "")
        if c.strip()
    ]
    spec["placements"].append(
        {
            "id": pid,
            "location": location,
            "technique": technique,
            "elements": elements,
            "notes": notes,
        }
    )
    for ref in _refs(deck_id, s):
        spec["references"].append(
            {
                "id": slug(ref),
                "kind": "mockup",
                "ref": ref,
                "caption": f"{pid} mockup",
                **({"authority": "approximate"} if approximate else {}),
            }
        )


def _construction_line(spec: dict, prof: dict, line: str) -> None:
    spec["construction"]["notes"].append(line)
    for rule in prof["construction_lines"]:
        m = re.search(rule["pattern"], line, re.I)
        if not m:
            continue
        target, how = rule["set"], rule["value_from"]
        if how == "match_lower":
            value = m.group(0).lower()
        elif how == "group1_lower":
            value = (m.group(1) or "").lower()
        else:
            value = line
        if target.startswith("construction."):
            spec["construction"][target.split(".", 1)[1]] = value
        elif target.startswith("material."):
            role = target.split(".", 1)[1]
            if not any(x["id"] == role for x in spec["materials"]):
                spec["materials"].append({"id": role, "role": role, "description": value})
            if role == "strap" and re.search(r"\bhardware\b", line, re.I):
                spec["hardware"].append(
                    {"id": "strap-hardware", "kind": "clasp", "description": value}
                )


def import_revisions(path: Path, product: Product, profile: dict | None = None) -> Product:
    """A revision deck -> a sample round on ``product``, its changes applied in spec v+1.

    Targets that are lengths set the POM; hardware and labels named by a change are created
    if missing; anything else is recorded as a note on what it changes. Nothing is guessed.
    """
    prof = (profile or load_profile())["deck"]
    deck_id, slides = read_slides(path)
    first = "\n".join([slides[0].title, *slides[0].texts])
    m = re.search(prof["revision_title"], first, re.I | re.M)
    if not m:
        raise ValueError(f"{deck_id}: no 'Revisions - Sample N' on the title slide")
    spec = product.model_dump(mode="json", exclude_none=True)
    old, new = product.spec_version, product.spec_version + 1
    changes: dict[int, dict] = {}
    for s in slides[1:]:
        cm = re.match(prof["change_title"], s.title.strip())
        if not cm:
            continue
        n = int(cm["n"])
        ch = changes.setdefault(
            n, {"n": n, "summary": cm["summary"].strip(), "body": [], "refs": []}
        )
        ch["body"] += [x for x in s.texts if not re.fullmatch(r"(before|after):?", x.strip(), re.I)]
        ch["refs"] += _refs(deck_id, s)
    round_ = {
        "n": int(m["n"]),
        "made_from_spec_version": old,
        "applied_in_spec_version": new,
        "changes": [],
    }
    for n in sorted(changes):
        round_["changes"].append(_change(spec, prof, changes[n]))
    spec["spec_version"] = new
    spec.setdefault("sample_rounds", []).append(round_)
    spec["notes"].append(f"sample round {round_['n']} imported from Haki revision deck {deck_id}")
    return Product.model_validate(spec)


def _change(spec: dict, prof: dict, ch: dict) -> dict:
    callouts = [x for x in ch["body"] if _CALLOUT.match(x)]
    prose = [x for x in ch["body"] if not _CALLOUT.match(x)]
    text = " ".join([ch["summary"], *prose])
    rule = next((r for r in prof["change_areas"] if re.search(r["pattern"], text, re.I)), None)
    out = {
        "n": ch["n"],
        "summary": ch["summary"],
        "image_refs": ch["refs"],
        **({"target": " ".join(prose)} if prose else {}),
    }
    ct = _CURRENT_TARGET.search(text)
    current_mm = to_mm(ct[1], ct[2]) if ct else None
    target_mm = to_mm(ct[3], ct[4]) if ct else None
    if target_mm is None and callouts:
        cm = _CALLOUT.match(callouts[0])
        target_mm = to_mm(cm[1], cm[2])
    if current_mm is not None:
        out["current_value"] = {"mm": current_mm}
    if target_mm is not None:
        out["target_value"] = {"mm": target_mm}
    if rule is None or rule["area"] == "other":
        out.update(area="other", field="notes")
        spec["notes"].append(f"change {ch['n']}: {text}")
    elif rule["area"] == "pom":
        code = rule["pom"]
        pom = next((p for p in spec.setdefault("poms", []) if p["code"] == code), None)
        if pom is None:
            pom = {"code": code, "name": code.replace("-", " ").capitalize(), "values": {}}
            spec["poms"].append(pom)
        if target_mm is not None:
            pom["values"]["OS"] = {"mm": target_mm}
        out.update(area="pom", field=f"poms.{code}")
    elif rule["area"] == "hardware":
        kind = rule["hardware_kind"]
        hw = next((h for h in spec["hardware"] if h["kind"] == kind), None)
        if hw is None:
            hw = {"id": kind, "kind": kind, "description": ch["summary"]}
            spec["hardware"].append(hw)
        hw.setdefault("requirements", []).extend(prose)
        out.update(area="hardware", field=f"hardware.{hw['id']}")
    elif rule["area"] == "label":
        kind = rule["label_kind"]
        lb = next((x for x in spec["labels"] if x["kind"] == kind), None)
        if lb is None:
            lb = {"id": f"{kind}-label", "kind": kind}
            spec["labels"].append(lb)
        out.update(area="label", field=f"labels.{lb['id']}")
    else:
        words = text.lower()
        pl = next((p for p in spec["placements"] if p["location"] in words), None) or next(
            iter(spec["placements"]), None
        )
        if pl is None:
            out.update(area="other", field="notes")
            spec["notes"].append(f"change {ch['n']}: {text}")
        else:
            pl.setdefault("notes", []).append(f"change {ch['n']}: {text}")
            out.update(area=rule["area"], field=f"placements.{pl['id']}")
    return out
