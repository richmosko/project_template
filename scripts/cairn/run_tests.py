#!/usr/bin/env python3
"""
run_tests.py — PT-93: file-level parallel runner for the cairn Python suite.

Measured (process/reviews/PT-93/timings.md, sha 5fd6db1, 10 logical cores):
serial `unittest discover` is 171 s wall against 79 s of CPU (spawn/sleep-
bound, not CPU-bound), because ~30 of 82 files spawn real servers/daemons
or build fresh git-repo fixtures. `unittest` itself has no file-level
parallelism, so each test_*.py runs as its own subprocess and the
subprocesses are fanned out across a thread pool (the threads block on
`subprocess.run`, not on the GIL).

Standalone script (sibling of cairn.py), not a `cairn` subcommand — the
seam below is the architect's gate-1 ruling (process/cairn/issues/PT-93.md
@ cb3b4a4). Guard tests: scripts/cairn/tests/test_run_tests.py — that file
is the spec for names/signatures; this docstring is a summary. None of
those tests invoke the real suite (PT-94 D11: this feature pays back the
seconds it adds).

Library contract:
    discover_files(tests_dir, patterns) -> List[Path]
        union of sorted(tests_dir.glob(p)) for each pattern, deduped and
        sorted. Default pattern is ["test_*.py"].
    order_by_size(files) -> List[Path]
        same files, largest source file first (size is a stateless proxy
        for duration, r = 0.474 against measured time in the ruling's
        data — no cached timings file to go stale).
    build_argv(python_exe, file_name) -> List[str]
        [python_exe, "-m", "unittest", "discover", "-s", "tests", "-p",
        file_name] — no "-t": passing `-t .` drops tests/ off sys.path and
        every module fails importing `helpers`, each still printing a
        plausible-looking "Ran 1 test ... FAILED (errors=1)".
    parse_summary(stderr) -> (ran, failures, errors, skipped)
        parsed from unittest's own summary lines; raises ParseError if the
        summary can't be found (an unparseable child is an error, never a
        silent 0 — see run_all).
    default_jobs() -> int
        min(8, os.cpu_count() or 4) — the ruling's measured floor: 4
        workers does not reliably clear 45 s (44-48 s across orderings),
        8 does with ~40% margin.
    parse_args(argv) -> argparse.Namespace
        .jobs (resolved: --serial -> 1, else --jobs or default_jobs()),
        .pattern (resolved: defaults to ["test_*.py"]), .serial, .list,
        .json.
    run_all(files, jobs, cwd, runner=subprocess.run) -> dict
        runs `files` in a ThreadPoolExecutor(max_workers=jobs), returns
        {wall, jobs, files, tests, failures, errors, skipped,
        failed_files, times} (times: file name -> seconds). A file counts
        as failed if its child returncode is non-zero OR its stderr is
        unparseable, whichever first.
    exit_code(agg) -> int
        0 iff agg["failed_files"] == [].

CLI contract:
    python3 scripts/cairn/run_tests.py [-p PATTERN ...] [-j N | --serial]
                                        [--list] [--json PATH]
    -p/--pattern   repeatable, default ["test_*.py"]; narrowing this is
                   the tiered-run entry point (WORKFLOW → Implement →
                   Inner loop): `run_tests.py -p "test_<area>*.py"`.
    -j/--jobs N    default min(8, os.cpu_count() or 4).
    --serial       jobs = 1 (a doubt-the-parallel-path control).
    --list         print discovered file names, one per line, exit 0;
                   does not run anything.
    --json PATH    write run_all()'s dict to PATH — this is AC3's
                   instrument.

    Exit 0 iff every child file's process exited 0 and every child's
    output was parseable. stdout ends with unittest's own two summary
    lines so existing greps survive:
        Ran <N> tests in <W>s (<F> files, <J> workers)
        OK (skipped=<N>)
      or
        FAILED (failures=<N>, errors=<M>, files=<K>)
    A failing file prints its captured stdout+stderr, then a
    `FAIL <name> (<s>s)` line, before the final summary. Passing files
    print nothing.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_DIR = SCRIPT_DIR / "tests"

# PT-119 gate-1 ruling, re-issued (PT-119.md @6cd7e44): kept byte-identical
# to `.claude/hooks/_test_run_shared.REFUSAL_MESSAGE` -- used ONLY as a
# fallback when that module can't be imported (a fake-engine-root test
# copy of this file has no .claude/hooks alongside it; every such
# existing test only ever runs narrowed or gated, so this text is what a
# reader actually sees in that one synthetic case, not the production
# path). The real checkout always imports the shared constant instead --
# see `_refuse_if_untiered_and_unclaimed` below.
_FALLBACK_REFUSAL_MESSAGE = (
    "test_run_guard: refusing an un-tiered full-suite run. Mid-loop, narrow it: "
    'python3 run_tests.py -p "test_<area>*.py" (WORKFLOW -> Implement -> Inner loop). '
    "At a gate, declare it: python3 run_tests.py --gate <red|green|verdict|finish> (PT-94 C9).\n"
)


def _refuse_if_untiered_and_unclaimed(args: argparse.Namespace) -> bool:
    """PT-119 gate-1 ruling, re-issued whole (architect, PT-119.md @6cd7e44):
    a runner-side backstop for an INDIRECTLY invoked run -- a wrapper
    script's body (`sh probe.sh`) is invisible to the command-text
    prefilter in `.claude/settings.json` and to both hooks, so neither
    ever sees it. Refuse when ALL hold: `CLAUDECODE` is set (any Claude
    Code lane -- there is no agent-identity env var to discriminate the
    lead's lane from a teammate's, measured live; this deliberately
    extends the refusal to the lead's own un-tiered full runs too, per
    the ruling's own judgment call), the run is FULL (no `-p`/
    `--pattern`/`-k` -- `--list` is exempt, same as PT-115's `--help`/
    `--list` exemption: nothing runs), and `--gate` is absent. Exact,
    never text-scanned: reads `args.pattern`/`args.gate` directly, so
    none of PT-111/113/115's defect class (quoted text, heredocs,
    versioned interpreters, launchers) can apply here at all. Caller
    must check this BEFORE discovery, `run_all`, and `_self_record` --
    a refused run leaves no ledger row, because nothing ran."""
    if not os.environ.get("CLAUDECODE"):
        return False
    if args.list or args.pattern != ["test_*.py"] or args.gate is not None:
        return False
    try:
        hooks_dir = SCRIPT_DIR.parent.parent / ".claude" / "hooks"
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        from _test_run_shared import REFUSAL_MESSAGE
    except Exception:
        REFUSAL_MESSAGE = _FALLBACK_REFUSAL_MESSAGE
    sys.stderr.write(REFUSAL_MESSAGE)
    return True

_RAN_RE = re.compile(r"^Ran (\d+) tests? in", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^(OK|FAILED)\b\s*(?:\(([^)]*)\))?", re.MULTILINE)
_NO_TESTS_RE = re.compile(r"^NO TESTS RAN", re.MULTILINE)


class ParseError(Exception):
    """Raised when a child's stderr doesn't contain unittest's own summary
    lines — e.g. the `-t .` trap, where every module dies on ImportError
    before unittest ever prints "Ran N tests". Guard threshold 3: this
    must surface as an error, never a silently-returned 0."""


def discover_files(tests_dir: Path, patterns: List[str]) -> List[Path]:
    found = set()
    for pattern in patterns:
        found.update(tests_dir.glob(pattern))
    return sorted(found)


def order_by_size(files: List[Path]) -> List[Path]:
    """Largest source file first — see module docstring."""
    return sorted(files, key=lambda p: (-p.stat().st_size, p.name))


def build_argv(python_exe: str, file_name) -> List[str]:
    return [python_exe, "-m", "unittest", "discover", "-s", "tests", "-p", str(file_name)]


def _last_match(pattern: "re.Pattern", text: str):
    last = None
    for last in pattern.finditer(text):
        pass
    return last


def parse_summary(stderr: str, file_name: Optional[str] = None) -> Tuple[int, int, int, int]:
    # Gate-4 verdict delta 6 (PT-97.md @ 0b44fc4, found in PT-97, recorded
    # as a PT-93 AC1 defect on the failure axis): unittest prints its own
    # real summary LAST. `.search` (first match) undercounts the moment
    # anything upstream leaks an earlier "Ran N tests"/"OK|FAILED" line --
    # measured live: this suite's own test_run_tests.py leaked an early
    # "OK (skipped=0)" ahead of its real "FAILED (failures=1)", and the
    # first-match parse silently dropped that one failure. `failed_files`
    # was never wrong (it comes from the child's returncode) -- only the
    # failure *count*, which is why PT-93's own counts-only guards missed it.
    ran_match = _last_match(_RAN_RE, stderr)
    summary_match = _last_match(_SUMMARY_RE, stderr)
    if not ran_match or not summary_match:
        # NO TESTS RAN is parseable -- unittest exits 5 and prints a "Ran 0
        # tests" line with no OK/FAILED summary -- and it names a real,
        # nameable condition (an empty test file, a bad -k), not the
        # generic "garbled output" case. Gate-4 verdict delta 2: never
        # lump the two into the same message.
        if _NO_TESTS_RE.search(stderr):
            raise ParseError(f"no tests ran in {file_name if file_name is not None else '<unknown>'}")
        raise ParseError(f"unparseable unittest stderr: {stderr[:200]!r}")
    ran = int(ran_match.group(1))
    failures = errors = skipped = 0
    detail = summary_match.group(2) or ""
    for part in detail.split(","):
        key, _, val = part.strip().partition("=")
        key = key.strip()
        val = val.strip()
        if val.isdigit():
            if key == "failures":
                failures = int(val)
            elif key == "errors":
                errors = int(val)
            elif key == "skipped":
                skipped = int(val)
    return ran, failures, errors, skipped


def default_jobs() -> int:
    return min(8, os.cpu_count() or 4)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_tests.py",
        description="File-level parallel runner for the cairn Python suite (PT-93).",
    )
    parser.add_argument("-p", "--pattern", dest="pattern", action="append", default=None,
                         help='glob pattern under tests/, repeatable (default: "test_*.py")')
    jobs_group = parser.add_mutually_exclusive_group()
    jobs_group.add_argument("-j", "--jobs", dest="jobs", type=int, default=None,
                             help="worker count (default: min(8, cpu_count))")
    jobs_group.add_argument("--serial", dest="serial", action="store_true", help="equivalent to -j 1")
    parser.add_argument("--list", dest="list", action="store_true", help="print discovered file names and exit")
    parser.add_argument("--json", dest="json", default=None, metavar="PATH",
                         help="write the machine-readable summary to PATH")
    parser.add_argument(
        "--gate", dest="gate", default=None, choices=("red", "green", "verdict", "finish"),
        help="declares this as a full-suite gate run (PT-94 C9) -- required for a full run "
             "under the PT-97 PreToolUse guard; the PostToolUse recorder reads it back out "
             "of the command line, it is not consumed here",
    )
    args = parser.parse_args(argv)
    if args.gate is not None and args.pattern is not None:
        # Gate-4 verdict delta 5 (PT-97.md @ bfb1d92): a narrowed run is
        # not a gate run (PT-94 C9 -- the gate owner runs the full
        # suite). Silently dropping --gate would leave the operator
        # believing they recorded a gate that never happened; refuse
        # instead. Checked here, before the pattern default below, so
        # this only fires when the caller actually passed -p/--pattern.
        parser.error(
            "--gate is a full-suite gate run and cannot be combined with -p/--pattern "
            "(a narrowed run is not a gate run, PT-94 C9) -- drop --gate for a tiered "
            "mid-loop run, or drop -p/--pattern to run the full suite at this gate."
        )
    if args.serial:
        args.jobs = 1
    elif args.jobs is None:
        args.jobs = default_jobs()
    if args.pattern is None:
        args.pattern = ["test_*.py"]
    return args


def _run_one(file: Path, cwd: Path, runner) -> Dict[str, object]:
    t0 = time.time()
    completed = runner(build_argv(sys.executable, file.name), cwd=str(cwd),
                        capture_output=True, text=True)
    seconds = time.time() - t0
    try:
        ran, failures, errors, skipped = parse_summary(completed.stderr, file_name=file.name)
        unparseable = False
    except ParseError:
        ran, failures, skipped = 0, 0, 0
        errors = 1
        unparseable = True
    failed = completed.returncode != 0 or unparseable
    return {
        "name": file.name,
        "seconds": seconds,
        "ran": ran,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "failed": failed,
        "output": (completed.stdout or "") + (completed.stderr or ""),
    }


def _run_files(files: List[Path], cwd: Path, jobs: int, runner) -> List[Dict[str, object]]:
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        return list(executor.map(lambda f: _run_one(f, cwd, runner), files))


def _aggregate(results: List[Dict[str, object]], jobs: int, wall: float) -> Dict[str, object]:
    return {
        "wall": round(wall, 3),
        "jobs": jobs,
        "files": len(results),
        "tests": sum(r["ran"] for r in results),
        "failures": sum(r["failures"] for r in results),
        "errors": sum(r["errors"] for r in results),
        "skipped": sum(r["skipped"] for r in results),
        "failed_files": [r["name"] for r in results if r["failed"]],
        "times": {r["name"]: round(r["seconds"], 2) for r in results},
        # Gate-4 verdict delta (PT-96.md @ 85006ff, blocking): populated
        # for failing files only, so a green run's aggregate stays small.
        # main() prints each entry above that file's FAIL line -- the
        # PT-93 contract ("a failing file prints its captured stdout+
        # stderr, then a FAIL <name> (<s>s) line") that this dict's
        # earlier shape silently dropped.
        "outputs": {r["name"]: r["output"] for r in results if r["failed"]},
    }


def run_all(files: List[Path], jobs: int, cwd: Path, runner=None) -> Dict[str, object]:
    runner = runner or subprocess.run
    t0 = time.time()
    results = _run_files(files, cwd, jobs, runner)
    wall = time.time() - t0
    return _aggregate(results, jobs, wall)


def exit_code(agg: Dict[str, object]) -> int:
    return 0 if not agg["failed_files"] else 1


_RECORDS_REL = Path("process") / "cairn" / "metrics" / "test-runs.jsonl"
# PT-97 gate-4 verdict delta 7 (PT-97.md @ f66fe09, blocking): _self_record
# derives repo_root from this script's own __file__ location -- for a REAL
# subprocess spawn of the real run_tests.py (several guard tests do this),
# that location IS the real checkout, so every such spawn silently
# appended to the committed process/cairn/metrics/test-runs.jsonl. Tests
# that spawn the real script set this to a throwaway path instead.
_RECORDS_PATH_ENV = "CAIRN_TEST_RUNS_FILE"


def _run_git(repo_root: Path, *git_args: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(repo_root), *git_args], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _resolve_worktree_main_checkout(repo_root: Path) -> Optional[Path]:
    """PT-82 (architect's ruling, re-issued, PT-82.md @ 69e9664): the
    MAIN checkout's root, iff `repo_root` is a LINKED worktree --
    discriminated by `--git-dir != --git-common-dir`. Measured, four
    contexts: a linked worktree is the ONLY one where they differ
    (`--git-dir` = `.git/worktrees/<name>`, `--git-common-dir` = the
    main `.git`); the main checkout and a fake engine root NESTED INSIDE
    this repo both report the same value for both -- so common-dir alone
    is not a safe signal, and using it unconditionally would redirect a
    fake-engine-root test copy's self-record into the real
    `test-runs.jsonl`. `None` for every other case (main checkout, a
    fake root inside or outside a repo, git unavailable) -- callers fall
    back to the pre-existing default. Never raises."""
    try:
        git_dir = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=5,
        )
        common_dir = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError):
        return None
    if git_dir.returncode != 0 or common_dir.returncode != 0:
        return None
    git_dir_path = (repo_root / git_dir.stdout.strip()).resolve()
    common_dir_path = (repo_root / common_dir.stdout.strip()).resolve()
    if git_dir_path == common_dir_path:
        return None  # main checkout, or a fake root nested inside the repo
    return common_dir_path.parent


def _self_record(args: argparse.Namespace, agg: Dict[str, object]) -> None:
    """Gate-4 verdict delta 2 (PT-97.md @ d896d8d, blocking): the runner
    writes its own record -- it has the counts, seconds, jobs and gate
    directly, in-process, so nothing needs scraping back out of stdout
    afterward (unreliable the moment a gate owner pipes to `| tail`, per
    the verdict's own three reproduction runs). `who` is left null: only
    `.claude/hooks/test_run_record.py`'s `agent_type` field knows that,
    and it patches this same line in afterward. Repo root is derived from
    this file's own location, not $CLAUDE_PROJECT_DIR -- the runner must
    work identically under a fake-engine-root test copy and in the real
    checkout. Never raises: a broken recorder must not fail the run it's
    attached to.

    PT-82 (architect's ruling, re-issued whole, PT-82.md @ 69e9664,
    superseding @6316a9b and its addenda, item (c)): from a teammate's
    worktree, `repo_root` above resolves to the WORKTREE's own checkout
    (a linked worktree, same file layout), so a gate run recorded there
    never reaches the main checkout's `test-runs.jsonl` -- `cairn
    loop-stats` and the PostToolUse hook both read the main checkout's
    copy. `$CLAUDE_PROJECT_DIR` is unset in a teammate's own Bash tool
    calls (only set for hook shells), so it cannot be the discriminator
    (measured, spike step 9's correction). `CAIRN_TEST_RUNS_FILE` (the
    existing override) wins if set; otherwise `_resolve_worktree_main_checkout`
    below is tried: it uses `git rev-parse --git-common-dir` (cwd-based, no environment
    dependency, follows the worktree) -- but ONLY when `--git-dir !=
    --git-common-dir`, which is true SOLELY in a linked worktree.
    Measured: both compare equal in the main checkout AND in a fake
    engine root nested inside this repo, so common-dir alone is not a
    safe signal -- unguarded, it would redirect a fake-engine-root test
    copy's self-record into the REAL `test-runs.jsonl`, exactly the
    regression the file-location default exists to prevent. Every other
    case (main checkout, fake root inside or outside a repo, git
    unavailable) falls back to today's `repo_root` default.

    PT-107 (architect's ruling, PT-107.md @ 1aa5a71): `sha` and `branch`
    are both resolved from `records_repo_root` -- never from the
    worktree, even under the redirect. They must come from one root: a
    record naming a `sha` that is not on its own `branch` is worse than
    a `sha` a few commits behind the worktree that actually ran."""
    try:
        repo_root = SCRIPT_DIR.parent.parent
        records_repo_root = repo_root
        if not os.environ.get(_RECORDS_PATH_ENV):
            main_checkout = _resolve_worktree_main_checkout(repo_root)
            if main_checkout is not None:
                records_repo_root = main_checkout
        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "who": None,
            "gate": args.gate,
            "full": args.pattern == ["test_*.py"],
            "runner": "run_tests",
            "sha": _run_git(records_repo_root, "rev-parse", "HEAD"),
            "branch": _run_git(records_repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
            "seconds": agg["wall"],
            "harness_ms": None,
            "jobs": args.jobs,
            "files": agg["files"],
            "tests": agg["tests"],
            "skipped": agg["skipped"],
            "ok": exit_code(agg) == 0,
            # PT-116 gate-1 ruling (PT-116.md @8c1cc29): failure detail --
            # both counts come straight from the in-process aggregate, so
            # they are always known (never null-filled) on this path,
            # whether zero or not.
            "failures": agg["failures"],
            "errors": agg["errors"],
            # PT-112 gate-1 ruling (PT-112.md @8b60a8b): the hook's stdin
            # `session_id` and this process's own `CLAUDE_CODE_SESSION_ID`
            # are the identical string (measured live) -- a deterministic
            # attribution key needing no new channel and no run id printed
            # in the summary (unreadable the moment stdout is redirected
            # or suppressed, per PT-111's own measurement).
            "session": os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
            "cmd": " ".join([sys.executable] + sys.argv)[:200],
        }
        override = os.environ.get(_RECORDS_PATH_ENV)
        path = Path(override) if override else (records_repo_root / _RECORDS_REL)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # PT-119 gate-1 ruling: checked before discovery/run_all/_self_record --
    # nothing has run yet, so a refusal leaves no ledger row at all.
    # `__name__ == "__main__"` -- same guard as _self_record's own call
    # site below (PT-97 gate-4 delta 7's reasoning applies identically
    # here): true for a real `python3 run_tests.py ...` invocation
    # (direct or via an indirect wrapper, subprocess either way), false
    # when a test imports this module and calls main() in-process to
    # exercise its internal plumbing -- that is not a run a teammate
    # typed, and must never be refused.
    if __name__ == "__main__" and _refuse_if_untiered_and_unclaimed(args):
        return 2

    files = discover_files(TESTS_DIR, args.pattern)

    if not files:
        # Gate-4 verdict delta 1 (blocking): the tiered rule has every
        # teammate typing `-p "test_<area>*.py"` mid-loop, and a typo'd
        # or wrong-prefix pattern used to discover nothing and still exit
        # 0 -- a silent pass on the exact operator error the runner
        # exists to catch. Exit 2, distinct from 1 (a red suite), so a
        # caller can tell "nothing ran" from "something failed". Applies
        # to --list too -- it's the same discovery step.
        print(f"no test files matched: {args.pattern}", file=sys.stderr)
        return 2

    if args.list:
        for file in files:
            print(file.name)
        return 0

    files = order_by_size(files)
    agg = run_all(files, args.jobs, TESTS_DIR.parent)
    if __name__ == "__main__":
        # Only when this file is the actual running script (a real `python3
        # run_tests.py ...` invocation, subprocess or direct) -- NOT when a
        # test imports this module and calls main() in-process
        # (test_run_tests.py's MainCallsRunAllTests mocks discover_files/
        # order_by_size/subprocess.run/run_all, per D11, but self-recording
        # is a side effect none of those patch, and it must never write
        # into the real repo's process/cairn/metrics/test-runs.jsonl from
        # a unit test run). `__name__` here is this module's own global,
        # true regardless of who calls main() -- exactly the signal needed.
        _self_record(args, agg)

    for name in agg["failed_files"]:
        output = agg["outputs"].get(name, "")
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        print(f"FAIL {name} ({agg['times'].get(name, 0.0):.2f}s)")

    print(f"Ran {agg['tests']} tests in {agg['wall']:.3f}s ({agg['files']} files, {agg['jobs']} workers)")
    if exit_code(agg) == 0:
        print(f"OK (skipped={agg['skipped']})")
    else:
        print(f"FAILED (failures={agg['failures']}, errors={agg['errors']}, files={len(agg['failed_files'])})")

    if args.json:
        Path(args.json).write_text(json.dumps(agg, indent=1) + "\n")

    return exit_code(agg)


if __name__ == "__main__":
    sys.exit(main())
