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
└── archive/PT-1.md          same schema; moved here as hygiene

scripts/cairn/            THE ENGINE — self-contained, spin-off-ready
├── cairn                 bash shim → cairn.py
├── cairn.py              CLI + parser + server (stdlib only)
└── board/                board.html · board.js · board-logic.js · board.css · vendor/
```

**Data under `process/`** because it *is* process state — sibling to `STATE.md`, `DECISIONS.md`, and still a distinctive grep root.

**The layout is fixed at `process/cairn/` in v1 — no `data_dir` key (ruled 2026-08-20).** Such a key would be circular: `config.yml` lives *inside* the directory it would declare, so the engine must find the directory before it can read where the directory is. Relocation, if ever wanted, belongs to an env var or a flag.

**A missing or config-less data dir is an error, never an empty result.** If the engine can't resolve a directory containing `config.yml` it says so and exits non-zero — it does not report zero issues. "No tracker here" and "no issues here" are different facts and must never render identically.

**Engine under `scripts/cairn/`** and nowhere else. It touches no project file outside `process/cairn/`, so `git subtree split --prefix=scripts/cairn` extracts it cleanly — a combined `cairn/` would drag every project's issue history into the extracted repo.

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

`process/cairn/archive/` holds the same files, moved. The board reads the live directories only. Layout:

```
archive/PT-14.md              issues
archive/milestones/PT-0.4.md  milestones   (PT-39)
archive/majors/PT-V0.md       majors       (PT-39)
```

Issues stay at the top level rather than moving to `archive/issues/`: `_dir_glob` is non-recursive, so the two subdirectories are invisible to every existing glob and cost no migration. Archiving is invoked explicitly — **exactly one selector, always**, and `--dry-run` previews any of them:

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

### API surface

Five endpoints. All bind `127.0.0.1`, no auth — same posture as `serve-docs.py`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/board` | Full parsed state: majors, milestones, all non-archived issues (without comment bodies). Supports `ETag`/`If-None-Match`. |
| `GET` | `/api/issue/<id>` | One issue: frontmatter, description, acceptance criteria, full comment list, `seen` token. |
| `GET` | `/api/events` | SSE stream (`text/event-stream`). A background thread `os.scandir`s the data dir every 500 ms and diffs `(path, mtime_ns)` — not a kernel fs-watch, since `kqueue`/`inotify` have no portable stdlib wrapper. Emits `{"type":"changed"\|"created"\|"removed","ids":[…]}`; the client refetches only the named issues. |
| `POST` | `/api/issue` | Create. Body `{title, …}`. Allocates an ID via the same `O_EXCL` path as `cairn new`. **Primary root only** — there is no way to create an issue in a secondary root through the board. |
| `POST` | `/api/issue/<id>` | Mutate. Body `{seen, patch?, comment?}`. Handles the drag-to-column case (`patch: {status: …}`), inline field edits, and comment append through one code path. **Primary root only** — an id that resolves to a secondary root is refused with `403 {"error": "read_only_root", "message": "…"}`, file left untouched. |

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
| `cairn check` | Lint: id/filename mismatch, dangling `parent`, unknown `milestone`, bad `status` (issues **and** milestones/majors, each against its own vocabulary — see [Milestone / major status vocabulary](#milestone--major-status-vocabulary)), an archived issue whose milestone isn't `done`/`cancelled` (see [Archive](#archive)), milestone id-shape ↔ `kind` agreement (see [Milestone ids](#milestone-ids--definition-vs-development)), `blocked_by` dependency integrity (dangling ref, self-reference, cycles — see [Dependencies](#dependencies)), unsupported YAML, `config.yml`'s `roots:` shape (list of non-empty relative-path strings — reachability is a runtime concern, not lint, see [Multi-root](#multi-root-pt-3-2026-08-21)), milestone/major/issue id **prefix shape** (see [Milestone ids](#milestone-ids--definition-vs-development)), `config.yml`'s `prefix:` (present and matching `^[A-Z]{2,5}$` — every id regex is derived from it). |
| `cairn migrate prefix-ids [--dry-run]` | One-shot 0.6.1 migration: prefixes bare major/milestone ids and retargets every `major:`/`milestone:` reference. Idempotent — safe to re-run after an interruption. Runs on a repo whose lint is failing; that is its purpose. |
| `cairn migrate lifecycle-status [--dry-run]` | One-shot 0.7.0 migration: rewrites milestone/major `status:` onto the [unified vocabulary](#milestone--major-status-vocabulary) — `completed` → `done`, `active` → `in-progress`. Value-keyed, so idempotent by construction; any other value is left untouched for the lint to report. Same posture as `prefix-ids`: runs on a repo whose lint is already failing. |
| `cairn serve [--repos a,b]` | The board. `--repos` (PT-3) replaces `config.yml`'s `roots:` for that invocation — read-only cross-project aggregation, see [Multi-root](#multi-root-pt-3-2026-08-21). |

**The CLI is legitimate under "agents never need a server" (ruled 2026-08-19)** — that constraint reads as *no MCP, no HTTP, no JSON payloads in context*, which a local script printing one line satisfies.

**Hand-editing stays fully supported** — the files are the interface; the CLI is a convenience. But prefer `cairn ls` over grepping a directory (saves context) and `cairn new` over composing a file (the only race-safe allocation).

### Board

**Kanban view (`/`)**
- Columns per [`board.columns`](#configyml) — the five defaults (`backlog` → `done`) unless the project narrows or reorders them; `cancelled` behind a filter toggle.
- **Card:** ID · title · assignee chip · label chips · milestone chip · `2/3` sub-issue badge (or a `↳ parent` badge on a child) · a blocked chip when the issue has **open** blockers.
- **Swimlanes by milestone**, collapsible, toggleable to flat. One swimlane dimension only — assignee/label swimlanes are a filter away and don't earn a second layout mode.
- **Header:** major tabs (concurrent majors are first-class), then per-milestone progress — `1.0 · GA · v1.0.0 · 7/12 done`.
- **Filters** (client-side over the one `/api/board` payload): milestone, assignee, label, major, free-text. Keeping filtering in the browser is what keeps the API at one read endpoint.
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
