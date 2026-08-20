# Decisions

> Append-only log of non-trivial decisions made over the life of this project. Conventions in [`WORKFLOW.md`](WORKFLOW.md) → Decision logging.
>
> This file lives **outside** `MILESTONES.md` so it doesn't bloat the auto-loaded session context. Pull this file in explicitly when you need to recall *why* a past decision was made.

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
