---
name: start-feature
description: Kicks off a feature — creates a feature branch, claims a Linear issue (promoting from process/BACKLOG.md if needed), runs a Linear active-issue budget check, posts the feature plan, spawns the Implement team, and updates process/MILESTONES.md. Use at the start of each Implement→Validate loop. Takes a Linear issue ID or process/BACKLOG.md row reference; if omitted, asks the user which to start.
---

# start-feature

Bootstraps one feature = one Implement→Validate loop = one PR. Features are the innermost work unit; they live inside sprints (Linear cycles), which live inside milestones (Linear projects).

## Inputs

- `$ARGUMENTS` — optional:
  - **Linear issue ID** (e.g. `ABC-123`) → use that issue directly
  - **Feature title** (or substring) → search both Linear and `process/BACKLOG.md`; promote from process/BACKLOG.md if found there
  - **empty** → list candidates from Linear + process/BACKLOG.md and ask the user to pick

## Steps

### 1. Resolve the feature source (Linear or process/BACKLOG.md)

If `$ARGUMENTS` looks like a Linear issue ID (e.g. matches `[A-Z]+-\d+`):
- Call `mcp__claude_ai_Linear__get_issue` to load it.

Otherwise:
- Search **Linear** via `mcp__claude_ai_Linear__list_issues` filtered by team + status in `[Todo, Backlog, In Progress]`.
- Search **`process/BACKLOG.md`** for matching rows (by title substring, FIFO across milestones).
- If `$ARGUMENTS` is empty: present a unified candidate list — Linear issues first (already promoted, ready to start), then process/BACKLOG.md entries (would need promotion) — and ask the user to pick.
- If the user picks a **process/BACKLOG.md entry**, go to **Step 1a (promote)** below.

### 1a. Promote from process/BACKLOG.md (only when feature isn't yet in Linear)

If the selected feature is in `process/BACKLOG.md` rather than Linear:

- Invoke `/sync-backlog 1` with the specific item to promote (or call its logic directly — same MCP path).
- Pass through the budget check (see Step 2 below) — if Linear is at cap, hard-block and route the user to `/cleanup-linear`.
- Once the promotion succeeds and a Linear issue ID exists, continue with Step 2 using that ID.

### 2. Linear active-issue budget check

Call `mcp__claude_ai_Linear__list_issues` filtered by `state != archived` for the team. Capture the count.

| Active count | Behavior |
|---|---|
| `< 200` | Proceed silently. |
| `200–249` | Warn the user: "Linear has N active issues (cap is 250 on free tier). Consider running `/cleanup-linear` after this feature to free space." |
| `250` | **Hard block.** Stop. Tell the user: "Linear is at the active-issue cap. Run `/cleanup-linear` before starting a new feature." |

The budget check applies whether the feature came from Linear or was just promoted from process/BACKLOG.md.

### 3. Sanity-check phase

Read `process/MILESTONES.md` → `## Current Phase`. If we're not in `Implement`, ask the user: "We're in <phase>. Confirm starting a feature anyway?" Don't proceed silently.

### 4. Create the branch

```bash
git checkout main
git pull --ff-only
git checkout -b feature/<issue-id>-<kebab-slugified-title>
```

Slug rule: lowercase, ASCII, hyphens; max 50 chars total branch length.

### 5. Update Linear

- Set the issue's status to "In Progress".
- Add a comment: "Feature started. Branch: `feature/<issue-id>-<slug>`. Lead: <main-session-user>."

### 6. Post the feature plan

Drop a markdown block in the conversation with:
- Issue title and link
- Parent sprint (Linear cycle) and milestone (Linear project)
- Acceptance criteria (parsed from the Linear issue description)
- Proposed approach (high-level — implementation leads detail it later)
- Estimated I→V loop duration
- Current Linear active-issue count (from Step 2) so the user sees budget context

Ask the user: "Confirm this plan? Then we'll spawn the Implement team."

### 7. Spawn the Implement team

After user confirmation:
- "Create an agent team for the Implement phase" — roster comes from the project configuration in `process/WORKFLOW.md` (active implementation leads + `qa-engineer`).
- Pass the issue ID and acceptance criteria to all teammates via `SendMessage`.
- qa-engineer goes first — they write the failing acceptance test.

### 8. Create the anchor task on the shared task list

Following the anchor-task pattern in `process/WORKFLOW.md` → Team coordination:

- Create one **anchor task** mirroring the Linear issue:
  - **Title:** feature title (same as the Linear issue)
  - **Description:** the acceptance criteria, verbatim
  - **Owner:** `qa-engineer` (TDD starts with the failing test)
- Teammates then post subtasks underneath as work flows (e.g. `backend-lead` posts "implement endpoint" with `blockedBy: <anchor>`).
- Don't pre-populate every subtask — let the team self-organize via `blockedBy` chains as they pick up work.

### 9. Update process/MILESTONES.md

Set the `## Active Feature` block:
- Feature: the issue title
- Linear issue: ABC-123
- Milestone: parent Linear project name
- Sprint (Linear cycle): parent cycle name
- Branch: feature/abc-123-...
- Started: today's date (absolute)
- Goal: one sentence
- Status: "In Progress"

## Failure modes

- **Branch exists already**: ask the user if they want to switch to the existing branch (feature was interrupted) or pick a different feature.
- **Linear MCP not configured**: prompt to run `/setup-linear-team` first.
- **Uncommitted changes on main**: stop and ask the user to commit or stash first. Never auto-stash.
- **No active Linear cycle**: warn the user — features should normally belong to a sprint (cycle). Either create a cycle in Linear first, or proceed and flag the orphan feature in process/MILESTONES.md.
- **Linear at active-issue cap (250)**: hard-block; advise `/cleanup-linear` before retrying.
- **Requested feature not found in Linear or process/BACKLOG.md**: report; suggest checking the PRD or refining the search term.
- **Promotion from process/BACKLOG.md fails mid-flow**: report partial state (item was removed from process/BACKLOG.md but Linear issue creation failed); advise the user to manually restore the row to process/BACKLOG.md or retry.
