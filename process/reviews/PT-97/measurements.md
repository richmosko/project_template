# PT-97 — hook payload and cost measurements

Machine: darwin 25.6.0, 10 logical cores, python 3.14.7. Sha 09a0843.
Raw captures: `process/reviews/PT-97/hook-payloads.json` (real payloads, `effort` stripped).

## Method

A probe hook was registered in `.claude/settings.local.json` (gitignored, restored to its
original 155 bytes afterwards) that appended its stdin to a file and exited 0. Two Bash calls
were then made — one from this session, and one that happened to be an `implementation-lead`
session running concurrently in the same checkout. `.claude/settings.json` was never touched.

## PreToolUse (matcher `Bash`) — what the hook actually receives

Keys: `agent_type`, `cwd`, `effort`, `hook_event_name`, `permission_mode`, `scratchpad_dir`,
`session_id`, `tool_input`, `tool_name`, `tool_use_id`, `transcript_path`. No pid field.

- **`agent_type` carries the teammate role directly** — observed `"architect"` and
  `"implementation-lead"` on the two sessions captured. No transcript walk is needed to
  attribute a run. (This is a *hook* fact; it does not contradict the OTel finding that
  `agent.name` is never emitted for teammates — different channel.)
- `tool_input.command` is the full command string, including any `cd … &&` prefix.
- **`cwd` is the session's cwd, and it is not the repo root.** The concurrently-captured
  `implementation-lead` record has `cwd = …/scripts/cairn`. That is exactly the condition that
  broke `message_cap.py`, which `.claude/settings.json` invokes as `python3
  .claude/hooks/message_cap.py`.
- **`$CLAUDE_PROJECT_DIR` is set in the hook's shell**, to `/Users/mosko/Projects/project_template`,
  in the same invocation whose `$PWD` was `…/scripts/cairn`. It is the anchor to use.

The main session's `agent_type` value was **not** captured (only teammate sessions ran Bash
during the probe window) — the decision rule below is fail-open on any unrecognised value, so
it does not depend on knowing it.

## PostToolUse (matcher `Bash`) — enough to record a run without touching the CLI

Adds `duration_ms` and `tool_response` (`stdout`, `stderr`, `interrupted`, `isImage`,
`noOutputExpected`) to the same envelope, and still carries `agent_type`. Captured against a
real `python3 run_tests.py -p "test_yaml_parser.py"`:

    stdout = "Ran 29 tests in 0.079s (1 files, 8 workers)\nOK (skipped=0)"
    agent_type = "architect"   cwd = …/scripts/cairn

So who / gate / command / seconds / files / tests / pass-fail are all available **after** the
run, in one place, for `run_tests.py` and `unittest discover` alike.

## Cost

20 invocations each, `/usr/bin/time -p`:

| Variant | Total | Per Bash call |
|---|---|---|
| `python3 <hook>.py` reading stdin, deciding, exiting 0 | 0.58 s | **29 ms** |
| `python3 -c pass` (interpreter floor) | 0.54 s | 27 ms |
| `sh` prefilter, `case` glob miss, no python spawned | 0.08 s | 4 ms |

The hook's own logic is ~2 ms; the 29 ms is interpreter start. A shell prefilter in
`settings.json` would save ~25 ms on every Bash call that is not a test run — see the ruling
for why it is not taken.

## Root-anchoring control

Scan of every `hooks[*].hooks[*].command` in `.claude/settings.json` referencing
`.claude/hooks/`: **1 command, 1 unanchored** — `python3 .claude/hooks/message_cap.py`. The
scan finds the known offender, so an empty result after the fix means something.

## Prefilter, as shipped (addendum 1, verified end to end)

Command form measured against the captured payload, not reasoned about:

    in=$(cat); case "$in" in *unittest*|*run_tests*) printf %s "$in" | python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/test_run_guard.py";; *) exit 0;; esac

| Case | python spawned | Exit | Per call (20 runs) |
|---|---|---|---|
| `git status`-shaped payload (glob miss) | no | 0 | **~6 ms** (0.13 s / 20 incl. one extra `sh -c` of harness; 0.08 s / 20 for the prefilter alone) |
| `cd scripts/cairn && python3 run_tests.py` | yes | **2** | 32 ms (0.64 s / 20) |
| `python3 run_tests.py -p "test_x.py"` | yes | 0 | 32 ms |

Exit 2 propagates through the pipe, so the block still works; the pipeline's status is python's.

## Gate 4 constructions (2026-09-07, sha e86f163)

### Guard branch matrix — real hook, real captured payload, `agent_type` varied

| Command | agent_type | Exit | Expected |
|---|---|---|---|
| `python3 run_tests.py` | qa-engineer | 2 | 2 |
| `python3 run_tests.py --gate verdict` | qa-engineer | 0 | 0 |
| `python3 run_tests.py -p "test_x*.py"` | qa-engineer | 0 | 0 |
| `python3 run_tests.py --pattern "test_x*.py"` | qa-engineer | **2** | **0** |
| `python3 -m unittest discover -s tests` | qa-engineer | 2 | 2 |
| `python3 -m unittest discover -s tests -p "test_x.py"` | qa-engineer | 0 | 0 |
| `/usr/bin/time -p python3 -m unittest discover -s tests` | architect | **0** | **2** |
| `python3 run_tests.py` | (absent) | 0 | 0 |
| `python3 run_tests.py` | team-lead (unknown) | 0 | 0 |
| `grep -n run_tests.py foo.py` | qa-engineer | 0 | 0 |
| malformed stdin | — | 0 | 0 |

Control for the `time -p` row: the identical command without the `/usr/bin/time -p` prefix
exits 2. The prefix, not the command, is what changes the answer.

### The three gate-4 verdict runs, as recorded

Commanded exactly as the gate asks (`--gate verdict`, `--serial --gate verdict`, `discover`),
each wrapped in `/usr/bin/time -p` and piped to `tail`, which is how a gate owner reads them:

| ts | who | gate | full | tests | seconds |
|---|---|---|---|---|---|
| 06:40:43 | architect | verdict | **false** | **null** | **null** |
| 06:42:38 | architect | verdict | **false** | **null** | **null** |
| 06:44:25 | architect | **null** | **false** | 1433 | 102.055 |

Measured truth for those same three runs: 19.82 s / 109.17 s / 102.21 s wall, all
**1433 tests, skipped=1, OK, 85 files**. None was recorded as `full`.

### Record-file noise at e86f163

10 records; 4 have no parseable summary (`tests: null`). Two of those are `git` commands that
merely name the hook files. One `git log … && git status … && git show …` command recorded
`tests: 39, seconds: 1.163` — a git command carrying a measured-looking test result. One
`git add …` recorded `gate: "green"` because that string appeared in its argument list.

### loop-stats internal disagreement

`cairn loop-stats PT-97` prints `full_suite_runs 2` in the metric table while the per-agent
table below it, from the transcript detector, sums 12 (implementation-lead 8, architect 4) —
in the same output. `suite_seconds_added` prints `86.55799999999999`, which is the serial run
(106.536 s) minus the parallel run (19.978 s) of identical code: a configuration difference,
not seconds added by the feature.

