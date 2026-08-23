# Template Decisions

> Append-only log of decisions about the `project_template` repo itself — its workflow, conventions, structure, tooling, and shape. Audience: the template maintainer and any Claude session working on the template.
>
> **⚠️ Delete this file when you bootstrap a new project from the template.** Your project's own decision log is [`DECISIONS.md`](DECISIONS.md). This file documents the template, not your project.

## Format

```
### YYYY-MM-DD — <short decision title> (#<pr>)
**Decision:** <one sentence>
**Why:** <one or two sentences>
**Alternatives considered:** <bullets, if relevant>
**Approved by:** <name>
**Supersedes:** <ref to prior decision, if any>
```

Same format as the seed `DECISIONS.md`. The log is **append-only**. Don't edit historical entries; supersede them.

---

### 2026-08-22 — Swallowed-report defenses adopted: uniform addressing block, report-first multi-item jobs, idle escalation ladder
**Decision:** Adopt the fintech swallowed-report brief's three layers, adapted: (1) a byte-identical addressing block in all 10 agent definitions — report to the inbound `teammate_id` (here `team-lead`), never `"main"` (background-subagent-only; silently swallows the report, leaving a `[to main]`-prefixed idle summary as the only trace), failed send = undelivered finding, plain text is not a fallback, verify by the send result; (2) report-first ordering for multi-item jobs (survey table before applying, idempotency markers, position reports, verbatim-error reporting) in WORKFLOW.md's hand-off protocol + a compact echo in every agent's hand-off block; (3) the idle-without-report escalation ladder (temp/ → `[to main]` signature → one poke → direct ground-truth reads → survey-first replacement briefs) in the team-lead role. The lead memory `teammate_reply_address.md` deleted as superseded — two homes for one rule is how they diverge.
**Why:** This repo hit the exact bug 2026-08-20 (qa-pt18's first delivery bounced addressing "main") but patched it in the weakest layer — coordinator memory + dispatch-prompt habit. The audit found no `"main"` address anywhere in tracked files; the gap was the absence of a rule where the failing reader looks: the freshly spawned agent's own definition. Report-last is additionally the measured death position for long jobs' deliverables.
**Approved by:** Rich Mosko
**Supersedes:** _extends the 2026-08-22 sha-pinned hand-offs adoption (same source repo's protocol series)._

### 2026-08-22 — `/sweep-memory`: memory stores get a session-close audit, peer to `/sweep-temp`
**Decision:** New `/sweep-memory` skill audits both persistent memory stores — the lead's auto-memory (`~/.claude/projects/<slug>/memory/`) and every teammate `agent-memory/` dir in the tree, strays included — verifying each memory against the current tree and keeping / condensing / merging / deleting, then rebuilding the `MEMORY.md` indexes. Wired into session close as obligation #3 in the team-lead role (same priority class as the `temp/` sweep) and into CLAUDE.md → Session management. Guardrail: `feedback`/`user`-type memories are never deleted on the lead's judgment alone unless plainly superseded — otherwise the call is batched to the user.
**Why:** Memory had guidelines (dedupe-before-save, delete-when-wrong) but zero enforcement and no retrospective mechanism — write-time rules can't counter append-bias, and the stores were already growing fossils (a RESOLVED outage memory annotated instead of deleted; point-in-time status snapshots rotting silently in teammate stores nobody reads). `temp/` has a sweep + hook + staleness threshold; memory had nothing. No SessionStart hook for memory, by design: staleness is only detectable by verification, which needs a model, not an `awk` line.
**Approved by:** Rich Mosko
**Supersedes:** —

### 2026-08-22 — STATE.md keeps no history: Session Cycles table retired; cairn is the work-history ledger
**Decision:** `STATE.md` is a dashboard, not a log — it holds only current state (Current Phase, Active Feature pointer, Releases table). The Session Cycles history table is deleted, the `Session Cycle` field drops from the Active Feature block and `/start-feature`, and no session narrative is ever written to `STATE.md` again; work history lives in cairn (issues + comments), the git log, and PRs. Session Cycles remain a planning heuristic with zero footprint anywhere. All referencing surfaces updated (CLAUDE.md, WORKFLOW.md, TRACKER.md, team-lead role, `/start-feature`, `/merge-pr`, README).
**Why:** The file is auto-injected into every session; the SC rows had grown to 8.9KB of 13.8KB (65%) — monotonically (SC1 337 → SC6 2,381 chars) — and this session the injection exceeded the hook's 10.7KB persistence threshold, truncating the dashboard it exists to provide. Nearly all row content duplicated cairn issues, this ledger, or the git log. The one unplaced finding (the 0.6 QA shared-tree incident's worktree rule) was codified into WORKFLOW.md § Sha-pinned hand-offs as part of this change.
**Alternatives considered:**
- Per-row size cap ("one line per cycle") — rejected: prose fields regrow; no enforceable bound. The only durable discipline is that no prose field exists.
- Keeping a current-cycle-only row — rejected: an ephemeral heuristic needs no persistence; the plan lives in conversation and the tracker.
**Approved by:** Rich Mosko
**Supersedes:** _narrows the 2026-08-19 tracker consolidation's "STATE.md keeps Session Cycles" carve-out; extends the same "history-prose belongs in the ledger, not the spec/dashboard" principle as the 2026-08-22 ledger consolidation._

### 2026-08-22 — Sha-pinned hand-offs adopted; one-writer-per-checkout made explicit; deliverable-grade temp/ integration
**Decision:** Adopt the sha-pinned hand-off discipline (from a brief out of the fintech project, where a crossed-message worktree reset silently destroyed an uncommitted deliverable), adapted to this template's topology: (1) the existing sha-leading message convention expands into a full WORKFLOW.md § *Sha-pinned hand-offs* — frozen-sha reviews, merge-is-a-dispatch, and the **one writer per checkout** principle, with per-agent worktrees + full commit-based delivery named as the package deal for any escalation to concurrent writers; (2) `temp/` hand-offs split into *findings* (summarizable) vs *deliverables* (`kind: deliverable` + `target:` frontmatter → land verbatim, **verify-before-delete**, integrator reports `landed @ <sha>`, author verifies via `git show <sha>:<path>`).
**Why:** A description ("it's ready") is a claim about a moment that has passed; a sha either resolves or fails loudly. The template's prior protocol guaranteed temp/ files get *noticed* (sweep + SessionStart nag) but not *faithfully integrated* — placement was an unverified copy whose delete-in-the-same-action destroyed the only comparison source, and the author never saw the landed form. Pinning at the integrating commit closes both holes with zero new state.
**Alternatives considered:**
- Full commit-based delivery for all hand-offs now (per-agent worktrees / handoff refs) — rejected: our shared-checkout, one-committer topology lacks the incident's vector (a private worktree to reset); the cost would be paid on every hand-off against a failure class never observed here. Named as the designated upgrade path instead.
- Content-addressing temp files at authoring time (`git hash-object -w`, blob sha in the hand-off message) — rejected: the sha goes stale the moment the author legitimately revises the file, recreating the stale-description problem one level down, and a verification against a stale sha is worse than none. The integrating commit is the pinning point.
**Approved by:** Rich Mosko
**Supersedes:** _extends the 2026-08-20 sha-leading convention (WORKFLOW.md, adopted after four crossings on PT-3)._

### 2026-08-22 — Decision ledgers consolidated; TRACKER.md Resolutions log lives here
**Decision:** All decisions made in the template repo belong in this ledger — `DECISIONS.md` returns to its seed-stub state (its four accumulated entries migrated here, marked), and `TRACKER.md`'s Resolutions log moves here verbatim (below) as part of a TRACKER.md tightening pass; the spec keeps inline `ruled YYYY-MM-DD` stamps and points here.
**Why:** This repo *is* the template, so every decision here is a template decision; `DECISIONS.md` must ship clean as the seed for instantiated projects, and `TEMPLATE_DECISIONS.md` is deleted at bootstrap — so history parked here costs downstream projects nothing. TRACKER.md is pulled into agent context on every tracker task; history-prose belongs in the ledger, not the spec.
**Approved by:** Rich Mosko
**Supersedes:** _extends 2026-05-25 — `TEMPLATE_DECISIONS.md` separated from seed `DECISIONS.md`._

**The migrated cairn-spec Resolutions log** (rows 1–7 ruled 2026-08-19 at design time; 8 on 2026-08-20 during stage-2 conformance review; 9 on 2026-08-21 with PT-27; 10 on 2026-08-22 with PT-26 — each ruling is also folded into the TRACKER.md section it governs):

| # | Question | Ruling | Where it lives |
|---|---|---|---|
| 1 | Does `STATE.md` keep its *Major line*, *Roadmap*, and *Features* tables, or do they dissolve into cairn? | **Dissolve.** Stage 3 removes all four overlapping tables; `STATE.md` keeps Current Phase, Active Feature, Session Cycles, Releases, plus a board pointer and an optional `cairn snapshot`. The Completed-table rolloff ritual retires with them. | TRACKER.md → Relationship to `STATE.md` |
| 2 | Is losing Linear's cross-project board acceptable at v1? | **Accepted as a v1 regression at first (2026-08-19), then built read-only as PT-3 (2026-08-21)** — `roots:` in `config.yml` / `--repos`, warn-and-skip on unreachable roots, cross-root writes structurally refused (`403 read_only_root`). | TRACKER.md → Non-goals · API surface |
| 3 | How is the ID prefix chosen? | **Repo-derived default with a one-time confirm prompt** at `/setup-tracker`. | TRACKER.md → ID scheme · `config.yml` |
| 4 | Render markdown in the detail drawer, or ship `<pre>`? | **`<pre>` ships in phase 1.** Vendoring a JS renderer (the `vendor-mermaid.sh` path) is deferred until it demonstrably annoys. _(Later built: PT-4 shipped marked+DOMPurify in 0.5.)_ | TRACKER.md → Board — phase 1 scope |
| 5 | Should `/start-feature` reserve IDs on `main` to avoid cross-branch collisions? | **No — the git add/add conflict stays the detector.** A rare loud conflict beats an extra `main` commit per feature, forever. | TRACKER.md → ID scheme |
| 6 | Does the CLI violate "agents never need a server"? | **No — the CLI stands as specified.** The constraint reads as no-MCP / no-HTTP / no-JSON-in-context, which a one-line-printing local script satisfies. | TRACKER.md → CLI |
| 7 | Should the board write back acceptance-criteria checkboxes? | **Deferred.** Phase 1 keeps zero body-touching write paths (comment append excepted — tail-only). If ever built, it would be the first middle-of-file rewrite and needs its own design. | TRACKER.md → deferred work |
| 8 | Should `config.yml` carry a `data_dir` key so a project can relocate the tracker to a top-level `cairn/`? | **No — affordance removed (2026-08-20, stage-2 conformance review).** The key is circular: `config.yml` lives inside the directory it would declare. v1 fixes the layout at `process/cairn/`, and a **loud-error contract** replaces it — an unresolvable data dir is an error, never an empty result. | TRACKER.md → Directory layout · `config.yml` |
| 9 | With definition milestones moving to letter ids, do repos already seeded with `M0`/`M1` + `kind: process` get a grandfather clause? | **No clause (2026-08-21, PT-27).** `check_repo` errors on the old shape and the error string carries the migration. A permanent exception would mean "`M0` might be a definition milestone" forever — the exact ambiguity the convention deletes — and this template's own tracker has no `kind: process` milestone, so the clause would have zero users where the lint runs. | TRACKER.md → Milestone ids |
| 10 | Can a `blocked_by` reference cross roots, and does blocking enforce anything? | **Same-root only, and informational in v1 (2026-08-22, PT-26).** `check_repo` runs per-root, so a cross-root edge could never be validated by the lint that exists to guarantee referential integrity — the guarantee would be structurally unavailable, not merely unimplemented. Enforcement was considered and declined: it would need one predicate at three write paths and is unenforceable against a plain `Edit`, which the tracker fully supports. | TRACKER.md → Dependencies |

### 2026-08-20 — board.js test harness: zero-dependency node:test, no jsdom (PT-22)
_(Migrated from `DECISIONS.md`, 2026-08-22.)_
**Decision:** board.js's pure-logic functions are extracted into `scripts/cairn/board/board-logic.js` (a `CairnLogic` global loaded before board.js — no module system, no build step) and unit-tested with Node's built-in `node:test`/`node:assert`/`node:vm` under `scripts/cairn/tests/js/`. No jsdom, no npm, no `package.json`. Node is a soft prerequisite for the JS test suite only (board.js still runs framework-free in any browser); the JS suite skips-with-notice when Node is absent, and the Python suite stays the hard gate.
**Why:** The bug class that motivated this (PT-3's six id-collision lookups + the twice-written draggable predicate) is pure logic — it needs no DOM to test once the functions are extracted. Adding jsdom+npm to a *template* is the deciding cost: every instantiated project and every `/spin-off-component` inherits the toolchain whether or not it has any JS, and jsdom's transitive tree can't be byte-verified the way seceng's vendored deps (PT-4/PT-20) are. The extraction also converts two hand-maintained invariants into shared functions (`issueMilestoneKey`, `isDraggable`), removing the duplication class outright — the payoff independent of any test.
**Alternatives considered:**
- *jsdom + a test runner* — rejected: npm toolchain in a template, unverifiable transitive deps, contradicts the vendored-dependency posture.
- *Hand-rolled harness on Node stdlib* — rejected: `node:test` already is the minimal harness, maintained by the Node team; rolling our own only adds maintenance.
**Approved by:** Rich Mosko
**Supersedes:** _none — closes the coverage gap PT-3 exposed (board.js had zero automated tests). Bundled with PT-24 (the `/finish-feature` gate that never actually ran)._

### 2026-08-20 — Multi-root board layout: repo-grouped, read-only (PT-3)
_(Migrated from `DECISIONS.md`, 2026-08-22.)_
**Decision:** The multi-root board (`cairn serve` aggregating a `roots:` config list, or `--repos` which replaces it) is **read-only** and renders **repo-grouped** — a top-level section per repo, milestone lanes nested inside, each card repo-tagged. Single-root renders byte-identically to before (no repo wrapper). Because milestone/major ids are version-named and therefore **not** distinct across roots (every repo has a `0.5`, a `V1`), every id-keyed lookup is repo-scoped via a `repo::id` identity; the major-tab bar dedupes by bare id with union filtering while the lookup stays repo-scoped. `--repos` replaces the config list (`B`); `cairn check` validates `roots:` shape only, not reachability (`C`).
**Why:** Milestones only share a version string by coincidence across independently-versioned spun-off components, so fusing lanes on bare id would merge unrelated roadmaps — repo-grouping keeps each project legible, which is the point of a cross-project view. Read-only keeps writes structurally scoped to the primary root (no code path from a POST handler to a secondary root), sidestepping cross-root write-routing entirely for v1.
**Alternatives considered:**
- *Composite `repo·milestone` lanes* (architect's recommendation, lighter board.js change) — rejected by Mosko in favor of clearest project separation over smallest diff.
- *Fused lanes + card tags* (the literal reading of "keep milestone swimlanes, tag each card") — rejected: merges milestones that only share a version number.
- *Editable cross-root board* — deferred: cross-root write-routing is real complexity with no v1 need.
**Approved by:** Rich Mosko
**Supersedes:** _refines the 2026-08-19 "not cross-project by default" ruling; see TRACKER.md → Multi-root (PT-3)._

### 2026-08-20 — Cross-root read access accepted as a security risk (PT-3)
_(Migrated from `DECISIONS.md`, 2026-08-22.)_
**Decision:** Accept the trust-boundary widening from the multi-root board — `cairn serve` reading directories named in a committed `roots:` config — as a recorded Open Risk in [`docs/SECURITY`](../docs/SECURITY/index.html) rather than adding a runtime path-jail. Compensating control: a startup stderr banner logging each resolved root path.
**Why:** Read-only, localhost-only, no exfiltration channel, and config.yml-gated before any read; whoever can commit a `roots:` entry already has a stronger vector (editing the server code directly), so a path-jail would be theater against the real threat. seceng reviewed and recommended acceptance.
**Alternatives considered:**
- *Runtime path-jail confining `roots:` to a parent workspace* — rejected: closes a narrow sub-vector while leaving the actual attacker capability (commit access) untouched.
**Approved by:** Rich Mosko
**Supersedes:** _none — new Open Risk entry in [`docs/SECURITY`](../docs/SECURITY/index.html) § 11._

### 2026-08-20 — Template ships CLAUDE_CODE_ENABLE_TODO_TOOLS=1; degraded mode documented as fallback (#47)
**Decision:** Add `CLAUDE_CODE_ENABLE_TODO_TOOLS: "1"` to `.claude/settings.json` → `env`, alongside the agent-teams flag. The shared Task tools (`TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate`) are session-gated by model — absent by default on Opus 4.8 / Sonnet 5 / Fable 5 and later — so without the opt-in the anchor-task pattern is dead-by-default on current models. WORKFLOW.md's new *Task-tool availability & the degraded mode* section (PT-18) documents the gating, the opt-in, and the SendMessage + `temp/` fallback as the pattern's degraded mode.
**Why:** The template already commits to the agent-teams experiment; shipping a workflow whose primary coordination pattern silently cannot operate on current models is the worse state. Verified live: the flag took effect in the running session the moment it landed in settings (Claude Code reapplies settings `env` on save) and the Task tools appeared.
**Alternatives considered:**
- *Docs-only (document the opt-in, don't ship it):* leaves every derived project to rediscover the gap PT-17/PT-18 already paid for.
**Approved by:** Mosko
**Supersedes:** nothing — complements PT-18's documentation.

---

### 2026-08-20 — 0.5 milestone scoped: deferrals plus small follow-ups, backlog cleared
**Decision:** Cut the `0.5` milestone (major V1, `target_tag: v0.5.0`, name *polish*) with all six backlog issues: the three 0.4 deferrals — PT-2 (snapshot appendix), PT-3 (multi-root board), PT-4 (markdown drawer rendering) — plus the small follow-ups filed during the 0.4 cycle: PT-16 (board milestone names + swimlane expand/collapse), PT-18 (document the anchor-task degraded mode), PT-19 (check_repo title-shape lint). Suggested order: PT-18 → PT-19 → PT-16 → PT-4 → PT-2 → PT-3, saving the PT-3 design conversation for last as the largest item.
**Why:** The backlog is exactly six items and all are already committed direction — deferring any would be tracker overhead, not a real cut. PT-3 is the only item with design weight; sequencing it last keeps the milestone shippable even if that conversation pushes it out.
**Alternatives considered:**
- *Defer PT-3 to 0.6:* honest about its design weight, but strands a one-item milestone; sequencing last achieves the same protection.
**Approved by:** Mosko
**Supersedes:** nothing.

---

### 2026-08-20 — 0.4 milestone scoped: debt paid, engine hardened, board live
**Decision:** Cut the `0.4` milestone (major V1, `target_tag: v0.4.0`, name *hardening*) with 12 of the 15 backlog issues: the two committed debts — PT-14 (remove deprecated Linear skills + BACKLOG.md stub, due "one release after v0.3.0") and PT-15 (rename `process/MILESTONES.md` → `STATE.md`, ruled 2026-08-20) — plus the board headliner PT-1 (SSE live push), the P2 hardening set PT-5/PT-6/PT-12, and the small P3 fixes PT-7/PT-8/PT-9/PT-13 (CLI/parser) and PT-10/PT-11 (board drawer). Deferred to 0.5: PT-2 (snapshot appendix — depends on what the post-rename state file is), PT-3 (multi-root board — a design conversation, not a fix), PT-4 (markdown drawer rendering). Suggested cycle order: PT-15 first (widest blast radius), then PT-14, then the hardening batches, PT-1 last.
**Why:** The P3 items are each tiny — leaving them in backlog costs more tracker overhead than fixing them — while PT-2/3/4 are the only items with real design weight, so they are the honest cuts. Scope fits one session cycle.
**Alternatives considered:**
- *Lean (6 issues, P1/P2 only):* comfortable fit but strands a tail of trivial P3 fixes in backlog.
- *Everything (15 issues):* clears the backlog but spills past one session cycle and forces the PT-3 design conversation prematurely.
**Approved by:** Mosko
**Supersedes:** nothing.

---

### 2026-08-19 — In-template file-based issue tracker replaces Linear as the default backend (#28)
**Decision:** Build a file-based issue tracker — named **cairn** — as template infrastructure: one markdown file per issue (YAML frontmatter + appended attributed comments) living in each project's own repo, supporting the **major → milestone → issue → sub-issue** hierarchy per the 2026-07-23 version-driven model (the top level is named `major`, after the semver digit it is bound to; "initiative" retires with Linear, and "line" was rejected as too generic). Agents interact with it purely via file reads/writes — no server, no MCP. A small stateless local server (serve-docs pattern) provides a live Kanban/list board for the human, parsing the issue directory at request time, with drag-to-edit write-back that rewrites frontmatter; board edits dirty the working tree, never auto-commit. The engine ships inside the template (every instantiated project carries a copy), kept self-contained so `/spin-off-component` can extract it later if cross-project drift justifies it. Linear is replaced as the *default* backend — Linear skills remain one release, marked deprecated; no dual-backend abstraction. Delivery is staged as four PRs: design spec (`process/TRACKER.md`), engine, skills migration, dogfood.
**Why:** Linear's free tier caps active issues at 250 (a real bottleneck), forces 1-month auto-archive, allows one user (agent-hostile), and its MCP server is so verbose it required the `mcp-broker` firewall agent. Files-in-git keep what Linear did well (post-and-comment issue database, four-level hierarchy, Kanban visualization) while deleting the context-bloat problem outright: agents already have file tools, git supplies history/audit/undo for free, and the write volume (a handful of events per session) makes git-as-database genuinely correct.
**Alternatives considered:**
- *Vikunja (self-hosted, single Go binary + SQLite):* polished UI for free, but the service is the sole interface — agents would need `curl` + auth and JSON payloads back in context, issues wouldn't live in git next to the code, and a mandatory always-on daemon replaces an optional stateless lens. Plane rejected as heavier still (Docker + Postgres).
- *SQLite / PocketBase:* real queries and schema, but binary blob in git, comments become rows instead of readable prose, and the Kanban front end must be built anyway — PocketBase's actual value (auth, realtime, remote REST) is unneeded on a single machine.
- *AppFlowy:* Kanban out of the box but no scriptable local data access — trades MCP bloat for no programmatic agent access at all.
- *Standalone repo from day one:* cleanest fix propagation across projects, rejected for now per WORKFLOW.md's "don't split for size alone" — spin-off is the escape hatch once drift pain is demonstrated, not before.
**Approved by:** Mosko
**Supersedes:** nothing yet — Linear remains functional for existing derived projects; the skills-migration PR (stage 3) will supersede the Linear-specific workflow bindings.

---

### 2026-07-23 — Deployment topology: trunk-based, production deploys from tags
_(Migrated from `DECISIONS.md`, 2026-08-22.)_
**Decision:** Default deploy wiring is **preview → PRs, staging → `main`, production → release tags (`v*`)**; "no feature breaks `main`" is enforced by making required CI status checks a *mandatory* box in `main` branch protection, not by branch topology. Incomplete-but-mergeable work ships dark behind feature flags. A per-milestone integration branch is an opt-in exception, logged per-use.
**Why:** Keeps trunk-based development's small, continuously-reviewed PRs while making production advance only at milestone/release cadence — satisfying the CI/CD concern (prod never sees half-finished milestone work) without a long-lived integration branch that costs the 1:1 issue=PR=I→V invariant, forces big-bang reviews, and accumulates drift.
**Alternatives considered:**
- *Milestone-integration branch as default* (features → `milestone/N.y` → one PR to `main` at milestone close) — rejected as default: breaks the 1:1 invariant, degrades review quality, drifts from `main`; kept as a logged opt-in for un-flaggable atomic work.
- *Point production directly at `main`* — rejected: makes every feature merge a prod deploy, the exact churn the concern was about.
- *Rely on the `self-merge-within-milestone` autonomy knob* — orthogonal (it moves the *human gate*, not the *deploy target*); doesn't address CI/CD.
**Approved by:** Rich Mosko
**Supersedes:** _none — new section in [`WORKFLOW.md`](WORKFLOW.md) → Deployment topology._

### 2026-07-23 — Version-driven hierarchy: Initiative-per-major, semver binding, Session Cycles
**Decision:** Rebind the workflow hierarchy so version numbers drive the Linear layers. A Linear **Initiative** now scopes **one major version line** (`V1`, `V2`, …) rather than the whole project forever — a breaking change opens a new Initiative, `V1.x`/`V2.x` run as concurrent Initiatives, and an Initiative closes when its line is EOL'd. Releases follow **strict semver** with `MAJOR`←Initiative, `MINOR`←milestone (product milestones **named by target version**, one milestone per `MINOR` — "Model A"), `PATCH`←hotfix; a feature is **not** a version digit (identity = Linear issue ID + release notes). The **GA milestone** (`→ vN.0.0`) is explicitly designated during Plan via a Roadmap *Target tag* column, never inferred from position; `0.y.z` is the founding line's pre-1.0 zone and later majors use pre-release identifiers (`2.0.0-rc.1`); parallel majors are maintained via long-lived `release/N.x` branches with a flat tag namespace. The old **Sprint** layer is renamed **Session Cycle** — a **context-budget-bounded** working session (heuristic only, **no Linear Cycle**), with **session planning at the start** of each session as the new trigger for `/sync-backlog` promotion and `/cleanup-linear` archiving. Propagated across `WORKFLOW.md`, `MILESTONES.md`, `CLAUDE.md`, `README.md`, the `architect`/`mcp-broker` agents, and the `start-feature`/`merge-pr`/`sync-backlog`/`cleanup-linear`/`setup-linear-team`/`drive` skills.
**Why:** Requested by the maintainer to make the model AI-native and version-legible. Per-major Initiatives give an Initiative a natural close and enable simultaneous `V1` maintenance + `V2` development (impossible under one-Initiative-forever). Binding semver digits to layers makes "what version does this milestone ship?" mechanical. Dropping the Linear Cycle removes a whole class of expensive Linear MCP calls — the real WIP limit in an AI-driven project is the context window, not the calendar, so a context-bounded Session Cycle is both cheaper and more honest.
**Alternatives considered:**
- *`PATCH = feature` (tag-per-PR):* the maintainer's first instinct; rejected for the default because it spends semver's compatibility signal on internal bookkeeping and churns tags. Documented as an opt-in only for continuous-deploy app projects; strict semver is the default (spin-off components must honor semver regardless).
- *Keep Session Cycle mirrored to a Linear Cycle (optional, off by default):* rejected — any Linear footprint reintroduces the token cost the change exists to remove.
- *Multiple pre-GA product milestones converging on GA ("Model B"):* rejected in favor of Model A (one subdividable `N.0` milestone with `-alpha/-beta/-rc` checkpoints) to keep milestone↔`MINOR` strictly 1:1.
- *Milestone ordinal drives `MINOR`:* rejected — process milestones don't tag, so the `Mn` label runs ahead of `MINOR`; naming product milestones by version makes the mapping unambiguous instead.
**Approved by:** Mosko
**Supersedes:** the prior "Project = one Initiative for the whole repo; Sprint = Linear Cycle" mapping in `WORKFLOW.md` → Version control & Linear.

---

### 2026-07-21 — `mcp-broker` context-firewall agent for verbose remote MCP servers
**Decision:** Ship a tenth teammate, `mcp-broker` (`.claude/agents/mcp-broker.md`), that owns the chatty remote MCP servers (Linear, Google Drive, Gmail, Calendar, Spotify). Callers delegate a *query intent* via `SendMessage`; the broker makes the fat MCP call in its own isolated context and returns only the distilled fact + IDs. Wired in **additively** — the nine specialists keep their own `mcpServers` and the Linear skills keep calling Linear directly; the broker is an opt-in escape hatch for ad-hoc, payload-heavy traffic, documented in `WORKFLOW.md` → MCP Broker, `CLAUDE.md`, and `README.md`.
**Why:** Surfaced as upstream feedback from a derived project — touching Linear caused large jumps in context % because the multi-KB JSON those tools return lands permanently in the team-lead's window. A subagent has an isolated context, so routing the raw payload through a broker keeps the bloat off the lead and returns ~3 lines instead of ~5 KB. The win is largest on reads (`list_issues`, `get_issue`, `get_project`, `get_thread`, `search_files`); writes return little, so the broker covers them for single-writer tidiness rather than context savings.
**Alternatives considered:**
- *Full rewire (strip `mcpServers` from the nine + route the Linear skills through the broker):* maximum savings but couples every agent + ~15 skill files to the broker being alive; large, error-prone edit. Deferred — revisit if additive delegation proves insufficient.
- *Rewire agents only (strip `mcpServers` from the nine, leave skills):* enforces the pattern but still couples every agent to a live broker for no gain when a direct call is cheaper. Rejected in favor of additive opt-in.
- *Broker owns all MCP incl. Figma + claude-in-chrome:* those are interactive, per-node/live-session tools a broker can't distill — counterproductive. Scoped to remote-JSON servers only.
- *Give the broker an `agent:<role>` Linear label:* it's a utility that doesn't own issues, so no attribution label; the nine-label seed in `/setup-linear-team` stays nine.
**Approved by:** Mosko

---

### 2026-05-30 — Team-mode `task_assignment` echo-suppression convention
**Decision:** Codify the "silently drop self-known `task_assignment` notifications" convention at the template level. Add an explanatory subsection to `WORKFLOW.md` → Team coordination ("Async notification mechanics") and append a short standardized heads-up block to every `.claude/agents/*.md` so the convention lands in each teammate's persistent system prompt at spawn time.
**Why:** Surfaced as upstream feedback from a derived project (mosko-fintech Phase 3 ARCH session, PRs #65–#69). Team-mode fires a `task_assignment` notification on every `TaskUpdate` ownership change — including self-claim — and queues it for the assignee's next turn boundary, which is typically *after* the agent has already delivered its work. Without a heads-up, the agent has no provenance check and produces a defensive "sync-mismatch echo" message that wastes a turn on each end. Observed at ~70% rate (14/20 events) on the derived project. Mitigation tested at the project level; codifying at the template tier lets every downstream repo benefit without rediscovering the pattern.
**Alternatives considered:**
- *Skill-level convention only (e.g. in `/start-feature`):* this template doesn't centralize spawn prompts in a single skill — teammates' persistent context is their `.claude/agents/*.md` file, so a skill-only fix would miss most spawn paths.
- *WORKFLOW.md only (no per-agent duplication):* canonical explanation but doesn't reach the agent's system prompt at spawn time — teammates would only see it if they read WORKFLOW.md on demand.
- *Repo-level standalone doc (`docs/team-mode-conventions.md`):* less discoverable; not auto-loaded into agent context. Rejected.
- *Upstream platform fix (provenance flag on notifications):* cleanest long-term but out of scope for the template. If/when Claude Code adds a `selfTriggered: true` flag, the convention can be relaxed.
- *Switch all task ownership to lead-claim:* doesn't solve the problem — lead-claim fires the same notification shape to the assignee; the echo still happens.

**Approved by:** Mosko

---

### 2026-05-28 — UX/UI design artifact home (`docs/DESIGN/`) + `/generate-designdoc` (#16)
**Decision:** Give UX/UI design its own first-class artifact home at `docs/DESIGN/` — an `index.html` doc plus the design-system deliverables (`tokens.css`, `screen.css`, `design-system-spec.md`) and `wireframes/` / `flows/` / `styled-screens/`. Owned by the `ux-designer` agent; generated/refined by a new `/generate-designdoc` skill; wired into the same doc-review loop (comments sidecar, `/refine-doc DESIGN`, `/serve-docs DESIGN`) as the other docs.
**Why:** Design previously had no home of its own — flows/wireframes lived only in Figma + the PRD's Design Considerations section, and there was nowhere in-repo for a code-level design system (tokens/CSS) that `frontend-lead` consumes directly. Surfaced on a real test project.
**Alternatives considered:**
- *Keep design in Figma + the PRD only:* loses the in-repo, reviewable, code-level system and couples the contract to an external tool. Rejected.
- *Tier 1 only (seed the home, skip the skill + review-loop wiring):* would leave DESIGN a second-class doc inconsistent with PRD/ARCH/SECURITY. Rejected for full parity.
- *Treat `tokens.css`/`screen.css` as app source, not a design deliverable:* they're the design *contract* — during Implement `frontend-lead` derives the app's real styles from them; keeping them in `docs/DESIGN/` keeps them reviewable and decoupled from any one app layout.
**Notes:**
- **Cross-phase:** flows/wireframes begin late-Research; the design system matures through Plan/Implement. `start-doc-update` defaults `docs/DESIGN/*` to `phase/research-<slug>`.
- Figma stays the high-fidelity tool; `docs/DESIGN/` is the in-repo home, kept in sync via exports + Code Connect.

**Approved by:** Mosko

---

### 2026-05-28 — Shared / reusable components model + `/spin-off-component` (#15)
**Decision:** Add a "Shared / reusable components" model to the workflow. A substantial, reusable component graduates to its own repo as a fresh template instance with its own Linear Initiative, released on its own cadence via semver git tags, and consumed by parent projects as a tag-pinned dependency. Ship `/spin-off-component` to mechanize the history-preserving extraction + repo creation + initial `v0.1.0` release + linkage recording; **borrow** stays a documented procedure (no skill).
**Why:** For a solo dev the recurring driver is reuse — a component used by ≥2 projects, needing its own release clock, or already built elsewhere. The shared-team / multi-Initiative model already supports this with no new infra; the only gaps were a graduation rubric, a linkage convention, and mechanizing the error-prone git extraction.
**Alternatives considered:**
- *Submodules / subtree as the default coupling:* sharp edges (detached HEAD, fiddly merge-back). Kept as opt-in for "borrow"; not the default.
- *Monorepo workspaces only (never split):* the right answer when the driver is size/context — documented as the "don't split" path — but doesn't serve genuine reuse / independent release.
- *Give "borrow" its own skill too:* deferred — pinning a dependency + recording linkage is light enough to stay convention-only until it proves repetitive.
- *Require a package registry:* unnecessary for solo dev; git tags are consumed natively by every major ecosystem.

**Approved by:** Mosko

---

### 2026-05-28 — `/drive` goal-driven loop + delivery-autonomy methodologies (#14)
**Decision:** Add the `/drive` skill, which prepares a native `/goal` loop to run an Implement→Validate cycle hands-off and **surfaces the `/goal` line for the user to paste** (a skill cannot self-issue `/goal`). Two delivery-autonomy methodologies, chosen per project at `/setup-linear-team`: `stop-at-merge` (default) and `self-merge-within-milestone`.
**Why:** Lets a large project be driven deliverable-by-deliverable with less turn-by-turn prompting, while keeping a human checkpoint at goal-set time. `stop-at-merge` preserves the per-feature human gate; `self-merge` trades it for unattended speed within a milestone (needs auto mode). Phase-gate transitions stay human under both.
**Alternatives considered:**
- *A skill that self-issues `/goal`:* impossible — no model-callable goal tool, no `SlashCommand` tool (verified against Claude Code docs). Construct-and-paste is the supported pattern.
- *Stop hook or nested `claude -p "/goal"` subprocess to fake self-issue:* unsupported (no mid-session hook hot-reload; nested sessions contend over state). Rejected.
- *Convention-only (no skill):* rejected — assembling a ~4,000-char condition from live state each loop is error-prone.

**Approved by:** Mosko

---

### 2026-05-25 — Template gets its own semver tags + GitHub Releases
**Decision:** The `project_template` repo will tag its own semver versions (`vX.Y.Z`) and publish GitHub Releases, using the same `/merge-pr`-prompted process the template defines for downstream projects. Only meaningful template-shape changes get a tag — not every PR.
**Why:** Downstream projects need a way to say *"this project was bootstrapped from project_template vX.Y.Z"* for recovery and debugging. Without tags, every workflow bug becomes "which commit of the template were you on?" guesswork. The template should eat its own dog food on this convention.
**Alternatives considered:**
- *Always-current template (no tags):* simpler, but loses the pin-point affordance. Rejected.
- *Date-based versioning (YYYY.MM.DD):* clearer ordering, but breaks the convention the template defines for downstream. Rejected for consistency.
- *Tag every merged PR:* too noisy; defeats the "release = milestone" intent. Rejected.

**Mechanics:**
- First tag: **v0.1.0**, cut from `main` immediately after this PR merges. Covers everything in `#1`–`#13`, including the versioning system itself.
- Bootstrap step in `CLAUDE.md` writes the template version into the new project's `DECISIONS.md` bootstrap entry: *"Bootstrapped from project_template vX.Y.Z."*
- No `CHANGELOG.md` (per existing template convention). GitHub Releases auto-draft from PR titles, curated and published manually.

**Approved by:** Mosko

---

### 2026-05-25 — `TEMPLATE_DECISIONS.md` separated from seed `DECISIONS.md`
**Decision:** Decisions about the template itself live in `TEMPLATE_DECISIONS.md` (root, deleted on bootstrap). The seed `DECISIONS.md` only contains format scaffolding + a bootstrap example, with no template-meta entries.
**Why:** Without separation, template-meta decisions accumulate in `DECISIONS.md` and travel into every downstream project as irrelevant baggage. The two logs have different audiences and lifecycles.
**Alternatives considered:**
- *Single `DECISIONS.md` with a "template" section:* downstream projects would have to remember to strip it. Brittle. Rejected.
- *Hidden directory `.template-meta/`:* cleaner namespace but easy to forget; harder to discover in GitHub's file tree. Rejected.

**Approved by:** Mosko

---

### 2026-05-25 — Team-agents requirement made explicit in `CLAUDE.md` (#12)
**Decision:** `CLAUDE.md` (auto-loaded every session) states explicitly that the template requires Claude Code's experimental team-agents feature, names the two settings, and warns that disabling them breaks `SendMessage` / shared task list / anchor-task coordination.
**Why:** Prior wording said *"verify teammate mode"*, which could be read as *"pick a mode"* rather than *"team-agents must be on."* The README + WORKFLOW.md already enforced it; CLAUDE.md was the gap.

**Approved by:** Mosko

---

### 2026-05-23 — `/serve-docs` skill: background docs server under Claude session (#11)
**Decision:** Add a `/serve-docs` skill that runs `scripts/serve-docs.sh` as a background process owned by the Claude harness, with `start | status | stop | <DOC>` subcommands. Server lifecycle is bound to the Claude session — dies on `/exit`.
**Why:** Without it, the user had to keep a separate terminal open to run the comments-sidecar server. The skill collapses that into a single in-session command.
**Trade-off:** Server logs go to the harness's background-shell buffer, not the user's terminal. For debugging the server itself, the standalone `./scripts/serve-docs.sh` invocation still works.

**Approved by:** Mosko

---

### 2026-05-23 — PRD `§appendix` numbering + comments-FAQ default (#10)
**Decision:** Number the PRD's `§appendix` consistently with prior sections (`11.` H2 / `11.1` H3) and replace the placeholder FAQ Q/A with a real default Q&A about the comments-sidecar workflow. Also added a `section h3` rule to `doc.css` so H3 subsections render distinctly from their parent H2.
**Why:** Surfaced during the first real `/refine-doc` dogfood pass. The PRD's TOC numbered the appendix but the body didn't; H3s under H2 sections inherited browser defaults and read indistinct.

**Approved by:** Mosko

---

### 2026-05-23 — Comments-sidecar Pass 2: inline widget + local server (#9)
**Decision:** Layer an inline comment-authoring UX (`docs/_assets/comments.js` + `comments.css`, served by `scripts/serve-docs.py` / `.sh`) on top of Pass 1's `comments.md` convention. Widget detects doc from URL, shows a status badge, injects `+ Comment` and `💬 N` buttons next to every `<section>` heading.
**Why:** Hand-editing `comments.md` works but is friction-heavy. Inline authoring removes the friction without changing the on-disk format — widget-authored and hand-edited comments use the same `## §<section-id>` shape and feed `/refine-doc` identically.
**Security shape:** Server binds `127.0.0.1` only (no LAN exposure); two API endpoints; `doc` whitelist-validated; `section` regex-validated; no auth (localhost only).
**Graceful degradation:** Opened via `file://` (no server) → widget shows offline badge; doc remains readable; hand-editing still works.

**Approved by:** Mosko

---

### 2026-05-23 — Comments-sidecar Pass 1: convention + `/refine-doc` skill (#8)
**Decision:** Establish `docs/<DOC>/comments.md` as the per-doc review sidecar (gitignored), with `## §<section-id>` blocks anchored to existing `<section id="...">` IDs in the HTML doc. New skill `/refine-doc <PRD|ARCH|SECURITY>` walks the sidecar, addresses each comment in the matching HTML section, and removes addressed comments as it goes.
**Why:** The doc-review feedback loop needed a structured-but-low-overhead surface. Sidecar files keep working notes out of the committed doc; the resolution (the doc edit) is what gets committed.
**Decisions baked in:**
- Per-section granularity (reuses existing `<section id="...">` anchors).
- Addressed comments are removed (not struck through or archived).
- Single-user assumed; multi-user attribution deferred.
- Commit shape: one batch commit per `/refine-doc` run, listing addressed sections in the body.
- Sidecar files gitignored at the template level (in-process working notes only).

**Approved by:** Mosko

---

### 2026-05-23 — `/open-doc` invokes browser explicitly, bypassing `.html` LaunchServices default (#7)
**Decision:** `/open-doc` Step 2 on macOS uses `open -a "Google Chrome" <path> 2>/dev/null || open -a "Safari" <path>` instead of the bare `open <path>`. Linux/Windows guidance unchanged.
**Why:** macOS LaunchServices `.html` defaults drift to whatever editor was installed last (MacVim, VS Code, Sublime) — a common side-effect of editor installs. The explicit `-a` bypass routes the doc to an actual browser regardless of LS state.
**README "Customizing doc preview"** documents how to swap the preferred browser by editing a single string.

**Approved by:** Mosko

---

### 2026-05-23 — HTML docs live in per-doc subdirectories (#6)
**Decision:** Each top-level HTML doc gets its own subdirectory with `index.html` as the entry point. `docs/PRD.html` → `docs/PRD/index.html`; same for `ARCH` and `SECURITY`. Path-style references use the new form; bare prose references shorten to `PRD` / `ARCH` / `SECURITY`.
**Why:** Forward-plans for growth. When a doc accumulates supporting assets (mockup images, threat-model graphics, sub-pages), they sit alongside the index without crowding template-shared `docs/_assets/`. The `index.html` filename stays stable as the entry point even if a doc later splits into multiple files.

**Approved by:** Mosko

---

### 2026-05-23 — Mermaid: CDN by default, vendoring script for offline/regulated projects (#5)
**Decision:** HTML docs load Mermaid via `docs/_assets/mermaid-init.js` from `cdn.jsdelivr.net` by default. Projects with CDN-access restrictions (fintech, healthcare, air-gapped) run `scripts/vendor-mermaid.sh` to download the UMD bundle to `docs/_assets/vendor/` and rewrite the init script to load from local file.
**Why:** Most projects work fine with the CDN — zero setup, always-current Mermaid version. Regulated projects can't. A one-command vendor script covers both audiences without forcing the template to pick a default that's wrong for half its users.
**Implementation choices:**
- UMD (not ESM) so `file://` URLs continue to work for doc preview.
- Vendor directory gitignored at the template level so the template itself isn't bloated by the ~3MB bundle. Downstream projects choose commit-or-not.
- Version overridable: `MERMAID_VERSION=11.4.0 ./scripts/vendor-mermaid.sh`.
- Idempotent; revert via `git checkout`.

**Approved by:** Mosko

---

### 2026-05-23 — Doc additions from mosko-fintech feedback (#4)
**Decision:** Several documentation additions surfaced from adoption notes on a derived project:
- README: new "Common project-specific extensions" section (Visual Designer / Compliance Officer / Data-pipeline Lead as documented optional add-on roles) + new "Customizing doc preview" section.
- WORKFLOW.md: Decision logging "What goes where" table separating DECISIONS / git+MILESTONES / GitHub Releases. New "Release process" subsection formalizing `gh release create --generate-notes --draft → curate → publish`. Explicitly states the template does NOT ship `CHANGELOG.md`.
- `/merge-pr` skill: Step 6 prompts for both the tag and the GitHub Release draft, with curation handoff to the Principal.
- MILESTONES.md: Roadmap table gains an explicit **Gate** column.

**Why:** Adopting projects surfaced gaps the template hadn't anticipated. Bundled as one PR because individually they're each too small to justify the full I→V loop.

**Approved by:** Mosko

---

### 2026-05-22 — Seed M0 + M1 process milestones at bootstrap (#3)
**Decision:** `/setup-linear-team` creates **M0 (Bootstrap & Research)** and **M1 (Plan)** as Linear projects and back-fills the MILESTONES.md Roadmap with both rows at project Day 0. Each phase can be subdivided if complexity warrants (`M0a`, `M0b`...); the two seeded rows are a floor, not a cap.
**Why:** Without seeded process milestones, the Roadmap is empty until the architect populates product milestones during M1 — which makes Research and Plan phases invisible in Linear's Roadmap view. Seeding M0/M1 makes the heavyweight phases first-class trackable units from session one.

**Approved by:** Mosko

---

### 2026-05-22 — SessionStart hook robustness + Resume runbook (#2)
**Decision:**
- `SessionStart` hook uses `awk '/^## Roadmap/{exit} {print}'` to capture MILESTONES.md head through (but not including) the Roadmap section, instead of `head -40`. Robust to row drift.
- `CLAUDE.md` → Session management gains a 6-step **Resume runbook** for fresh "let's continue" sessions: read full MILESTONES → inspect git → match branch to context → check open PRs → read WORKFLOW only if needed → confirm pickup point before acting. Plus a mid-feature gotcha callout.

**Why:** Hard-coded `head -40` silently broke when MILESTONES tables grew past 40 lines. Cold-start resumes were over-relying on the auto-injected head and missing important context (Active Feature row drift, branch-state mismatches).

**Approved by:** Mosko

---

### 2026-05-22 — PRD aligned with "Aligned" template elements (#1)
**Decision:** Cross-reference the template's PRD against chatprd.ai's template and the internal "Aligned" PRD Google Doc; pull in selected elements that fit a team-of-agents workflow:
- Added §1.1 **High-Level Approach** (subsection of Overview).
- Reframed §3 **Non-Goals** to require the *why*.
- Added an **FAQs** subsection under Appendix.
- Normalized §2 **Goals & Success Metrics** from a table to an ordered list for consistency with Non-Goals.

**Skipped** (deliberately): phase sign-off gates (too formal for solo + agents), operational checklist (out of scope), in-doc changelog (lives in `DECISIONS.md`).

**Approved by:** Mosko

---

<!--
Add new template-meta decisions ABOVE this comment, newest first.
-->
