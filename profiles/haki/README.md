# Haki (client 0): profile

Method only; Haki's decks, products and numbers never enter git.

- **Their method:** a slide deck per product and colourway (title; shape-reference photos; a
  slide per artwork placement titled "<Location> Embroidery - <Technique> (<colours>)"; a back
  or label slide; "Construction Details" as a few upper-case lines), then after each sample a
  "Revisions - Sample N" deck: one slide (or two) per numbered change "#N: <summary>", before
  and after photos, the instruction in a text column, measurements drawn on photos as a
  dimension line with an "X cm" callout, often "Current sample is X, adjust to Y".
- **Gaps warn** (`gap_severity: warn`): their factory relationship fills gaps; the gap report
  is always produced.
- **Import:** `uv run python -m dmi.importers haki --id pre:haki:<slug> --brief DECK
  --revision DECK...` reads the decks in place and writes spec versions under `DMI_HOME`.
- `profile.json` holds the deck vocabulary (title patterns, techniques, locations,
  construction lines, change areas) the importer applies.
