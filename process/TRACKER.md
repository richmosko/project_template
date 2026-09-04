# Cairn — the file-based issue tracker

> Spec for the template's project-management backend. Replaces Linear as the default.
> Status: **built and in use.** See [Rulings](#rulings) for how decisions are recorded.

## Purpose

Cairn replaced Linear, whose free tier imposed limits the template couldn't design around: a 250 active-issue cap, a 1-month minimum auto-archive, one user (so nine agents shared an identity), and an MCP server verbose enough that the template shipped a firewall agent (`mcp-broker`) to keep its payloads out of the team-lead's context. Three moving parts existed *only* to work around the cap and the archive policy; cairn's arrival let the template shed them.

What Linear got right and this design keeps: a **post-and-comment issue database**, a **major → milestone → issue → sub-issue hierarchy**, and **Kanban + list** visualisation.

**Cairn** is that, as files in git. The name was chosen because `grep -rn cairn` never collides
with prose — unlike "tracker", which the docs use as ordinary English constantly — and because
it is short enough to serve as directory, CLI, and ID prefix. Write it as "cairn (the file-based
issue tracker)" on first mention in any doc.

### Principles

1. **The files are the database.** One markdown file per issue, YAML frontmatter, comments appended to the body — in the project's own repo, next to the code it describes.
2. **Git is the engine.** History, blame, audit trail, undo, branching, and conflict detection come free. No second store to sync, nothing to back up.
3. **Agents never need a server.** Agents use `Read` / `Write` / `Edit` / `Grep` and one thin local CLI. **Zero MCP, zero HTTP, zero JSON payloads in context.** The core design goal — it *deletes* the context-bloat problem rather than firewalling it.
4. **The server is a lens, not a source of truth.** It parses the issues directory **at request time**, holds no state, has no build step, and runs only while a human is looking. Killing it loses nothing.
5. **No caps, no expiry.** Archiving is moving a file to `archive/` — hygiene, never a quota.
6. **Boring stack.** Python 3 stdlib + a static page. Nothing to install on macOS.

### Non-goals

- **Not a backend abstraction.** Cairn is *the* backend. There is no pluggable-provider layer and no dual-write to Linear.
- **Not multi-user or networked.** Binds `127.0.0.1`. Collaboration is git.
- **Not cross-project by default.** Cairn is per-repo by construction. An opt-in, **read-only** multi-root mode aggregates sibling repos into one board (ruled 2026-08-19 as an accepted v1 regression, then built 2026-08-21). Cross-root **writes stay out of scope** — `POST` endpoints are structurally scoped to the primary root, and a foreign-root mutation is refused with `403 read_only_root`. See [API surface](#api-surface).
- **Not a Session-Cycle tracker.** Session Cycles are a session-planning heuristic with deliberately no tracker artifact (ruled 2026-07-23, with the version hierarchy). Nothing here re-opens it.

---

## Data model

### Directory layout

```
process/cairn/
├── config.yml               engine + project config (committed — no secrets)
├── majors/PT-V1.md          major version line
├── milestones/
│   ├── PT-A.md · PT-B.md    definition milestones
│   └── PT-1.0.md            development milestone, named by target version
├── issues/PT-1.md           feature (and sub-issues — same file type)
├── archive/issues/PT-1.md   same schema; moved here as hygiene   (PT-50)
└── metrics/token-usage.jsonl   token counts only, not tracker data  (PT-77)

scripts/cairn/            THE ENGINE — self-contained, spin-off-ready
├── cairn                 bash shim → cairn.py
├── cairn.py              CLI + parser + server (stdlib only)
└── board/                board.html · board.js · board-logic.js · board.css · vendor/
```

**Data under `process/`** because it *is* process state — sibling to `STATE.md`, `DECISIONS.md`, and still a distinctive grep root.

**The layout is fixed at `process/cairn/` in v1 — no `data_dir` key (ruled 2026-08-20).** Such a key would be circular: `config.yml` lives *inside* the directory it would declare, so the engine must find the directory before it can read where the directory is. Relocation, if ever wanted, belongs to an env var or a flag.

**A missing or config-less data dir is an error, never an empty result.** If the engine can't resolve a directory containing `config.yml` it says so and exits non-zero — it does not report zero issues. "No tracker here" and "no issues here" are different facts and must never render identically. **`load_config` itself enforces this (PT-80)** — it raises naming the path when `config.yml` is absent, rather than returning built-in defaults, so every caller inherits the rule even if it reaches the loader directly instead of through the CLI's own resolver.

**Engine under `scripts/cairn/`** and nowhere else. It touches no project file outside `process/cairn/`, so `git subtree split --prefix=scripts/cairn` extracts it cleanly — a combined `cairn/` would drag every project's issue history into the extracted repo.

**`metrics/token-usage.jsonl` is data, not a tracker record.** It holds token-usage counts only (input/cache-write/cache-read/output per issue × role × model), never issue content, and lives outside `issues/` `milestones/` `majors/` `archive/` so no cairn loader or `cairn check` ever scans it. `scripts/cairn/backfill_tokens.py` (PT-77) wrote it **once**, scraping the local Claude Code transcripts before their retention window pruned the history; PT-78 owns appending to it going forward from live OTel data, in the same schema, so the two sources merge without translation. A branch touching more than one issue (`feature/pt-7-8-9-13-*`) attributes its whole contribution to the first id only — the transcript carries no finer signal. The backfilled data starts at 2026-08-18 because Claude Code's own retention window had already pruned everything earlier by the time PT-77 ran; PT-79's chart must not present it as complete history.

**Ongoing collection (PT-78): a local OTel receiver, off by default.** `/setup-tracker` opts a project in by adding this `env` block to `.claude/settings.json` (absent from the template until then):

```json
"env": {
  "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
  "OTEL_METRICS_EXPORTER": "otlp",
  "OTEL_LOGS_EXPORTER": "none",
  "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
  "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"
}
```

`OTEL_LOGS_EXPORTER` stays `none` and `OTEL_LOG_RAW_API_BODIES` stays unset — the logs stream is where prompt-adjacent content would ride; this project only ever collects metrics (counts), never content. `scripts/cairn/otel_receiver.py` is a separate long-lived local HTTP server (**not** inside `cairn serve`, which dies on `/exit`) started idempotently by the `SessionStart` hook — pidfile + a port probe, a second start is a no-op. It decodes `claude_code.token.usage` OTLP/JSON, counts it correctly under either delta or cumulative aggregation temporality (max within a (series, `startTimeUnixNano`) group, summed across groups, in memory only — a receiver restart drops whatever accrued while it was down, never reconstructed), and appends `source: "otel"` lines to the **same** `token-usage.jsonl`, under the same file lock, in the same 12-key schema PT-77 writes (minus the two optional `cache_write_5m`/`cache_write_1h` fields OTel doesn't split).

**PT-81 hardened three receiver hazards, each verified by construction with two fake project roots.** One of them produced a real contamination during PT-79: a payload POSTed from an unrelated directory was accepted and written into this repo's committed `token-usage.jsonl` under a PT-79 row (removed before commit). `otel_port` in `process/cairn/config.yml` is the single source of truth for which port the receiver binds — `/setup-tracker`'s telemetry step (below) writes it and `OTEL_EXPORTER_OTLP_ENDPOINT` from **one** answer, so the two can never independently drift the way they did here:

1. **Telemetry gate (H1).** `ensure_running` requires `CLAUDE_CODE_ENABLE_TELEMETRY` truthy in its own environment (`"1"`/`"true"`/`"yes"`/`"on"`, case-insensitive — the same string shape this project's other boolean env flags already use); otherwise it returns `False`, spawns nothing, and the hook exits 0 quietly. The `env` block reaches hook-spawned subprocesses, so this one block controls both the exporter and the receiver — a project that never opted in gets no bound port and no idle daemon.
2. **Bind verification (H2).** `ensure_running` doesn't just check the child is alive — it polls the port and distinguishes two failure shapes: a **different** process already holding `otel_port` (refuses to spawn a doomed second instance; very plausibly another project sharing the same default port) from a spawn that never actually came up (the child may have exited immediately — see the log). Either way it names the port and `otel_port`, prints to stderr, and returns `False`. The `SessionStart` hook line still always exits 0 (telemetry must never fail a session) but no longer redirects stderr to `/dev/null`, so these messages are visible instead of only ever reaching the gitignored log. `python3 scripts/cairn/otel_receiver.py --status` reports whether a receiver is running, its port, and its `--out-file` (exit 0 running / 1 not) — an operator-facing health check, distinct from `--ensure-running`.
3. **Port/endpoint agreement (H3).** Before spawning, `ensure_running` compares `otel_port` against the port named by its own **inherited** `OTEL_EXPORTER_OTLP_ENDPOINT` — not by parsing `settings.json`, since the telemetry env may legitimately live in `settings.local.json` or a shell profile instead. If the variable is set and the ports disagree, it refuses to start, naming both (a mismatch doesn't lose telemetry — it silently delivers it to whatever else is listening on the wrong port, exactly PT-79's real incident). If the variable is unset, H1 already declined before this check is ever reached.

**Issue attribution is branch-first, not `cairn.issue`-first** — the repo's current branch, through the exact same regex `backfill_tokens.py` uses, wins whenever it resolves to something other than `main`; the `cairn.issue` resource attribute (set via `OTEL_RESOURCE_ATTRIBUTES`) is only consulted as a fallback when the branch itself is `main`. This is a deliberate departure from the original design (`/start-feature` setting `cairn.issue` for a session): `OTEL_RESOURCE_ATTRIBUTES` is read once at process start and a long-running session would otherwise carry a stale value that could silently override a correct, live branch signal.

**The receiver strips identity on an allow-list, not a deny-list.** The real export carries `user.email`, `user.id`, `user.account_id`, `user.account_uuid`, `organization.id`, `terminal.type`, `effort`, and `session.id` on every datapoint — none of it is ever written to disk; `session.id` is held in memory only, as the in-process series key and the role resolver's lookup key, and discarded at flush. Only `agent.name`, `model`, `query_source`, `cairn.issue`, and `type` are read past the allow-list boundary.

**Role resolves per `session.id`, through a transcript-header lookup, not from the OTel payload directly.** Measured (amendment B, 25d7a42): `agent.name` is absent on real teammate-process exports, so the receiver reads `<transcripts-dir>/<session.id>.jsonl` (same slug derivation `backfill_tokens.py` uses), takes the first `agentName` within the first 50 records, and normalises it through PT-77's own roster-anchored function. A transcript that exists with no `agentName` resolves to `team-lead`; no transcript at all resolves to `subagent-unattributed` — a loud guard, never a silent fold into `team-lead` — and that miss is deliberately **not** cached, since a session's transcript appears on its first turn and a later lookup should retry rather than pin an early false negative. If a future Claude Code version ever emits `agent.name` directly on a teammate's own datapoints, that value wins outright and this lookup becomes the fallback (one condition to flip).

**Residual not yet verified end-to-end: a real spawned teammate's OTel export actually resolving to a non-`team-lead` role through the live receiver.** What *is* verified (PT-78's merge basis, 2026-09-03): the resolver's logic is correct against synthetic fixtures for all three cases (agentName found and normalised, transcript exists with none, no transcript at all); and a real, currently-running teammate's own transcript genuinely carries `agentName` at line 4 (confirmed by reading a live teammate's own session file directly) — so the data the resolver depends on does exist for genuine team-agent spawns. What's *not yet* run end-to-end is a spawned teammate's live export flowing through a running receiver in a session where the OTel env block was actually active at that teammate's start (§5's C1 caveat: the env only takes effect for a session started *after* it's written, so this can't be checked retroactively in an already-running session). **Run this once, in the first telemetry-on session, before trusting PT-79's per-role split:** 1) add the env block below to `.claude/settings.json` and start a fresh session; 2) `python3 scripts/cairn/otel_receiver.py --ensure-running`; 3) spawn one real teammate and have it complete a turn; 4) `python3 scripts/cairn/otel_receiver.py --flush-now`; 5) read `process/cairn/metrics/token-usage.jsonl` and confirm at least one fresh `source: "otel"` line carries a `role` that is neither `team-lead` nor `subagent-unattributed`. Either outcome is a real finding worth recording as an issue comment, not a silent pass/fail.

**Tokens are exact; dollars are estimated.** The receiver does not persist `claude_code.cost.usage` (Claude Code's own client-side estimate) — dollars are recomputed from token counts for *both* sources (backfilled and live) using PT-79's one dated price table, so the chart never mixes two costing methods with a discontinuity at the boundary that looks like a real cost change and isn't. Token counts themselves are the API's own usage numbers and are exact for both sources.

**The price table lives at `scripts/cairn/prices.json`, beside the engine — not under `process/cairn/`.** The rates are identical for every project that ever uses cairn (engine data, not this project's state): `git subtree split --prefix=scripts/cairn` must carry the table with the engine, and a spun-off cairn must never drag a project's usage history along with it.

**To update a rate:** edit the model's entry directly and bump `retrieved` to today's date. **Rates are explicit per-model numbers, never multipliers derived from a base rate** — the published docs express caching as multipliers (5m = 1.25×, 1h = 2×, cache read = 0.1× input), and that is measurably wrong for at least one model in this table (Claude Fable 5.1's cache read is 0.025× input, not 0.1× — a multiplier-derived table would overcharge it 4×). Always copy the vendor's *published number* for each field, never compute one.

**This is one flat snapshot, not a dated history.** `retrieved` records when the numbers were last checked; there is no `effective_from`/`effective_to` range. **Consequence: editing a rate here silently re-prices every past bucket that used that model, backfilled and live alike** — the dashboard has no way to know a rate changed on a particular date and will price August's tokens at today's number. If a rate ever actually changes (not just gets re-verified at the same value), the fix is to promote each model's value to a list of `{effective_from, rates}` entries and have the one consumer (`build_tokens_payload` in `cairn.py`) pick by the contributing line's own `window_end` — a schema change, not a data edit. Until that's built, only edit this file when a rate is *unchanged but re-verified*, or accept that you are re-pricing history.

**An unpriced model never renders as free.** A model absent from `models` gets `cost_usd: null` on every bucket it contributes to (propagating up: a bucket with even one unpriced contribution has a `null`, not partial, total) — never `0`. Its token counts still render normally. `/api/tokens`' `prices.unpriced_models` names every such model so the dashboard's caption can say so, rather than silently under-counting the total.

### `config.yml`

```yaml
prefix: PT              # issue ID prefix; derived from the repo name at setup,
                        # confirmed or overridden by the user once (see /setup-tracker)
port: 8766              # board server port
board:
  columns: [backlog, todo, in-progress, in-review, done]
                        # Kanban columns: which, and in what order.
  swimlane: milestone   # milestone | none -- the Swimlanes checkbox's
                        # STARTING value, not a lock
roots:                  # optional -- sibling repos to aggregate into a
                        # read-only cross-project board. Flat list of paths
                        # relative to the repo root; mapping entries are
                        # rejected (a root's id/label are derived, never
                        # configured). Absent or [] -> single-root. See
                        # Multi-root below.
  - ../cairn-ui
```

**`board.columns` selects and orders columns; it does not invent statuses (PT-38).** Each entry must be one of the five column statuses — `backlog`, `todo`, `in-progress`, `in-review`, `done` — with no duplicates and at least one entry. `cancelled` is **rejected**: it is owned by the board's Show-cancelled toggle, and two mechanisms producing one column is exactly the drift this spec keeps closing elsewhere. Omitting a status is legitimate and means what it says — a board configured `[todo, in-progress, done]` does not render backlog issues, and (by the [visible-equals-counted rule](#board)) does not count them either.

**`board.swimlane` sets the Swimlanes checkbox's initial state, then gets out of the way.** `none` starts the board flat; the checkbox still works, and a user's toggle owns the setting for the rest of the session. It is a default, not a lock.

**Invalid config is loud in the lint and soft at runtime — deliberately, not inconsistently.** `cairn check` **errors** on a present-but-invalid `board.columns` / `board.swimlane` (an *absent* key is fine — that is what defaults are for), while the server **falls back** to the default and prints one warning line to stderr naming the offending value. A typo in a config file should stop a lint, not stop you seeing your board. Both postures read the same validator, so they cannot disagree about what "invalid" means.

**Scope, so it isn't re-proposed:** the **primary root's** config governs in [multi-root](#multi-root-pt-3-2026-08-21) — secondary roots are read-only lenses and their `board.*` never reaches the payload. And `cairn snapshot` ignores `board.columns` entirely, always rendering the full status order: a snapshot silently missing a project's hidden statuses would be data loss in the one artifact that exists for reading offline. Board view and canonical rendering are different jobs.

Status vocabulary itself is deliberately **not** configurable in v1 — the skills hard-code the transitions, and a per-project vocabulary would fork them. (This is also why `board.columns` is a *selection* from the fixed vocabulary rather than a place to define new statuses: the issue drawer's status picker is built from that same vocabulary, so a project-defined status would be renderable but not settable.)

### Issue file — complete example

`process/cairn/issues/PT-14.md`:

```markdown
---
id: PT-14
title: Google OAuth login
status: in-progress
milestone: PT-1.0
parent: null
blocked_by: []
assignee: backend-lead
labels: [auth, api]
priority: P1
pr: null
created: 2026-08-14
updated: 2026-08-19
---

A returning user should be able to sign in with their Google account instead of
a password, so first-run friction drops and we stop storing credentials.

## Acceptance criteria

- [ ] `GET /auth/google` redirects to Google's consent screen with the correct scopes
- [ ] An existing email-password user signing in via Google is linked, not duplicated

## Comments

### @qa-engineer — 2026-08-18

Failing acceptance test committed: `tests/auth/test_google.py::test_consent_redirect`.

### @architect — 2026-08-19

Reuse `lib/session/store.py` rather than introducing a second session abstraction.
```

### Frontmatter schema

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | ✅ | Must equal the filename stem. **The filename is authoritative**; `cairn check` errors on a mismatch. Kept in-file so a pasted or moved file is self-describing. |
| `title` | string | ✅ | One line. No trailing period. |
| `status` | enum | ✅ | See [Status vocabulary](#status-vocabulary). |
| `milestone` | string \| null | ✅ | Milestone id (`PT-1.0`, `PT-M2`, `PT-A`). `null` = unassigned. |
| `parent` | id \| null | ✅ | Sub-issue linkage. One level is expected; the parser tolerates deeper nesting but the board renders two. |
| `blocked_by` | list[id] | — | Issues that must resolve before this one can start. **Same-root ids only.** An absent key ≡ `[]`. `cairn check` lints dangling refs, self-reference, and cycles. See [Dependencies](#dependencies). |
| `assignee` | string \| null | ✅ | Bare agent role (`backend-lead`) matching a file in `.claude/agents/`, or `@handle` for a human. Replaces Linear's `agent:<role>` labels — attribution becomes a field, not a label. |
| `labels` | list[string] | ✅ | Free-form, lowercase-kebab. May be `[]`. |
| `priority` | `P0`–`P3` \| null | — | Backlog ordering only. Not a due date. |
| `pr` | url \| null | — | Written by `/finish-feature`. Lets the board link out. |
| `created` | date | ✅ | `YYYY-MM-DD`. |
| `updated` | date | ✅ | `YYYY-MM-DD`. |

**Dates are date-only, everywhere.** Precise timestamps are git's job (`git log --follow <file>`). `updated` earns its place only because `git checkout` resets file mtimes, so mtime can't order issues across clones.

**Deliberately absent, so they don't get re-proposed:** `estimate` (the workflow never reads one), `branch` (derivable — `feature/pt-14-<slug>`), and `major` on issues (derivable via `milestone` → milestone file → `major`; two sources would drift).

### Milestone file

`process/cairn/milestones/PT-1.0.md`:

```markdown
---
id: PT-1.0
name: MVP
kind: product          # product | process
major: PT-V1
status: planned        # planned | in-progress | paused | done | cancelled
target_tag: v1.0.0
ga: true               # exactly one development milestone per major carries ga: true
---

**Definition of done:** a new user can sign up, log in, and complete the core loop
end to end on staging, with the acceptance suite green.

## Comments

### @mosko — 2026-08-24

A milestone/major file MAY carry a `## Comments` section (PT-51) — identical
format, parser, and author vocabulary as an issue's (see [Comment
format](#comment-format) below). No second convention.
```

Definition milestones (`A — Bootstrap & Research`, `B — Plan`) use `kind: process`, `target_tag: null`, `ga: false`.

### Milestone ids — definition vs. development

Milestones come in two flavours, distinguished by `kind:`. **The id shape and the kind must agree** — `cairn check` errors when they don't.

| Flavour | `kind:` | Id shape | Examples | Tags a release? |
|---|---|---|---|---|
| **Definition** — the phases that produce the artifacts (Bootstrap & Research → PRD; Plan → ARCH + SECURITY) | `process` | the repo prefix, then one capital letter, optionally one lowercase subdivision suffix | `PT-A`, `PT-B`, `PT-C`, `PT-Aa`, `PT-Ab` | never (`target_tag: null`, `ga: false`) |
| **Development** — the scope chunks that build the product | `product` | the repo prefix, then a version string or `M<n>` (optionally subdivided) | `PT-1.0`, `PT-0.6`, `PT-0.5.1`, `PT-M0`, `PT-M0a` | version-named ones do (`target_tag: v1.0.0`) |

A fresh project bootstraps with `PT-A — Bootstrap & Research` and `PT-B — Plan`; its first development milestone is `PT-M0`, or better, a version-named one.

**`M` and `V` are reserved.** `M<n>` means development, always, and `V<n>` is a major line — so both letters are skipped in the definition sequence (`… K`, `L`, `N` … `U`, `W` …), making "M means development" and "V means major" absolute at the cost of two letters out of 26. `V` joined `M` in 0.6.1 (PT-28), when prefixing put majors and milestones in one namespace: without it, `PT-V` (a definition milestone) sits one character from `PT-V1` (a major). The four shapes never formally collide even without the reservation, but formally-unambiguous and readable-at-a-glance are different properties, and the second one is what prefixing is for.

**Prefer version-named ids for anything that tags.** `M<n>` is an ordinal carrying no version information, so a milestone that will cut a release is named for the release (`PT-1.0` → `v1.0.0`) — that is what keeps **milestone ↔ `target_tag` 1:1** ([WORKFLOW.md → Versioning scheme](WORKFLOW.md#versioning-scheme)). `M<n>` is for development milestones that don't tag one.

**Any release granularity is legitimate** (ruled 2026-08-23). A development milestone's id sits at whatever granularity the release it cuts does — `PT-0.6` → `v0.6.0` (a feature milestone, moving MINOR) and `PT-0.6.1` → `v0.6.1` (a patch milestone, moving PATCH) are both correct, and the id-shape regex accepts both. What is 1:1 is milestone ↔ tag, never milestone ↔ `MAJOR.MINOR`: the earlier wording said the latter, which the `0.5.1` / `0.6.1` / `0.6.2` milestones had already outgrown. A patch milestone is a separate release with its own tag, not a split of one release across two milestones — the thing [Model A](WORKFLOW.md#versioning-scheme) actually forbids.

**Subdivision** works the same in both flavours: append one lowercase letter — `PT-Aa` / `PT-Ab`, `PT-M0a` / `PT-M0b`. Each subdivision is its own file.

**The enum keeps its old values.** `kind:` stays `process` | `product` — renaming to `definition` | `development` would be a data migration across every repo, the board, and the skills for a vocabulary gain. Prose says *definition* / *development*; the file says `process` / `product`.

**`cairn check` enforces the pairing.** The regexes are built from `config.yml`'s `prefix:`, with `<P>` standing for that value:

```
definition  (kind: process)   ^<P>-(?!M|V)[A-Z][a-z]?$
development (kind: product)   ^<P>-(?:M\d+[a-z]?|\d+\.\d+(?:\.\d+)?)$
major                         ^<P>-V\d+$
issue                         ^<P>-\d+$
```

**The regexes are built from `config.yml`'s `prefix:`, never a literal.** That makes a missing, malformed, or non-`^[A-Z]{2,5}$` prefix a hard lint error — `check_repo` otherwise tolerates an absent `config.yml`, and a lint that quietly stops linting is worse than no lint. It also means the four shapes are separable by the first character class after the prefix: a digit is an issue (no dot) or a development milestone (dot), `V`+digit is a major, `M`+digit is a development milestone, and any other capital is a definition milestone.

Four errors: (1) `kind: process` on a development-shaped id; (2) `kind: product` on a definition-shaped id; (3) an id matching neither shape (`mvp`, `PT-V`, `PT-1.0-rc`); (4) `kind:` missing or not one of `product` | `process` — the id rule is meaningless without it and there is no safe default. Nothing here constrains `target_tag` or `ga` against the id shape: an `M<n>` milestone that never tags is legitimate.

**No grandfather clause** (ruled 2026-08-21 for letter milestones, reaffirmed 2026-08-22 for prefixed ids). A repo seeded before 0.6 carries `M0`/`M1` with `kind: process`; a repo seeded before 0.6.1 carries bare ids on majors and milestones. Both fail the lint, intentionally — a permanent exception would mean `M0` might be a definition milestone forever, and a bare `0.5` might belong to any repo, which are the exact ambiguities these conventions delete. **Migration is a command, not a recipe:** `cairn migrate prefix-ids --dry-run` to review, then without the flag to apply. It is idempotent and safe to re-run after an interruption. The break is lint-only — an unmigrated repo's board and CLI keep working, only `cairn check` fails.

### Major file

`process/cairn/majors/PT-V1.md`:

```markdown
---
id: PT-V1
status: in-progress    # planned | in-progress | paused | done | cancelled
owner: mosko
target_ship: null
health: on-track       # on-track | at-risk | off-track
---

Founding major line. Starts at MAJOR 0; `1.0` is the GA-designated milestone.
```

A major file, too, may carry a `## Comments` section (PT-51) — same schema as the milestone example above, one convention for both record types.

**`<PREFIX>-V<N>` names the line by the major version it culminates in (ruled 2026-08-23, PT-41).** A line is `V1` from its very first `0.x` commit — the name states where it is *going*, not where it is. `PT-V1` shipping `v0.6.2` is therefore correct and expected, not a mislabel: `V1` is precisely "the line whose GA milestone tags `v1.0.0`", and `0.x` releases are its pre-GA scope chunks (semver's reserved no-compatibility-promise zone — [WORKFLOW.md → Versioning scheme](WORKFLOW.md#versioning-scheme)).

Two alternatives were considered and rejected. **`PT-V0` now, renamed to `PT-V1` at GA** makes the id honest at a glance, but pays a full id migration *twice* — including one at the most delicate moment in a line's life — destroys the stability that makes ids safe to reference from every milestone file, and leaves a line named `V0` cutting `1.0.0`, contradicting the GA convention. **`PT-V1.x`** reads as a range but needs a literal `x` inside an id shape, sits one character from a development-milestone id (`PT-1.0`), and is arguably *less* accurate — the `V1` line contains every `0.x` release too, not only the `1.x` ones. Keeping the id stable and defining it in one sentence beats renaming the thing every other file points at.

**Exactly one milestone per major may carry `ga: true`, and its `target_tag` must be `v<N>.0.0`** for that major's `N`. `cairn check` enforces both. **Zero is legal** — a young major that hasn't designated GA yet is a normal state, not an error; the designation is a planning act (WORKFLOW.md → GA is designated at planning time), and a lint that demanded it would fire on every repo the day it was created.

### Milestone / major status vocabulary

**One enum for both, sharing the issue cycle's `done` (ruled 2026-08-23, PT-39):**

```
planned | in-progress | paused | done | cancelled
```

Milestones and majors are the same kind of thing at different scales — a scope container with a
lifecycle — so they take one vocabulary, not two that overlap by four values out of five. It
shares `done` and `cancelled` with the [issue vocabulary](#status-vocabulary) deliberately: two
records meaning "finished" must not spell it two ways. It does **not** share `backlog`,
`todo`, or `in-review`, none of which a container has.

Before 0.7.0 the two schemas disagreed with each other *and* with reality: milestones documented
`completed` while majors documented `active`, and nothing linted either — which is how a live
milestone came to carry `status: active`, a value its own documented enum never contained.
`cairn check` now validates both against this enum, and `cairn set <milestone-or-major-id>
status=done` is the one way to mark one finished.

**No grandfather clause**, the same call as [prefixed ids](#milestone-ids--definition-vs-development):
`completed` and `active` fail the lint. **Migration is a command, not a recipe** —
`cairn migrate lifecycle-status --dry-run` to review, then without the flag to apply; it is
idempotent and safe to re-run after an interruption. The break is lint-only: an unmigrated repo's
board and CLI keep working (the board renders an unknown status via its label fallback, never
`undefined`), only `cairn check` fails.

### Status vocabulary

| Slug | Meaning | Kanban column |
|---|---|---|
| `backlog` | Scoped, not queued | 1 |
| `todo` | Queued for this milestone | 2 |
| `in-progress` | A feature branch is open (`/start-feature` sets it) | 3 |
| `in-review` | PR open, awaiting QA + merge (`/finish-feature` sets it) | 4 |
| `done` | Merged (`/merge-pr` sets it) | 5 |
| `cancelled` | Dropped | hidden behind a filter |

`cancelled` gets no column: a dead card sitting in a live column is noise, and the count it inflates is the one people read.

### Comment format

Comments append to the end of the file, under a single `## Comments` heading, oldest first — see the issue-file example above.

**Not issue-only.** Milestone and major files use the identical `## Comments` schema, parser (`split_comments`), and author vocabulary (PT-51) — there is no second comment convention for records. `cairn comment <id>` resolves any id (issue, milestone, major, live or archived) via the same six-subdir lookup `cairn set` already uses. One difference: `append_comment` bumps an issue's `updated` field on every comment, but never a record's — records have no `updated` field in their schema at all (see [Frontmatter schema](#frontmatter-schema)), so the bump is gated on "is this an issue-shaped file", not applied unconditionally.

**Parser rule:** everything after the first line matching `^## Comments\s*$` is the comment log. A new comment starts at a line matching **exactly** `^### @([a-z0-9][a-z0-9-]*) — (\d{4}-\d{2}-\d{2})\s*$`; its body runs to the next such line or EOF. Any other `###` line is body content, including `###` headings inside a comment body. The em dash is required — it is what makes the delimiter unambiguous against ordinary headings.

**Author vocabulary:** an agent role (`@backend-lead`, `@qa-engineer`, …), a human handle (`@mosko`), or `@board` for a comment authored from the board UI by a human who didn't set a handle.

This shape lets an agent append a comment with a **plain `Edit`** — the anchor is the last line of the file — while a regex still splits the log reliably.

### Sub-issues

A sub-issue is an ordinary issue file with `parent: PT-14`. It has its own status and can be assigned independently. The board renders a `2/3` badge on the parent and nests children in the detail drawer. There is no separate file type and no ordering field — children sort by ID.

### Dependencies

An issue may declare others as blocking it: `blocked_by: [PT-9, PT-12]`. The relation is stored one-directionally and derived in both directions at read time — nothing writes a reverse `blocks` field, because two stored sides of one relation is two things to keep in agreement.

**Same-root only (ruled 2026-08-22).** An entry resolves within its own root; an id from another root is dangling. Ids are unique only within a repo and `cairn check` runs per-root, so a cross-root edge could never be validated by the lint whose job is exactly that guarantee. `parent` is same-root-only by identical construction.

**A blocker that is `done` or `cancelled` is resolved, not an error.** The entry stays; "resolved" is computed at render time. Erasing a blocker on completion would make the field self-erasing and destroy the dependency record.

**Blocking is informational — nothing refuses or warns (ruled 2026-08-22).** Moving a blocked issue to `in-progress` is allowed on the board, through `cairn set`, and through `/start-feature`. Enforcement would need the same predicate at three write paths and is unenforceable against a plain `Edit`, which is fully supported here — a rule the files can bypass teaches confidence the system cannot honour. The board shows open blockers on the card and in the drawer; that is where the decision is made.

`cairn check` errors on a dangling reference, a self-reference, and any dependency cycle (reported once per cycle, with the full path). Self-references and dangling refs are excluded from the cycle walk, so one typo yields one error.

### Archive

`process/cairn/archive/` holds the same files, moved. The board reads the live directories only, unless you ask for more — **Show archived** (default off) refetches with `?archived=1` and folds archived records back in. Layout:

```
archive/issues/PT-14.md        issues       (PT-50)
archive/milestones/PT-0.4.md   milestones   (PT-39)
archive/majors/PT-V0.md        majors       (PT-39)
```

**Reversed 2026-08-24, PT-50: issues now move to `archive/issues/`, matching milestones and majors.** The earlier reasoning ("stay flat — `_dir_glob` is non-recursive, so the two subdirectories are invisible to every existing glob and cost no migration") held only while no migration existed to pay for; once one did, the flat layout was the odd one out among three record types, not the cheap default. `cairn migrate archive-issues [--dry-run]` moves every legacy `archive/*.md` file into `archive/issues/` — filesystem-only, no bytes rewritten inside any file, idempotent, safe to re-run after an interruption.

**The engine reads `archive/issues/` only (PT-52, same day, pulled into 0.7.1 before it shipped).** PT-50's transition posture — every read site accepting both layouts while the break stayed lint-only — was deliberately temporary; PT-52 deleted the legacy leg before 0.7.1 ever released, so no repo instantiated from this template ran with the dual-read live. A file left at the legacy flat `archive/*.md` path is not merely unlinted, it is **invisible**: absent from the board (`?archived=1` included), uncounted by id allocation, and unresolvable by `parent`/`blocked_by`/`milestone:` reference resolution — a reference to it dangles. `cairn check` still errors on it, first in the list, naming the count and the exact fix command; a dangling-reference error caused by the same file is reported too, as a separate, cascading symptom. `cairn new` (CLI) and `POST /api/issue` (HTTP) additionally **refuse to allocate a new id at all** while any legacy file remains — id allocation counts `archive/issues/` only, so proceeding could re-issue an id an invisible archived issue already holds, which the migration afterward could not repair. The guard is self-clearing: run `scripts/cairn/cairn migrate archive-issues --dry-run` (then without the flag) and both the lint error and the allocation refusal disappear. Archiving is invoked explicitly — **exactly one selector, always**, and `--dry-run` previews any of them:

```
scripts/cairn/cairn archive --done-before 2026-06-01   # issues, by date
scripts/cairn/cairn archive --milestone PT-0.4         # a milestone + its issues
scripts/cairn/cairn archive --major PT-V0              # a major + its milestones
```

It exists so a three-year-old project doesn't parse 1,400 files per request — **not** because anything expires. (Measured 2026-08-23: 1,400 archived issues cost ~83 ms to parse, against ~3 ms for a live-only board payload. That 28× gap is why the default board payload never opens `archive/`.) Archived records remain in git, remain greppable, and can be moved back with `git mv`. Their IDs are never reused, and `cairn check` resolves `parent` / `blocked_by` / `milestone:` / `major:` references against the archive directories as well as the live ones — archiving a record never dangles a reference to it.

**Archiving never sweeps issues out from under a live milestone (ruled 2026-08-23, PT-39).** Every selector enforces it: `--done-before` *skips* an issue whose milestone isn't `done`/`cancelled` (printing why), and `--milestone` / `--major` *refuse* outright unless the record itself and everything under it is `done`/`cancelled` — validated before any file moves, so a partially-archived major is not a reachable state. `cairn check` errors on an archived issue whose milestone is not `done`/`cancelled`, which closes the hand-`git mv` bypass.

That invariant is not hygiene — it is what lets the board's arithmetic stay honest without paying the 83 ms above. Because a non-done milestone's live issues *are* all of its issues, `n/m done` computed from the live tree alone is the whole count, so the board never has to open `archive/` to be correct. A **done** milestone is the other half: it has no meaningful ratio left to show, so it reports completion and release state instead of a count — which is why a fully-archived milestone can never report `0/0 done`. That rendering is the board's side of the same ruling and lands with it.

---

## ID scheme and collision-free allocation

**Format:** `<PREFIX>-<n>` — `PT-14`. Prefix from `config.yml`; `n` a plain incrementing integer. **Ruled 2026-08-19:** `/setup-tracker` derives the prefix from the repo name (`project_template` → `PT`) and asks the user to confirm or override it — once, at setup, never again. Two projects sharing a prefix is harmless (IDs never leave their repo) but confusing when pasting between sessions, and one prompt is cheaper than the confusion. Readable in branch names (`feature/pt-14-google-oauth`), commit subjects (`feat(PT-14): …`), and conversation. No ULIDs, no hashes — an ID a human has to read aloud is worth the allocation work.

**The race:** `max(existing) + 1` by directory scan is not atomic — two agents scanning concurrently both see `14`, both write `PT-15.md`, one silently clobbers the other. The fix has two layers:

1. **Within a worktree — atomic claim.** `cairn new` computes `max + 1` over `issues/` **and** `archive/` (archived IDs are never reused), then creates the file with `O_CREAT|O_EXCL`, incrementing and retrying up to 50 times. `O_EXCL` is atomic on every filesystem the template targets, so the loser of a race gets `PT-16` rather than a lost write. This is the one operation that cannot be done safely with a plain `Write`, and the main reason the CLI exists.

2. **Across branches — git is the detector (ruled 2026-08-19).** Two branches that each allocate `PT-15` produce an **add/add conflict** at merge; resolution is `git mv` on one file plus a one-line `id:` edit, because the file is self-describing and nothing else references the ID except the branch name and commit trailers. Having `/start-feature` reserve IDs on `main` instead would trade a rare, loud, cheap conflict for an extra `main` commit per feature, forever.

**Rejected: a counter file** (`process/cairn/.counter`) — a second source of truth that conflicts on *every* concurrent branch rather than only on genuine collisions, and can drift from the directory it describes. Deriving `max` from the directory means the directory is always right.

---

## Hierarchy mapping

One file type per durable layer of the [version-driven hierarchy](WORKFLOW.md#versioning-scheme), nothing for the heuristic one.

A major owns milestones; a milestone owns issues; an issue owns sub-issues. **One issue = one PR = one Implement→Validate loop.**

| Concept | Cairn artifact | Version digit |
|---|---|---|
| Major version line (`PT-V1`, `PT-V2`, concurrent) | `majors/<prefix>-V<n>.md` | **MAJOR** |
| Milestone (development, named by target version) | `milestones/<prefix>-<version>.md`, `kind: product` | **MINOR**, or **PATCH** for a patch milestone — the digit its `target_tag` moves |
| Milestone (development, unversioned ordinal) | `milestones/<prefix>-M<n>.md`, `kind: product` | — (untagged unless `target_tag` is set) |
| Milestone (definition: Bootstrap & Research, Plan) | `milestones/<prefix>-<letter>.md`, `kind: process` | — (untagged) |
| Feature | `issues/<ID>.md` | — (identity = ID + PR + release notes) |
| Sub-issue | `issues/<ID>.md` with `parent:` | — |
| Hotfix | `issues/<ID>.md` on the milestone it patches, or a patch milestone grouping a batch of them | **PATCH** |
| Session Cycle | **none, by design** | — |

Concurrent majors fall out for free: `majors/PT-V1.md` and `majors/PT-V2.md` both `status: in-progress`, each with its own milestones, in one repo, on one board with a major selector.

---

## Relationship to `STATE.md`

The one place cairn overlapped an existing artifact. **Ruled 2026-08-19: the overlap dissolves** — `STATE.md`'s hand-maintained *Major line*, *Roadmap*, and *Features* tables were removed, and the Completed-table rolloff ritual retired with them (its only purpose was bounding a duplicate).

**Division of labour.** Durable work state — majors, milestones, issues — lives in `process/cairn/`. `STATE.md` keeps only what cairn deliberately does *not* model: **Current Phase**, **Active Feature**, and **Releases**, plus a board pointer and, optionally, a snapshot appended at milestone close (the Session Cycles history table was retired 2026-08-22 — session history lives in issue comments, the git log, and PRs):

```
scripts/cairn/cairn snapshot >> process/STATE.md
```

The snapshot exists for offline reading (a plane, a cold session before the board is up); it is a rendering, never an input.

---

## Engine

### Stack

**Python 3 standard library, no dependencies, no build step.** Same choice as `scripts/serve-docs.py`: macOS ships `python3`, and a second toolchain would be one more thing to install before the board renders.

- **YAML:** a ~60-line strict-subset parser inside `cairn.py`, handling what the schema uses — scalars, quoted strings, `null`, flow lists (`[a, b]`), block lists — and **erroring loudly** on anything else. PyYAML is never imported, not even optionally: an "import it if present" path means two parse behaviours and a bug that reproduces on one machine only.
- **Frontend:** one `board.html` + vanilla `board.js` + `board.css`, plus vendored `marked`/`DOMPurify`. No framework, no bundler, no CDN — the board works offline, matching the `vendor-mermaid.sh` precedent.

*Alternatives rejected:* Node and Deno/Bun (not guaranteed present on macOS), Go (needs a toolchain and a build step, and makes the in-template copy a binary artifact). Python's only cost is startup latency on a local board nobody is benchmarking.

### Lifecycle

```
/cairn                    # skill: backgrounds the server under the Claude session,
                          # cleaned up on /exit; probes for a running instance first
scripts/cairn/cairn serve # direct invocation, foreground, request logs
CAIRN_PORT=8899 … serve   # port override
```

**Session-bound by default** (mirrors `/serve-docs`), **persistent-capable** via the direct invocation in your own terminal or under `launchd`. The server holds no state, so the two modes are indistinguishable to the data.

**Separate server and port from `serve-docs`** — docs on `8765`, cairn on `8766`. Merging them would couple the docs review loop to the tracker and drag `docs/` into any future cairn spin-off. Both are one-line skills, and the board header links to `:8765` when it responds.

**Engine staleness (PT-49).** The data half of "the board is a stateless lens" was always true — `/api/board` re-parses `process/cairn/` on every request. The **process** half wasn't: a server started before a `cairn.py` upgrade keeps running the old code until it's restarted, silently. At server construction, `make_server` fingerprints `cairn.py` itself (content sha256, not a git hash — an uncommitted edit has no commit to name) and holds that as the boot stamp. Every `/api/board` build re-stats the file and, only on a stat mismatch, re-hashes it; `/api/board` always carries a top-level `engine: {source_sha, started_at, stale}`, folded into the response's `ETag` so a stale flip is never masked by a `304`. The `/cairn` skill auto-restarts a server it detects as stale (safe: the server holds no state); a server started outside the skill instead shows a persistent banner on the board naming the fix (`/cairn stop`, then `/cairn`) — the board keeps serving real data throughout, since only the process's *behaviour*, not the data it reads, can be stale.

### API surface

Six endpoints. All bind `127.0.0.1`, no auth — same posture as `serve-docs.py`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/board` | Full parsed state: majors, milestones, issues (without comment bodies), plus the resolved `columns` / `swimlane`. **`?archived=1`** (the only accepted spelling — anything else is off) additionally reads all three archive directories; without it, `archive/` is never opened at all. Every record always carries `archived: true\|false`. A top-level `engine: {source_sha, started_at, stale}` (PT-49 — see Lifecycle above) is always present too. Every milestone/major record ALSO carries `seen` and `comments` (PT-51) — `body` is the pre-`## Comments` half of the file, via the same `split_comments` an issue's own read path uses. Issues still carry no `comments` key here (unchanged). Supports `ETag`/`If-None-Match` — the archived flag AND the engine identity are both folded into the hash, so neither representation nor a stale flip can hide behind a `304`. |
| `GET` | `/api/issue/<id>` | One issue: frontmatter, description, acceptance criteria, full comment list, `seen` token. |
| `GET` | `/api/events` | SSE stream (`text/event-stream`). A background thread `os.scandir`s the data dir every 500 ms and diffs `(path, mtime_ns)` — not a kernel fs-watch, since `kqueue`/`inotify` have no portable stdlib wrapper. Emits `{"type":"changed"\|"created"\|"removed","ids":[…]}`; the client refetches only the named issues. |
| `POST` | `/api/issue` | Create. Body `{title, …}`. Allocates an ID via the same `O_EXCL` path as `cairn new`. **Primary root only** — there is no way to create an issue in a secondary root through the board. |
| `POST` | `/api/issue/<id>` | Mutate. Body `{seen, patch?, comment?}`. Handles the drag-to-column case (`patch: {status: …}`), inline field edits, and comment append through one code path. **Primary root only** — an id that resolves to a secondary root is refused with `403 {"error": "read_only_root", "message": "…"}`, file left untouched. An **archived** id is refused the same way with `403 {"error": "archived", …}`, checked before the `seen` comparison so it holds regardless of the request body. |
| `POST` | `/api/record/<id>` | The milestone/major sibling of `POST /api/issue/<id>` (PT-51) — **a separate endpoint, not a widening** of the issue one, so the two field policies (below) can never drift onto each other. Same body shape `{seen, patch?, comment?}`, same `read_only_root`/`archived`/`stale` semantics, checked in that order (archived before the seen comparison). An issue id is refused `400 {"error": "wrong_endpoint", …}` naming `/api/issue/<id>` — this is not a second write path to issues. `patch` is validated against a **narrower, board-editable** field set per schema — milestone: `name`/`status`/`major`/`target_tag`/`ga`; major: `status`/`health`/`owner`/`target_ship` — `id` and milestone `kind` are legal `cairn set` fields but CLI-only (id is filename-authoritative; kind is pinned to the id shape by lint), so both 400 here. Cross-record invariants (GA cap, `target_tag` shape, `major:` resolving) are **not** re-checked at the write path — `cairn check` is the backstop, same posture `cairn set` already takes. |

Plus static routes: `/` (Kanban), `/list` (list view), `/board/*` (assets).

There is deliberately **no** dedicated status endpoint — a drag is just a patch, and a second write path is a second place for the frontmatter rewriter to be subtly different.

#### Multi-root (PT-3, 2026-08-21)

`cairn serve` optionally aggregates read-only data from sibling repos — `roots:` in `config.yml`, or `--repos a,b` (replaces the config list for that invocation; the primary root is always included). A missing/unreachable root warns and is skipped, never crashes; `cairn check` validates the `roots:` *shape* only, never reachability, since a clone lacking a sibling must still lint clean.

`/api/board` gains two top-level keys — `roots` (`[{id, label, primary}]`) and `warnings` (`[{root, reason, detail}]`) — plus a `repo` field on **every** major, milestone, and issue record. `GET /api/issue/<id>` additionally stamps `repo` and `read_only` (true when that root isn't primary).

**There is no conditional payload shape.** Single-root means `roots` has exactly one entry, `warnings` is `[]`, and every record still carries `repo`; the client branches on `roots.length > 1` for presentation only. `roots[]` deliberately never carries filesystem paths, so a localhost HTTP surface can't leak directory layout. Write endpoints are unaffected — see the table above.

#### Mutation behaviour

**Drag / field edit.** `POST /api/issue/<id>` with `{seen, patch}` returns `200` and the issue's new field values plus a fresh `seen`.

**Stale card.** If `seen` doesn't match the file's current mtime, the server returns `409` with `{"error": "stale", "message": …, "current": {…}}`; the board snaps the card back, applies `current`, and flashes *"PT-14 changed on disk — refreshed."* The `current` object is **illustrative, not a schema** — any response carrying at least the issue's current field values and a fresh `seen` is conformant, and returning the full issue payload is a preferred superset since it lets the drawer re-render from the same response.

**Comment append.** `POST /api/issue/<id>` with `{seen, comment: {author, body}}` appends a correctly-delimited `### @author — YYYY-MM-DD` block to the file's tail.

### Write-back and conflict handling

Board edits **rewrite only the frontmatter block**, re-emitted in canonical key order; the body after the closing `---` is concatenated **byte-for-byte** from the original. Comment appends touch only the tail. Writes go to a temp file in the same directory followed by `os.replace` — atomic, so a crashed write can't truncate an issue.

**`seen` is `st_mtime_ns` as a string.** The browser receives it with every read and returns it with every write; the server compares against the file's current mtime and returns `409` on mismatch.

**The mtime check is not optional**, though the original decision allowed last-write-wins. The collision it prevents is the one this architecture creates: an agent edits `PT-14` while a twenty-minute-old board tab still shows the old card, and one drag silently reverts the agent's work. Last-write-wins is fine between two humans who can see each other, not between a human and a background agent.

**No auto-commit.** Board edits dirty the working tree exactly as an agent's do, and are committed by the same feature-close discipline. A tracker that committed on its own would interleave commits into whatever branch happens to be checked out.

### CLI

`scripts/cairn/cairn` — the only non-file interface, and it exists for two jobs a plain `Edit` cannot do safely:

| Command | Why it isn't just an Edit |
|---|---|
| `cairn new "<title>" [--milestone 1.0 --assignee backend-lead --status backlog --parent PT-14]` | Atomic `O_EXCL` ID allocation. |
| `cairn ls [--status todo --milestone 1.0 --assignee qa-engineer]` | One line per issue instead of reading N files into context. Context economy is the whole point. |
| `cairn set PT-14 status=in-review pr=<url>` · `cairn set PT-0.7.0 status=done` · `cairn set PT-V1 status=done` | Frontmatter-only rewrite that can't corrupt the body. Resolves **any** record id — issue, milestone or major, live or archived (PT-39) — and validates the field name and `status=` value against *that* schema's vocabulary ([issue](#status-vocabulary) vs [record](#milestone--major-status-vocabulary)). This is the one way to mark a milestone or major done; a bad value is refused before anything is written. |
| `cairn comment PT-14 --author qa-engineer --body -` | Correct delimiter + date, from stdin. |
| `cairn show PT-14` | Rendered single issue, plus its children when it has any. |
| `cairn archive (--done-before <date> \| --milestone <id> \| --major <id>) [--dry-run]` | Bulk `git mv`, with the preconditions in [Archive](#archive) — exactly one selector, and `--dry-run` previews without moving anything. |
| `cairn check` | Lint: id/filename mismatch, dangling `parent`, unknown `milestone`, bad `status` (issues **and** milestones/majors, each against its own vocabulary — see [Milestone / major status vocabulary](#milestone--major-status-vocabulary)), an archived issue whose milestone isn't `done`/`cancelled` (see [Archive](#archive)), milestone id-shape ↔ `kind` agreement (see [Milestone ids](#milestone-ids--definition-vs-development)), `blocked_by` dependency integrity (dangling ref, self-reference, cycles — see [Dependencies](#dependencies)), unsupported YAML, `config.yml`'s `roots:` shape (list of non-empty relative-path strings — reachability is a runtime concern, not lint, see [Multi-root](#multi-root-pt-3-2026-08-21)), milestone/major/issue id **prefix shape** (see [Milestone ids](#milestone-ids--definition-vs-development)), `config.yml`'s `prefix:` (present and matching `^[A-Z]{2,5}$` — every id regex is derived from it), any archived issue still at the legacy flat `archive/*.md` layout (PT-50 — see [Archive](#archive)). |
| `cairn migrate prefix-ids [--dry-run]` | One-shot 0.6.1 migration: prefixes bare major/milestone ids and retargets every `major:`/`milestone:` reference. Idempotent — safe to re-run after an interruption. Runs on a repo whose lint is failing; that is its purpose. |
| `cairn migrate lifecycle-status [--dry-run]` | One-shot 0.7.0 migration: rewrites milestone/major `status:` onto the [unified vocabulary](#milestone--major-status-vocabulary) — `completed` → `done`, `active` → `in-progress`. Value-keyed, so idempotent by construction; any other value is left untouched for the lint to report. Same posture as `prefix-ids`: runs on a repo whose lint is already failing. |
| `cairn migrate archive-issues [--dry-run]` | One-shot 0.7.1 migration (PT-50): moves every legacy flat `archive/*.md` issue into `archive/issues/` via `git mv`. Filesystem-only — touches zero bytes inside any file. Idempotent — safe to re-run after an interruption; a destination that already exists with *differing* content refuses the entire run rather than guessing a winner. Same posture as the other two: runs on a repo whose lint is already failing (that's what it fixes). |
| `cairn serve [--repos a,b]` | The board. `--repos` (PT-3) replaces `config.yml`'s `roots:` for that invocation — read-only cross-project aggregation, see [Multi-root](#multi-root-pt-3-2026-08-21). |

**The CLI is legitimate under "agents never need a server" (ruled 2026-08-19)** — that constraint reads as *no MCP, no HTTP, no JSON payloads in context*, which a local script printing one line satisfies.

**Hand-editing stays fully supported** — the files are the interface; the CLI is a convenience. But prefer `cairn ls` over grepping a directory (saves context) and `cairn new` over composing a file (the only race-safe allocation).

### Board

**Kanban view (`/`)**
- Columns per [`board.columns`](#configyml) — the five defaults (`backlog` → `done`) unless the project narrows or reorders them; `cancelled` behind a filter toggle.
- **Card:** ID · title · assignee chip · label chips · milestone chip · `2/3` sub-issue badge (or a `↳ parent` badge on a child) · a blocked chip when the issue has **open** blockers.
- **Swimlanes by milestone**, collapsible, toggleable to flat. One swimlane dimension only — assignee/label swimlanes are a filter away and don't earn a second layout mode.
- **Header:** major tabs (concurrent majors are first-class), each with a status dot and a `▸` button opening that major's card. **There is no progress strip** — it was retired in 0.7.0 because a milestone's identity belongs on the milestone, not in a header row that repeats it.
- **Milestone lane header** is where that content now lives: `id · name`, a status chip, progress, a release chip, and `GA` when designated. Clicking the label opens the milestone's card. A lane is rendered for **every** milestone, not only those with issues — otherwise a finished, fully-archived milestone would vanish from the board entirely once the strip was gone.
- **Progress is decided by the milestone's status, not by counting `archive/`:** a `done`/`cancelled` milestone shows completion, never a ratio; anything else shows `n/m`. That is what makes the old `0/0 done` reading of a shipped milestone unrepresentable rather than merely fixed — and it is why the board never needs to open `archive/` to be correct (see [Archive](#archive)).
- **Release state** comes from the local git tag set, read once per payload build: a milestone whose `target_tag` is tagged reads as released, otherwise unreleased; a milestone with no `target_tag` (every definition milestone) makes no claim and gets no chip. Two states, not three — a local tag cannot distinguish a draft release from a published one, and that nuance stays in `STATE.md`'s Releases table where a human writes it.
- **Filters** (client-side over the one `/api/board` payload): milestone, assignee, label, major, free-text. Keeping filtering in the browser is what keeps the API at one read endpoint.
- **Show archived** (default off) is the one toggle that is *not* a client-side filter — archived records aren't in the payload at all until it's on, so flipping it refetches rather than re-renders. Archived cards appear in their **original milestone lane and status column**, muted and badged, never in a separate Archive lane: the point is to see the work where it happened. They are read-only — not draggable, inline editors suppressed via the same `read_only` flag a foreign-root issue uses, and the server refuses a mutation with `403 archived`. The CLI can still write them; un-archiving is `git mv`, deliberately.
- **Drag** a card between columns → `POST /api/issue/<id>`.

**List view (`/list`)** — same data and filters, sortable table (ID, title, status, milestone, assignee, priority, updated). **Read-only**; click a row to open the drawer and edit there.

**Detail drawer** (both views) — description, acceptance-criteria checklist, comment log, add-comment box, inline editors for title / status / assignee / milestone / labels / priority, links to the PR and file path, plus the relational lists: **Children**, **Parent**, **Blocked by** (open vs resolved distinguished) and **Blocks**. Markdown **is** rendered, via vendored `marked` + `DOMPurify` (`board/vendor/`); DOMPurify sanitizes marked's *output*, never the raw source, under `USE_PROFILES: {html: true}`.

**Liveness:** `EventSource` on `/api/events`, falling back automatically to a 4s `setInterval` poll of `/api/board` if the stream 404s or drops — so an older server and a newer board stay compatible both ways. Plus an immediate refetch on `visibilitychange` and `focus`. `ETag` = a hash over `(path, mtime_ns)` for every file, so an unchanged board costs a `304` and no parse.

**Explicitly out of scope:** issue creation from the board beyond title + milestone, drag-to-reorder, keyboard shortcuts, saved filter presets, charts of any kind.

---

## Deferred work

| Candidate | Status | Note |
|---|---|---|
| **Acceptance-criteria checkbox write-back** — board renders live checkboxes that rewrite `- [ ]` → `- [x]` | **Deferred (ruled 2026-08-19)** | Cairn keeps **zero body-touching write paths** — the sole exception is comment append, which is tail-only and cannot disturb what precedes it. Checkbox write-back would be the first path that rewrites the *middle* of a file, which is exactly what the byte-preserving guarantee in [Write-back](#write-back-and-conflict-handling) exists to avoid. If ever built, it needs its own anchored-rewrite design and its own conflict story. The board renders these checkboxes `disabled` until then. |

---

## Rulings

**Nothing in this spec is pending a decision.** Every ruling still in force is stamped
`ruled YYYY-MM-DD` inline in the section it governs, alongside the reasoning — that stamp is
self-sufficient and is the authoritative record for a project instantiated from this template.
A few early rulings were later reversed by shipped work (markdown rendering, the cross-project
board); those sections describe current behaviour and carry no stamp.

The full resolutions log — every question, its ruling, and the reasoning — lives in
[`TEMPLATE_DECISIONS.md`](TEMPLATE_DECISIONS.md) (2026-08-22 entry). **That file documents the
template itself and is deleted at bootstrap**, so a downstream project keeps only the inline
stamps. That is why they must never be trimmed to a bare assertion.
