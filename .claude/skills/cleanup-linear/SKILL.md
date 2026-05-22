---
name: cleanup-linear
description: Bulk-archives Done Linear issues to free space under the 250-active-issue free-tier cap. Use when /sync-backlog warns about active count approaching cap, when /start-feature is hard-blocked, at milestone close as hygiene, or periodically on long-running projects. Reports before/after counts.
---

# cleanup-linear

Explicitly archives **Done** issues on the shared Linear team to keep the active-issue count under the free-tier cap.

Linear's workspace setting can auto-archive Done issues after a delay (default 14 days). This skill is for **explicit, on-demand archiving** — useful when:

- `/sync-backlog` warned that active count is approaching cap.
- `/start-feature` hard-blocked due to the cap.
- You just closed a milestone and want to free space immediately.
- You disabled Linear's auto-archive setting.

## Inputs

- `$ARGUMENTS` — optional filter:
  - **empty** → archive all Done issues on the shared team
  - **milestone name** (e.g. `M1`) → archive Done issues in that Linear Project only
  - **sprint name** (e.g. `Sprint 3`) → archive Done issues from that Linear cycle
  - **age** (e.g. `30d`, `2w`) → archive Done issues whose completed date is older than the threshold

## Pre-flight

- Read `.claude/linear-team.json` for `teamId`. Bail if missing → direct user to `/setup-linear-team`.

## Steps

### 1. List candidate issues

Call `mcp__claude_ai_Linear__list_issues` filtered by:
- `team`: from cache
- `state`: `Done` or `Completed` (whichever Linear uses for the team's workflow)
- Apply any `$ARGUMENTS` filter on top

Capture the matching count and the first 5 titles for the preview.

### 2. Preview and confirm

Print:

```
Found 23 Done issues matching your filter.

Sample (first 5):
- PRJ-87  Add login form
- PRJ-91  Wire password reset email
- PRJ-94  Add session timeout
- PRJ-97  Add OAuth provider
- PRJ-102 Add 2FA opt-in

Active count: 218 → 195 after archive

Archive these 23 issues? [Y/n]
```

Don't proceed silently. Archiving is reversible (un-archive in Linear UI) but bulk-undo is friction.

### 3. Archive

For each candidate, archive via the Linear MCP. The current MCP doesn't expose a dedicated archive operation; the closest path is `mcp__claude_ai_Linear__save_issue` with an archived state update. **If the MCP rejects the operation:**

- Surface the failure with the specific error message.
- Fall back: instruct the user to bulk-archive via Linear's UI — Linear → filter by state=Done → select all → right-click → Archive.
- Don't pretend success.

### 4. Report

Print:

```
Archived: 23 issues
Active count: now 195/250 (was 218)
Headroom: 55 issues
```

If `/sync-backlog` was queued or pending: suggest re-running it now that space is freed.

## Failure modes

- **No Done issues match filter**: report cleanly; suggest relaxing the filter or checking the workflow state names Linear uses for this team.
- **MCP doesn't expose archive**: surface the gap clearly; provide the UI-based fallback instructions.
- **Partial archive failure**: report which IDs succeeded vs failed; un-archived ones remain active.

## Notes

- This is complementary to Linear's workspace **Auto-archive after N days** setting (Settings → Workflow). The auto-archive runs passively; this skill is for explicit hygiene when you don't want to wait.
- Archiving is **non-destructive** — issues stay in Linear, just out of the active count and most filters. Un-archive any time via Linear's UI.
- Don't archive issues in non-terminal states (Todo, In Progress, In Review). The filter is `state == Done` for a reason; overriding it can hide in-flight work.
