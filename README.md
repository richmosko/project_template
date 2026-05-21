# project_template

> A reusable Claude Code starter for running new projects with an AGILE-grounded workflow, a team of specialist Agents, and consistent artifacts — from PRD through release.

## What this is

This repo is a **meta-template**, not a product. Clone it (or use it as a GitHub template) to seed a new project with:

- a four-phase workflow (**Research → Plan → Implement ⇄ Validate**),
- nine specialist team-Agents (PM, UX, Architect, SecOps, two implementation leads + a generalist, QA, DevOps),
- doc-generation skills for PRD / Architecture / Security,
- workflow skills for branching, PR + Linear integration, releases,
- HTML doc templates with embedded Mermaid diagrams,
- a state ledger (`MILESTONES.md`) and decision log conventions,
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
| `secops` | SECURITY doc, threat model, gating | Plan + Validate |
| `frontend-lead` | UI implementation | Implement |
| `backend-lead` | API / service implementation | Implement |
| `implementation-lead` | generalist (CLI / lib / ML / data) | Implement (non-web projects) |
| `qa-engineer` | tests, acceptance, release readiness | Validate (TDD entry-point) |
| `devops-engineer` | CI/CD, deploy, observability | Plan + Validate |

**Skills** (`.claude/skills/`):

- `/generate-prd` — interview-driven PRD generation (chatprd.ai-grounded)
- `/generate-archdoc` — Architecture doc with Mermaid diagrams
- `/generate-secdoc` — STRIDE-based threat model + controls
- `/start-feature` — branch + Linear issue + Implement team spawn
- `/finish-feature` — commit, push, PR, link Linear
- `/merge-pr` — gated merge, tag releases, update state
- `/open-doc` — open HTML/Markdown docs in default viewer
- `/setup-linear-team` — wire Linear into a new project (one-time)
- `/setup-claude-deploy-key` — generate a per-repo passphrase-less SSH deploy key so Claude can push to GitHub without TTY-unlockable passphrases (one-time per repo)

**Artifacts** (top level + `docs/`):

- `CLAUDE.md` — session-bootstrap context (loaded automatically)
- `WORKFLOW.md` — phases, roles, gates, team coordination
- `MILESTONES.md` — live state ledger + Decision Log
- `docs/PRD.html` — Product Requirements (HTML + Mermaid)
- `docs/ARCH.html` — Architecture + Infrastructure
- `docs/SECURITY.html` — Security + Compliance
- `docs/_assets/` — shared CSS + Mermaid loader

## Roles

- **Principal** (you) — sets vision, makes gate decisions, authorizes Agents.
- **Team Lead** — the main Claude Code session. Coordinates teams, delegates, summarizes specialist output into executive language.
- **Agents** — nine specialists spawned per phase as Claude team-agents.

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
3. Replace the project description placeholders in `CLAUDE.md`.
4. `/setup-linear-team` — link to your shared Linear team and create this project's Initiative.
5. Verify `teammateMode` in `.claude/settings.json` (default: `tmux` for split-pane).
6. Spawn the Research team: _"Create an agent team for the Research phase."_
7. `/generate-prd` — start the discovery interview.

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
├── README.md                    this file
├── docs/
│   ├── PRD.html                 product requirements (Research)
│   ├── ARCH.html                architecture (Plan)
│   ├── SECURITY.html            security (Plan + Validate)
│   ├── starting-prompt.md       original design notes (kept for posterity)
│   └── _assets/                 shared CSS + Mermaid loader
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

### Optional for richer artifacts

- **Figma MCP** + **Figma plugin** — required only if the `ux-designer` Agent will produce wireframes / Code Connect mappings (skills under `figma:*`).
- **Modern browser** — for viewing the generated HTML docs (`PRD.html`, `ARCH.html`, `SECURITY.html`). They're self-contained and load Mermaid from CDN, so an internet connection helps on first open.

## Where to read next

- [`CLAUDE.md`](CLAUDE.md) — session bootstrap, first-run checklist, session-management heuristics.
- [`WORKFLOW.md`](WORKFLOW.md) — phases, roles, Linear mapping, team coordination, decision logging.
- [`MILESTONES.md`](MILESTONES.md) — state-ledger structure and Decision Log conventions.
- [`docs/starting-prompt.md`](docs/starting-prompt.md) — the original design brief that shaped this template.

## License

MIT — see [`LICENSE`](LICENSE).

Projects instantiated from this template can adopt whatever license suits them; the template itself is MIT-licensed so you can fork, modify, and reuse without friction.

## Contributing

This is a living template. Improvements made inside any project derived from it can be ported back here so future projects benefit. Open a PR or fork freely.
