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


def parse_summary(stderr: str, file_name: Optional[str] = None) -> Tuple[int, int, int, int]:
    ran_match = _RAN_RE.search(stderr)
    summary_match = _SUMMARY_RE.search(stderr)
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
    args = parser.parse_args(argv)
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


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
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
