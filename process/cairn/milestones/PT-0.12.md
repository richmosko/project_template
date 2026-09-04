---
id: PT-0.12
name: telemetry attribution
kind: product
major: PT-V1
status: planned
target_tag: v0.12.0
ga: false
---

**Definition of done:** the token-usage numbers the board shows can be trusted per role and
per milestone without a caveat. The OTel receiver runs only while a session on the repo is
alive and stops itself after the exporter's final flush (PT-86); a teammate's usage lands under
its roster role, never its spawn name, for live and backfilled lines alike (PT-87); usage on
`main` is attributed to the active milestone as overhead instead of an untracked bucket (PT-84);
and the dashboard's flow chart reads as throughput — opened/closed per period plus WIP,
milestone-scoped (PT-85).

## Comments

### @team-lead — 2026-09-04

Opened with the user after the PT-78 §5 end-to-end check (PR #164). Scope is the four
telemetry follow-ups from the PT-0.11 loops; PT-82 (worktrees) and PT-83 (chart-ramp guard /
JS runner) are a separate theme and stay in the backlog for a later milestone.
