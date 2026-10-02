"""Render a spec as Haki's own deck format: the brief deck and a revision deck per sample round.

The factory keeps the structure it already knows (title, shape references, a slide per artwork
placement, the back, construction details; numbered changes after a sample), and every slide
now also carries the spec's numbers: sizes and positions with tolerances, colour references,
the measurement table. Gaps are shown on the slide in a highlighted box, never left out.

Images are refs (never files in git): each shows as a labelled frame, or as the image when a
``resolve(ref) -> Path | None`` is given. Output is deterministic: same spec, same bytes.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Cm, Pt

from dmi.render import fmt as F
from dmi.spec.models import Length, Placement, Product, SampleRound

Resolver = Callable[[str], Path | None]
FIXED = datetime(2000, 1, 1)
GAP_FILL = RGBColor(0xFF, 0xF1, 0xB8)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x66, 0x66, 0x66)
W, H = Cm(25.4), Cm(14.29)  # Haki's decks are 16:9 at this size


def fmt(v: Length | None) -> str | None:
    """A length with its tolerance (dmi.render.fmt), or None for a gap."""
    return F.length(v, with_tol=True)


class _Deck:
    def __init__(self, resolve: Resolver | None):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = W, H
        self.resolve = resolve

    def slide(self, title: str):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[5])  # title only
        s.shapes.title.text = title
        t = s.shapes.title
        t.left, t.top, t.width, t.height = Cm(0.9), Cm(0.6), Cm(23.6), Cm(1.6)
        t.text_frame.paragraphs[0].runs[0].font.size = Pt(26)
        return s

    def text(self, s, x, y, w, h, lines: list[str], size=12, gap=False, colour=INK) -> None:
        tb = s.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
        tf = tb.text_frame
        tf.word_wrap = True
        if gap:
            tb.fill.solid()
            tb.fill.fore_color.rgb = GAP_FILL
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = line
            p.runs[0].font.size = Pt(size)
            p.runs[0].font.color.rgb = colour

    def image(self, s, ref: str, x, y, w, h) -> None:
        path = self.resolve(ref) if self.resolve else None
        if path is not None:
            s.shapes.add_picture(str(path), Cm(x), Cm(y), Cm(w), Cm(h))
            return
        box = s.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
        box.line.color.rgb = MUTED
        box.text_frame.text = f"image: {ref}"
        box.text_frame.paragraphs[0].runs[0].font.size = Pt(9)
        box.text_frame.paragraphs[0].runs[0].font.color.rgb = MUTED

    def images(self, s, refs: list[str], x0=0.7, y=3.0, width=13.0, height=10.5) -> None:
        if not refs:
            return
        w = width / len(refs) - 0.3
        for k, ref in enumerate(refs):
            self.image(s, ref, x0 + k * (w + 0.3), y, w, min(height, w * 1.3))

    def gaps(self, s, missing: list[str], y=10.4) -> None:
        """The "Not specified yet" box: sized to its lines, the overflow counted, never cut."""
        if not missing:
            return
        shown = missing[:6] + (
            [f"+{len(missing) - 6} more (see the tech pack)"] if len(missing) > 6 else []
        )
        h = min(0.5 + 0.45 * (len(shown) + 1), H.cm - y - 0.2)
        self.text(s, 14.2, y, 10.4, h, ["Not specified yet:", *shown], size=10, gap=True)

    def save(self) -> bytes:
        cp = self.prs.core_properties
        cp.created = cp.modified = cp.last_printed = FIXED
        cp.author = cp.last_modified_by = "design-manufacture-interface"
        cp.revision = 1
        buf = io.BytesIO()
        self.prs.save(buf)
        return F.fixed_zip(buf.getvalue())


def _placement_title(pl: Placement) -> str:
    loc = pl.location.replace("-", " ").title()
    tech = (pl.technique or "artwork").replace("-", " ").title()
    colours = " + ".join(e.colour.name for e in pl.elements if e.colour)
    return f"{loc} {tech}" + (f" ({colours})" if colours else "")


def _placement_lines(pl: Placement) -> tuple[list[str], list[str]]:
    lines, missing = [], []
    for label, v in (("Width", pl.width), ("Height", pl.height)):
        s = fmt(v)
        (lines.append(f"{label}: {s}") if s else missing.append(label.lower()))
    pos = F.position(pl.position)
    (lines.append(f"Position: {pos}") if pos else missing.append("measured position"))
    for e in pl.elements:
        ref = f"{e.colour.system or ''} {e.colour.code or ''}".strip() if e.colour else ""
        thread = f", {e.thread}" if e.thread else ""
        lines.append(f"• {e.name}: {e.colour.name if e.colour else '?'} {ref}{thread}".rstrip())
        if not (e.colour and e.colour.code):
            missing.append(f"colour reference for {e.name}")
    if not pl.elements:
        missing.append("thread colours")
    if pl.technique == "puff-embroidery" and pl.foam_height_mm is None:
        missing.append("puff foam height")
    if not pl.artwork_ref:
        missing.append("artwork file")
    return [*lines, *pl.notes], missing


def render_brief(p: Product, resolve: Resolver | None = None) -> bytes:
    d = _Deck(resolve)
    s = d.slide(p.name)
    d.text(
        s,
        0.9,
        4.0,
        23.6,
        3.0,
        [f"Spec v{p.spec_version} · {p.id} · colourway {p.colourway}"],
        14,
        colour=MUTED,
    )

    shapes = [r for r in p.references if r.kind == "shape"]
    for k in range(0, len(shapes), 2):
        s = d.slide("Shape References")
        d.images(s, [r.ref for r in shapes[k : k + 2]], width=23.6)

    for pl in p.placements:
        s = d.slide(_placement_title(pl))
        mocks = [
            r.ref
            for r in p.references
            if r.kind == "mockup" and (r.caption or "").startswith(pl.id)
        ]
        d.images(s, mocks or ([pl.artwork_ref] if pl.artwork_ref else []))
        lines, missing = _placement_lines(pl)
        d.text(s, 14.2, 3.0, 10.4, 8.4, lines, 12)
        d.gaps(s, missing)

    if p.labels or p.hardware:
        s = d.slide("Back of Hat (Label)" if p.category == "headwear" else "Labels and Hardware")
        d.images(s, [r.ref for r in p.references if r.kind == "detail"])
        lines, missing = [], []
        for h in p.hardware:
            parts = [x for x in (h.material, h.finish, fmt(h.size)) if x]
            qty = f"{h.quantity} × " if h.quantity else ""
            lines.append(
                f"• {qty}{h.kind}: {h.description}" + (f" ({', '.join(parts)})" if parts else "")
            )
            lines += [f"   must: {r}" for r in h.requirements]
            if h.material is None or h.finish is None:
                missing.append(f"{h.kind}: material and finish")
            if h.size is None or not h.size.known:
                missing.append(f"{h.kind}: size")
        for lb in p.labels:
            w, ht = fmt(lb.width), fmt(lb.height)
            parts = [
                x for x in (lb.material, lb.attachment, f"{w} × {ht}" if w and ht else None) if x
            ]
            lines.append(f"• {lb.kind} label" + (f": {', '.join(parts)}" if parts else ""))
            pos = F.position(lb.position)
            if pos:
                lines.append(f"   at {pos}")
            if lb.content:
                lines.append(f"   reads: {lb.content}")
            for what, ok in (("position", pos), ("size", w and ht), ("material", lb.material)):
                if not ok:
                    missing.append(f"{lb.kind} label: {what}")
        d.text(s, 14.2, 3.0, 10.4, 7.2, lines, 11)
        d.gaps(s, missing)

    s = d.slide("Measurements")
    rows, missing = [], []
    for pm in p.poms:
        for size in p.sizes:
            v = fmt(pm.values.get(size))
            (
                rows.append(f"{pm.name} ({size}): {v}")
                if v
                else missing.append(f"{pm.name} ({size})")
            )
    d.text(s, 0.9, 3.0, 13.0, 10.5, rows or ["No measurements yet"], 13, gap=not rows)
    d.gaps(s, missing, y=3.0)

    s = d.slide("Construction Details")
    c = p.construction
    lines = [x.upper() for x in c.notes] or [
        ", ".join(
            x for x in (c.structure, f"{c.crown} crown" if c.crown else None, c.brim) if x
        ).upper()
    ]
    lines += [
        m.description.upper() for m in p.materials if m.description.upper() not in " ".join(lines)
    ]
    lines += [
        f"{sm.location}: {sm.stitch_type or ''} {f'{sm.spi:g} SPI' if sm.spi else ''}".strip()
        for sm in c.seams
    ]
    d.text(s, 0.9, 3.0, 23.6, 10.5, lines, 16)
    return d.save()


def render_revisions(p: Product, round_: SampleRound, resolve: Resolver | None = None) -> bytes:
    d = _Deck(resolve)
    s = d.slide(p.name)
    d.text(s, 0.9, 4.0, 23.6, 2.0, [f"Revisions - Sample {round_.n}"], 20)
    d.text(
        s,
        0.9,
        6.0,
        23.6,
        1.5,
        [f"Sample made from spec v{round_.made_from_spec_version}"],
        11,
        colour=MUTED,
    )
    for c in round_.changes:
        s = d.slide(f"#{c.n}: {c.summary}")
        d.images(s, c.image_refs[:3])
        lines = []
        cur = fmt(c.current_value) or c.current
        tgt = fmt(c.target_value) or c.target
        if cur:
            lines.append(f"Current sample: {cur}")
        if tgt:
            lines.append(f"Adjust to: {tgt}" if cur else tgt)
        if c.reason:
            lines.append(f"Why: {c.reason}")
        d.text(s, 14.2, 3.0, 10.4, 8.4, lines or ["(no instruction text)"], 13)
    return d.save()
