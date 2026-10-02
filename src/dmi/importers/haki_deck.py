"""Read Haki's slide decks into the spec: brief deck -> spec v1, revision deck -> a sample round.

The decks are read in place, read-only (python-pptx); nothing is copied. How Haki's decks are
laid out (slide titles, the construction lines, how a change is worded) is data in
``profiles/haki/profile.json``; this module only applies it.

Nothing is guessed: a value is taken only when the deck states it in a form the profile
recognises (e.g. "current ... X cm ... to Y cm"). Anything else is kept verbatim as a note,
and the spec field stays empty, so the checks report it as a gap. No slide is dropped.
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


def _note(s: Slide, deck_id: str) -> str:
    parts = [s.title or "(untitled slide)", *s.texts]
    pics = f" [{s.pictures} image(s): {', '.join(_refs(deck_id, s))}]" if s.pictures else ""
    return f"slide {s.n}: " + " / ".join(parts) + pics


def import_brief(
    path: Path, product_id: str, profile: dict | None = None, colourway: str | None = None
) -> Product:
    """A brief deck -> spec v1. The title slide names the product; the last ' - ' part is the
    colourway unless given. Every line of the construction slide is kept verbatim."""
    prof_all = profile or load_profile()
    prof, defaults = prof_all["deck"], prof_all["defaults"]
    deck_id, slides = read_slides(path)
    title = slides[0].title or (slides[0].texts[0] if slides[0].texts else "")
    if colourway is None:
        if " - " not in title:
            raise ValueError(f"{deck_id}: no colourway in the title; pass colourway=")
        colourway = title.rsplit(" - ", 1)[-1].strip()
    spec: dict = {
        "id": product_id,
        "client": prof_all["client"],
        "category": defaults["category"],
        "name": title,
        "colourway": colourway.lower(),
        "spec_version": 1,
        "sizes": defaults["sizes"],
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
        if t and re.search(prof["shape_reference_title"], t, re.I):
            for ref in _refs(deck_id, s):
                spec["references"].append({"id": slug(ref), "kind": "shape", "ref": ref})
            spec["notes"] += [f"shape references: {x}" for x in s.texts]
        elif t and (m := re.search(prof["placement_title"], t, re.I)):
            _placement(spec, prof, m, s, deck_id)
        elif t and re.search(prof["label_title"], t, re.I):
            kind = _label_kind(prof, t) or slug(t.split("(")[0])
            spec["labels"].append({"id": slug(t), "kind": kind})
            for ref in _refs(deck_id, s):
                spec["references"].append(
                    {"id": slug(ref), "kind": "detail", "ref": ref, "caption": t}
                )
            spec["notes"] += [f"{t}: {x}" for x in s.texts]
        elif t and re.search(prof["construction_title"], t, re.I):
            for text in s.texts:
                for line in (x.strip() for x in text.splitlines()):
                    if line:
                        _construction_line(spec, prof, line)
        else:  # untitled or unrecognised: kept, never dropped
            spec["notes"].append(_note(s, deck_id))
            for ref in _refs(deck_id, s):
                spec["references"].append(
                    {"id": slug(ref), "kind": "other", "ref": ref, "caption": t or None}
                )
    return Product.model_validate(spec)


def _label_kind(prof: dict, text: str) -> str | None:
    for word, kind in prof["label_kinds"].items():
        if re.search(rf"\b{word}\b", text, re.I):
            return kind
    return None


def _placement(spec: dict, prof: dict, m: re.Match, s: Slide, deck_id: str) -> None:
    loc_word, kind = m["location"].strip(), m["kind"].strip().title()
    tech_word = (m["technique"] or "").strip().title()
    key = f"{kind}/{tech_word}" if tech_word else kind
    technique = prof["techniques"].get(key)  # unknown: a gap, not "other"
    location = prof["locations"].get(loc_word.title(), slug(loc_word))
    pid = slug(f"{location}-{kind}")
    notes = list(s.texts)
    if technique is None:
        notes.insert(0, f"technique as written: {key!r} (not mapped)")
    approximate = any(re.search(r"not\s+exact", x, re.I) for x in notes)
    elements = [
        {"name": c.strip().lower(), "colour": {"name": c.strip()}}
        for c in re.split(r"\s*\+\s*|\s*,\s*|\s+and\s+", m["colours"] or "")
        if c.strip()
    ]
    pl = {"id": pid, "location": location, "elements": elements, "notes": notes}
    if technique:
        pl["technique"] = technique
    spec["placements"].append(pl)
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
        elif target == "hardware.kind":
            kind = m.group(1).lower()
            if not any(h["kind"] == kind for h in spec["hardware"]):
                spec["hardware"].append({"id": slug(kind), "kind": kind, "description": value})


def import_revisions(path: Path, product: Product, profile: dict | None = None) -> Product:
    """A revision deck -> a sample round on ``product``, its changes applied in spec v+1.

    A length target is applied only when the deck states both current and target in words
    ("current ... X ... to Y"); a lone measurement drawn on a photo is kept as text. Untitled
    slides continue the change before them; other slides become notes.
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
    last: dict | None = None
    for s in slides[1:]:
        cm = re.match(prof["change_title"], s.title.strip())
        if cm:
            n = int(cm["n"])
            last = changes.setdefault(
                n, {"n": n, "summary": cm["summary"].strip(), "body": [], "refs": []}
            )
        elif s.title.strip() or last is None:
            spec["notes"].append(f"revision deck {deck_id}, " + _note(s, deck_id))
            continue
        # an untitled slide continues the change before it
        last["body"] += [x for x in s.texts if not re.fullmatch(r"(before|after):?", x, re.I)]
        last["refs"] += _refs(deck_id, s)
    round_ = {
        "n": int(m["n"]),
        "made_from_spec_version": old,
        "applied_in_spec_version": new,
        "changes": [_change(spec, prof, changes[n]) for n in sorted(changes)],
    }
    spec["spec_version"] = new
    spec.setdefault("sample_rounds", []).append(round_)
    spec["notes"].append(f"sample round {round_['n']} imported from Haki revision deck {deck_id}")
    return Product.model_validate(spec)


def _find_placement(spec: dict, text: str) -> dict | None:
    """The one placement a change names by its location word, or None (never a fallback)."""
    hits = [
        p
        for p in spec["placements"]
        if re.search(rf"\b{re.escape(p['location'].replace('-', ' '))}\b", text, re.I)
    ]
    return hits[0] if len(hits) == 1 else None


def _change(spec: dict, prof: dict, ch: dict) -> dict:
    callouts = [x for x in ch["body"] if _CALLOUT.match(x)]
    prose = [x for x in ch["body"] if not _CALLOUT.match(x)]
    text = " ".join([ch["summary"], *prose])
    out: dict = {"n": ch["n"], "summary": ch["summary"], "image_refs": ch["refs"]}
    target_text = " ".join(prose + [f"(drawn on photo: {c})" for c in callouts])
    if target_text:
        out["target"] = target_text
    ct = _CURRENT_TARGET.search(text)
    target_mm = None
    if ct:
        out["current_value"] = {"mm": to_mm(ct[1], ct[2])}
        target_mm = to_mm(ct[3], ct[4])
        out["target_value"] = {"mm": target_mm}
    areas = [(r, mm) for r in prof["change_areas"] if (mm := re.search(r["pattern"], text, re.I))]
    if not areas:
        spec["notes"].append(f"change {ch['n']}: {text}")
        return {**out, "area": "other", "field": "notes"}
    rule, match = areas[0]
    also = sorted({r["area"] for r, _ in areas[1:]} - {rule["area"]})
    if also:
        out["summary"] += f" (also: {', '.join(also)})"
    area = rule["area"]
    if area == "pom":
        code = rule["pom"]
        pom = next((p for p in spec.setdefault("poms", []) if p["code"] == code), None)
        if pom is None:
            pom = {"code": code, "name": code.replace("-", " ").capitalize(), "values": {}}
            spec["poms"].append(pom)
        if target_mm is not None:
            pom["values"]["OS"] = {"mm": target_mm}
        return {**out, "area": "pom", "field": f"poms.{code}"}
    if area == "hardware":
        kind = match.group(1).lower()
        same = [h for h in spec["hardware"] if h["kind"] == kind]
        hw = same[0] if same else (spec["hardware"][0] if len(spec["hardware"]) == 1 else None)
        if hw is None:
            hw = {"id": slug(kind), "kind": kind, "description": ch["summary"]}
            spec["hardware"].append(hw)
        hw.setdefault("requirements", []).extend(prose)
        return {**out, "area": "hardware", "field": f"hardware.{hw['id']}"}
    if area == "label":
        kind = _label_kind(prof, text) or "unspecified"
        lb = next((x for x in spec["labels"] if x["kind"] == kind), None)
        if lb is None:
            lb = {"id": f"{kind}-label", "kind": kind}
            spec["labels"].append(lb)
        return {**out, "area": "label", "field": f"labels.{lb['id']}"}
    pl = _find_placement(spec, text)
    if pl is None:
        spec["notes"].append(f"change {ch['n']} (placement not named): {text}")
        return {**out, "area": area, "field": "placements"}
    pl.setdefault("notes", []).append(f"change {ch['n']}: {text}")
    return {**out, "area": area, "field": f"placements.{pl['id']}"}
