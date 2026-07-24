# Milestones & State

> Live ledger of where the project is. Updated by the team-lead at every phase transition, feature completion, session-cycle boundary, and decision.

## Major line / Initiative

The **active major version line** (`V1`, `V2`, …). Each major line is mirrored to its own Linear **Initiative** and maps to the `MAJOR` version digit; a new major opens a new Initiative, and `V1.x`/`V2.x` can run concurrently (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). List every open line; the founding line starts at MAJOR `0`. Status values: **Planned · Active · Completed** (Completed = line EOL'd). Health values: **On track · At risk · Off track**.

| Major line | Linear Initiative | Status | Owner | Target ship | Health | Notes |
|---|---|---|---|---|---|---|
| _V1_ | _LINEAR-INIT-XXX_ | _Planned_ | _—_ | _—_ | _On track_ | _founding line; MAJOR 0 → 1.0.0 at GA_ |

## Current Phase

**Phase:** _not started — run `/setup-linear-team` and begin Research_  
**Started:** _—_  
**Driver agent:** _—_  
**Gate criteria:** _see [`WORKFLOW.md`](WORKFLOW.md)_

## Active Feature

A feature = one Linear issue = one PR = one Implement→Validate loop. Exists only during Implement phase.

| Field | Value |
|---|---|
| Feature | _—_ |
| Linear issue | _—_ |
| Milestone | _—_ |
| Session Cycle | _—_ |
| Branch | _—_ |
| Started | _—_ |
| Goal | _—_ |
| Status | _—_ |

## Roadmap

Each milestone maps to a **Linear project** and to the `MINOR` version digit (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). Status values match Linear project statuses: **Backlog · Planned · In Progress · Paused · Completed · Cancelled**. The **Target tag** column records the version each product milestone ships; exactly one milestone per major line is flagged **GA** (`→ vN.0.0`).

**Two flavors:**
- **Process milestones** (Bootstrap & Research, Plan) track the Research and Plan phases themselves and **don't tag releases**. They ship by default at bootstrap so the Roadmap is never empty. **Each can be subdivided** if a phase turns out to be complex (e.g. `Research: PRD draft` → `Research: PRD review & refinement`, or `Plan: Architecture` → `Plan: Security` → `Plan: milestone enumeration`). Keep one Linear project per row.
- **Product milestones** are the scope chunks of the product, **named by target version** (`1.0`, `1.1`, `2.0`). One milestone per `MINOR` (Model A — subdivide internally if large; cut `-alpha/-beta/-rc` at checkpoints). Populated + GA-flagged by the `architect` during Plan.

| # | Milestone | Status | Gate | Target tag | Linear Project | Notes |
|---|---|---|---|---|---|---|
| M0 | _Bootstrap & Research_ | _In Progress_ | _PRD locked_ | _—_ | _LIN-XXX_ | Process milestone; untagged. Issues: PRD-drafting work (problem framing, user stories, NFRs, design considerations). |
| M1 | _Plan_ | _Planned_ | _ARCH + SECURITY locked, product-milestone rows populated + GA flagged, first session planned_ | _—_ | _LIN-XXX_ | Process milestone; untagged. Issues: (a) Draft ARCH; (b) Draft SECURITY; (c) **Populate product milestones + designate GA**; (d) Plan first session. |
| _1.0_ | _MVP — first product milestone (output of M1)_ | _Planned_ | _—_ | _**v1.0.0 (GA)**_ | _—_ | _GA-designated for the V1 line; founding line may precede it with 0.1, 0.2 rows_ |

## Session Cycles

Session Cycles are **context-bounded working sessions**, not calendar sprints and **not Linear artifacts** — a heuristic only (see [`WORKFLOW.md`](WORKFLOW.md) → Session Cycles). Each is one Claude session's worth of work: the features + directives that fit under ~80% context. Log them here as lightweight notes; there is no Linear Cycle. Status is implied by recency: **Current · Previous**.

| Session | Milestone | Planned work (features + directives) | Status | Notes |
|---|---|---|---|---|
| _e.g. SC1_ | _1.0_ | _—_ | _—_ | _—_ |

## Features

A feature = one **Linear issue** = one PR = one Implement→Validate loop. Status values match Linear issue statuses: **Backlog · Todo · In Progress · In Review · Done · Cancelled**.

### Completed

**Capped to the active milestone.** Only features completed under the current milestone live here. When a milestone closes, its completed rows **roll off** — the durable record survives in Linear (Done issues), git history, and the [Releases](#releases) table below. This keeps a full read of this file cheap on resume; see [`WORKFLOW.md`](WORKFLOW.md) → Completed-table rolloff.

| Feature | Linear issue | Session Cycle | Milestone | Merged | PR |
|---|---|---|---|---|---|
| _none yet_ | | | | | |

### In Flight

| Feature | Linear issue | Session Cycle | Milestone | Branch | Status |
|---|---|---|---|---|---|
| _none yet_ | | | | | |

### Backlog

Pulled from Linear. The lead syncs the top of the backlog here at session-planning time for quick reference.

| Feature | Linear issue | Milestone | Priority |
|---|---|---|---|
| _none yet_ | | | |

## Releases

Tagged releases across all major lines. Cut via `/merge-pr` when a product milestone completes — tagging is never automatic. Strict semver; version = milestone name + Target tag (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). `V1.x` maintenance and `V2.x` releases coexist here; note the branch for maintenance tags.

| Version | Date | Major line | Milestone shipped | Branch | Notes |
|---|---|---|---|---|---|
| _e.g. v0.1.0_ | _—_ | _V1_ | _1.0 (MVP)_ | _main_ | _—_ |
| _e.g. v1.1.1_ | _—_ | _V1_ | _1.1 hotfix_ | _release/1.x_ | _maintenance while main carries V2_ |

## Decisions

The Decision Log lives alongside this file at [`DECISIONS.md`](DECISIONS.md) (under `process/`) — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
