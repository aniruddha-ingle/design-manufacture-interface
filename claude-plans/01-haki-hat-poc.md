# 01 · Haki POC: one hat, one spec, a package that needs no revisions

Status: **draft** (2026-10-02, design-manufacture-interface-d4, before the first factory-lead).

## Why
Haki's first hat went to its factory as a slide deck (references, artwork per placement, a
four-line construction summary). Sample 2 came back needing five numbered revisions, every one
of them a field a complete tech pack states before sample 1: an artwork's position and size, two
points of measure, a hardware spec, a missing label. The north star (the user): "the ideal tech
pack should not need revisions". This plan proves the idea on that one real product.

**Done when:** from Haki's two decks the system holds one spec for the hat, renders (a) Haki's
own deck format and (b) a complete tech pack, BOM and gap report, and the factory-reviewer
confirms the complete pack, as of before sample 1 plus what is now known, states all five
sample-2 revision items. The package goes into Haki swipe for the CEO and COO.

## Inputs (outside git)
- Haki's two decks, read in place where the user keeps them (~/Downloads), read-only; paths
  passed on the command line or by `DMI_HAKI_DECKS`. The product is named here only by its
  local id `haki-hat-01`; no name, number or image of it enters git.
- Outputs under `DMI_HOME` (default `~/.dmi`), never in the repo.

## Nodes (the board)
| Node | Agent | Depends on | Delivers |
|---|---|---|---|
| `spec-contract` | spec-dev | — | `docs/contracts/spec.md` + pydantic models, `format_version: 1`: identity, materials, placements, POMs with unit/tolerance, construction, hardware, trims/labels, packaging, sample rounds (change: field, current → target, reason, image refs), approvals; headwear POMs. A synthetic golden hat that validates. |
| `checks-headwear` | spec-dev | spec-contract | Completeness checks as data: standard headwear set (researched, sources in the plan) plus the five revision-derived checks; severity per client profile; a gap report as JSON. |
| `haki-importer` | client-dev | spec-contract | `profiles/haki/` (deck structure, vocabulary, gap severity = warn) and a python-pptx importer: brief deck → spec v1, revision deck → sample round with numbered changes. Synthetic decks shaped like Haki's for tests; on the real decks it reports counts and field names only. |
| `render-haki-deck` | techpack-dev | spec-contract | `.pptx` in Haki's structure (brief and revision round) from the spec; deterministic. |
| `render-techpack` | techpack-dev | spec-contract, checks-headwear | Complete tech pack PDF (cover, references, placements with measured positions, POM table with tolerances, BOM, labels, construction, change log, gaps highlighted), BOM `.xlsx`, gap report page. |
| `poc-hat-package` | lead | all above | Import the real decks → spec → both renders → factory-reviewer (incl. the north-star test) → a Haki swipe item. |

`spec-contract` merges first; the four after it run in parallel worktrees.

## Calls made (2026-10-02, with reasons)
- **Libraries** (checked: all install from Intel wheels on this Mac): pydantic (spec models),
  python-pptx (read and write decks), openpyxl (BOM), PyMuPDF (render pages to images for
  review). PDF: **Typst via the `typst` wheel** (templated, deterministic, good typography);
  reportlab as fallback if a layout need appears that Typst can't meet.
- **Units:** stored in mm (integers or one decimal), rendered in cm and in; tolerances per POM.
- **Product id:** `pre:haki:<slug>` for sample-stage products, mapped to the Shopify handle when
  the product goes on the site (a proposal to copy-lead-1, who owns the catalogue).
- **Haki swipe item** (pip-lead-2's v2 shape): `item_key: "dmi:<product>:spec-<n>[:round-<k>]"`,
  `department: "design-manufacture"`, `kind: "tech-package" | "revision-round" | "idea"`,
  `source: {product, spec_version, sample_round}`; page images only into the private page.
- **Gaps warn for Haki**, always listed; they block only for clients whose profile says so.

## What the user sees
The complete pack's PDF and Haki-format deck for the hat (locally, under `~/.dmi`), the gap
report, and the reviewer's table of the five revisions: stated or not. Then the Haki swipe card.

## Open questions (with recommendations; non-blocking)
1. Information the decks don't hold (fabric composition and weight, thread colours, hardware
   supplier, label artwork): ask Haki through a Haki swipe "idea"/question card, or leave as
   gaps? **Recommend:** leave as visible gaps in the POC; the gap report is the question list.
2. Does Haki want the complete pack sent to its factory, or only its deck? **Recommend:** both,
   the deck as the cover the factory knows, the pack attached.

## Cost
CPU: seconds per render; nothing heavy. Spend: none.
