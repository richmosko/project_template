---
name: setup-linear-team
description: One-time bootstrap that wires Linear into this project — confirms the shared Linear team (one per workspace), helps create this project's Initiative, seeds the eight `agent:<role>` labels, and caches IDs in `.claude/linear-team.json`. Run on the first session of a new project, or whenever the cache is missing. No arguments — interviews the user as needed.
---

# setup-linear-team

Bootstraps Linear for this project under the **shared-team model**: one Linear team for the whole workspace (free-tier-friendly), one **Initiative** per project (this repo), and labels for per-agent attribution.

## When to run

- First session of a freshly cloned project.
- Whenever `.claude/linear-team.json` is missing or invalid.
- If the user wants to switch this project to a different Initiative.

## Pre-flight

Verify the Linear MCP is connected by calling `mcp__claude_ai_Linear__list_teams`. If it fails:
- Surface the error.
- Point the user to claude.ai → settings → MCP → Linear (or their setup equivalent).
- Stop here.

## Steps

### 1. Resolve the shared Linear team

Call `mcp__claude_ai_Linear__list_teams`.

- **If exactly one team exists:** use it. Confirm with the user: "Using existing Linear team `<name>` (key: `<KEY>`) as the shared team for all your projects. Continue?"
- **If multiple teams exist:** present them via `AskUserQuestion` — "Which is the shared team for your projects?"
- **If zero teams exist:** direct the user:
  > Linear MCP doesn't support team creation directly. Go to Linear → Settings → Teams → New team. Suggested:
  >  - **Name:** `Projects` (or your handle, e.g. `Mosko`)
  >  - **Key:** 3–5 uppercase chars; will prefix all issue IDs (e.g. `PRJ-123`)
  > Once created, restart this skill.

### 2. Create or link this project's Initiative

Initiatives must be created in Linear's UI — neither creation nor listing is exposed by the current MCP.

Ask the user via `AskUserQuestion`:
- "Does this project already have a Linear Initiative?"
  - **Yes** → ask the user to paste the Initiative ID (visible in the Initiative URL, e.g. `linear.app/<workspace>/initiative/<id>`)
  - **No** → walk them through creating one:
    > Go to Linear → Initiatives → New initiative. Suggested:
    >  - **Name:** `<current directory basename, prettified>`
    >  - **Owner:** yourself
    >  - **Status:** `Planned`
    >  - **Target date:** leave blank — set during Plan phase once the milestone roadmap exists
    > Once created, paste the Initiative ID back here.

Capture: `initiativeId`, `initiativeName`.

### 3. Seed agent labels on the shared team

Check existing labels via `mcp__claude_ai_Linear__list_issue_labels` for this team. For each of the nine agent roles, create the label if missing via `mcp__claude_ai_Linear__create_issue_label`:

| Label | Suggested color |
|---|---|
| `agent:product-manager` | `#bb87fc` (purple) |
| `agent:ux-designer` | `#f2b94c` (amber) |
| `agent:architect` | `#4ea7fc` (blue) |
| `agent:secops` | `#eb5757` (red) |
| `agent:frontend-lead` | `#26b5ce` (cyan) |
| `agent:backend-lead` | `#5e6ad2` (indigo) |
| `agent:implementation-lead` | `#95a2b3` (slate) |
| `agent:qa-engineer` | `#4cb782` (green) |
| `agent:devops-engineer` | `#f59f00` (orange) |

These labels are how agents claim ownership of issues — the v1 attribution mechanism (see `WORKFLOW.md` for the OAuth upgrade path).

### 4. Write the cache

Create `.claude/linear-team.json`:

```json
{
  "teamId": "<uuid>",
  "teamKey": "PRJ",
  "teamName": "Projects",
  "initiativeId": "<uuid>",
  "initiativeName": "<this project's name>",
  "labelsSeeded": true,
  "linkedAt": "<absolute-date>"
}
```

The file is gitignored — each clone resolves its own cache.

### 5. Update MILESTONES.md

Fill the `## Project / Initiative` block with:
- Project name (use `initiativeName`)
- Linear Initiative (paste ID with a link, e.g. `[INIT-abc](linear.app/<workspace>/initiative/<id>)`)
- Status (`Planned` until Plan phase completes)
- Owner (the user)
- Target ship date (blank until Plan)
- Health (`On track` by default)

### 6. Seed the backlog (optional)

If the user is in Research/Plan phase with a draft PRD containing user stories:

> "Create one Linear issue per user story from `docs/PRD.html` now? They'll be created on team `<name>` without a parent Linear Project (milestones get assigned during Plan)."

If yes, walk PRD User Stories and for each call `mcp__claude_ai_Linear__save_issue` with:
- `team`: `<teamId>`
- `title`: the story text
- `description`: link back to PRD section
- `labels`: `agent:product-manager` (PM agent seeded these)

Issues attach to the Initiative implicitly via the team. When milestones are created as Linear Projects later, they get re-parented.

### 7. Confirm and finish

Print a summary:
- Shared team: `<name>` (`<KEY>`)
- Initiative: `<name>`
- Labels seeded: 9 of 9
- Issues seeded: N (if backlog seeded)

Suggest the next step:
- If PRD is empty → `/generate-prd`
- If ARCH not yet drafted → spawn the Plan team to draft `ARCH.html` and `SECURITY.html`; create Linear Projects (milestones) under the Initiative
- If implementation-ready → `/start-feature`

## Notes

- **Don't overwrite the cache** if it already exists with valid IDs — ask first.
- **Don't recreate labels** that already exist on the team.
- **Don't attempt to create teams or initiatives via MCP** — neither operation is exposed; direct the user to Linear's UI.
- **Shared-team model is intentional.** Linear's free tier caps you at 2 teams. Using one shared team across all your projects (with Initiatives differentiating them) keeps you well under the cap and shares the 250-active-issues budget across everything.
- **Linear cycles are team-wide.** All of your projects share the same sprint cadence. Plan cycle scope across projects accordingly.
