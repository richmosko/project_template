# State

> Live ledger of where the project is. Updated by the team-lead at every phase transition, feature completion, session-cycle boundary, and decision.
>
> **Durable work state lives in the tracker, not here.** Majors, milestones (the roadmap), and features are cairn artifacts under [`process/cairn/`](cairn/) — view them on the board (`/cairn`, `http://localhost:8766/`) or list them with `scripts/cairn/cairn ls`. This file keeps only what the tracker deliberately doesn't model: the current phase, the active feature pointer, Session Cycles, and shipped releases. (The old Major-line / Roadmap / Features tables dissolved into cairn — ruled 2026-08-19, see [`TRACKER.md`](TRACKER.md) → Relationship to STATE.md.)

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
| SC2 (2026-08-20) | 0.4 | 0.4 scoped (12 issues; PT-2/3/4 deferred to 0.5). Order: PT-15 (STATE.md rename) → PT-14 (Linear removal) → hardening batches (PT-5/6/12, PT-7/8/9/13, PT-10/11) → PT-1 (SSE live push). | Current | Scope decision logged in TEMPLATE_DECISIONS.md (2026-08-20). PT-15 (#34), PT-14 (#35), PT-5 (#36), PT-17 (#37), PT-6 (#38) shipped — 0.4 at 5/13. Standing order (Mosko, 2026-08-20): self-merge authorized for the remaining 0.4 issues; stop only for real decisions (v0.4.0 tag at milestone close is a planned stop). Fresh post-PT-17 teammates coordinate by live SendMessage. PT-17 closed the SendMessage outage (fresh spawns); Task tools session-gated → PT-18 filed. PT-16 scope grew via a board-UI comment (swimlane expand/collapse) — first dogfood round-trip through the board. PT-16 filed (board name display). Teammate SendMessage down all session (allowlist omission found, but docs say auto-add — session-level cause suspected; PT-17 tests it); temp/ fallback held. QA corrected its PDF-check method (byte-grep → pdftotext, on PT-15) and caught an orphaned live-data cairn serve on :18766 (killed). |
| SC1 (2026-08-19/20) | 0.3 | cairn end-to-end: design ruling → TRACKER.md spec (#28) → engine + 128-test suite (#29) → skills migration (#30) → dogfood scaffold + v0.3.0 (#31) | Previous | Teammate SendMessage outage all session — coordination ran through the temp/ buffer, which held. PT-1…PT-15 seeded as the 0.4-candidate backlog. |

## Releases

Tagged releases across all major lines. Cut via `/merge-pr` when a product milestone completes — tagging is never automatic. Strict semver; version = milestone name + its `target_tag` (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). `V1.x` maintenance and `V2.x` releases coexist here; note the branch for maintenance tags.

| Version | Date | Major line | Milestone shipped | Branch | Notes |
|---|---|---|---|---|---|
| v0.3.0 | 2026-08-20 | V1 | 0.3 (cairn) | main | Draft — [release](https://github.com/richmosko/project_template/releases) pending Mosko's curation/publish. cairn replaces Linear: spec #28, engine #29, skills migration #30, dogfood #31. |

## Decisions

The Decision Log lives alongside this file at [`DECISIONS.md`](DECISIONS.md) (under `process/`) — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
