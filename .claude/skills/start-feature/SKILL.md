---
name: start-feature
description: Kicks off a feature — creates a feature branch, claims a cairn issue (status → in-progress), posts the feature plan, spawns the Implement team, and updates process/STATE.md. Use at the start of each Implement→Validate loop. Takes a cairn issue ID (e.g. PT-14) or a title substring; if omitted, lists candidates from the tracker and asks the user which to start.
---

# start-feature

Bootstraps one feature = one Implement→Validate loop = one PR. Features are the innermost work unit; they live inside milestones (`process/cairn/milestones/`), which live inside majors (`process/cairn/majors/`). Session Cycles group the features you attempt in one working session — a heuristic, not a tracker layer.

The tracker is **cairn** — files under `process/cairn/`, worked via the `scripts/cairn/cairn` CLI (spec: [`process/TRACKER.md`](../../../process/TRACKER.md)). There is no issue cap, no budget check, and no promotion tier — those were Linear-era scar tissue.

## Inputs

- `$ARGUMENTS` — optional:
  - **cairn issue ID** (matches `[A-Z]{2,5}-\d+`, e.g. `PT-14`) → use that issue directly
  - **Title substring** → search the tracker for it
  - **empty** → list candidates and ask the user to pick

## Steps

### 1. Resolve the feature

If `$ARGUMENTS` is an issue ID:

```bash
scripts/cairn/cairn show <ID>
```

Otherwise list candidates (statuses that can start: `backlog`, `todo`, `in-progress` for resume):

```bash
scripts/cairn/cairn ls --status todo
scripts/cairn/cairn ls --status backlog
```

Filter by the title substring if one was given; if `$ARGUMENTS` was empty, present the candidates (todo first — they're queued for this milestone) and ask the user to pick. Read the chosen issue in full with `cairn show <ID>` — the description body carries the acceptance criteria.

### 2. Sanity-check phase

Read `process/STATE.md` → `## Current Phase`. If we're not in `Implement`, ask the user: "We're in <phase>. Confirm starting a feature anyway?" Don't proceed silently.

### 3. Create the branch

```bash
git checkout main
git pull --ff-only
git checkout -b feature/<id-lowercase>-<kebab-slugified-title>
```

Slug rule: lowercase, ASCII, hyphens; max 50 chars total branch length. (`PT-14` → `feature/pt-14-google-oauth`.)

### 4. Claim the issue

```bash
scripts/cairn/cairn set <ID> status=in-progress
scripts/cairn/cairn comment <ID> --author team-lead --body - <<'EOF'
Feature started. Branch: `feature/<id>-<slug>`.
EOF
```

These edits dirty the working tree on the feature branch and merge with the feature's PR — the tracker state change and the work that caused it land atomically.

### 5. Post the feature plan

Drop a markdown block in the conversation with:
- Issue ID + title
- Parent milestone (from the issue's `milestone:` field) and major (via the milestone file's `major:` field)
- Acceptance criteria (from the issue body)
- Proposed approach (high-level — implementation leads detail it later)
- Estimated I→V loop duration

Ask the user: "Confirm this plan? Then we'll spawn the Implement team."

### 6. Spawn the Implement team

After user confirmation:
- "Create an agent team for the Implement phase" — roster comes from the project configuration in `process/WORKFLOW.md` (active implementation leads + `qa-engineer`).
- Pass the issue ID and acceptance criteria to all teammates via `SendMessage`. Teammates read the issue file directly (`process/cairn/issues/<ID>.md`) — no payload relay needed.
- qa-engineer goes first — they write the failing acceptance test.

### 7. Create the anchor task on the shared task list

**Skip this step if the session lacks the Task tools** (`TaskCreate` etc. — session-gated by model; check your own tool set) and coordinate via lead-mediated `SendMessage` dispatch instead — see `process/WORKFLOW.md` → Task-tool availability & the degraded mode.

Following the anchor-task pattern in `process/WORKFLOW.md` → Team coordination:

- One **anchor task** mirroring the cairn issue: title = feature title, description = acceptance criteria verbatim, owner = `qa-engineer` (TDD starts with the failing test).
- Teammates post subtasks underneath via `blockedBy` chains as work flows. Don't pre-populate.

### 8. Update process/STATE.md

Set the `## Active Feature` block:
- Feature: the issue title
- Issue: `<ID>` (cairn)
- Milestone: the issue's milestone
- Session Cycle: the current session's label (heuristic; e.g. `SC3`)
- Branch: `feature/<id>-<slug>`
- Started: today's date (absolute)
- Goal: one sentence
- Status: "In Progress"

## Failure modes

- **Branch exists already** — ask the user: switch to it (interrupted feature) or pick a different feature.
- **cairn not set up** (`cairn` errors about a missing `config.yml`) — run `/setup-tracker` first.
- **Uncommitted changes on main** — stop and ask the user to commit or stash. Never auto-stash.
- **Issue has no milestone** — warn; either attach it (`cairn set <ID> milestone=<m>`) with the user's ok, or proceed and flag the orphan in the feature plan.
- **Requested issue not found** — `cairn ls` the likely statuses and report; suggest checking the PRD or creating it (`cairn new "<title>" --status todo --milestone <m>`).
- **Issue already `in-progress` with a different branch** — surface the mismatch; the tracker or the tree is stale, and the user decides which.
