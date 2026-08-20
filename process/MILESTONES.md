# Milestones & State

> Live ledger of where the project is. Updated by the team-lead at every phase transition, feature completion, session-cycle boundary, and decision.
>
> **Durable work state lives in the tracker, not here.** Majors, milestones (the roadmap), and features are cairn artifacts under [`process/cairn/`](cairn/) — view them on the board (`/cairn`, `http://localhost:8766/`) or list them with `scripts/cairn/cairn ls`. This file keeps only what the tracker deliberately doesn't model: the current phase, the active feature pointer, Session Cycles, and shipped releases. (The old Major-line / Roadmap / Features tables dissolved into cairn — ruled 2026-08-19, see [`TRACKER.md`](TRACKER.md) → Relationship to MILESTONES.md.)

## Current Phase

**Phase:** Template maintenance — this is the template repo itself; Research/Plan predate the ledger. Meta-work runs as Implement⇄Validate loops on the `0.3` milestone (see the board).  
**Started:** 2026-08-19 (cairn line of work)  
**Driver agent:** team-lead  
**Gate criteria:** _see [`WORKFLOW.md`](WORKFLOW.md)_

## Active Feature

A feature = one cairn issue = one PR = one Implement→Validate loop. Exists only during Implement phase. This is a pointer — the issue file (`process/cairn/issues/<ID>.md`) is the record.

| Field | Value |
|---|---|
| Feature | _—_ |
| Issue | _—_ |
| Milestone | _—_ |
| Session Cycle | _—_ |
| Branch | _—_ |
| Started | _—_ |
| Goal | _—_ |
| Status | _—_ |

## Session Cycles

Session Cycles are **context-bounded working sessions**, not calendar sprints and **not tracker artifacts** — a heuristic only (see [`WORKFLOW.md`](WORKFLOW.md) → Session Cycles). Each is one Claude session's worth of work: the features + directives that fit under ~80% context. Log them here as lightweight notes. Status is implied by recency: **Current · Previous**.

| Session | Milestone | Planned work (features + directives) | Status | Notes |
|---|---|---|---|---|
| _e.g. SC1_ | _1.0_ | _—_ | _—_ | _—_ |

## Releases

Tagged releases across all major lines. Cut via `/merge-pr` when a product milestone completes — tagging is never automatic. Strict semver; version = milestone name + its `target_tag` (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). `V1.x` maintenance and `V2.x` releases coexist here; note the branch for maintenance tags.

| Version | Date | Major line | Milestone shipped | Branch | Notes |
|---|---|---|---|---|---|
| _e.g. v0.1.0_ | _—_ | _V1_ | _1.0 (MVP)_ | _main_ | _—_ |
| _e.g. v1.1.1_ | _—_ | _V1_ | _1.1 hotfix_ | _release/1.x_ | _maintenance while main carries V2_ |

## Decisions

The Decision Log lives alongside this file at [`DECISIONS.md`](DECISIONS.md) (under `process/`) — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
