---
id: PT-0.5.1
name: follow-ups
kind: product
major: PT-V1
status: done
target_tag: v0.5.1
ga: false
---

**Definition of done:** the review-surfaced follow-ups from 0.5 are resolved —
`cairn ls` sorts numerically by id (PT-21), board.js gains a JS unit-test layer
so DOM-logic bugs stop depending on a human Chrome pass (PT-22), and the board's
bare-`{}`-as-set lookups move to `Object.create(null)` (PT-23). Deferred from 0.5
(Mosko, 2026-08-20) so v0.5.0 could ship on its seven completed features.
