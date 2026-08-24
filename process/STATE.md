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
| Feature | _—_ |
| Issue | _—_ |
| Milestone | _—_ |
| Branch | _—_ |
| Started | _—_ |
| Goal | _—_ |
| Status | _—_ |

## Releases

Tagged releases across all major lines. Cut via `/merge-pr` when a product milestone completes — tagging is never automatic. Strict semver; version = milestone name + its `target_tag` (see [`WORKFLOW.md`](WORKFLOW.md) → Versioning scheme). `V1.x` maintenance and `V2.x` releases coexist here; note the branch for maintenance tags.

| Version | Date | Major line | Milestone shipped | Branch | Notes |
|---|---|---|---|---|---|
| v0.7.1 | 2026-08-24 | PT-V1 | PT-0.7.1 (board + archive follow-ups) | main | Draft — [release](https://github.com/richmosko/project_template/releases/tag/v0.7.1). 7 issues, PRs #109–#115: ga-cap lint marks archived siblings (PT-47), archived badge on lane headers / major tabs / record drawer (PT-48), `archive/issues/` layout + `cairn migrate archive-issues` with this repo's 43 archived issues migrated as git renames (PT-50), stale board-server detection — engine fingerprint in the payload, persistent banner, `/cairn` auto-restart (PT-49), milestone/major cards editable + comments via new `POST /api/record/<id>` + `cairn comment` on any record (PT-51), then two pre-tag roll-ins (Mosko): legacy archive read leg deleted with a `cairn new` allocation guard (PT-52), `_git_mv_or_rename` nested-relative-path fix (PT-53). **BREAKING for downstream template instances:** the engine no longer reads flat `archive/*.md` — run `cairn migrate archive-issues` on upgrade; until then flat files are invisible, `cairn check` fails naming the count + command, and `cairn new` refuses to allocate. Board/CLI otherwise unaffected. |
| v0.7.0 | 2026-08-24 | PT-V1 | PT-0.7.0 (milestone/major lifecycle + board surfaces) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.7.0). 10 issues, PRs #94–#102: statusLabel fallback (PT-37), lifecycle — unified done vocabulary + `cairn migrate lifecycle-status` + `cairn set` on records + archive for milestones/majors with never-sweep-under-live preconditions (PT-39), setup-tracker Day-0 prefixed-id fix live since v0.6.1 (PT-45), board.columns + board.swimlane actually consumed (PT-38), Show-archived toggle + 403 on archived HTTP mutation (PT-42), archived-record status lint (PT-46), viewable milestone/major cards + status indicators (PT-40), progress strip retired into lane headers with git-tag release chips (PT-44, closes PT-43's 0/0), major naming Option A + ga-lint (PT-41). **BREAKING (lint-only) for downstream template instances:** old `completed`/`active` record statuses fail `cairn check` until `cairn migrate lifecycle-status` runs — one command, previewable via --dry-run; board/CLI otherwise unaffected. Migration note: hand-quoted frontmatter scalars are unquoted (representation-only, verified no data change) — diff noise, not data loss. |
| v0.6.2 | 2026-08-23 | PT-V1 | PT-0.6.2 (board follow-ups — trackpad + cancelled column) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.6.2). 3 issues, PRs #86/#87/#88: trackpad-overscroll pull-to-refresh adapter with quiet-gap momentum defense (PT-33), conditional cancelled column with honest counts via reference-identity enforcement (PT-35), cross-language column-list drift guard + Python single-sourcing (PT-36). Also first `cairn archive` run: 33 done issues swept to archive/ (exposed PT-43, filed to 0.7.0). |
| v0.6.1 | 2026-08-22 | PT-V1 | PT-0.6.1 (board roll-up + tracker-id follow-ups) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.6.1). 6 issues, PRs #72/#74/#75/#76/#78/#79: board default roll-up + ▼/▶ disclosure + containment cards (PT-29), localStorage view-state + expand/collapse-all (PT-30), touch pull-to-refresh with three-state outcome (PT-32), PT-prefixed major/milestone ids + `cairn migrate prefix-ids` (PT-28), /api/board 503s resolved as measured instrument artifact with server-log/harness/convention hardening (PT-34), polish bundle incl. third rehome gap fix (PT-31). **BREAKING (lint-only) for downstream template instances:** bare major/milestone ids fail `cairn check` until `cairn migrate prefix-ids` runs — one command, previewable via --dry-run; unmigrated repos otherwise function normally. |
| v0.6.0 | 2026-08-22 | V1 | 0.6 (tracker relations + milestone conventions) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.6.0). 3 features, PRs #61/#62/#63: letter-milestone convention A/B/C + check_repo id-shape lint (PT-27), sub-issue delivery — n/m badge, drawer nesting, cairn show children (PT-25), issue dependencies — blocked_by + dangling/self/cycle lint + board surfacing (PT-26). **BREAKING for downstream template instances:** no grandfather clause — a pre-0.6 repo carrying M0/M1 `kind: process` milestones fails `cairn check` until migrated (the error string carries the four-step recipe; also in TRACKER.md § Milestone ids). |
| v0.5.1 | 2026-08-20 | V1 | 0.5.1 (follow-ups) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.5.1). 4 issues, PRs #57/#58: board.js JS test harness (PT-22) + finish-feature gate-fix (PT-24), then cairn ls numeric sort (PT-21) + board.js Object.create(null) sets (PT-23). Closed the PT-3-driven coverage arc: board.js now has automated tests, and the "one expression written twice" duplication class is a standing Validate review criterion. |
| v0.5.0 | 2026-08-20 | V1 | 0.5 (polish) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.5.0). 7 features, PRs #47/#49–#55: anchor-task degraded-mode docs (PT-18), title-shape lint (PT-19), board names+collapse (PT-16), drawer markdown + pre-existing pr-link XSS fix (PT-4/PT-20), cairn snapshot (PT-2), multi-root read-only board (PT-3). Follow-ups deferred to 0.5.1: PT-21/22/23. |
| v0.4.0 | 2026-08-20 | V1 | 0.4 (hardening) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.4.0). 13 issues, PRs #34–#42: STATE.md rename, Linear removal, engine/board hardening, teammate coordination toolset, SSE live push. |
| v0.3.0 | 2026-08-20 | V1 | 0.3 (cairn) | main | Published — [release](https://github.com/richmosko/project_template/releases/tag/v0.3.0). cairn replaces Linear: spec #28, engine #29, skills migration #30, dogfood #31. |

## Decisions

The Decision Log lives alongside this file at [`DECISIONS.md`](DECISIONS.md) (under `process/`) — split out so this file stays compact for auto-loading. Append new entries there; conventions are documented in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
