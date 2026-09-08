"""PT-93 gate 2 (qa-engineer): failing tests for scripts/cairn/run_tests.py,
the parallel test runner, pinned to the architect's gate-1 ruling
(process/cairn/issues/PT-93.md @ cb3b4a4 -- "Seam" and "Guard thresholds").

D11 (this feature pays back the seconds it adds): NONE of these tests may
run the real 1379-test suite. Every test that needs a subprocess.run of the
runner's *inner* logic mocks it; the only real subprocess calls here are
`--list` (prints names, never runs a test) and pure-function calls against
run_tests.py's own module-level functions.

Expected public surface of run_tests.py (this file IS the spec for gate 3):
    discover_files(tests_dir, patterns) -> List[Path]      sorted, deduped
    build_argv(python_exe, file_name) -> List[str]          exact child argv, no -t
    parse_summary(stderr, file_name=...) -> (ran, failures, errors, skipped)
    ParseError                                              raised, not swallowed;
                                                             a NO TESTS RAN child names
                                                             the file ("no tests ran in
                                                             <file>"), not a generic message
    order_by_size(files) -> List[Path]                      largest first
    default_jobs() -> int                                   min(8, os.cpu_count() or 4)
    parse_args(argv) -> argparse.Namespace                   .jobs, .pattern, .serial, .list, .json
    run_all(files, jobs, cwd, runner=subprocess.run) -> dict  wall/jobs/files/tests/failures/
                                                              errors/skipped/failed_files/times
    exit_code(agg) -> int                                    0 iff failed_files == []
    main(argv) -> int                                        CLI entry. A -p pattern
                                                              matching zero files (run
                                                              OR --list) prints "no test
                                                              files matched: <patterns>"
                                                              to stderr and exits 2 --
                                                              distinct from 1 (red suite).

Gate-4 verdict deltas (2fd2a01, blocking): the empty-pattern safety net
(EmptyPatternSafetyTests below) and the NO-TESTS-RAN message fix
(ParseSummaryNoTestsRanTests below) were added after the first build --
see PT-93.md @ 8c4409e.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import helpers  # noqa: F401

import run_tests

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
REAL_METRICS_DIR = REPO_ROOT / "process" / "cairn" / "metrics"
REAL_TEST_RUNS_PATH = REAL_METRICS_DIR / "test-runs.jsonl"
REAL_RECEIVER_PIDFILE = REAL_METRICS_DIR / ".receiver.pid"
REAL_SESSIONS_DIR = REAL_METRICS_DIR / ".sessions"
# PT-97 delta 7 seam: run_tests.py's _self_record honours this override
# when set, writing there instead of the path it derives from its own
# __file__ location -- which, for a REAL subprocess spawn of the real
# script (several tests below do this), IS the real checkout.
CAIRN_TEST_RUNS_ENV = "CAIRN_TEST_RUNS_FILE"


def _completed(returncode: int, stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout="", stderr=stderr)


def _env_with_test_runs_override(tmp_path) -> dict:
    env = dict(os.environ)
    env[CAIRN_TEST_RUNS_ENV] = str(tmp_path)
    return env


class DiscoveryTests(unittest.TestCase):
    """Guard threshold 1: discovery == sorted(glob("test_*.py")), >= 80
    files; -p narrows it; --list prints exactly that, exit 0."""

    def test_default_pattern_discovers_at_least_80_files_matching_sorted_glob(self):
        expected = sorted(helpers.TESTS_DIR.glob("test_*.py"))
        got = run_tests.discover_files(helpers.TESTS_DIR, ["test_*.py"])
        self.assertEqual(got, expected)
        self.assertGreaterEqual(len(got), 80, "the real suite has 82 test_*.py files at this sha")

    def test_a_narrower_pattern_returns_only_matching_files(self):
        got = run_tests.discover_files(helpers.TESTS_DIR, ["test_run_tests.py"])
        self.assertEqual([p.name for p in got], ["test_run_tests.py"])

    def test_cli_list_prints_exactly_the_discovered_names_and_exits_zero(self):
        expected_names = [p.name for p in sorted(helpers.TESTS_DIR.glob("test_*.py"))]
        result = subprocess.run(
            [sys.executable, str(helpers.CAIRN_DIR / "run_tests.py"), "--list"],
            cwd=helpers.CAIRN_DIR, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        printed = [line for line in result.stdout.splitlines() if line]
        self.assertEqual(printed, expected_names)


class EmptyPatternSafetyTests(unittest.TestCase):
    """Gate-4 verdict delta 1 (blocking, PT-93.md @ 8c4409e): a `-p`
    pattern matching nothing must not silently exit 0 -- that is exactly
    the operator-typo class the tiered rule invites (every teammate runs
    `run_tests.py -p "test_<area>*.py"` mid-loop). Real subprocess calls
    of the built script, both `--list` and a run: neither ever executes a
    real test (discovery finds nothing, or narrows to one small real
    file), so this stays inside D11."""

    NONEXISTENT_PATTERN = "test_zzz_pt93_nonexistent_area*.py"

    def _run(self, *args):
        tmp = helpers.make_empty_tmp_dir(self)
        return subprocess.run(
            [sys.executable, str(helpers.CAIRN_DIR / "run_tests.py"), *args],
            cwd=helpers.CAIRN_DIR, capture_output=True, text=True,
            env=_env_with_test_runs_override(tmp / "test-runs.jsonl"),
        )

    def test_a_pattern_matching_nothing_exits_2_and_names_the_pattern(self):
        result = self._run("-p", self.NONEXISTENT_PATTERN)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(self.NONEXISTENT_PATTERN, result.stderr)

    def test_list_with_a_pattern_matching_nothing_also_exits_2_and_names_the_pattern(self):
        result = self._run("--list", "-p", self.NONEXISTENT_PATTERN)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(self.NONEXISTENT_PATTERN, result.stderr)

    def test_a_matching_pattern_still_exits_0_control(self):
        # Control (the guard must not pass by rejecting everything): a
        # real, narrow, matching pattern -- a small, fast, real test file
        # that spawns nothing itself, so this run costs milliseconds, not
        # a copy of the real suite.
        result = self._run("-p", "test_id_sort.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ChildArgvTests(unittest.TestCase):
    """Guard threshold 2: child argv equals the ruling's list element for
    element; '-t' never appears (the measured trap: -t . drops tests/ off
    sys.path and every module dies on `import helpers`)."""

    def test_build_argv_matches_the_ruling_exactly(self):
        argv = run_tests.build_argv(sys.executable, "test_x.py")
        self.assertEqual(
            argv,
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_x.py"],
        )
        self.assertNotIn("-t", argv)


class ParseSummaryTests(unittest.TestCase):
    """Guard threshold 3: parsing real unittest stderr yields (ran,
    failures, errors, skipped); a `Ran 0 tests` child contributes 0 rather
    than being dropped; an unparseable child is an error, not a silent 0."""

    def test_ok_with_skipped(self):
        stderr = "Ran 26 tests in 0.212s\n\nOK (skipped=1)\n"
        self.assertEqual(run_tests.parse_summary(stderr), (26, 0, 0, 1))

    def test_failed_with_failures_and_errors(self):
        stderr = "Ran 12 tests in 1.011s\n\nFAILED (failures=2, errors=1)\n"
        self.assertEqual(run_tests.parse_summary(stderr), (12, 2, 1, 0))

    def test_ran_zero_tests_contributes_zero_not_dropped(self):
        stderr = "Ran 0 tests in 0.000s\n\nOK\n"
        self.assertEqual(run_tests.parse_summary(stderr), (0, 0, 0, 0))

    def test_unparseable_stderr_raises_rather_than_silently_returning_zero(self):
        # e.g. the -t . trap: every module dies on ImportError before
        # unittest ever prints its own "Ran N tests" summary line.
        stderr = "Traceback (most recent call last):\nImportError: no module named helpers\n"
        with self.assertRaises(run_tests.ParseError):
            run_tests.parse_summary(stderr)


class ParseSummaryNoTestsRanTests(unittest.TestCase):
    """Gate-4 verdict delta 2 (PT-93.md @ 8c4409e): a NO TESTS RAN child
    (measured for real, `python3 -m unittest discover -s tests -p
    "palette_check.py"` -> exit 5, exact stderr below) must report 'no
    tests ran in <file>', not the generic 'unparseable unittest stderr'
    message -- it IS parseable, just a different, nameable condition
    (guard threshold 3 read correctly: never a silent 0, and the message
    must say what actually happened)."""

    # Captured verbatim from the real command above.
    NO_TESTS_RAN_STDERR = (
        "\n----------------------------------------------------------------------\n"
        "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n"
    )

    def test_no_tests_ran_still_raises_but_names_the_file(self):
        with self.assertRaises(run_tests.ParseError) as ctx:
            run_tests.parse_summary(self.NO_TESTS_RAN_STDERR, file_name="palette_check.py")
        self.assertIn("no tests ran in palette_check.py", str(ctx.exception))

    def test_genuinely_unparseable_stderr_is_not_lumped_in_with_no_tests_ran(self):
        stderr = "Traceback (most recent call last):\nImportError: no module named helpers\n"
        with self.assertRaises(run_tests.ParseError) as ctx:
            run_tests.parse_summary(stderr, file_name="test_x.py")
        self.assertNotIn("no tests ran", str(ctx.exception))


class ParseSummaryTakesTheLastMatchTests(unittest.TestCase):
    """Gate-4 verdict delta 6 (PT-97.md @ 0b44fc4): parse_summary must
    take the LAST `Ran N tests`/`OK|FAILED` match, not the first --
    unittest prints its own real summary last, so a leaked earlier
    summary (e.g. a red test's own failure message embedding a nested
    subprocess's successful child output -- exactly what happened in
    this file, see GateRequiresFullRunTests below) must never shadow it.
    Measured live at 84e2f32: test_run_tests.py's own child stderr
    carried an early leaked 'OK (skipped=0)' (line 9) ahead of its real
    'FAILED (failures=1)' (line 15) -- parse_summary's first-match
    .search undercounted the true failure by exactly one."""

    def test_a_leaked_early_summary_does_not_shadow_the_real_last_one(self):
        stderr = (
            "Ran 2 tests in 0.01s\n\nOK (skipped=0)\n"
            "\n----------------------------------------------------------------------\n"
            "Ran 28 tests in 0.5s\n\nFAILED (failures=1)\n"
        )
        self.assertEqual(run_tests.parse_summary(stderr), (28, 1, 0, 0))

    def test_control_a_normal_single_summary_stderr_parses_identically(self):
        # The fix cannot pass by breaking the common (single-summary)
        # case -- this must parse the same whether first- or last-match.
        stderr = "Ran 28 tests in 0.5s\n\nFAILED (failures=1)\n"
        self.assertEqual(run_tests.parse_summary(stderr), (28, 1, 0, 0))


class DefaultJobsTests(unittest.TestCase):
    """Guard threshold 5: default jobs == min(8, os.cpu_count() or 4);
    --serial => jobs 1."""

    def test_default_jobs_matches_the_formula(self):
        self.assertEqual(run_tests.default_jobs(), min(8, os.cpu_count() or 4))

    def test_parse_args_default_jobs(self):
        args = run_tests.parse_args([])
        self.assertEqual(args.jobs, min(8, os.cpu_count() or 4))

    def test_serial_flag_forces_one_job(self):
        args = run_tests.parse_args(["--serial"])
        self.assertEqual(args.jobs, 1)

    def test_explicit_jobs_flag_is_honoured(self):
        args = run_tests.parse_args(["--jobs", "3"])
        self.assertEqual(args.jobs, 3)

    @patch("os.cpu_count", return_value=None)
    def test_cpu_count_none_falls_back_to_four(self, _mock):
        self.assertEqual(run_tests.default_jobs(), min(8, 4))


class SizeOrderingTests(unittest.TestCase):
    """Guard threshold 6: for files of known sizes, submission order is
    size-descending."""

    def test_files_are_ordered_largest_first(self):
        tmp = helpers.make_empty_tmp_dir(self)
        small = tmp / "test_small.py"
        medium = tmp / "test_medium.py"
        large = tmp / "test_large.py"
        small.write_text("x" * 10, encoding="utf-8")
        medium.write_text("x" * 100, encoding="utf-8")
        large.write_text("x" * 1000, encoding="utf-8")
        ordered = run_tests.order_by_size([small, medium, large])
        self.assertEqual([p.name for p in ordered], ["test_large.py", "test_medium.py", "test_small.py"])


class AggregationExitCodeTests(unittest.TestCase):
    """Guard threshold 4: one child exiting non-zero => process exit 1 and
    that name in failed_files; all zero => exit 0, failed_files == [].
    Every subprocess.run call here is mocked -- no real test file is ever
    executed (D11)."""

    def _run_all_with(self, side_effects):
        files = [Path(f"test_fake_{i}.py") for i in range(len(side_effects))]
        with patch("run_tests.subprocess.run", side_effect=side_effects):
            return run_tests.run_all(files, jobs=1, cwd=Path("."))

    def test_all_files_passing_exits_zero_and_failed_files_empty(self):
        agg = self._run_all_with([
            _completed(0, "Ran 3 tests in 0.01s\n\nOK\n"),
            _completed(0, "Ran 5 tests in 0.02s\n\nOK (skipped=1)\n"),
        ])
        self.assertEqual(run_tests.exit_code(agg), 0)
        self.assertEqual(agg["failed_files"], [])
        self.assertEqual(agg["tests"], 8)
        self.assertEqual(agg["skipped"], 1)

    def test_one_failing_file_exits_nonzero_and_is_named(self):
        agg = self._run_all_with([
            _completed(0, "Ran 3 tests in 0.01s\n\nOK\n"),
            _completed(1, "Ran 5 tests in 0.02s\n\nFAILED (failures=1)\n"),
        ])
        self.assertEqual(run_tests.exit_code(agg), 1)
        self.assertEqual(agg["failed_files"], ["test_fake_1.py"])

    def test_an_unparseable_child_counts_as_an_error_not_a_silent_pass(self):
        agg = self._run_all_with([
            _completed(0, "garbage, no summary line at all\n"),
        ])
        self.assertEqual(run_tests.exit_code(agg), 1)
        self.assertEqual(agg["failed_files"], ["test_fake_0.py"])
        self.assertEqual(agg["errors"], 1)


class JsonOutputTests(unittest.TestCase):
    """Guard threshold 7: --json writes every key from the ruling's Seam
    section; `times` has one entry per discovered file."""

    def test_run_all_result_has_every_required_key_and_one_time_entry_per_file(self):
        files = [Path("test_a.py"), Path("test_b.py")]
        side_effects = [
            _completed(0, "Ran 1 tests in 0.01s\n\nOK\n"),
            _completed(0, "Ran 2 tests in 0.02s\n\nOK\n"),
        ]
        with patch("run_tests.subprocess.run", side_effect=side_effects):
            agg = run_tests.run_all(files, jobs=1, cwd=Path("."))
        for key in ("wall", "jobs", "files", "tests", "failures", "errors", "skipped", "failed_files", "times"):
            self.assertIn(key, agg, f"missing required key {key!r}")
        self.assertEqual(set(agg["times"]), {"test_a.py", "test_b.py"})


class FailingOutputDiagnosticsTests(unittest.TestCase):
    """Gate-4 verdict delta 1 (PT-96.md @ 85006ff, blocking): run_all must
    return each failing child's captured output, and main() must print it
    above that file's FAIL line -- restoring the PT-93 contract exactly
    ("A failing file prints its captured stdout+stderr, then a FAIL
    <name> (<s>s) line"). Measured regression at c36af58: run_all drops
    the output entirely, so main has nothing to print -- a red suite
    today names the file and nothing else. discover_files/order_by_size/
    subprocess.run are all patched (D11); real stdout is captured, never
    left to leak (delta 2, same batch)."""

    def _main_output(self, side_effects, fake_files, argv=None):
        buf = io.StringIO()
        with patch("run_tests.discover_files", return_value=fake_files), \
             patch("run_tests.order_by_size", return_value=fake_files), \
             patch("run_tests.subprocess.run", side_effect=side_effects), \
             redirect_stdout(buf):
            rc = run_tests.main(argv or ["--jobs", "1"])
        return rc, buf.getvalue()

    def test_a_failing_childs_output_is_printed_above_its_fail_line(self):
        marker = "expected-marker-pt96"
        fake_files = [Path("test_fake_fail.py")]
        side_effects = [_completed(
            1, f"Traceback (most recent call last):\nAssertionError: {marker!r}\n"
               f"Ran 1 tests in 0.01s\n\nFAILED (failures=1)\n",
        )]
        rc, out = self._main_output(side_effects, fake_files)
        self.assertNotEqual(rc, 0)
        self.assertIn(marker, out, "the failing child's captured output must appear in main()'s stdout")
        fail_line_pos = out.find("FAIL test_fake_fail.py")
        marker_pos = out.find(marker)
        self.assertNotEqual(fail_line_pos, -1, f"no FAIL line printed at all -- got: {out!r}")
        self.assertLess(
            marker_pos, fail_line_pos,
            "the PT-93 contract prints diagnostics ABOVE the FAIL line, not below or instead of it",
        )

    def test_a_green_run_prints_no_per_file_output(self):
        # Control: the guard above can't pass by printing every child's
        # output unconditionally -- a passing run must print only the one
        # aggregate summary, never a child's own "Ran N tests"/"OK" text.
        fake_files = [Path("test_fake_ok.py"), Path("test_fake_ok2.py")]
        side_effects = [
            _completed(0, "Ran 3 tests in 0.01s\n\nOK\n"),
            _completed(0, "Ran 2 tests in 0.01s\n\nOK\n"),
        ]
        rc, out = self._main_output(side_effects, fake_files)
        self.assertEqual(rc, 0)
        self.assertNotIn("FAIL ", out, "a passing file must never print a FAIL line")
        self.assertEqual(
            out.count("Ran "), 1,
            f"a green run must print only the aggregate 'Ran <N> tests' line, never a "
            f"child's own summary too -- got: {out!r}",
        )


class MainCallsRunAllTests(unittest.TestCase):
    """PT-96 gate-1 ruling AC6 (PT-93.md @ 8c4409e, "note, no action this
    loop", folded into PT-96): main() must call run_all() rather than
    re-implementing its timer-plus-aggregate sequence inline -- otherwise
    run_all's own guard tests (AggregationExitCodeTests etc.) don't cover
    the CLI path they describe. discover_files/order_by_size/subprocess.run
    are all patched so this never touches a real file or the real suite
    (D11)."""

    def test_main_calls_run_all_with_the_ordered_file_list_and_resolved_jobs(self):
        fake_files = [Path("test_b.py"), Path("test_a.py")]
        ordered = [Path("test_a.py"), Path("test_b.py")]
        fake_agg = {
            "wall": 0.01, "jobs": 3, "files": 2, "tests": 2, "failures": 0,
            "errors": 0, "skipped": 0, "failed_files": [], "times": {},
        }
        harmless_completed = _completed(0, "Ran 1 tests in 0.01s\n\nOK\n")
        # Gate-4 verdict delta 2 (PT-96.md @ 85006ff): main() writes to
        # real stdout -- left uncaptured here, a full `discover` run of
        # this suite emits a stray second "Ran 2 tests"/"OK" pair after
        # its own summary, defeating PT-93's one-summary-per-run contract
        # that external greps rely on.
        with patch("run_tests.discover_files", return_value=fake_files), \
             patch("run_tests.order_by_size", return_value=ordered), \
             patch("run_tests.subprocess.run", return_value=harmless_completed), \
             patch("run_tests.run_all", return_value=fake_agg) as mock_run_all, \
             redirect_stdout(io.StringIO()):
            rc = run_tests.main(["--jobs", "3"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            mock_run_all.call_count, 1,
            "main() must call run_all() -- if this is 0, main() is still re-implementing "
            "run_all's timer-plus-aggregate sequence inline",
        )
        call = mock_run_all.call_args
        passed_files = call.args[0] if call.args else call.kwargs.get("files")
        self.assertEqual(passed_files, ordered, "must pass the already-ordered (size-descending) file list")
        passed_jobs = call.args[1] if len(call.args) > 1 else call.kwargs.get("jobs")
        self.assertEqual(passed_jobs, 3, "must pass the resolved job count, not the raw --jobs string or None")


class GateRequiresFullRunTests(unittest.TestCase):
    """Gate-4 verdict delta 5 (PT-97.md @ bfb1d92): --gate combined with
    -p/--pattern is refused -- a narrowed run is not a gate run (PT-94
    C9: the gate owner runs the full suite), and silently dropping the
    tag would leave the operator believing they recorded a gate that
    never happened. Belongs in the runner, not the hook -- the runner is
    the only party that parses its own flags reliably (the whole lesson
    of delta 1's substring bugs)."""

    def test_gate_combined_with_pattern_is_refused(self):
        tmp = helpers.make_empty_tmp_dir(self)
        result = subprocess.run(
            [sys.executable, str(helpers.CAIRN_DIR / "run_tests.py"), "--gate", "green", "-p", "test_yaml_parser.py"],
            cwd=helpers.CAIRN_DIR, capture_output=True, text=True,
            env=_env_with_test_runs_override(tmp / "test-runs.jsonl"),
        )
        # PT-97 delta 6: while this test is red (pre-fix, the inner call
        # actually runs test_yaml_parser.py successfully), embedding the
        # child's RAW stdout+stderr here would put its own "Ran N tests"/
        # "OK" lines, real newlines and all, into THIS module's own
        # output when some outer run_tests.py aggregates this file --
        # exactly the leak the delta measured (test_run_tests.py line 9).
        # repr() collapses those newlines to literal "\n" text so no
        # MULTILINE `^(OK|FAILED)` scan can ever match inside it.
        self.assertEqual(result.returncode, 2, repr(result.stdout + result.stderr))
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)

    def test_gate_alone_still_parses(self):
        # Control: the refusal is specific to the -p/--gate COMBINATION,
        # not to --gate itself.
        args = run_tests.parse_args(["--gate", "green"])
        self.assertEqual(args.gate, "green")


# --------------------------------------------------------------------------
# PT-97 delta 7 (blocking, PT-97.md @ f66fe09): _self_record derives its
# repo root from the SCRIPT'S OWN __file__ location -- for a real
# subprocess spawn of the real run_tests.py (several tests above do this),
# that IS the real checkout, so every such spawn silently appended to the
# real process/cairn/metrics/test-runs.jsonl. This module-wide backstop
# catches any test in this file (present or future) that spawns the real
# script without the CAIRN_TEST_RUNS_FILE override. setUpModule/
# tearDownModule are unittest's own guaranteed whole-module brackets (a
# per-class setUpClass/tearDownClass only brackets its own class -- PT-91/
# PT-84 discipline). A bare `assert` is stripped entirely under
# `python -O` (measured, PT-91/PT-95) -- raise explicitly instead.
# --------------------------------------------------------------------------

_REAL_STATE_SNAPSHOT = None


def setUpModule():
    # PT-100 (architect's re-issued ruling, PT-100.md @ 0487f33): ported
    # onto the shared, self-diagnosing snapshot -- raw-line multiset
    # containment for test-runs.jsonl (this file's records carry no
    # `issue` field, so the helper's issue-backing check treats any
    # added line as unbacked, preserving this guard's original
    # byte-exact-on-any-write intent); pidfile/sessions come along for
    # free even though this module never spawns a receiver.
    global _REAL_STATE_SNAPSHOT
    _REAL_STATE_SNAPSHOT = helpers.snapshot_real_state(
        REAL_TEST_RUNS_PATH, REAL_RECEIVER_PIDFILE, REAL_SESSIONS_DIR, REAL_METRICS_DIR.parent,
    )


def tearDownModule():
    helpers.assert_real_state_untouched(_REAL_STATE_SNAPSHOT)


if __name__ == "__main__":
    unittest.main()
