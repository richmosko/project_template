# State

> Live dashboard of where the project is. Updated by the team-lead at every phase transition, feature completion, and release.
>
> **Durable work state lives in the tracker, not here.** Majors, milestones (the roadmap), and features are cairn artifacts under [`process/cairn/`](cairn/) — view them on the board (`/cairn`, `http://localhost:8766/`) or list them with `scripts/cairn/cairn ls`. This file keeps only what the tracker deliberately doesn't model: the current phase, the active feature pointer, and shipped releases. **No history accumulates here** — this file is auto-injected into every session, so it holds only current state; work history lives in the tracker (issue comments), the git log, and the PRs. (Major-line / Roadmap / Features tables dissolved into cairn — ruled 2026-08-19; the Session Cycles history table retired 2026-08-22 — see [`TEMPLATE_DECISIONS.md`](TEMPLATE_DECISIONS.md).)

## Current Phase

**Phase:** Template maintenance — this is the template repo itself; Research/Plan predate the ledger. Meta-work runs as Implement⇄Validate loops on the current maintenance milestone (see the board).  
**Started:** 2026-08-19 (cairn line of work)  
**Driver agent:** team-lead  
**Gate criteria:** _see [`WORKFLOW.md`](WORKFLOW.md)_

## Active Feature

A feature = one cairn issue = one PR = one Implement→Validate loop. Exists only during Implement phase. This is a pointer — the issue file (`process/cairn/issues/<ID>.md`) is the record.

| Field | Value |
|---|---|
| Feature | Receiver logs its own self-stop (registry drained, grace elapsed) — today it exits silently |
| Issue | PT-90 (cairn) |
| Milestone | PT-0.12.1 |
| Branch | `feature/pt-90-receiver-logs-self-stop` |
| PR | https://github.com/richmosko/project_template/pull/181 |
| Started | 2026-09-07 |
| Goal | The receiver writes one log line naming the trigger at its self-stop point of no return, and one when a registration cancels an armed grace window, both asserted by the existing tests. |
| Status | In Review |

## Releases

Full history, every tagged release with its notes, lives at [the GitHub Releases page](https://github.com/richmosko/project_template/releases) — this row is a pointer, not a log. Cut via `/merge-pr`; `/merge-pr` **replaces** this row (never appends) on every tag.

| Version | Date | Major line | Milestone shipped | Branch | Notes |
|---|---|---|---|---|---|
| v0.12.0 | 2026-09-05 | PT-V1 | PT-0.12 (telemetry attribution) — [release](https://github.com/richmosko/project_template/releases/tag/v0.12.0) | main | Published |

## Decisions

The Decision Log lives alongside this file at [`DECISIONS.md`](DECISIONS.md) (under `process/`) — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
