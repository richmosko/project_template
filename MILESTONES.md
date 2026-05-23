# Milestones & State

> Live ledger of where the project is. Updated by the team-lead at every phase transition, feature completion, sprint boundary, and decision.

## Project / Initiative

This project's overall effort. Mirrored to a Linear **Initiative** at the workspace level. Status values: **Planned · Active · Completed**. Health values: **On track · At risk · Off track**.

| Field | Value |
|---|---|
| Project name | _—_ |
| Linear Initiative | _LINEAR-INIT-XXX_ |
| Status | _Planned_ |
| Owner | _—_ |
| Target ship date | _—_ |
| Health | _On track_ |
| Notes | _—_ |

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
| Sprint (Linear cycle) | _—_ |
| Branch | _—_ |
| Started | _—_ |
| Goal | _—_ |
| Status | _—_ |

## Roadmap

Each milestone maps to a **Linear project** and contains one or more sprints. Status values match Linear project statuses: **Backlog · Planned · In Progress · Paused · Completed · Cancelled**.

**Two flavors:**
- **Process milestones** (M0, M1) track the Research and Plan phases themselves. They ship by default at bootstrap so the Roadmap is never empty. **Each can be subdivided** if a phase turns out to be complex (e.g. `M0a: PRD draft` → `M0b: PRD review & refinement`, or `M1a: Architecture` → `M1b: Security` → `M1c: Sprint planning`). Keep one Linear project per row.
- **Product milestones** (M2+) are the actual scope chunks of the product. Populated by the `architect` during M1 (Plan) — that's the work product of Plan.

| # | Milestone | Status | Gate | Linear Project | Notes |
|---|---|---|---|---|---|
| M0 | _Bootstrap & Research_ | _In Progress_ | _PRD locked_ | _LIN-XXX_ | Issues: PRD-drafting work (problem framing, user stories, NFRs, design considerations). |
| M1 | _Plan_ | _Planned_ | _ARCH + SECURITY locked, M2+ Roadmap rows populated, first sprint planned_ | _LIN-XXX_ | Issues: (a) Draft ARCH; (b) Draft SECURITY; (c) **Populate product milestones in this Roadmap** (V1.0, V1.1, etc.); (d) Plan first sprint. |
| _M2_ | _first product milestone — output of M1's "Populate product milestones" issue_ | _Planned_ | _—_ | _—_ | _—_ |

## Sprints (Linear cycles)

Sprints are time-bounded delivery cadences (~1–2 weeks). Each sprint maps to a **Linear cycle**, sits inside a milestone, and groups several features. Status is implied by date: **Upcoming · Current · Previous**.

| Sprint | Milestone | Start | End | Features in sprint | Status | Notes |
|---|---|---|---|---|---|---|
| _e.g. S1_ | _M1_ | _—_ | _—_ | _—_ | _—_ | _—_ |

## Features

A feature = one **Linear issue** = one PR = one Implement→Validate loop. Status values match Linear issue statuses: **Backlog · Todo · In Progress · In Review · Done · Cancelled**.

### Completed

| Feature | Linear issue | Sprint | Milestone | Merged | PR |
|---|---|---|---|---|---|
| _none yet_ | | | | | |

### In Flight

| Feature | Linear issue | Sprint | Milestone | Branch | Status |
|---|---|---|---|---|---|
| _none yet_ | | | | | |

### Backlog

Pulled from Linear. The lead syncs the top of the backlog here at the start of each sprint for quick reference.

| Feature | Linear issue | Milestone | Priority |
|---|---|---|---|
| _none yet_ | | | |

## Releases

Tagged releases of the project. Cut via `/merge-pr` when a milestone completes — tagging is never automatic.

| Version | Date | Milestone shipped | Notes |
|---|---|---|---|
| _e.g. v0.1.0_ | _—_ | _M1_ | _—_ |

## Decisions

The Decision Log lives in [`DECISIONS.md`](DECISIONS.md) at the repo root — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
