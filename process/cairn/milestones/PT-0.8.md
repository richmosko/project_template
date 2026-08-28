---
id: PT-0.8
name: project dashboard
kind: product
major: PT-V1
status: done
target_tag: v0.8.0
ga: false
---

**Definition of done:** the board server grows a `/dashboard` view on real
data — status cards (git state, latest release, tracker health), the live
kanban/list board embedded, and an agent-roster panel — styled per the
shadcn-svelte design system (preset `b6XadDxmQS`, preset-pure; see
`docs/DESIGN/design-system-spec.md`, merged in #119) at the approved
dashboard scale. `tokens.css` ships as the machine-readable deliverable.
The design reference is the canvas mockup (claude.ai artifact, session of
2026-08-26). board.css token migration (PT-57) rides along if capacity
allows; it is not a release blocker. Scoped 2026-08-26 (Mosko).
