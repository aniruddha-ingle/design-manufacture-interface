# 00 · Organisation: how this department was set up

2026-10-02, session design-manufacture-interface-d4, before the first factory-lead.

- **Origin.** The user, in studio: "time to expand org with new department ... The goal of this
  is to create an output that we can give to manufacturers. Haki has their own method but we
  should build a general system and specialise for haki in that system as they are client 0."
  Studio's lead-9 (studio-ed) cloned the empty repo and wrote the handoff and kit
  (studio `claude-plans/handoffs/2026-10-02-design-manufacture-interface/`).
- **Haki's method**, from its two hat decks (read in place, never copied): a spec deck per
  product, then a numbered revision deck per sample round. The user: "this is the specialised
  workflow we build for haki but we want this repo to be cutting edge standards of a tech
  pack ... long term goal the agnostic system short term goal build for haki".
- **North star** (the user): "the ideal tech pack should not need revisions thats the north
  star. if coo is sure about design the tech pack should tell factory exactly how to make it".
- **Org goal** (the user): "everything goes into haki swipe for now. the over arching org goal
  is to build a swipe app for the ceo and coo to vote on ideas created by all departments
  combined." Broadcast to every live lead. Agreed with copy-lead-1: product ids are the
  catalogue's handles, a pre-release id for sample-stage products. Agreed with pip-lead-2:
  the Haki swipe item v2 shape (item_key, department, kind, source).
- **Orders** come from the user and the gateway lead (sample-staging-platform-ad). **Autonomy**
  (the user, here): "full autonomy as long as you are not destructive or adding any cost, all
  open source".
- **Kit** (commit 3d77d8a): `/factory-lead`, the product-spec skill, agents spec-dev,
  techpack-dev, client-dev, factory-reviewer, adapted from lead-9's draft after Haki's method
  was known.
- **Lead tooling** (`scripts/lead/`): ported from product-in-video's port (closest: no live
  consumer, board on the trunk), `DMI_` prefix, factory-reviewer gate, Haki's deck, document,
  spreadsheet, vector and CAD formats added to the pre-push refusals.
- **Confidentiality slip, fixed:** the handoff's first §2 recorded the hat's name and
  measurements in studio's git; lead-9 removed both commits before any push (studio 8fc37e6
  holds the method only).
