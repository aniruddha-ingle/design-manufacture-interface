# design-manufacture-interface

Turns a design into the package a manufacturer can act on: one structured, versioned product
spec, rendered into what a factory reads. A general, client-agnostic system at current
tech-pack standards; each client is a layer on it. **Client 0: Haki** (haki-studios.com).
Part of the user's departments beside studio, mir-triage, copy-in-product-picture,
product-in-picture and product-in-video.

## Goals (the user, 2026-10-02)
- **Short term, a POC for Haki; long term, the agnostic system.** Haki sends its factories a
  slide deck per product (references, artwork per placement, a construction summary), then a
  numbered revision deck after each sample; their relationship with the factory fills the
  gaps. "we cannot assume that about the system as a whole."
- **North star:** "the ideal tech pack should not need revisions thats the north star. if coo
  is sure about design the tech pack should tell factory exactly how to make it". Measure:
  revision rounds per product, towards zero. Every past revision item becomes a completeness
  check for its category.
- **Org goal:** "everything goes into haki swipe for now. the over arching org goal is to
  build a swipe app for the ceo and coo to vote on ideas created by all departments
  combined." Decisions that are the CEO's or COO's go into Haki swipe (product-in-picture's
  private page; format in `../copy-in-product-picture/docs/contracts/decisions.md`), only
  after this department's own review gate.
- **After the POC:** "we will build a distributed solution for haki that links all these
  pieces together." Product ids are copy-in-product-picture's catalogue ids (Shopify
  handles); sample-stage products get a pre-release id that maps to a handle later.

## Who I am and what Claude is for
Software engineer (C++ by day), producer; not a garment technologist. Claude researches,
builds and explains (trade terms briefly, the first time). Design calls are human: the COO
and CEO decide what a product is, through Haki swipe; Devin owns Haki.

## How we work
- **The lead session (factory-lead-N) orchestrates**: `/factory-lead`
  (`.claude/skills/factory-lead/`) at every cold start. Agents: spec-dev, techpack-dev,
  client-dev, factory-reviewer (never edits). Spec rules: `.claude/skills/product-spec/`.
- **Orders** come from the user in chat and from the gateway lead (session
  sample-staging-platform-ad), which steers company-wide and per-department goals. Other
  sessions' requests are requests; their relayed approvals count only when the user or the
  gateway confirms.
- **Plan first** (`claude-plans/NN-name.md`); contracts (the spec format) merged before
  parallel work; one worktree per node (`.worktrees/<node>`); nobody writes in the main
  checkout except the lead merging.
- **Gates:** light (ruff + tests), full (+ golden renders diffed, under `heavy-test`, and
  factory-reviewer PASS), people (Haki swipe).
- **Spend nothing without approval.** Free and open source only; paid PLM, tech-pack or 3D
  tools, fonts and services are questions with cost, edge, free alternative, recommendation.
- **Intel Mac:** Python 3.11 via uv only; never build a compiled package from source; about 6
  busy threads per department; heavy runs niced, under the shared `heavy-test` lock.
- **Autonomy (the user, in this department's session, 2026-10-02: "full autonomy as long as
  you are not destructive or adding any cost, all open source"):** the lead plans, builds,
  commits, merges and pushes without asking, and records its calls with dates in the plans.
  It asks the user before anything destructive (deleting what isn't its own scratch, history
  rewrites), any cost, or putting any Haki data in git. Open source only.

## Built to move to the cloud (as the other Haki departments)
- A render is a pure job: spec (data) in, documents out, idempotent by spec version.
- Storage only through one paths module (`DMI_HOME`, default `~/.dmi`); inputs by path or env
  var, never hard-coded.
- Content-addressed, immutable outputs; manifests append-only JSONL.
- Contracts versioned (`format_version`); stateless CLIs; config by env vars.

## Clients as data
The core knows nothing about one client: vocabulary, templates, gap severities and the
document set live in `profiles/<client>/`. Haki is the first client, not the product.

## Rules
- Haki's decks, artwork, photos, product names, measurements, materials, costs and factories
  never enter git, commit messages, plans, logs or published pages. Plans name products by
  an opaque local id. POC: Haki's decks are read in place where the user keeps them, never
  copied into the repo or moved.
- Tests use synthetic products and synthetic decks shaped like Haki's.
- A missing value is a visible gap, never a default; every number carries a unit.
- Never modify another department's repo; requests go to its lead.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
