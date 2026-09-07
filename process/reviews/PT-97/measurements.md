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
