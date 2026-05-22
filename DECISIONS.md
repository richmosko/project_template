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

### YYYY-MM-DD — Project bootstrapped from template
**Decision:** Use the `project_template` starter as the foundation for this project.
**Why:** Provides the R→P→I→V workflow, team-agent roster, and artifact conventions out of the box.
**Alternatives considered:** Bare repo + ad-hoc workflow.
**Approved by:** _<your name>_

<!--
Add new decisions ABOVE this comment, newest first.
-->
