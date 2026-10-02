---
name: product-spec
description: design-manufacture-interface's rules for the product spec and its outputs - the general, category-agnostic spec model (components, materials, colourways, placements and techniques, points of measure and tolerances, construction, hardware, trims and labels, packaging, quantities), sample rounds and revision history, completeness checks learned from past revisions, renderers (the client's own deck, the complete tech pack, BOM), client profiles as a layer, golden products, and confidentiality. Load before touching the spec, a check, a renderer, an importer or a client profile.
paths:
  - "src/**"
  - "profiles/**"
---

# product-spec

Draft before any code exists; the department rewrites it as the POC teaches it.

## The spec (the general core)
- One product = a versioned document: identity (product id matching the brand's catalogue
  id, category, colourway, season), components and materials (composition, weight, colour
  reference, supplier ref), placements (artwork ref, position from fixed reference points,
  finished size, technique: flat or puff embroidery, print, patch, with thread or ink
  colours), points of measure with tolerances (and grading where the category is sized),
  construction (structure, panels, seams), hardware, trims and labels (each placed and
  specified), packaging, quantities, references (images the factory may match), notes and
  approvals (Haki swipe verdicts by spec version: who, decision, note).
- **Category-agnostic.** Headwear first (one size or adjustable; panel height, brim length,
  crown, circumference, strap), garments later. A category adds its points of measure and
  checks; it never forks the core.
- **Every number has a unit and, where it matters, a tolerance.** cm/in both supported;
  conversion at render time, tested.
- A missing value is an explicit, visible gap in every output, never a default.

## Sample rounds and revisions
- A product carries its sample history: round N, what the sample measured, each change as
  current → target with the reason and before/after image refs, and its Haki swipe verdict.
- The current spec is the base plus every approved change; the factory always sees what
  changed since the version it last saw.
- **Revision items become checks.** Each change is classified by the field it fixed; a
  field that has needed a revision becomes a completeness check for its category, so the
  next first package states it. Track revision rounds per product: the north star is zero.

## Completeness checks and gaps
- Checks are data (per category, from standard practice and from past revisions); each
  finding names the field, why a factory needs it, and its severity.
- **The client profile sets severity:** for a client whose factory relationship fills gaps
  (Haki), gaps warn; for one without, they block. The report is always produced.

## Renderers
- From one spec: the client's own format (for Haki, a slide deck per product and per sample
  round, in their structure), the complete tech pack (PDF), a BOM (spreadsheet), and a gap
  report. Deterministic: the same spec renders the same bytes (fixed timestamps and fonts).
- Client-specific templates belong to the client profile.

## Importers
- Read a client's existing files (for Haki, its .pptx decks with python-pptx) into the spec,
  in place, read-only. What can't be read reliably becomes a gap or a question, not a guess.

## Client profiles (Haki is client 0)
- `profiles/<client>/` in git: vocabulary, defaults, gap severities, templates, the document
  set each factory receives, the importer's mapping. **No client data**: no product names,
  measurements, artwork, photos, costs or supplier contacts. Those stay in the client's files
  outside git, found by a path passed in or set by env var.
- A feature only one client needs goes into its profile; promote it to the core when a second
  client needs it.

## Tests
- Synthetic golden products (a hat first), never a client's real styles; synthetic decks
  shaped like the client's for importer tests. Rendered outputs approved once, diffed on every
  change.
