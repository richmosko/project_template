---
id: PT-5
title: priority drawer input as a select + check_repo rule for P0-P3|null
status: in-progress
milestone: "0.4"
parent: null
assignee: null
labels: []
priority: P2
pr: null
created: 2026-08-20
updated: 2026-08-20
---


## Comments

### @team-lead — 2026-08-20

Feature started. Branch: `feature/pt-5-priority-select-lint`.

Acceptance criteria (team-lead):
1. Board detail drawer: the priority field is a <select> offering P0, P1, P2, P3, and
   a none/empty option (writes `priority: null`), replacing the free-text input at
   board.js:475. Selecting a value persists through the existing POST path and
   round-trips after a poll refresh.
2. Engine lint: `cairn check` flags any issue whose `priority` is neither null nor
   one of P0-P3 (exact case), reporting the issue ID and offending value; exits
   non-zero on violation.
3. Tests: new unit tests cover the lint rule (valid P0-P3, null, missing field OK;
   invalid string/case rejected). Existing 128-test suite stays green.
4. `cairn check` on the real data dir passes (all current issues carry valid values).
