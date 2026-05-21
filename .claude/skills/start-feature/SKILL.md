---
name: start-feature
description: Kicks off a feature — creates a feature branch, claims a Linear issue, posts the feature plan, and updates MILESTONES.md. Use at the start of each Implement→Validate loop. Takes a Linear issue ID (e.g. ABC-123) as argument; if omitted, asks the user which issue to start.
---

# start-feature

Bootstraps one feature = one Implement→Validate loop = one PR. Features are the innermost work unit; they live inside sprints (Linear cycles), which live inside milestones (Linear projects).

## Inputs

- `$ARGUMENTS` — Linear issue ID (e.g. `ABC-123`). Optional; if missing, list candidate issues and ask the user to pick.

## Steps

### 1. Resolve the Linear issue

If `$ARGUMENTS` is empty:
- Read `.claude/linear-team.json` to get the team ID.
- Use `mcp__claude_ai_Linear__list_issues` filtered by team + status="Todo" or "Backlog".
- Prefer issues attached to the **current Linear cycle** (active sprint). Show the cycle name in the candidates.
- Present the top 10 to the user via `AskUserQuestion`.

If `$ARGUMENTS` is set:
- `mcp__claude_ai_Linear__get_issue` to load the issue details.

### 2. Sanity-check phase

Read `MILESTONES.md` → `## Current Phase`. If we're not in `Implement`, ask the user: "We're in <phase>. Confirm starting a feature anyway?" Don't proceed silently.

### 3. Create the branch

```bash
git checkout main
git pull --ff-only
git checkout -b feature/<issue-id>-<kebab-slugified-title>
```

Slug rule: lowercase, ASCII, hyphens; max 50 chars total branch length.

### 4. Update Linear

- Set the issue's status to "In Progress".
- Add a comment: "Feature started. Branch: `feature/<issue-id>-<slug>`. Lead: <main-session-user>."

### 5. Post the feature plan

Drop a markdown block in the conversation with:
- Issue title and link
- Parent sprint (Linear cycle) and milestone (Linear project)
- Acceptance criteria (parsed from the Linear issue description)
- Proposed approach (high-level — implementation leads detail it later)
- Estimated I→V loop duration

Ask the user: "Confirm this plan? Then we'll spawn the Implement team."

### 6. Spawn the Implement team

After user confirmation:
- "Create an agent team for the Implement phase" — roster comes from the project configuration in `WORKFLOW.md` (active implementation leads + `qa-engineer`).
- Pass the issue ID and acceptance criteria to all teammates via `SendMessage`.
- qa-engineer goes first — they write the failing acceptance test.

### 7. Create the anchor task on the shared task list

Following the anchor-task pattern in `WORKFLOW.md` → Team coordination:

- Create one **anchor task** mirroring the Linear issue:
  - **Title:** feature title (same as the Linear issue)
  - **Description:** the acceptance criteria, verbatim
  - **Owner:** `qa-engineer` (TDD starts with the failing test)
- Teammates then post subtasks underneath as work flows (e.g. `backend-lead` posts "implement endpoint" with `blockedBy: <anchor>`).
- Don't pre-populate every subtask — let the team self-organize via `blockedBy` chains as they pick up work.

### 8. Update MILESTONES.md

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

- **Branch exists already**: ask the user if they want to switch to the existing branch (feature was interrupted) or pick a different issue.
- **Linear MCP not configured**: prompt to run `/setup-linear-team` first.
- **Uncommitted changes on main**: stop and ask the user to commit or stash first. Never auto-stash.
- **No active Linear cycle**: warn the user — features should normally belong to a sprint (cycle). Either create a cycle in Linear first, or proceed and flag the orphan feature in MILESTONES.md.
