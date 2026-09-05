---
id: PT-0.12
name: telemetry attribution
kind: product
major: PT-V1
status: done
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

### @team-lead — 2026-09-05

Status planned → in-progress (four of five issues done). DoD caveat from PT-87: "a teammate's usage lands under its roster role … for live and backfilled lines alike" holds from PT-87 forward; three live lines flushed before it keep their spawn names permanently (session.id is discarded at flush). Likewise PT-84's six pre-PT-84 live main lines keep `main`. Both documented in TRACKER → Ongoing collection.

### @team-lead — 2026-09-05

Milestone complete 2026-09-05: PT-86 (#166), PT-87 (#167), PT-84 (#168), PT-89 (#169), PT-85 (#171) all merged. DoD holds from PT-87 forward for live lines (three pre-PT-87 spawn-named and six pre-PT-84 main-bucketed live lines are permanent, documented in TRACKER); backfilled lines are fully re-bucketed. Follow-ups in PT-0.12.1. Release tag v0.12.0 is the user's decision; archive after tagging per policy.
