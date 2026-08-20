# State

> Live ledger of where the project is. Updated by the team-lead at every phase transition, feature completion, session-cycle boundary, and decision.
>
> **Durable work state lives in the tracker, not here.** Majors, milestones (the roadmap), and features are cairn artifacts under [`process/cairn/`](cairn/) — view them on the board (`/cairn`, `http://localhost:8766/`) or list them with `scripts/cairn/cairn ls`. This file keeps only what the tracker deliberately doesn't model: the current phase, the active feature pointer, Session Cycles, and shipped releases. (The old Major-line / Roadmap / Features tables dissolved into cairn — ruled 2026-08-19, see [`TRACKER.md`](TRACKER.md) → Relationship to STATE.md.)

## Current Phase

**Phase:** Template maintenance — this is the template repo itself; Research/Plan predate the ledger. Meta-work runs as Implement⇄Validate loops on the `0.5` milestone (see the board).  
**Started:** 2026-08-19 (cairn line of work)  
**Driver agent:** team-lead  
**Gate criteria:** _see [`WORKFLOW.md`](WORKFLOW.md)_

## Active Feature

A feature = one cairn issue = one PR = one Implement→Validate loop. Exists only during Implement phase. This is a pointer — the issue file (`process/cairn/issues/<ID>.md`) is the record.

| Field | Value |
|---|---|
| Feature | check_repo: enforce title presence on issues, absence on milestones/majors |
| Issue | PT-19 |
| Milestone | 0.5 |
| Session Cycle | SC4 |
| Branch | `feature/pt-19-title-shape-lint` |
| Started | 2026-08-20 |
| Goal | Close the `_is_issue_shaped` gap at the lint layer: check_repo flags missing `title:` on issues and stray `title:` on milestones/majors. |
| Status | In Progress |

## Session Cycles

Session Cycles are **context-bounded working sessions**, not calendar sprints and **not tracker artifacts** — a heuristic only (see [`WORKFLOW.md`](WORKFLOW.md) → Session Cycles). Each is one Claude session's worth of work: the features + directives that fit under ~80% context. Log them here as lightweight notes. Status is implied by recency: **Current · Previous**.

| Session | Milestone | Planned work (features + directives) | Status | Notes |
|---|---|---|---|---|
| SC4 (2026-08-20) | 0.5 | Finish 0.5 through PT-2: PT-19 (title-shape lint) → PT-16 (board names + collapse) → PT-4 (drawer markdown) → PT-2 (snapshot appendix). PT-3 gated on a design conversation; milestone close (v0.5.0) is a planned stop. Standing order (Mosko, 2026-08-20): self-merge authorized up to milestone end. | Current | Stale remote-tracking refs pruned (branches already deleted on GitHub). First feature to exercise the restored anchor-task pattern (Task tools live in-session). |
| SC3 (2026-08-20) | 0.5 | 0.5 scoped (all 6 backlog issues; backlog cleared). Order: PT-18 (anchor-task degraded-mode docs) → PT-19 (title-shape lint) → PT-16 (board names + collapse) → PT-4 (drawer markdown) → PT-2 (snapshot appendix) → PT-3 (multi-root board, design conversation last). | Previous | v0.3.0 + v0.4.0 GitHub releases published (#45). 0.5 scope decision logged in TEMPLATE_DECISIONS.md (2026-08-20). PT-18 shipped (#47) — 0.5 at 1/6; scope add: template now ships CLAUDE_CODE_ENABLE_TODO_TOOLS=1 (decision logged; verified live — Task tools appeared in the running session on save). QA (fresh spawn) validated by live SendMessage; two coordination lessons banked in team-lead memory: claude-code-guide has no SendMessage (spawn unnamed or WebFetch docs directly), and teammates reply to "team-lead", not "main". /doctor run: figma plugin disabled user-scope (~2k est. tokens/session reclaimed); setup otherwise healthy. Next: PT-19 (title-shape lint) — first feature to exercise the restored anchor-task pattern. |
| SC2 (2026-08-20) | 0.4 | 0.4 scoped (12 issues; PT-2/3/4 deferred to 0.5). Order: PT-15 (STATE.md rename) → PT-14 (Linear removal) → hardening batches (PT-5/6/12, PT-7/8/9/13, PT-10/11) → PT-1 (SSE live push). | Previous | Scope decision logged in TEMPLATE_DECISIONS.md (2026-08-20). PT-15 (#34), PT-14 (#35), PT-5 (#36), PT-17 (#37), PT-6 (#38), PT-12 (#39), batch PT-7/8/9/13 (#40), batch PT-10/11 (#41), PT-1 (#42) shipped — 0.4 COMPLETE at 13/13; milestone flipped completed on the closing branch. Team-lead closed QA's browser-verification gap with a real Chrome pass (SSE live/polling/reconnect all visually confirmed). PT-19 filed (title-lint gap, from batch Validate). Standing order (Mosko, 2026-08-20): self-merge authorized for the remaining 0.4 issues; stop only for real decisions (v0.4.0 tag at milestone close is a planned stop). Fresh post-PT-17 teammates coordinate by live SendMessage. PT-17 closed the SendMessage outage (fresh spawns); Task tools session-gated → PT-18 filed. PT-16 scope grew via a board-UI comment (swimlane expand/collapse) — first dogfood round-trip through the board. PT-16 filed (board name display). Teammate SendMessage down all session (allowlist omission found, but docs say auto-add — session-level cause suspected; PT-17 tests it); temp/ fallback held. QA corrected its PDF-check method (byte-grep → pdftotext, on PT-15) and caught an orphaned live-data cairn serve on :18766 (killed). |
| SC1 (2026-08-19/20) | 0.3 | cairn end-to-end: design ruling → TRACKER.md spec (#28) → engine + 128-test suite (#29) → skills migration (#30) → dogfood scaffold + v0.3.0 (#31) | Previous | Teammate SendMessage outage all session — coordination ran through the temp/ buffer, which held. PT-1…PT-15 seeded as the 0.4-candidate backlog. |

## Releases

Tagged releases across all major lines. Cut via `/merge-pr` when a product milestone completes — tagging is never automatic. Strict semver; version = milestone name + its `target_tag` (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). `V1.x` maintenance and `V2.x` releases coexist here; note the branch for maintenance tags.

| Version | Date | Major line | Milestone shipped | Branch | Notes |
|---|---|---|---|---|---|
| v0.4.0 | 2026-08-20 | V1 | 0.4 (hardening) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.4.0). 13 issues, PRs #34–#42: STATE.md rename, Linear removal, engine/board hardening, teammate coordination toolset, SSE live push. |
| v0.3.0 | 2026-08-20 | V1 | 0.3 (cairn) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.3.0). cairn replaces Linear: spec #28, engine #29, skills migration #30, dogfood #31. |

## Decisions

The Decision Log lives alongside this file at [`DECISIONS.md`](DECISIONS.md) (under `process/`) — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
