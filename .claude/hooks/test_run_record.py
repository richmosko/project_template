#!/usr/bin/env python3
"""PostToolUse hook on Bash (PT-97): appends one record per test run to
`process/cairn/metrics/test-runs.jsonl` under `$CLAUDE_PROJECT_DIR`, so
`cairn loop-stats` can report a measured `suite_seconds_added` and
full-run count instead of `(unmeasured -- PT-93)`. Writes nothing for a
non-test Bash call. Never raises: a broken hook must not block the tool
result it's attached to (PostToolUse cannot refuse a call that already
ran, only fail to record it).

Registered behind the same shell `case` glob prefilter as
test_run_guard.py (see TEST_CMD_TOKENS there) in `.claude/settings.json`.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

TEST_CMD_TOKENS = ("unittest", "run_tests")

# A token match alone is too broad -- see test_run_guard.py's own note
# (hit live while building it): `grep -n run_tests.py foo.py` mentions the
# string without invoking it. Require an actual python invocation before
# recording anything.
_PYTHON_RE = re.compile(r"\bpython3?\b")
_GATE_RE = re.compile(r"--gate\s+(red|green|verdict|finish)\b")
_NARROW_RE = re.compile(r"(?:^|\s)(-p|-k)(?:\s|$)")
# run_tests.py's own summary line: "Ran <N> tests in <W>s (<F> files, <J> workers)".
# Plain `unittest discover` prints the same "Ran N tests in Ws" prefix with
# no trailing parenthetical -- the files group is optional here for that.
_SUMMARY_RE = re.compile(r"Ran (\d+) tests? in ([\d.]+)s(?:\s*\((\d+) files?, \d+ workers?\))?")
_SKIPPED_RE = re.compile(r"skipped=(\d+)")
_RESULT_RE = re.compile(r"^(OK|FAILED)\b", re.MULTILINE)


def _is_test_run(command: str) -> bool:
    return bool(_PYTHON_RE.search(command)) and any(token in command for token in TEST_CMD_TOKENS)


def _is_full_suite_run(command: str) -> bool:
    return _is_test_run(command) and not _NARROW_RE.search(command)


def _runner_of(command: str) -> str:
    return "run_tests" if "run_tests" in command else "unittest"


def _run_git(project_dir: Path, *args: str):
    import subprocess
    try:
        result = subprocess.run(["git", "-C", str(project_dir), *args], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _build_record(data: dict, project_dir: Path) -> dict:
    command = data["tool_input"].get("command", "")
    response = data.get("tool_response") or {}
    stdout = response.get("stdout") or ""

    summary = _SUMMARY_RE.search(stdout)
    tests = int(summary.group(1)) if summary else None
    seconds = float(summary.group(2)) if summary else None
    files = int(summary.group(3)) if summary and summary.group(3) else None
    skipped_match = _SKIPPED_RE.search(stdout)
    skipped = int(skipped_match.group(1)) if skipped_match else (0 if summary else None)
    result_match = _RESULT_RE.search(stdout)
    ok = (result_match.group(1) == "OK") if result_match else None
    gate_match = _GATE_RE.search(command)

    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "who": data.get("agent_type"),
        "gate": gate_match.group(1) if gate_match else None,
        "full": _is_full_suite_run(command),
        "runner": _runner_of(command),
        "sha": _run_git(project_dir, "rev-parse", "HEAD"),
        "branch": _run_git(project_dir, "rev-parse", "--abbrev-ref", "HEAD"),
        "seconds": seconds,
        "harness_ms": data.get("duration_ms"),
        "files": files,
        "tests": tests,
        "skipped": skipped,
        "ok": ok,
        "session": data.get("session_id"),
        "cmd": command[:200],
    }


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0

    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not _is_test_run(command):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    try:
        record = _build_record(data, project_dir)
        path = project_dir / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
