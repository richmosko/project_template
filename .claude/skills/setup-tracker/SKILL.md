---
name: setup-tracker
description: One-time bootstrap that scaffolds cairn (the file-based issue tracker) for this project — creates process/cairn/ with config.yml (ID prefix derived from the repo name, confirmed by the user once), seeds the founding major (V1) and the A/B definition milestones, optionally seeds PRD user stories as backlog issues, and sets the delivery-autonomy methodology for /drive. Run on the first session of a new project, or whenever process/cairn/ is missing. No arguments — interviews the user as needed.
---

# setup-tracker

Bootstraps **cairn** (the file-based issue tracker — see [`process/TRACKER.md`](../../../process/TRACKER.md)) for this project. Everything is local files in git: no MCP, no network, no account, no caps. The whole setup is a handful of file writes plus two questions.

## When to run

- First session of a freshly cloned project.
- Whenever `process/cairn/config.yml` is missing (the engine errors loudly and names this skill).
- Never twice: if `process/cairn/` already exists with a valid `config.yml`, stop and report — re-running would trample live issue data.

## Pre-flight

- `git rev-parse --git-dir` — must be a git repo (cairn leans on git for history/undo). If not, run the first-run checklist in `CLAUDE.md` first.
- `test -f process/cairn/config.yml` — if it exists, **stop**: "cairn is already set up (prefix `<X>`). Delete `process/cairn/` only if you truly want to start over."
- `test -x scripts/cairn/cairn` — the engine ships with the template; if missing, the clone is damaged or pre-cairn. Surface that.

## Steps

### 1. Derive and confirm the ID prefix

Derive a default from the repo directory name: take the first letter of each word (`project_template` → `PT`, `mosko-fintech` → `MF`); if that yields a single letter, take the first two letters uppercased. Then confirm with the user via `AskUserQuestion` (this is the one-time prompt ruled in `process/TRACKER.md` → Resolutions log #3):

> **Issue ID prefix** — issues will be numbered `<PREFIX>-1`, `<PREFIX>-2`, … and the prefix appears in branch names (`feature/pt-14-…`) and commit subjects (`feat(PT-14): …`).
> - `<derived>` (Recommended) — derived from the repo name
> - Pick my own — 2–5 uppercase ASCII letters

Validate a custom answer against `^[A-Z]{2,5}$`.

### 2. Scaffold the data directory

```bash
mkdir -p process/cairn/{issues,archive/issues,milestones,majors}
```

Write `process/cairn/config.yml` (committed — no secrets; every clone must agree on the prefix):

```yaml
prefix: <PREFIX>        # issue ID prefix; confirmed at setup
port: 8766              # board server port
board:
  columns: [backlog, todo, in-progress, in-review, done]
  swimlane: milestone   # milestone | none
```

### 3. Seed the founding major and definition milestones

Write `process/cairn/majors/<PREFIX>-V1.md` (PT-28: major ids are prefixed with the configured `<PREFIX>` — a bare `V1.md` fails `cairn check` on the very first lint run):

```markdown
---
id: <PREFIX>-V1
status: in-progress
owner: <user>
target_ship: null
health: on-track
---

Founding major line. Starts at MAJOR 0; the GA-designated milestone tags 1.0.0.
```

Write `process/cairn/milestones/<PREFIX>-A.md` and `<PREFIX>-B.md` (same PT-28 prefix requirement as the major above — `kind: process`, `major: <PREFIX>-V1`, `target_tag: null`, `ga: false`, status per phase — the `major:` key is load-bearing: the board derives an issue's major *through* its milestone, so omitting it hides every A/B issue from the V1 tab):

| id | name | status | Definition of done (body) |
|---|---|---|---|
| `<PREFIX>-A` | Bootstrap & Research | `in-progress` | PRD v1 approved; user stories enumerated; product-milestone scope sketched in PRD §9. |
| `<PREFIX>-B` | Plan | `planned` | ARCH + SECURITY approved; product milestones created in `milestones/` + GA designated; first session planned. |

Development milestones (`<PREFIX>-1.0`, `<PREFIX>-1.1`, …) are **not** seeded here — the `architect` creates them during Plan, flagging exactly one per major with `ga: true` (see `process/WORKFLOW.md` → Versioning scheme).

### 4. Seed PRD user stories as issues (optional)

If `docs/PRD/index.html` § User Stories has content, offer to seed each story as an issue. There is **no cap and no overflow tier** — every story becomes a real issue immediately:

```bash
scripts/cairn/cairn new "<story title>" --status backlog --milestone <<PREFIX>-A|<PREFIX>-B|null> --assignee product-manager
```

Show the count before writing ("Seed 14 stories from the PRD as backlog issues?"). Stories without a clear milestone get `--milestone` omitted (null = unassigned; the architect attaches them during Plan).

### 5. Choose the delivery-autonomy methodology

Ask via `AskUserQuestion` — list `stop-at-merge` first, labeled "(Recommended)":

> **How should the goal-driven loop (`/drive`) deliver features?**
> - **Stop at merge (Recommended)** — the loop builds one feature to an open, mergeable PR and stops. You review and merge.
> - **Self-merge within milestone** — the loop builds *and merges* every feature in a milestone (needs auto mode); the human gate moves to the milestone boundary.

Write the answer into `process/WORKFLOW.md` → *Project configuration* → **Delivery autonomy**, and append a `process/DECISIONS.md` entry (date, decision, why, approver).

### 6. Opt in to local token/cost telemetry (optional, off by default)

Ask via `AskUserQuestion`:

> **Enable local token/cost telemetry collection?** Feeds the dashboard's per-issue token/cost chart (PT-79) from Claude Code's own OTel export, through a local-only receiver (`scripts/cairn/otel_receiver.py` — no network egress, no account, off until this is confirmed). See `process/TRACKER.md` → "Ongoing collection".
> - **No (Recommended for now)** — skip; re-run this step later to opt in.
> - **Yes** — collect it.

If **No**: skip the rest of this step. `config.yml` carries no `otel_port` key and `.claude/settings.json`'s `env` block gets none of the telemetry keys — the receiver's `--ensure-running` (PT-81, H1) already declines quietly without `CLAUDE_CODE_ENABLE_TELEMETRY` set, so there is nothing else to guard.

If **Yes**, ask ONE follow-up via `AskUserQuestion` for the receiver's port:

> **Receiver port?**
> - `4318` (Recommended) — the OTLP/HTTP convention port.
> - Pick my own — any free local port.

Validate a custom answer is a bare integer in a sane ephemeral/user range (1024–65535). Then, from that **single** port answer — never asked or typed twice, which is exactly how PT-81's H3 hazard happened (the receiver's bound port and the exporter's destination configured independently, with nothing checking they agreed):

1. Add `otel_port: <port>` to `process/cairn/config.yml` (the file step 2 already wrote — append this key to it, don't regenerate the whole file).
2. Merge these five keys into `.claude/settings.json`'s top-level `env` object (additive — it already carries `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`/`CLAUDE_CODE_ENABLE_TODO_TOOLS`; don't replace the object, merge into it):

   ```json
   "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
   "OTEL_METRICS_EXPORTER": "otlp",
   "OTEL_LOGS_EXPORTER": "none",
   "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
   "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:<port>"
   ```

   `<port>` here is the exact same value just written as `otel_port` — construct the endpoint string from that one variable, don't re-type the number.
3. Confirm valid JSON after the merge (`python3 -c "import json; json.load(open('.claude/settings.json'))"`) before moving on.

The next fresh session's `SessionStart` hook starts the receiver automatically (H1's gate now passes); `python3 scripts/cairn/otel_receiver.py --status` reports whether it's running.

### 7. Lint, commit, confirm

```bash
scripts/cairn/cairn check        # must exit 0 on the freshly seeded tree
scripts/cairn/cairn ls           # show what was seeded
```

Commit the scaffold (via the current branch flow — `/start-doc-update` if nothing is open). Print a summary:

- Prefix: `<PREFIX>` · data dir: `process/cairn/`
- Seeded: `majors/<PREFIX>-V1.md`, `milestones/<PREFIX>-A.md`, `milestones/<PREFIX>-B.md`
- Issues seeded: N from PRD
- Delivery autonomy: `<choice>`
- Telemetry: `<on, port N | off>`
- Board: `/cairn` starts it at `http://localhost:8766/`

Suggest the next step: PRD empty → `/generate-prd`; ARCH pending → spawn the Plan team; implementation-ready → `/start-feature`.

## Failure modes

- **Not a git repo** — stop; point at the first-run checklist.
- **`process/cairn/config.yml` already exists** — stop; never overwrite live tracker data.
- **`cairn check` fails after seeding** — surface the lint output verbatim and fix the seed files before committing; never leave the tracker in a state its own linter rejects.
- **Invalid custom prefix** — re-ask; the format is load-bearing (IDs appear in branch names and commit subjects).
