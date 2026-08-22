---
id: PT-9
title: Accept --data-dir before the subcommand (top-level argparse option)
status: done
milestone: PT-0.4
parent: null
assignee: null
labels: []
priority: P3
pr: https://github.com/richmosko/project_template/pull/40
created: 2026-08-20
updated: 2026-08-20
---


## Comments

### @team-lead — 2026-08-20

AC (PT-9, same batch/branch): `--data-dir` is accepted as a top-level option before
the subcommand (`cairn --data-dir X ls`) AND keeps working in its current
per-subcommand position; when both are given, the more specific (subcommand) wins
or an unambiguous error is raised — implementation picks one and documents it in
the --help text.
