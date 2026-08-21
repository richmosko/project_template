# Decisions

> Append-only log of non-trivial decisions made over the life of this project. Conventions in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
>
> This file lives **outside** `STATE.md` so it doesn't bloat the auto-loaded session context. Pull this file in explicitly when you need to recall *why* a past decision was made.

## Format

```
### YYYY-MM-DD — <short decision title>
**Decision:** <one sentence>
**Why:** <one or two sentences>
**Alternatives considered:** <bullets>
**Approved by:** <name>
**Supersedes:** <ref to prior decision, if any>
```

The log is **append-only**. Don't edit historical entries. If a past decision is overturned, add a **new** entry that says so and references the entry it supersedes.

---

### 2026-08-20 — board.js test harness: zero-dependency node:test, no jsdom (PT-22)
**Decision:** board.js's pure-logic functions are extracted into `scripts/cairn/board/board-logic.js` (a `CairnLogic` global loaded before board.js — no module system, no build step) and unit-tested with Node's built-in `node:test`/`node:assert`/`node:vm` under `scripts/cairn/tests/js/`. No jsdom, no npm, no `package.json`. Node is a soft prerequisite for the JS test suite only (board.js still runs framework-free in any browser); the JS suite skips-with-notice when Node is absent, and the Python suite stays the hard gate.
**Why:** The bug class that motivated this (PT-3's six id-collision lookups + the twice-written draggable predicate) is pure logic — it needs no DOM to test once the functions are extracted. Adding jsdom+npm to a *template* is the deciding cost: every instantiated project and every `/spin-off-component` inherits the toolchain whether or not it has any JS, and jsdom's transitive tree can't be byte-verified the way seceng's vendored deps (PT-4/PT-20) are. The extraction also converts two hand-maintained invariants into shared functions (`issueMilestoneKey`, `isDraggable`), removing the duplication class outright — the payoff independent of any test.
**Alternatives considered:**
- *jsdom + a test runner* — rejected: npm toolchain in a template, unverifiable transitive deps, contradicts the vendored-dependency posture.
- *Hand-rolled harness on Node stdlib* — rejected: `node:test` already is the minimal harness, maintained by the Node team; rolling our own only adds maintenance.
**Approved by:** Rich Mosko
**Supersedes:** _none — closes the coverage gap PT-3 exposed (board.js had zero automated tests). Bundled with PT-24 (the `/finish-feature` gate that never actually ran)._

### 2026-08-20 — Multi-root board layout: repo-grouped, read-only (PT-3)
**Decision:** The multi-root board (`cairn serve` aggregating a `roots:` config list, or `--repos` which replaces it) is **read-only** and renders **repo-grouped** — a top-level section per repo, milestone lanes nested inside, each card repo-tagged. Single-root renders byte-identically to before (no repo wrapper). Because milestone/major ids are version-named and therefore **not** distinct across roots (every repo has a `0.5`, a `V1`), every id-keyed lookup is repo-scoped via a `repo::id` identity; the major-tab bar dedupes by bare id with union filtering while the lookup stays repo-scoped. `--repos` replaces the config list (`B`); `cairn check` validates `roots:` shape only, not reachability (`C`).
**Why:** Milestones only share a version string by coincidence across independently-versioned spun-off components, so fusing lanes on bare id would merge unrelated roadmaps — repo-grouping keeps each project legible, which is the point of a cross-project view. Read-only keeps writes structurally scoped to the primary root (no code path from a POST handler to a secondary root), sidestepping cross-root write-routing entirely for v1.
**Alternatives considered:**
- *Composite `repo·milestone` lanes* (architect's recommendation, lighter board.js change) — rejected by Mosko in favor of clearest project separation over smallest diff.
- *Fused lanes + card tags* (the literal reading of "keep milestone swimlanes, tag each card") — rejected: merges milestones that only share a version number.
- *Editable cross-root board* — deferred: cross-root write-routing is real complexity with no v1 need.
**Approved by:** Rich Mosko
**Supersedes:** _refines the 2026-08-19 "not cross-project by default" ruling in [`TRACKER.md`](TRACKER.md); see Multi-root (PT-3)._

### 2026-08-20 — Cross-root read access accepted as a security risk (PT-3)
**Decision:** Accept the trust-boundary widening from the multi-root board — `cairn serve` reading directories named in a committed `roots:` config — as a recorded Open Risk in [`docs/SECURITY`](../docs/SECURITY/index.html) rather than adding a runtime path-jail. Compensating control: a startup stderr banner logging each resolved root path.
**Why:** Read-only, localhost-only, no exfiltration channel, and config.yml-gated before any read; whoever can commit a `roots:` entry already has a stronger vector (editing the server code directly), so a path-jail would be theater against the real threat. seceng reviewed and recommended acceptance.
**Alternatives considered:**
- *Runtime path-jail confining `roots:` to a parent workspace* — rejected: closes a narrow sub-vector while leaving the actual attacker capability (commit access) untouched.
**Approved by:** Rich Mosko
**Supersedes:** _none — new Open Risk entry in [`docs/SECURITY`](../docs/SECURITY/index.html) § 11._

### 2026-07-23 — Deployment topology: trunk-based, production deploys from tags
**Decision:** Default deploy wiring is **preview → PRs, staging → `main`, production → release tags (`v*`)**; "no feature breaks `main`" is enforced by making required CI status checks a *mandatory* box in `main` branch protection, not by branch topology. Incomplete-but-mergeable work ships dark behind feature flags. A per-milestone integration branch is an opt-in exception, logged per-use.
**Why:** Keeps trunk-based development's small, continuously-reviewed PRs while making production advance only at milestone/release cadence — satisfying the CI/CD concern (prod never sees half-finished milestone work) without a long-lived integration branch that costs the 1:1 issue=PR=I→V invariant, forces big-bang reviews, and accumulates drift.
**Alternatives considered:**
- *Milestone-integration branch as default* (features → `milestone/N.y` → one PR to `main` at milestone close) — rejected as default: breaks the 1:1 invariant, degrades review quality, drifts from `main`; kept as a logged opt-in for un-flaggable atomic work.
- *Point production directly at `main`* — rejected: makes every feature merge a prod deploy, the exact churn the concern was about.
- *Rely on the `self-merge-within-milestone` autonomy knob* — orthogonal (it moves the *human gate*, not the *deploy target*); doesn't address CI/CD.
**Approved by:** Rich Mosko
**Supersedes:** _none — new section in [`WORKFLOW.md`](WORKFLOW.md) → Deployment topology._

### YYYY-MM-DD — Project bootstrapped from template
**Decision:** Use the `project_template` starter as the foundation for this project.
**Bootstrapped from:** `project_template` _vX.Y.Z_ (replace with the actual tag — check `git tag -l` on the template repo, or its GitHub Releases page)
**Why:** Provides the R→P→I→V workflow, team-agent roster, and artifact conventions out of the box.
**Alternatives considered:** Bare repo + ad-hoc workflow.
**Approved by:** _<your name>_

<!--
Add new decisions ABOVE this comment, newest first.
-->
