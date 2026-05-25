# project_template

> A reusable Claude Code starter for running new projects with an AGILE-grounded workflow, a team of specialist Agents, and consistent artifacts — from PRD through release.

## What this is

This repo is a **meta-template**, not a product. Clone it (or use it as a GitHub template) to seed a new project with:

- a four-phase workflow (**Research → Plan → Implement ⇄ Validate**),
- nine specialist team-Agents (PM, UX, Architect, SecEng, two implementation leads + a generalist, QA, DevOps),
- doc-generation skills for PRD / Architecture / Security,
- workflow skills for branching, PR + Linear integration, releases,
- HTML doc templates with embedded Mermaid diagrams,
- a state ledger (`MILESTONES.md`), a separate append-only decision log (`DECISIONS.md`), and a backlog overflow queue (`BACKLOG.md`),
- **AGILE issue / milestone / sprint tracking via [Linear](https://linear.app)** — our project / milestone / sprint / feature hierarchy maps to Linear's Initiative / Linear-Project / Cycle / Issue primitives,
- session-management heuristics tuned for asynchronous solo development.

The goal: every new project starts with the same shape, so async hand-offs and context-window management are predictable.

## Workflow at a glance

```mermaid
flowchart LR
  R[Research] --> P[Plan]
  P --> I[Implement]
  I --> V[Validate]
  V -->|feature passed,<br/>next feature| I
  V -->|milestone complete,<br/>plan next milestone| P
  V -->|findings invalidate PRD| R
  V -->|project complete| done([Ship / Wind-down])
```

Implement ⇄ Validate is the inner loop at three scales: **feature → milestone → project**. Sprints (Linear cycles) are a team-wide cadence wrapper, not a loop scale. Full details in [`WORKFLOW.md`](WORKFLOW.md).

## What you get

**Workflow Agents** (`.claude/agents/`):

| Agent | Owns | Drives |
|---|---|---|
| `product-manager` | PRD | Research |
| `ux-designer` | wireframes, interaction design | late Research, Implement consult |
| `architect` | ARCH doc, system design | Plan |
| `seceng` | SECURITY doc, threat model, gating | Plan + Validate |
| `frontend-lead` | UI implementation | Implement |
| `backend-lead` | API / service implementation | Implement |
| `implementation-lead` | generalist (CLI / lib / ML / data) | Implement (non-web projects) |
| `qa-engineer` | tests, acceptance, release readiness | Validate (TDD entry-point) |
| `devops-engineer` | CI/CD, deploy, observability | Plan + Validate |

**Skills** (`.claude/skills/`):

- `/generate-prd [source]` — interview-driven PRD generation (chatprd.ai-grounded). Accepts optional path to an existing PRD artifact (markdown / HTML / PDF / Google Doc) for **import mode**: analyzes the legacy content, maps it to the AGILE framework, ports what fits, flags what doesn't.
- `/generate-archdoc [source]` — Architecture doc with Mermaid diagrams. Same import-mode support as `generate-prd` for legacy ARCH artifacts.
- `/generate-secdoc` — STRIDE-based threat model + controls
- `/refine-doc <PRD|ARCH|SECURITY>` — walks `docs/<DOC>/comments.md` (gitignored review sidecar), addresses each `## §<section-id>` comment in the matching HTML section, removes addressed comments as it goes. Composable with `/start-doc-update` → `/finish-doc-update` → `/merge-pr`. See WORKFLOW.md → Doc review loop.
- `/serve-docs [PRD|ARCH|SECURITY|stop|status]` — starts `scripts/serve-docs.sh` in the background under the Claude session (no separate terminal needed) so the inline comment widget activates in the HTML docs. Pass a doc name to also open it in the browser. Server is cleaned up automatically on `/exit`.

**Helpers** (`scripts/`):

- `scripts/serve-docs.sh` — local Python server (stdlib only) at `http://localhost:8765` that activates an **inline comment widget** in the HTML docs. Click `+ Comment` next to any section heading, type, save — the widget POSTs to the server which appends to `docs/<DOC>/comments.md`. Same format as hand-edited comments; both feed `/refine-doc`. See WORKFLOW.md → Doc review loop → Inline-authoring mode.
- `scripts/vendor-mermaid.sh` — downloads Mermaid to `docs/_assets/vendor/` for projects that can't rely on CDN access at doc-view time (see Mermaid loading section above).
- `/start-feature` — branch + Linear issue + budget check + Implement team spawn (also promotes from `BACKLOG.md` on demand)
- `/finish-feature` — commit, push, PR, link Linear, hand off to Validate
- `/start-doc-update <slug>` — kicks off a `phase/<phase>-<slug>` branch for non-feature doc edits (PRD/ARCH/SECURITY/WORKFLOW/etc.); no Linear issue, no implementation team
- `/finish-doc-update` — commit + push + open PR for a doc-update branch; no QA handshake (lead reviews directly)
- `/merge-pr` — gated team-lead merge after QA sign-off (features) or lead review (doc updates); squash-merges, archives, updates state. Alternative to human-review-and-merge via GitHub UI
- `/open-doc` — open HTML/Markdown docs in default viewer
- `/setup-linear-team` — wire Linear into a new project (one-time): links the shared team, creates this project's Initiative via MCP, seeds agent labels, seeds first-milestone stories to Linear and rest to `BACKLOG.md`
- `/setup-claude-deploy-key` — generate a per-repo passphrase-less SSH deploy key so Claude can push to GitHub without TTY-unlockable passphrases (one-time per repo)
- `/sync-backlog [count|milestone]` — promote items from `BACKLOG.md` to Linear in milestone-FIFO order. Called at sprint-cycle boundaries, on demand, or implicitly by `/start-feature` when a queued feature is requested
- `/cleanup-linear [filter]` — bulk-archive Done Linear issues to free space under the 250-active-issue free-tier cap; use when sync-backlog warns near cap or at milestone close

**Artifacts** (top level + `docs/`):

- `CLAUDE.md` — session-bootstrap context (loaded automatically)
- `WORKFLOW.md` — phases, roles, gates, team coordination
- `MILESTONES.md` — live state ledger (compact; auto-loaded)
- `DECISIONS.md` — append-only decision log (not auto-loaded; pulled in when historical context is needed)
- `BACKLOG.md` — overflow queue for Linear (items waiting to be promoted)
- `docs/PRD/index.html` — Product Requirements (HTML + Mermaid)
- `docs/ARCH/index.html` — Architecture + Infrastructure
- `docs/SECURITY/index.html` — Security + Compliance
- `docs/archive/` — stashed originals of imported PRD/ARCH artifacts
- `docs/_assets/` — shared CSS + Mermaid loader

## Roles

- **Principal** (you) — sets vision, makes gate decisions, authorizes Agents.
- **Team Lead** — the main Claude Code session. Coordinates teams, delegates, summarizes specialist output into executive language.
- **Agents** — nine specialists spawned per phase as Claude team-agents.

## Common project-specific extensions

The nine-Agent roster is the **floor, not the ceiling**. Some domains benefit from additional specialists. Spin up a new agent file in `.claude/agents/` (copying an existing one as a starting template) and document the addition in your project's `DECISIONS.md`. Examples that have come up in practice:

| Extension | When to add | What it owns |
|---|---|---|
| **`visual-designer`** | Trust-driven UI (fintech, healthcare, regulated builds) where visual polish is functional, not decorative. Distinct from the generic `ux-designer`. | Design tokens, typography, color, spacing. Palette-and-typography lock with the Principal. Flags missing components back to UX rather than designing around the gap. |
| **`compliance-officer`** | Regulated builds (HIPAA, SOC 2, PCI-DSS, FedRAMP) where compliance evidence isn't a side-effect of security work. | Compliance evidence trails, audit prep, control mapping, attestation packages. Distinct from the generic `seceng`. |
| **`data-pipeline-lead`** | ML / ETL / analytics projects with substantial data-engineering surface. | Ingestion, transformation, lineage, data quality. Distinct from the generic `implementation-lead`. |

These are **suggestions, not bundled assets** — the template doesn't ship the agent files for them. Adopt the role pattern; write the file when your project actually exercises the work.

## Customizing doc preview

The `/open-doc` skill routes by extension: `.html` → browser (Chrome → Safari fallback on macOS), `.md` → One Markdown app (if installed) with editor fallback. This works for most macOS users but can be swapped:

- **Why Chrome → Safari (not the system default)?** On macOS, LaunchServices can route `.html` files through MacVim, VS Code, or any other app the user accidentally set as default. Using `open -a "Google Chrome"` (with Safari as fallback) bypasses that and ensures HTML docs always render in a real browser.
- **Use a different default browser** (Firefox, Arc, Brave, etc.) → edit the `.html` route in `.claude/skills/open-doc/SKILL.md` step 2: change `"Google Chrome"` to `"Firefox"` / `"Arc"` / `"Brave Browser"` etc. Keep Safari as the fallback (it's always present on macOS).
- **Use a different Markdown viewer** (Bear, IDE preview, `mdcat`, `glow`) → edit the same SKILL.md and replace the `open-one-markdown` route with your tool of choice.
- **Headless / SSH session** → replace the `open -a` calls with a terminal-friendly viewer (`w3m -dump`, `lynx`, etc.) or a network-share path.
- **Project-specific viewer skill** → if your project needs a non-default workflow (e.g. opening every artifact through a specific tool chain), add a project-local skill alongside `/open-doc`. The template won't fight you.

## Quick start

### Use as a GitHub template

1. Click **Use this template** on GitHub → **Create a new repository**.
2. Clone your new repo locally and `cd` in.
3. Start a Claude Code session — `CLAUDE.md` will load automatically and walk through the [First-run / bootstrap checklist](CLAUDE.md#first-run--bootstrap).

### Or clone manually

```bash
gh repo create my-new-project --template richmosko/project_template --private --clone
cd my-new-project
claude
```

### First-run checklist (abridged — see [`CLAUDE.md`](CLAUDE.md))

1. `gh auth status` — confirm GitHub auth.
2. **`/setup-claude-deploy-key`** — generate a passphrase-less SSH key scoped to this repo, add it to GitHub as a deploy key with write access, and pin the repo's git to use it. Without this, Claude's `git push` will fail when your main SSH key is passphrase-protected.
3. **Enable GitHub branch protection on `main`** — Settings → Branches → Add rule → ✅ Require pull request before merging, ✅ Do not allow bypassing. This is the hard enforcement layer behind the workflow's "no direct pushes" rule.
4. Replace the project description placeholders in `CLAUDE.md`.
5. `/setup-linear-team` — link to your shared Linear team and create this project's Initiative.
6. Verify `teammateMode` in `.claude/settings.json` (default: `tmux` for split-pane).
7. Spawn the Research team: _"Create an agent team for the Research phase."_
8. `/generate-prd` — start the discovery interview.

## The 4-tier hierarchy (Linear mapping)

| Concept | Linear primitive |
|---|---|
| Project (overall effort, this repo) | **Initiative** |
| Milestone | Linear Project |
| Sprint (team-wide cadence) | Linear Cycle |
| Feature (one PR, one I↔V loop) | Linear Issue |

One Linear team is shared across **all** your projects (free-tier-friendly). Each project gets its own Initiative. Agent attribution rides on `agent:<role>` issue labels (v1 mechanism; OAuth agent actors are an upgrade path documented in `WORKFLOW.md`).

## Layout

```
.
├── CLAUDE.md                    auto-loaded session context
├── WORKFLOW.md                  phases, roles, gates, coordination
├── MILESTONES.md                live state + decision ledger
├── DECISIONS.md                 append-only project decisions (seed; you keep this)
├── BACKLOG.md                   Linear overflow queue (seed; you keep this)
├── TEMPLATE_DECISIONS.md        decisions about the template itself — DELETE on bootstrap
├── README.md                    this file
├── docs/
│   ├── PRD/index.html           product requirements (Research)
│   ├── ARCH/index.html          architecture (Plan)
│   ├── SECURITY/index.html      security (Plan + Validate)
│   ├── starting-prompt.md       original design notes (kept for posterity)
│   └── _assets/                 shared CSS + Mermaid loader
│   (each doc lives in its own subdir — add per-doc images / diagrams /
│    sub-pages alongside the index.html as the doc grows)
├── scripts/                     repo-level helpers (vendor-mermaid.sh, serve-docs.sh, …)
└── .claude/
    ├── settings.json            hooks, env, permissions, teammateMode
    ├── agents/                  9 specialist definitions
    └── skills/                  workflow + doc-gen skills
```

## Requirements

### Tooling

- **Claude Code v2.1.32 or later** — required for the experimental team-agents feature. Check with `claude --version`.
- **macOS or Linux shell** — workflow skills assume POSIX + standard CLI tools (`bash`/`zsh`, `git`, `gh`, `open`/`xdg-open`).
- **GitHub CLI** (`gh`) — authenticated to the account that will host your new project (`gh auth status` should succeed; `gh auth login` if not).
- **Git** — modern enough to support worktrees and standard branching.
- *(Optional)* **tmux or iTerm2** — required only for split-pane teammate mode (the default). Without one of these, switch `teammateMode` to `"in-process"` in `.claude/settings.json`.
- *(Optional)* **One Markdown** macOS app — nicer rendered viewing of `.md` files via the `open-one-markdown` skill. Falls back to your `$EDITOR` if not installed.

### Recommended (quality-of-life)

Not required, but strongly improve visibility while working alongside Claude Code:

- **[Oh My Zsh](https://ohmyz.sh/)** — Zsh framework with themes that surface **git branch + dirty/clean status** in your shell prompt. Makes it obvious at a glance whether you're on `main` vs a `feature/...` branch, and whether you have uncommitted changes. Install with the one-line curl on their site; pick a theme like `agnoster` or `robbyrussell` that shows git state.
- **Custom Claude Code statusline** — Claude Code can render a customizable bottom status line showing the model in use, context usage, session cost, and git status, driven by a script you provide (e.g. `~/.claude/statusline-command.sh`). See the [official walkthrough](https://code.claude.com/docs/en/statusline.md). **Easiest setup:** run `/statusline` inside Claude Code, describe what you want in natural language, and the setup agent generates the script and wires up `~/.claude/settings.json` for you.

- **Async notifications when Agents wait on you** — Critical when work is asynchronous and you've stepped away. Claude Code fires a `Notification` hook on permission prompts, idle waits, and gate decisions; wire it in `~/.claude/settings.json` to route the alert wherever. The hook receives JSON on stdin (`message`, `notification_type`, etc.) — scope it via the `matcher` field (e.g. `permission_prompt`, `idle_prompt`). Practical destinations:
  - **iTerm2 + macOS banner** — wire the hook to `osascript -e 'display notification "$msg" with title "Claude Code"'`. macOS Notification Center shows the banner whether or not iTerm2 has focus; respects Focus Mode. Enable iTerm2 → Settings → Profiles → Terminal → "Silence bell" off if you also want terminal-level signals. iTerm2's [Triggers](https://iterm2.com/documentation-triggers.html) feature can fire on output patterns independent of the hook.
  - **[`terminal-notifier`](https://github.com/julienXX/terminal-notifier)** (`brew install terminal-notifier`) — richer macOS notification UI than `osascript`; supports icons, sounds, click-through actions. Drop-in replacement in the hook command.
  - **[ntfy.sh](https://ntfy.sh/) / [Pushover](https://pushover.net/)** — HTTP push to your phone for true away-from-desk async alerts. Hook becomes a `curl` POST to their endpoint; no app/account setup beyond their free tiers.
  - **Slack or Discord webhook** — for team visibility or an audit trail of human-decision points. HTTP POST from the hook to an incoming-webhook URL.
  
  Reference: [Claude Code hooks docs](https://code.claude.com/docs/en/hooks.md). The `Notification` event is observability-only (no decision control), so the hook can't block Claude — it just alerts you.

### Claude Code configuration

The template **pre-sets** project-level config in `.claude/settings.json`:

| Setting | Value | Purpose |
|---|---|---|
| `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `"1"` | Enables team-agents (mailbox, shared task list, peer SendMessage). |
| `teammateMode` | `"tmux"` | Split-pane teammates; survives `/resume` (see [`CLAUDE.md`](CLAUDE.md) for mode trade-offs). |
| `hooks.SessionStart` | reads `MILESTONES.md` | Auto-surfaces current project state at session start. |
| `permissions.allow` | common read/git commands | Reduces permission prompts for routine ops. |

**Verify in your user-level config (`~/.claude/settings.json`):**

- That you haven't overridden `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` to `"0"`. If you have, the project-level setting will be honored, but expect surprise if you switch projects.
- That `teammateMode` aligns with your terminal — `"tmux"` requires tmux *or* iTerm2 with `it2` CLI; otherwise use `"in-process"`.

If you prefer to override anything per-project without committing, drop it in `.claude/settings.local.json` (gitignored).

### External integrations

- **Linear MCP** — connected at the workspace level (claude.ai → Settings → MCP → Linear, or equivalent). Required for `/setup-linear-team`, ticket sync, and Initiative/Project creation. **Free tier is fully supported.**
  - On first project, you'll be asked to create a shared Linear team and per-project Initiative manually in Linear's UI (these aren't exposed by the current MCP). The skill walks you through it.
  - Watch the **250-active-issues** free-tier cap — archive features aggressively at sprint boundaries.
- **Anthropic API access** — implicit via Claude Code itself; no additional config.

### Mermaid loading: CDN vs vendored

The HTML doc templates (`docs/PRD/index.html`, `docs/ARCH/index.html`, `docs/SECURITY/index.html`) load Mermaid via `docs/_assets/mermaid-init.js`. The template ships with the **CDN variant** — fetches Mermaid from `cdn.jsdelivr.net` at doc-view time. Works out of the box; requires internet access to render diagrams.

For projects that can't rely on CDN access — **regulated builds (fintech, healthcare), offline / air-gapped workflows, security-conscious postures** — swap to the vendored variant:

```bash
./scripts/vendor-mermaid.sh
```

The script:
- Downloads the Mermaid UMD bundle to `docs/_assets/vendor/mermaid.min.js` (defaults to pinned major version; override with `MERMAID_VERSION=11.4.0` etc.)
- Rewrites `docs/_assets/mermaid-init.js` to load from the local bundle instead of the CDN
- Uses the UMD build (not ESM) so `file://` URLs work — you can still double-click the HTML docs from Finder

The vendor directory is **gitignored by default** at the template level so the template itself doesn't carry the bundle. Downstream projects can either:
- Leave it gitignored and document `./scripts/vendor-mermaid.sh` as a setup step (the script is idempotent), or
- Un-ignore `docs/_assets/vendor/` in their own `.gitignore` to commit the bundle into their repo.

Revert to CDN at any time: `git checkout docs/_assets/mermaid-init.js && rm -rf docs/_assets/vendor/`.

### Optional for richer artifacts

- **Figma MCP** + **Figma plugin** — required only if the `ux-designer` Agent will produce wireframes / Code Connect mappings (skills under `figma:*`).
- **Modern browser** — for viewing the generated HTML docs (`docs/PRD/index.html` etc.). They're self-contained; default-CDN variant needs internet on first open, vendored variant works offline.

## Where to read next

- [`CLAUDE.md`](CLAUDE.md) — session bootstrap, first-run checklist, session-management heuristics.
- [`WORKFLOW.md`](WORKFLOW.md) — phases, roles, Linear mapping, team coordination, decision logging.
- [`MILESTONES.md`](MILESTONES.md) — live state-ledger structure.
- [`DECISIONS.md`](DECISIONS.md) — append-only decision log; conventions in WORKFLOW.md → Decision logging.
- [`BACKLOG.md`](BACKLOG.md) — Linear-overflow queue and FIFO promotion mechanism.
- [`docs/starting-prompt.md`](docs/starting-prompt.md) — the original design brief that shaped this template.

## License

MIT — see [`LICENSE`](LICENSE).

Projects instantiated from this template can adopt whatever license suits them; the template itself is MIT-licensed so you can fork, modify, and reuse without friction.

## Contributing

This is a living template. Improvements made inside any project derived from it can be ported back here so future projects benefit. Open a PR or fork freely.
