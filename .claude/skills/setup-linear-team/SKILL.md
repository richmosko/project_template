---
name: setup-linear-team
description: One-time bootstrap that wires Linear into this project — confirms the shared Linear team, creates this project's Initiative via MCP, seeds the nine `agent:<role>` labels, seeds first-milestone stories to Linear with overflow to `BACKLOG.md`, and caches IDs in `.claude/linear-team.json`. Run on the first session of a new project, or whenever the cache is missing. No arguments — interviews the user as needed.
---

# setup-linear-team

Bootstraps Linear for this project under the **shared-team model**: one Linear team for the whole workspace (free-tier-friendly), one **Initiative** per project (this repo), labels for per-agent attribution, and a tiered overflow system to keep active issues under the 250-issue cap.

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

### 2. Create or link this project's Initiative (via MCP)

The Linear MCP now exposes Initiative operations: `mcp__claude_ai_Linear__list_initiatives`, `get_initiative`, `save_initiative`.

- Call `list_initiatives` to see if an Initiative already exists for this project.
- Present results via `AskUserQuestion`:
  - **Existing initiative matches this project name** → use it; capture `initiativeId`.
  - **Link to a different existing initiative** → user picks; capture `initiativeId`.
  - **Create a new one** (default) → walk through inputs:
    - Name: prettified version of the current directory basename (e.g. `project_template` → `Project Template`)
    - Owner: the user (typically `me` / current Linear user)
    - Status: `Planned` (becomes `Active` when first feature work starts; `Completed` when project ships)
    - Target date: leave blank until Plan phase fills it
    - Description: one-line description from `CLAUDE.md` if available
  - Confirm with user, then call `save_initiative` with these fields. Capture the returned `initiativeId` and `initiativeName`.

If `save_initiative` fails (permissions, rate limit, MCP error), fall back to the manual-UI path:
> Couldn't create via MCP — please create manually at Linear → Initiatives → New initiative with the inputs above. Paste the Initiative ID back here.

### 3. Seed agent labels on the shared team

Check existing labels via `mcp__claude_ai_Linear__list_issue_labels` for this team. For each of the nine agent roles, create the label if missing via `mcp__claude_ai_Linear__create_issue_label`:

| Label | Suggested color |
|---|---|
| `agent:product-manager` | `#bb87fc` (purple) |
| `agent:ux-designer` | `#f2b94c` (amber) |
| `agent:architect` | `#4ea7fc` (blue) |
| `agent:seceng` | `#eb5757` (red) |
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

### 5. Update MILESTONES.md → Project / Initiative

Fill the `## Project / Initiative` block with:
- Project name (use `initiativeName`)
- Linear Initiative (paste ID with a link, e.g. `[INIT-abc](https://linear.app/<workspace>/initiative/<id>)`)
- Status (`Planned` until Plan phase completes)
- Owner (the user)
- Target ship date (blank until Plan)
- Health (`On track` by default)

### 6. Seed M0 + M1 process milestones as Linear projects

The template ships MILESTONES.md with two **process milestones** in the Roadmap: M0 (Bootstrap & Research) and M1 (Plan). These give Research/Plan work the same Linear-tracked visibility that product milestones get. Create both as Linear projects under the Initiative so Research/Plan sub-tasks can flow as Linear issues.

For each, call `mcp__claude_ai_Linear__save_project`:

| # | Name | State | Linked initiative | Description |
|---|---|---|---|---|
| M0 | `M0 — Bootstrap & Research` | `started` | `<initiativeId>` | "Definition of done: PRD v1 approved; user stories enumerated; M2+ scope sketched in PRD §9." |
| M1 | `M1 — Plan` | `planned` | `<initiativeId>` | "Definition of done: ARCH + SECURITY approved; M2+ Roadmap rows populated; first sprint planned." |

Capture both `projectId` values; cache them in `.claude/linear-team.json` under a new `processMilestones` key:

```json
{
  …existing keys…,
  "processMilestones": {
    "m0": "<project-id>",
    "m1": "<project-id>"
  }
}
```

Then update the M0 + M1 rows in `MILESTONES.md` → Roadmap with the actual Linear project IDs (replacing the `LIN-XXX` placeholders).

If the user subdivides M0 or M1 later (e.g. `M0a`/`M0b`), they'll create additional Linear projects manually and add rows to the Roadmap — the template's two seeded rows are the floor, not a cap.

### 7. Seed the backlog with tiered overflow (optional)

If the user is in Research/Plan phase with a draft PRD containing user stories, run the **tiered seeding** flow to keep Linear's active-issue count under 200 (80% of cap):

**a. Parse PRD user stories.** Read `docs/PRD/index.html` § User Stories. Group stories by their target milestone (if the PRD has a Timeline / Milestones section). If milestones aren't yet defined, treat everything as "M1 — to be planned" for now.

**b. Check current Linear active-issue count.** Call `mcp__claude_ai_Linear__list_issues` filtered by `state != archived`. Note the count; the goal is to end below 200.

**c. Split the seeding:**

- Stories in the **first milestone** → create as Linear issues (immediately actionable), subject to the budget cap.
- Stories in **all other milestones** → write to `BACKLOG.md` (overflow queue), grouped by milestone.

Show the split to the user before writing:

```
Proposed seeding:
  - 6 stories from M1 → Linear (immediate)
  - 9 stories from M2 → BACKLOG.md (overflow; promoted later via /sync-backlog)
  - 4 stories from M3 → BACKLOG.md

After seeding: Linear at 6/250 active.

Proceed? [Y/n]
```

**d. Create Linear issues** for the first-milestone batch. For each, call `mcp__claude_ai_Linear__save_issue` with:
- `team`: `<teamId>`
- `title`: the story text
- `description`: link back to PRD section
- `labels`: `agent:product-manager` (PM agent seeded these)
- `project`: the Linear Project for the milestone, if it exists; otherwise unset (attaches at team level, still rolls up to the Initiative)

**e. Write to BACKLOG.md** for the remainder. If `BACKLOG.md` doesn't exist yet, create it with the template structure (see existing `BACKLOG.md` for format). Each story becomes a row under its milestone heading:

```markdown
### Milestone: M2 — Onboarding polish (priority 2)
| Title | Priority | Source | Notes |
|---|---|---|---|
| As a user, I want to update my profile | P1 | PRD §4.5 | — |
```

**f. Append a Sync log entry** to BACKLOG.md indicating the initial seeding:

```
- <YYYY-MM-DD>: Initial seeding from PRD — 6 items to Linear (M1), 13 items queued in BACKLOG.md (M2–M3)
```

### 8. Confirm and finish

Print a summary:
- Shared team: `<name>` (`<KEY>`)
- Initiative: `<name>` (`<id>`)
- Process milestones seeded: M0, M1 (Linear projects)
- Labels seeded: 9 of 9
- Issues seeded to Linear: N (from milestone 1)
- Items queued in BACKLOG.md: M (from later milestones)
- Active Linear count: N/250

Suggest the next step:
- If PRD is empty → `/generate-prd`
- If ARCH not yet drafted → spawn the Plan team; create Linear Projects (milestones) under the Initiative
- If implementation-ready → `/start-feature`

Also remind the user (one-time advice on first run):
> **Enable Linear's auto-archive setting** for passive cleanup: Linear → Settings → Workflow → "Auto-archive after N days" (default 14). Compounds with `/cleanup-linear` to keep the active set lean.

## Notes

- **Don't overwrite the cache** if it already exists with valid IDs — ask first.
- **Don't recreate labels** that already exist on the team.
- **Don't attempt to create teams via MCP** — that operation isn't exposed; direct the user to Linear's UI.
- **Initiative creation IS now exposed** via `save_initiative` — use it instead of the manual UI path when possible.
- **Shared-team model is intentional.** Linear's free tier caps you at 2 teams. Using one shared team across all your projects (with Initiatives differentiating them) keeps you well under the cap and shares the 250-active-issues budget across everything.
- **Linear cycles are team-wide.** All of your projects share the same sprint cadence. Plan cycle scope across projects accordingly.
- **Tiered backlog is the cap-management strategy.** See `WORKFLOW.md` → Version control & Linear → "Free-tier issue-cap mitigation" for the full pattern.
