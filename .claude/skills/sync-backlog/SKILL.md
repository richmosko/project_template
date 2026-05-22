---
name: sync-backlog
description: Promotes the next batch of items from BACKLOG.md to Linear issues, in milestone FIFO order. Called at sprint-cycle boundaries during sprint planning, on demand by the user, or automatically by /start-feature when the requested feature is queued in BACKLOG.md. Honors the active-issue budget (won't create new issues past the 250-issue cap).
---

# sync-backlog

Promotes items from `BACKLOG.md` (overflow queue) into Linear issues. Default batch: "all items in the top milestone that fit under the active-issue budget."

## When to run

- **At sprint-cycle start**, during sprint planning. The lead promotes the next batch.
- **On demand**: "promote the next 5 items from backlog to Linear" or similar.
- **Implicitly by `/start-feature`** when the requested feature isn't in Linear yet but its row exists in BACKLOG.md.

## Inputs

- `$ARGUMENTS` — optional:
  - **empty** → promote all items from the top milestone in BACKLOG.md that fit budget
  - **integer** (e.g. `5`) → promote at most that many items, FIFO from the top
  - **milestone name** (e.g. `M1` or `M1 — MVP`) → promote items from that milestone only

## Pre-flight

- Read `.claude/linear-team.json` for `teamId` and `initiativeId`. Bail if missing → direct the user to `/setup-linear-team`.
- Read `BACKLOG.md`. Parse the milestone sections (`### Milestone: ...`) and their tables.
- Call `mcp__claude_ai_Linear__list_issues` filtered by `state != archived` to get the current active count.

## Budget check

| Active count | Behavior |
|---|---|
| `< 200` | Proceed normally. |
| `200–249` | Warn the user: "Linear has N active issues (cap is 250). Promotion may hit the cap." Offer: (a) continue with batch capped at headroom, (b) run `/cleanup-linear` first, (c) abort. |
| `≥ 250` | **Hard block.** Stop. Advise running `/cleanup-linear` before retrying. |

Cap the batch size at `250 − current` ("headroom") regardless of what the user asked for.

## Steps

### 1. Pick the batch

- Default: top milestone in BACKLOG.md (highest priority — first section in the file), all its items.
- If `$ARGUMENTS` is an integer, take that many from the top, FIFO across milestones.
- If `$ARGUMENTS` is a milestone name, restrict to that milestone.
- Apply the headroom cap from the budget check.

### 2. Confirm with user

Show a compact list:

```
About to promote 5 items to Linear:
- [M1] As a user, I want to log in via Google (P0)
- [M1] As a user, I want to reset my password (P1)
- [M1] As a user, I want to update my profile (P1)
- [M1] As a user, I want to delete my account (P2)
- [M1] As a user, I want to export my data (P2)

Proceed? [Y/n]
```

Don't proceed silently.

### 3. Create the Linear issues

For each item in the confirmed batch, call `mcp__claude_ai_Linear__save_issue` with:

- `team`: from `.claude/linear-team.json`
- `title`: the item's title
- `description`: source reference + any notes (e.g. "Source: PRD §4.1\n\nNotes: ...")
- `labels`: `agent:product-manager` (these came from the PRD; PM agent attribution)
- `project`: the Linear Project ID for the parent milestone, if one exists. If not, leave unset (issue attaches at team level, still rolls up to the Initiative).

Capture the new Linear issue IDs as you go.

### 4. Remove the promoted rows from BACKLOG.md

Edit `BACKLOG.md`: delete the rows corresponding to promoted items from their milestone table. Preserve everything else (other milestones' items, the "How this file works" section, the Sync log).

If a milestone's table is now empty, leave the empty section in place — the structure tells future syncs there are no items in that milestone right now.

### 5. Append to the Sync log

Append a single line to `## Sync log` at the bottom of `BACKLOG.md`:

```
- <YYYY-MM-DD>: Promoted <N> items to Linear (<context>) — issues <FIRST-ID> through <LAST-ID>
```

Where `<context>` is one of: `"Sprint <N> planning"`, `"on-demand"`, or `"auto from /start-feature"`.

If the new IDs aren't contiguous (rare but possible), list them as a comma-separated list instead of "through".

### 6. Confirm to user

Print a summary:

```
Promoted: 5 items
New Linear issues: PRJ-101, PRJ-102, PRJ-103, PRJ-104, PRJ-105
Remaining in BACKLOG.md: 12 items
Active Linear count: now 187/250
```

If active count is now > 200 (80% of cap), suggest: "Consider running `/cleanup-linear` to archive Done issues before the next sync."

## Failure modes

- **BACKLOG.md missing**: report; suggest `/setup-linear-team` to scaffold one, or create manually.
- **BACKLOG.md malformed**: report which section couldn't be parsed; ask the user to fix.
- **Linear at cap**: hard block; advise `/cleanup-linear` first.
- **Partial failure mid-batch** (some `save_issue` calls succeed, others fail): report partial progress, list which items were promoted and which weren't, and tell the user the failed rows are **still in BACKLOG.md** so a retry won't double-create.
- **No items match the filter**: report cleanly ("Milestone M2 has no queued items"); suggest checking BACKLOG.md or relaxing the filter.
