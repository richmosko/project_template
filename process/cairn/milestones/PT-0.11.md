---
id: PT-0.11
name: token accounting
kind: product
major: PT-V1
status: done
target_tag: v0.11.0
ga: false
---

**Definition of done:** the board shows what each issue cost to deliver, in tokens and
estimated dollars, split by role (team-lead and every teammate) and by input vs output.
The numbers come from a committed snapshot that a `cairn` subcommand regenerates from the
local Claude Code transcripts, so the chart survives transcript cleanup and never depends on
a live network call.
