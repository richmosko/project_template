---
id: "PT-0.6.2"
name: board follow-ups — trackpad + cancelled column
kind: product
major: PT-V1
status: active
target_tag: v0.6.2
ga: false
---

**Definition of done:** the two board follow-ups spun out of 0.6.1's loops ship —
pull-to-refresh gains the trackpad-overscroll adapter on PT-32's distance-based
state machine, with the momentum-decay heuristic architect-designed and red-tested
against the flick-to-top false positive (PT-33); and kanban renders cancelled
issues in a conditional sixth column when Show-cancelled is on, resolving the
inert-checkbox root cause PT-31 fixed only arithmetically (PT-35, architect
design first re BOARD_COLUMNS purity); and the cross-language column-list
drift risk PT-35's ruling flagged gets a loud guard or single-source
derivation (PT-36).
Scoped 2026-08-22 (Mosko); PT-36 rolled in pre-tag 2026-08-23 (Mosko).
