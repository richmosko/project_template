---
id: PT-0.6
name: tracker relations + milestone conventions
kind: product
major: PT-V1
status: done
target_tag: v0.6.0
ga: false
---

**Definition of done:** cairn models issue relations and the milestone naming
convention splits definition from development — the board and CLI deliver the
sub-issue UX the spec already promises (parent-side badge, drawer nesting,
`cairn show` children — PT-25); issues can declare blocking dependencies with
lint + board surfacing (PT-26); and doc/definition milestones adopt the
`A`/`B`/`C` id convention with `M0`/`M1`… reserved for development milestones,
encoded in TRACKER.md, the setup-tracker skill, and a `check_repo` lint (PT-27).
Scoped 2026-08-21 (Mosko); self-merge authorized through milestone close, v0.6.0
at the end.
