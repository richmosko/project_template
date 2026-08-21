---
id: PT-3
title: Multi-root board: cairn serve --repos for a cross-project view
status: done
milestone: "0.5"
parent: null
assignee: null
labels: []
priority: P3
pr: null
created: 2026-08-20
updated: 2026-08-20
---


## Comments

### @team-lead — 2026-08-20

Feature started. Branch: `feature/pt-3-multi-root-board`.

Design settled with Mosko (2026-08-21):
- **Read-only** cross-project view (cross-root editing explicitly out of scope for v1).
- Roots specified via a **`roots:` list in `process/cairn/config.yml`** (option B), paths **relative to the repo root**; missing/unreachable roots **warn-and-skip**, never crash. `cairn serve --repos <list>` remains an ad-hoc **override/extension** on top of the config default (option A layered on B).
- **Distinct ID prefixes assumed** across roots (guaranteed by /spin-off-component) — no collision handling.
- **Milestone swimlanes retained**; each card carries a **repo tag** identifying its source root.
- Architect owns a short design note before implementation.

### @team-lead — 2026-08-20

Architect design rulings settled (2026-08-21):

- **A (board layout) — REPO-GROUPED** (Mosko's call via preview comparison). Top-level section per repo; milestone lanes nested inside each repo section; status columns within each lane. Rationale: milestone/major ids are NOT prefix-distinct across roots (milestones are version-named — every repo has a 0.5 — and majors are V1), so keying lanes on bare milestone id would fuse unrelated roadmaps. Repo-grouped gives the clearest cross-project separation. Single-root board unchanged (no repo section wrapper when only the primary root loads). PT-16 per-milestone collapse is preserved; repo-section collapse is a nice-to-have — implement if cheap, else defer.
- **B (--repos) — REPLACE** the config `roots:` list (primary root always implicitly included).
- **C (check scope) — SHAPE ONLY**: `roots:` validated as a list of relative-path strings; reachability is a startup warn-and-skip, never a check_repo error.
- **D (trust boundary)** — routed to seceng for a proportionate read (read-only cross-root dir access gated on config.yml presence; no write, no exfil, localhost-only). Verdict pending; may add a control (roots confined to a parent workspace, no arbitrary `..` escape).

Payload carries the `repo` dimension on both cards and milestone entries. Architect design note: temp/2026-08-21-architect-pt3-design.md (to be placed at feature close).

### @team-lead — 2026-08-20

Front-end scope expanded (architect review, 2026-08-21): the milestone/major id collision hits six board.js call sites, not just renderKanban — milestoneLabel, milestoneMajor, progress strip, filter-milestone select, the major tabs (majors collide too — every repo has V1), plus renderKanban. Additional rulings:

- **repo::id internal identity** adopted across all six sites (bare ids aren't unique across roots).
- **new-issue-milestone select scoped to PRIMARY-ROOT milestones — non-negotiable (data integrity):** creation writes to primary, so offering a foreign milestone id would let a user create a primary issue referencing a nonexistent milestone (cairn check would then flag it). Read-only cross-project view must not corrupt local referential integrity via a dropdown. Hard requirement + test.
- **Major tabs (team-lead call):** visible tab bar dedupes by bare major id (no duplicate V1); a tab filters across repos (union), issues shown within their repo sections; internal identity stays repo-qualified.
- **seceng D verdict:** acceptable, no path-jail; stderr startup log of resolved roots added as a tripwire; absolute paths stay out of payload/header (architect §3.1). Accepted-risk record for docs/SECURITY pending Mosko sign-off at merge.

Net: nesting is the easy half; the collision cleanup is the bulk of the front-end work. PT-3 is larger than first sized but bounded.

### @team-lead — 2026-08-20

Validate GREEN — QA combined sign-off (suite 258/258 + read-review all commits), team-lead 3 Chrome passes (multi-root all six fixes + single-root byte-identity + null-guard defensive), seceng 2 PASSes (read-only structural + new-issue-milestone data-integrity), architect clean review. Merging. Closing — 0.5's last feature.
