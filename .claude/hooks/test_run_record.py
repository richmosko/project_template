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
job is filling that in.

PT-112 gate-1 ruling (PT-112.md @8b60a8b): with every teammate in its
own worktree, two runs finishing close together used to cross-attribute
under a last-line-only rule, and a stale `who: null` line could get
adopted by an unrelated later hook. The runner's own
`CLAUDE_CODE_SESSION_ID` and this hook's stdin `session_id` are the
identical string (measured live), so that -- not position, not a run id
printed in the summary -- is the deterministic matching key: scan the
last `_TAIL_SCAN_LINES` lines for the NEWEST record with `who is null`
and a non-null `session` equal to this payload's `session_id`, and
patch only that line. A null-`session` line (every pre-PT-112 record)
is never adopted -- that is the stale-line defect this replaces, and by
design those records stay `who: null` permanently. No match, and the
command is `run_tests` -> write nothing (the run recorded itself;
unattributed beats misattributed). The read-modify-write holds
`fcntl.flock(LOCK_EX)` across the whole critical section so a
concurrent runner's own append -- landing between this hook's read and
its write -- is never silently discarded; the runner's own append stays
a plain `"a"`-mode write, unlocked.

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
import fcntl
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
# PT-116 gate-1 ruling (PT-116.md @8c1cc29): failure detail parsed from
# the runner's own `FAILED (failures=N, errors=N)` summary, exactly as
# `skipped=` already is above.
_FAILURES_RE = re.compile(r"failures=(\d+)")
_ERRORS_RE = re.compile(r"errors=(\d+)")

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


_TAIL_SCAN_LINES = 200


def _patch_session_who(path: Path, session_id, who) -> bool:
    """PT-112 gate-1 ruling (PT-112.md @8b60a8b): scan the last
    `_TAIL_SCAN_LINES` lines for the NEWEST record with `who is null` and
    a non-null `session` equal to `session_id`; patch that line only. A
    null-`session` line is never adopted -- every pre-PT-112 record looks
    like that, and by design those stay `who: null` permanently. No
    match (or no `session_id`, or a missing file) -> False, nothing
    written. Holds `fcntl.flock(LOCK_EX)` across the whole
    read-modify-write so a concurrent runner's own append -- landing
    between this hook's read and its write -- is never silently
    discarded; never raises if locking is unavailable (a hook must not
    break the call it's attached to)."""
    if session_id is None or not path.exists():
        return False
    try:
        f = open(path, "r+", encoding="utf-8")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
        except OSError:
            pass
        lines = f.read().splitlines()
        tail_start = max(0, len(lines) - _TAIL_SCAN_LINES)
        target = None
        for i in range(len(lines) - 1, tail_start - 1, -1):
            line = lines[i]
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("who") is not None or rec.get("session") is None:
                continue
            if rec.get("session") != session_id:
                continue
            target = i
            break
        if target is None:
            return False
        rec = json.loads(lines[target])
        rec["who"] = who
        lines[target] = json.dumps(rec)
        f.seek(0)
        f.write("\n".join(lines) + "\n")
        f.truncate()
        return True
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


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
    # PT-116 gate-1 ruling (PT-116.md @8c1cc29): null when unknown (no
    # parseable OK/FAILED line at all -- the caller writes nothing in
    # that case anyway), 0 when a parseable OK/FAILED line names no
    # failures/errors of that kind, the parsed count otherwise. Never
    # 0-filled from ignorance, the same rule `tests` already follows.
    failures_match = _FAILURES_RE.search(stdout)
    errors_match = _ERRORS_RE.search(stdout)
    failures = (int(failures_match.group(1)) if failures_match else 0) if ok is not None else None
    errors = (int(errors_match.group(1)) if errors_match else 0) if ok is not None else None

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
        "failures": failures,
        "errors": errors,
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
        if _patch_session_who(path, data.get("session_id"), data.get("agent_type")):
            return 0
        # No session-matched self-recorded entry to patch. For a bare
        # `unittest` invocation (never self-records) fall back to
        # scraping, same as always -- `session` there comes straight from
        # the payload, so the appended record is self-attributing from
        # the start. For `run_tests.py`, only fall back when the ledger
        # itself doesn't exist yet (the hook being driven directly with
        # no prior real execution at all, e.g. this file's own isolated
        # tests) -- once a real ledger is present, a run_tests command
        # with no session match means the run recorded itself under a
        # DIFFERENT session, and scraping would misattribute or
        # double-record it (PT-112 gate-1 ruling, item 2: unattributed
        # beats misattributed).
        if _runner_of(command) == "run_tests" and path.exists():
            return 0
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
