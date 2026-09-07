#!/usr/bin/env python3
"""PostToolUse hook on Bash (PT-97): ensures a real test run has a
complete record in `process/cairn/metrics/test-runs.jsonl` under
`$CLAUDE_PROJECT_DIR`, so `cairn loop-stats` can report a measured
`suite_seconds_added` and full-run count instead of `(unmeasured --
PT-93)`. Never raises: a broken hook must not block the tool result it's
attached to (PostToolUse cannot refuse a call that already ran, only
fail to record it).

Gate-4 verdict delta 2 (PT-97.md @ d896d8d): `run_tests.py` now writes
its own record in-process (it has the counts, seconds, jobs and gate
directly -- no stdout to scrape, no risk from a gate owner's `| tail`
eating the summary before this hook ever sees it) with `"who": null`,
since only the hook's `agent_type` field knows that. This hook's first
job is filling that in: find the most recent still-`who: null` record
and patch it.

That covers `run_tests.py`. A bare `unittest discover` is stdlib code
this project doesn't own and can't make self-recording -- for that
runner only, this hook still falls back to scraping `tool_response.stdout`
(delta 2's own construction against a directly-invoked hook, no prior
runner execution, exercises exactly this path too).

Delta 3 (blocking): detection of "is this actually a run" is
`_test_run_shared.is_test_invocation` -- real tokenisation, not a
substring scan -- so a `git add` or `git log` whose text merely mentions
"run_tests.py --gate green" or "Ran 39 tests" is never mistaken for one
and never produces a record.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _test_run_shared import gate_of, is_full_suite_run, is_test_invocation, TEST_CMD_TOKENS  # noqa: E402,F401

# run_tests.py's own summary line: "Ran <N> tests in <W>s (<F> files, <J> workers)".
# Plain `unittest discover` prints the same "Ran N tests in Ws" prefix with
# no trailing parenthetical -- the files/workers group is optional here.
_SUMMARY_RE = re.compile(r"Ran (\d+) tests? in ([\d.]+)s(?:\s*\((\d+) files?, (\d+) workers?\))?")
_SKIPPED_RE = re.compile(r"skipped=(\d+)")
_RESULT_RE = re.compile(r"^(OK|FAILED)\b", re.MULTILINE)

_RECORDS_REL = Path("process") / "cairn" / "metrics" / "test-runs.jsonl"


def _runner_of(command: str) -> str:
    return "run_tests" if "run_tests.py" in command else "unittest"


def _run_git(project_dir: Path, *args: str):
    import subprocess
    try:
        result = subprocess.run(["git", "-C", str(project_dir), *args], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _read_last_line(path: Path):
    if not path.exists():
        return None
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size == 0:
            return None
        chunk = min(size, 8192)
        f.seek(-chunk, os.SEEK_END)
        tail = f.read().decode("utf-8", errors="replace")
    lines = [l for l in tail.splitlines() if l.strip()]
    return lines[-1] if lines else None


def _patch_last_who(path: Path, who) -> bool:
    """If the last record in `path` is still `who: null` (a self-recorded
    entry from run_tests.py awaiting attribution), fill it in and return
    True. Never touches an already-attributed record -- a stale null-who
    line from an earlier, different call is the one gap this leaves, and
    no test in this batch exercises concurrent writers."""
    last = _read_last_line(path)
    if last is None:
        return False
    try:
        rec = json.loads(last)
    except Exception:
        return False
    if rec.get("who") is not None:
        return False
    rec["who"] = who
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _scrape_record(data: dict, command: str, project_dir: Path) -> dict:
    response = data.get("tool_response") or {}
    stdout = response.get("stdout") or ""

    summary = _SUMMARY_RE.search(stdout)
    tests = int(summary.group(1)) if summary else None
    seconds = float(summary.group(2)) if summary else None
    files = int(summary.group(3)) if summary and summary.group(3) else None
    jobs = int(summary.group(4)) if summary and summary.group(4) else None
    skipped_match = _SKIPPED_RE.search(stdout)
    skipped = int(skipped_match.group(1)) if skipped_match else (0 if summary else None)
    result_match = _RESULT_RE.search(stdout)
    ok = (result_match.group(1) == "OK") if result_match else None

    full = is_full_suite_run(command)
    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "who": data.get("agent_type"),
        # Delta 5, defence in depth: a narrowed (full=False) record never
        # carries a gate, even if the command text has a --gate-shaped
        # substring -- the runner itself now refuses --gate combined with
        # -p/--pattern (test_run_tests.py's GateRequiresFullRunTests), but
        # this hook doesn't trust that from the outside; belt and
        # suspenders on the one field a narrowed run must never claim.
        "gate": gate_of(command) if full else None,
        "full": full,
        "runner": _runner_of(command),
        "sha": _run_git(project_dir, "rev-parse", "HEAD"),
        "branch": _run_git(project_dir, "rev-parse", "--abbrev-ref", "HEAD"),
        "seconds": seconds,
        "harness_ms": data.get("duration_ms"),
        "jobs": jobs,
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
    if not isinstance(command, str) or not is_test_invocation(command):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    path = project_dir / _RECORDS_REL
    try:
        if _patch_last_who(path, data.get("agent_type")):
            return 0
        # No self-recorded entry to patch -- either this is a bare
        # `unittest` invocation (never self-records) or, for run_tests.py,
        # the hook is being driven directly without a prior real
        # execution (qa's isolated hook tests). Fall back to scraping.
        record = _scrape_record(data, command, project_dir)
        if record.get("tests") is None:
            # Delta 3 gap: a test-shaped command (real python invocation)
            # whose captured stdout has no parseable "Ran N tests" summary
            # at all -- e.g. the invocation never completed (refused by
            # the runner's own arg parsing) -- is not a run with an
            # unknown result, it is not a result. Write nothing rather
            # than a null-filled record.
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
