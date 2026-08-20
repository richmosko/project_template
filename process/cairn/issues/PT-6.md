---
id: PT-6
title: Require seen on POST /api/issue/<id>; opt out via explicit null
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

Feature started. Branch: `feature/pt-6-require-seen`.

Acceptance criteria (team-lead):
1. POST /api/issue/<id> with the `seen` key ABSENT from the payload → 400 with a
   message naming the missing key; the write is not applied. (Today it silently
   bypasses the staleness check — the lost-update window this closes.)
2. Explicit `"seen": null` → deliberate override: write proceeds, no staleness check.
3. Present + matching → write proceeds (unchanged). Present + stale → 409 (unchanged).
4. All three board call sites (status drag, drawer patch, comment) already send
   `seen` — verified unchanged behavior; if any path can produce an absent key,
   fix it to send the token (or explicit null where override is intended).
5. Unit tests cover absent / null / match / stale on the POST path; suite (137) green;
   `cairn check` ok.
