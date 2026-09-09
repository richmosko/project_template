#!/usr/bin/env python3
"""PreToolUse hook on Bash (PT-97): refuses a teammate's un-tiered
full-suite run -- `scripts/cairn/run_tests.py` or `python -m unittest
discover -s tests`, either one, with no `-p`/`--pattern`/`-k` narrowing --
unless it carries `--gate {red,green,verdict,finish}`. Everything
unrecognised (malformed stdin, a non-Bash tool, a missing/unknown
`agent_type`, a narrowed or already-gated run) exits 0: that fail-open
list is what keeps this off a human's shell and off the main session's
own commands, since there is no `.claude/agents/team-lead.md` for
`agent_type` to match.

Registered behind a shell `case` glob prefilter in `.claude/settings.json`
(measured ~6 ms on a miss vs. 29 ms unconditional -- process/reviews/
PT-97/measurements.md) matched against `TEST_CMD_TOKENS`; the two must
never drift apart.

Invocation and narrowing detection live in `_test_run_shared.py` (gate-4
verdict delta 1), shared with `test_run_record.py` -- a naive substring
scan for the two directions this used to get wrong: `--pattern` doesn't
contain the literal ` -p `, and `/usr/bin/time -p ...` does (time's own
flag, not the runner's).

PT-119 gate-1 ruling (PT-119.md @6cd7e44): the refusal SENTENCE itself
("test_run_guard: refusing an un-tiered full-suite run...") also moved
into `_test_run_shared.REFUSAL_MESSAGE`, so `run_tests.py`'s own
runner-side backstop for an indirectly invoked run (a wrapper script's
body, invisible to both this hook and the prefilter) says the exact same
sentence -- one string, two lanes, never a second drifting copy.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# _test_run_shared.py lives alongside this file, but this script can be
# loaded two ways: `python3 test_run_guard.py` (subprocess -- Python
# already puts the script's own dir on sys.path[0]) and
# importlib.util.spec_from_file_location (qa's ShellPrefilterCouplingTests,
# which does NOT). Make both work.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _test_run_shared import REFUSAL_MESSAGE, TEST_CMD_TOKENS, gate_of, is_full_suite_run  # noqa: E402,F401

# PT-119 gate-1 ruling (PT-119.md @6cd7e44): moved into _test_run_shared
# so run_tests.py's own runner-side backstop (the indirect-invocation
# case) says the exact same sentence -- kept as a module attribute here
# (not inlined at the call site) since qa's tests read it as
# `test_run_guard._MESSAGE`.
_MESSAGE = REFUSAL_MESSAGE


def _known_agent_stems(project_dir: Path) -> set:
    agents_dir = project_dir / ".claude" / "agents"
    if not agents_dir.is_dir():
        return set()
    return {p.stem for p in agents_dir.glob("*.md")}


def _is_known_agent(agent_type, project_dir: Path) -> bool:
    if not isinstance(agent_type, str) or not agent_type:
        return False
    return agent_type in _known_agent_stems(project_dir)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    if not _is_known_agent(data.get("agent_type"), project_dir):
        return 0

    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0

    if not is_full_suite_run(command):
        return 0
    if gate_of(command) is not None:
        return 0

    sys.stderr.write(_MESSAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
