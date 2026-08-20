---
id: PT-8
title: Validate --done-before as YYYY-MM-DD in cairn archive
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

AC (PT-8, same batch/branch): `cairn archive --done-before <value>` rejects any
value not matching YYYY-MM-DD (real calendar date) with a clear error and non-zero
exit, before touching any file. Valid dates behave unchanged.
