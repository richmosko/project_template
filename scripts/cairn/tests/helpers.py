"""Shared test scaffolding: sys.path shim, fixture-copying.

Every test module imports from here first so that `import cairn` works
regardless of the caller's cwd, and so that no test ever mutates the
checked-in fixtures in tests/fixtures/ in place.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

TESTS_DIR = Path(__file__).resolve().parent
CAIRN_DIR = TESTS_DIR.parent  # scripts/cairn/
FIXTURES_DIR = TESTS_DIR / "fixtures"
FIXTURE_DATA_DIR = FIXTURES_DIR / "process" / "cairn"
CAIRN_BIN = CAIRN_DIR / "cairn"  # bash shim, invoked by CLI subprocess tests
CAIRN_PY = CAIRN_DIR / "cairn.py"

if str(CAIRN_DIR) not in sys.path:
    sys.path.insert(0, str(CAIRN_DIR))


def copy_fixture_data_dir(dest_root: Path) -> Path:
    """Copy the checked-in fixtures/process/cairn tree into dest_root.

    Returns the path to the copy (a `process/cairn`-shaped data_dir). Tests
    must never write into FIXTURE_DATA_DIR directly -- always operate on
    this copy so the suite is order-independent and repeatable.
    """
    dest = Path(dest_root) / "cairn"
    shutil.copytree(FIXTURE_DATA_DIR, dest)
    return dest


def make_tmp_data_dir(testcase) -> Path:
    """Create a fresh temp copy of the fixture data dir, auto-cleaned up.

    `testcase` is the unittest.TestCase instance -- cleanup is registered
    via addCleanup so it runs even on failure.
    """
    tmp = tempfile.mkdtemp(prefix="cairn-test-")
    testcase.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return copy_fixture_data_dir(Path(tmp))


def make_empty_tmp_dir(testcase) -> Path:
    """A bare temp dir with no cairn tree at all, for CLI-bootstrap-style tests."""
    tmp = tempfile.mkdtemp(prefix="cairn-test-empty-")
    testcase.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return Path(tmp)


# PT-96 gate-1 ruling (process/cairn/issues/PT-96.md @ fed43a4): the
# measured suite cost was never fixture construction (3.8-7.2 ms) -- it is
# socketserver.BaseServer.serve_forever()'s default poll_interval=0.5,
# which shutdown() blocks on (measured 501 ms at the default, 11.1 ms at
# 0.01). Every test that serves a cairn server in a background thread
# routes through this helper instead of hand-rolling
# threading.Thread(target=server.serve_forever, daemon=True) with no
# interval. Starts only -- existing _shutdown/addCleanup/self.thread
# teardown at each call site is untouched; converting teardown too would
# double-shutdown.
SERVE_POLL_INTERVAL = 0.01


def serve_in_thread(server, poll_interval: float = SERVE_POLL_INTERVAL) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, args=(poll_interval,), daemon=True)
    thread.start()
    return thread


# --------------------------------------------------------------------------
# PT-100 (architect's ruling, process/cairn/issues/PT-100.md @ 0487f33,
# superseding @d0de5e3; addendum @c2d868f): the shared real-file guard used
# by every module that must never touch the real, committed
# process/cairn/metrics/ tree. PT-91's original per-module guards compared
# whole-file byte equality, which cannot distinguish a genuine seam defect
# (a test wrote the real file) from the live otel receiver daemon flushing
# concurrently -- both look like "the bytes changed".
#
# The retraction that shapes this: an EARLIER version of this ruling keyed
# rows by `(issue, role, model, source)` into a dict to reason about
# per-key counters. That key is NOT unique on the real file (558 lines,
# 401 distinct keys, one key 32 times) -- last-occurrence-wins over
# duplicates silently invented an "in-place update" and several "decreased
# counters" that were never real. NEVER key token-usage.jsonl lines by
# identity here -- that is the exact defect this ruling corrects, and
# doing it again would hide the very rewrites this guard exists to catch.
#
# The corrected tolerance is RAW-LINE MULTISET CONTAINMENT: every
# pre-existing line must still be present VERBATIM somewhere in the
# current file (only its position may move -- otel_receiver.py's
# `_append_lines` re-sorts the whole file on every flush), plus every
# newly-added line's `issue` must resolve to a real cairn issue id (or
# `main` / a `milestone:` bucket) -- containment alone would tolerate a
# test appending fabricated rows.
# --------------------------------------------------------------------------


def _read_jsonl_lines(path: Path) -> List[str]:
    """Every non-blank raw line of `path`, verbatim (no parsing, no
    re-serialization) -- the exact text multiset containment compares.
    `[]` for a missing file, never a raise: a guard that can't find the
    file yet (before the first write) has nothing to compare against."""
    path = Path(path)
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _snapshot_dir_contents(dir_path: Path) -> Dict[str, bytes]:
    """{filename: bytes} for every FILE directly inside `dir_path` (not
    recursive -- `.sessions/` is flat). `{}` for a missing directory."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in dir_path.iterdir() if p.is_file()}


def _valid_issue_ids(data_dir: Path) -> "set[str]":
    """Every issue id with a real file backing it -- live (`issues/`) or
    archived (`archive/issues/`) -- read from `data_dir` (a
    `process/cairn`-shaped root, `make_tmp_data_dir`'s own shape)."""
    ids: "set[str]" = set()
    for rel in (Path("issues"), Path("archive") / "issues"):
        d = Path(data_dir) / rel
        if d.is_dir():
            ids.update(p.stem for p in d.glob("*.md"))
    return ids


def _issue_is_backed(issue: Optional[str], valid_issue_ids: "set[str]") -> bool:
    if not issue:
        return False
    if issue == "main":
        return True
    if issue.startswith("milestone:"):
        # Ruling: a milestone bucket is accepted without checking a
        # milestone file -- it is a different id namespace than issues/.
        return True
    return issue in valid_issue_ids


def _first_differing_line_index(old_lines: List[str], new_lines: List[str]) -> Optional[int]:
    """Position-wise first index where the two line lists disagree (a
    re-sort moves lines, so this is diagnostic context, not itself the
    pass/fail signal -- containment is). `None` when one is a prefix of
    the other with no positional disagreement inside the overlap."""
    for i in range(max(len(old_lines), len(new_lines))):
        old_v = old_lines[i] if i < len(old_lines) else None
        new_v = new_lines[i] if i < len(new_lines) else None
        if old_v != new_v:
            return i
    return None


def snapshot_real_state(
    token_usage_path: Path, pidfile_path: Path, sessions_dir: Path, data_dir: Path,
) -> Dict[str, Any]:
    """An opaque "before" snapshot of the three pieces of real, live state
    a test module must never disturb: the committed token-usage.jsonl
    (as a raw-line multiset, never parsed into an identity-keyed dict),
    the receiver's `.receiver.pid`, and the `.sessions/` registry.
    `data_dir` resolves which issue ids a NEW line is allowed to name."""
    return {
        "token_usage_path": Path(token_usage_path),
        "pidfile_path": Path(pidfile_path),
        "sessions_dir": Path(sessions_dir),
        "token_lines": _read_jsonl_lines(token_usage_path),
        "pidfile_bytes": Path(pidfile_path).read_bytes() if Path(pidfile_path).is_file() else None,
        "sessions": _snapshot_dir_contents(sessions_dir),
        "valid_issue_ids": _valid_issue_ids(data_dir),
    }


def diagnose_real_state(snapshot: Dict[str, Any]) -> List[str]:
    """Re-reads current state from the paths recorded in `snapshot` and
    returns human-readable findings -- `[]` when nothing changed or every
    change classifies as a tolerated live-daemon flush. Every non-empty
    finding for token-usage.jsonl names four facts: the line-count delta,
    whether containment holds, how many pre-existing lines are missing
    (plus the first one verbatim, classified as a suspected backfill
    re-run when every missing line carries `source: transcript-backfill`,
    else a suspected test write), and the first differing line index."""
    findings: List[str] = []

    old_lines = snapshot["token_lines"]
    new_lines = _read_jsonl_lines(snapshot["token_usage_path"])
    old_counter: "Counter[str]" = Counter(old_lines)
    new_counter: "Counter[str]" = Counter(new_lines)
    missing_lines = list((old_counter - new_counter).elements())
    added_lines = list((new_counter - old_counter).elements())
    delta = len(new_lines) - len(old_lines)
    first_diff_idx = _first_differing_line_index(old_lines, new_lines)

    if missing_lines:
        parsed_missing = []
        for line in missing_lines:
            try:
                parsed_missing.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                parsed_missing.append({})
        all_backfill = bool(parsed_missing) and all(
            p.get("source") == "transcript-backfill" for p in parsed_missing
        )
        classification = (
            "looks like a backfill re-run, not a test write" if all_backfill else "suspected test write"
        )
        findings.append(
            f"token-usage.jsonl: line count {len(old_lines)} -> {len(new_lines)} (delta {delta:+d}); "
            f"containment FAILED -- {len(missing_lines)} pre-existing line(s) missing verbatim, "
            f"first missing: {missing_lines[0]!r} ({classification}); "
            f"first differing line index: {first_diff_idx}"
        )
    elif added_lines:
        unbacked = []
        for line in added_lines:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                unbacked.append(line)
                continue
            if not _issue_is_backed(row.get("issue"), snapshot["valid_issue_ids"]):
                unbacked.append(line)
        if unbacked:
            findings.append(
                f"token-usage.jsonl: line count {len(old_lines)} -> {len(new_lines)} (delta {delta:+d}); "
                f"containment holds, but {len(unbacked)} new line(s) name an issue id no file backs -- "
                f"first unbacked: {unbacked[0]!r}; first differing line index: {first_diff_idx}"
            )

    old_pid = snapshot["pidfile_bytes"]
    new_pid = Path(snapshot["pidfile_path"]).read_bytes() if Path(snapshot["pidfile_path"]).is_file() else None
    if new_pid != old_pid:
        tolerated = False
        if new_pid is not None:
            try:
                pid = int(new_pid.decode("utf-8", errors="replace").strip())
                os.kill(pid, 0)
                tolerated = True
            except ProcessLookupError:
                tolerated = False
            except PermissionError:
                tolerated = True  # exists, just not ours to signal
            except (ValueError, OSError):
                tolerated = False
        if not tolerated:
            findings.append(
                f".receiver.pid changed ({old_pid!r} -> {new_pid!r}) and the new content is not a "
                f"live process's pid -- a deletion or a stale/garbage rewrite must never be tolerated"
            )

    old_sessions = snapshot["sessions"]
    new_sessions = _snapshot_dir_contents(snapshot["sessions_dir"])
    removed = sorted(set(old_sessions) - set(new_sessions))
    changed = sorted(
        name for name in old_sessions if name in new_sessions and new_sessions[name] != old_sessions[name]
    )
    if removed or changed:
        findings.append(
            f".sessions/ registry: removed={removed}, content-changed={changed} -- additions are "
            f"tolerated, but a removal or a content change is exactly the registry-draining damage "
            f"this guard exists to catch"
        )

    return findings


def assert_real_state_untouched(snapshot: Dict[str, Any]) -> None:
    """Raises `AssertionError` joining every finding when non-empty.
    Explicit raise, never a bare `assert` -- PT-91 Amendment 1 measured
    that `python -O` strips a bare `assert` silently, which would make
    this guard's firing depend on an interpreter flag."""
    findings = diagnose_real_state(snapshot)
    if findings:
        raise AssertionError("real state guard tripped:\n" + "\n".join(findings))
