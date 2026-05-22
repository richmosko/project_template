# Backlog

> Overflow queue for Linear. Items here are scoped but **not yet active in Linear**.
> Promoted to Linear via `/sync-backlog` — at sprint-cycle boundaries, on demand, or automatically by `/start-feature` when a requested feature is queued here.
> Rows are **removed from this file** once promoted; promotion events are recorded in the [Sync log](#sync-log) at the bottom for audit.

## How this file works

Linear's free tier caps **active (non-archived) issues at 250 across the workspace**. The template uses a tiered system to stay under:

```
docs/PRD.html         BACKLOG.md (here)        Linear active issues       Linear archived
(canonical scope)  →  (overflow queue)      →  (hot working set, ≤200) →  (cold storage)
                                                      ↓
                          /sync-backlog promotes;  /start-feature consumes;  /cleanup-linear archives Done
```

- `setup-linear-team` seeds only the **first milestone's** stories into Linear; everything else lands here.
- `/sync-backlog` promotes the next batch when a new sprint cycle starts (or on demand).
- `/start-feature` runs a budget check before creating new Linear issues; routes to BACKLOG.md if Linear is near cap.

## Ordering

FIFO by **milestone stage**: items in M1 promote before M2 before M3. Within a milestone, **insertion order** is the tiebreaker. The `Priority` column is informational — `/sync-backlog` doesn't enforce strict priority ordering in v1.

If you want strict priority ordering, sort the rows within a milestone manually before running `/sync-backlog`.

## Queued items

<!-- Add one section per milestone. Highest-priority milestone (next to ship) first. -->

### Milestone: _e.g. M1 — MVP_ (priority 1)

| Title | Priority | Source | Notes |
|---|---|---|---|
| _e.g. As a user, I want to log in via Google_ | _P0_ | _PRD §4.1_ | _—_ |
| _e.g. As a user, I want to reset my password_ | _P1_ | _PRD §4.2_ | _—_ |

### Milestone: _e.g. M2 — Onboarding polish_ (priority 2)

| Title | Priority | Source | Notes |
|---|---|---|---|
| _none yet_ | | | |

## Sync log

Append-only. Records each `/sync-backlog` promotion event for audit. Format:

```
- <YYYY-MM-DD>: Promoted <N> items to Linear (<context — e.g. "Sprint 3 planning" or "on-demand">) — issues <FIRST-ID> through <LAST-ID>
```

<!-- Promotion events go below this line, newest at bottom. -->
