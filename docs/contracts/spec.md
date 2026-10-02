# Contract: the product spec (format_version 1, 2026-10-02)

One product = one JSON document, the single truth every factory document is rendered from.
Models: `src/dmi/spec/models.py` (pydantic). JSON Schema: [`spec.schema.json`](spec.schema.json),
generated (`uv run python -m dmi.spec schema`) and checked against the models by a test.
Validate files: `uv run python -m dmi.spec validate FILE...`. Golden example (synthetic):
[`tests/golden/example-cap.json`](../../tests/golden/example-cap.json).

## Rules
- **Lengths are millimetres**: `Length {mm | min_mm+max_mm, tol_mm, tol_minus_mm}`; a range is for adjustable dimensions; `tol_mm` is ± unless `tol_minus_mm` sets the minus side. Rendering converts to cm
  and inches (`dmi.spec.units`, incl. factory fractions like `2 5/8`).
- **Unknown is `null`, never a default.** A missing `mm`, technique, colour reference or
  supplier ref is a gap the checks report and every render highlights.
- **Ids are stable** (`[a-z0-9-]`, unique per list), so sample-round changes, renders and
  Haki swipe verdicts point at them. POMs are keyed by `code`.
- **Product id** = the brand catalogue's handle (copy-in-product-picture's catalogue
  `products[].id`), or `pre:<client>:<slug>` before the product is on the site.
- **Canonical bytes:** `dmi.spec.dump` writes sorted keys, no nulls, a trailing newline: the
  same spec is always the same bytes.
- **No client data in git:** artwork, references and images are refs (file names or ids),
  never files; real products live outside the repo (`DMI_HOME`).

## Shape
| Field | What |
|---|---|
| `format_version` | `1` |
| `id`, `client`, `category`, `name`, `colourway`, `season`, `spec_version` | identity; `category` ∈ headwear, top, bottom, outerwear, accessory, other |
| `sizes` | required, e.g. `["OS"]` for one size; every POM value and quantity key must be one of them; quantities ≥ 0 |
| `materials[]` | `id, role, description, composition[{fibre, percent}]` (sums to 100), `weight_gsm`, `thickness`, `colour {name, system, code}`, `supplier_ref` |
| `placements[]` | artwork: `id, location, artwork_ref, technique` (flat/puff embroidery, chain stitch, appliqué, patches, prints), `width`, `height`, `position`, `elements[{name, colour, thread, stitch_type}]`, `stitch_count`, `density`, `foam_height_mm` |
| `poms[]` | `code, name, how_to_measure, values {size: Length}`; per-category definitions in `dmi.spec.categories` |
| `construction` | `structure, crown, panels, brim, closure, seams[{location, stitch_type, spi, thread, rows, finish}], notes[]` |
| `hardware[]` | `id, kind, description, quantity, position, material, finish, colour, size, supplier_ref, requirements[]` |
| `labels[]` | `id, kind, position, artwork_ref, material, attachment, width, height, content` |
| `trims[]` | `id, kind, description, material_id` (must name a material), `width`, `colour` |
| `packaging` | `unit, folding, labels[], carton` |
| `quantities` | `{size: count}` |
| `references[]` | images the factory may match: `kind` (shape, mockup, sample-photo, …), `ref`, `authority` exact/approximate |
| `sample_rounds[]` | `n` (ascending), `made_from_spec_version`, `applied_in_spec_version`, `received`, `changes[]`: `n, area, field` (dotted path to an existing id, e.g. `poms.brim-length`; the area must match), `summary, current, target, current_value, target_value, reason, image_refs[]` |
| `approvals[]` | verdicts (e.g. Haki swipe): `spec_version, who` (opaque id like `u-0001`), `decision` keep/cut/love, `note, at` (timezone required, stored UTC), `source` |
| `position` (placements, hardware, labels) | `{anchor, to, dx_mm, dy_mm, note}`: from a category anchor (`dmi.spec.categories`, or `other:<text>`) to a point of the item (`centre`, `bottom-edge`, …); seen from outside, +dx viewer's right, +dy up |

## Sample rounds and the north star
Each change records what the sample had (`current`), what it should have (`target`) and why,
and names the spec `field` it fixes and its `area`. The checks (node `checks-headwear`) turn
fields that needed a revision into completeness checks for the category, so the next first
package states them. Revision rounds per product, towards zero, is the measure.

## Changing this contract
Additive fields: same `format_version`, schema regenerated, golden products still valid. A
rename, removal or meaning change: `format_version` 2 with a migration for existing specs, and
a note to the departments that read it (Haki swipe items carry `spec_version`).
