---
id: PT-7
title: Preserve file mode on frontmatter rewrite (mkstemp 0600 flip)
status: in-progress
milestone: "0.4"
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

Batch feature started (PT-7/8/9/13, one PR per the ratified 0.4 scope decision).
Branch: `feature/pt-7-8-9-13-cli-hardening`.
AC (PT-7): a frontmatter rewrite preserves the original file's mode — an issue file
chmod'd e.g. 0644→0664 or 0600 keeps its exact mode after any cairn set/comment/
apply_patch write (today mkstemp's 0600 replaces it). Test proves mode before ==
mode after across at least two distinct starting modes.
