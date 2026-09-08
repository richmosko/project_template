"""PT-82 gate-1 ruling (architect, process/cairn/issues/PT-82.md @
6316a9b, item (c2)/AC3b): "PT-100's guard goes vacuous in a worktree."
`helpers.py`'s real-file-guard callers resolve the metrics directory
from the TEST FILE'S OWN LOCATION (`helpers.TESTS_DIR`-relative) --
from inside a teammate's worktree, that resolves to the WORKTREE's own
`process/cairn/metrics/`, which the daemon never writes. The guard
would pass while the main checkout's real file -- the thing it exists
to protect -- goes unwatched.

Ruled fix: metrics-path resolution prefers `CLAUDE_PROJECT_DIR` when
set, falling back to the current (`TESTS_DIR`-relative) derivation when
it is not. Mutation: dropping the `CLAUDE_PROJECT_DIR` preference
(reverting to the unconditional old derivation).

Assumed seam (the ruling fixes the OUTCOME -- resolve from
CLAUDE_PROJECT_DIR when set -- not this exact function name; flag to
the architect/implementation-lead if the real one diverges):
`helpers.real_metrics_dir() -> Path`, a NEW function the real-file-guard
CALLER modules (test_otel_receiver_self_stop.py etc., ported at PT-100)
use in place of their own hand-rolled `TESTS_DIR.parent.parent.parent /
"process" / "cairn" / "metrics"` construction, so the preference lives
in ONE place rather than being re-applied at every call site.

Real subprocess, real files on disk (never mocked): a fake "worktree"
directory holds its OWN copy of `helpers.py` (proving resolution can't
accidentally see the real repo's `__file__` location) plus its own,
DISTINCT `process/cairn/metrics/` -- and a separate fake "main checkout"
directory holds a DIFFERENT, distinguishable metrics tree. `helpers.py`
imported from the worktree copy, with `CLAUDE_PROJECT_DIR` pointed at
the main checkout, must resolve to the MAIN CHECKOUT's path."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

_PROBE_TEMPLATE = """
import os
import sys
from pathlib import Path

WORKTREE_TESTS_DIR = Path(sys.argv[1])
sys.path.insert(0, str(WORKTREE_TESTS_DIR))
import helpers  # noqa: E402

assert hasattr(helpers, "real_metrics_dir"), (
    "helpers.real_metrics_dir does not exist yet -- PT-82's ruled CLAUDE_PROJECT_DIR-preferring "
    "metrics-path resolution (process/cairn/issues/PT-82.md @ 6316a9b, item (c2)) is unimplemented"
)
print(str(helpers.real_metrics_dir()))
"""


def _make_worktree_helpers_copy(testcase) -> "tuple":
    """A fake 'worktree' dir carrying its OWN literal copy of the real
    helpers.py (so `Path(__file__).resolve().parent`-style derivation
    inside it points at THIS fake location, never the real repo) plus
    its own, distinguishable `process/cairn/metrics/token-usage.jsonl`."""
    worktree_root = helpers.make_empty_tmp_dir(testcase)
    worktree_tests_dir = worktree_root / "scripts" / "cairn" / "tests"
    worktree_tests_dir.mkdir(parents=True)
    real_helpers_py = helpers.TESTS_DIR / "helpers.py"
    shutil.copy(real_helpers_py, worktree_tests_dir / "helpers.py")

    worktree_metrics = worktree_root / "process" / "cairn" / "metrics"
    worktree_metrics.mkdir(parents=True)
    (worktree_metrics / "token-usage.jsonl").write_text('{"marker":"worktree-own-copy"}\n', encoding="utf-8")
    return worktree_root, worktree_tests_dir


def _make_fake_main_checkout(testcase) -> "object":
    main_root = helpers.make_empty_tmp_dir(testcase)
    main_metrics = main_root / "process" / "cairn" / "metrics"
    main_metrics.mkdir(parents=True)
    (main_metrics / "token-usage.jsonl").write_text('{"marker":"main-checkout"}\n', encoding="utf-8")
    return main_root


class MetricsPathResolutionPrefersClaudeProjectDirTests(unittest.TestCase):
    def test_a_worktree_shaped_layout_resolves_to_the_main_checkouts_metrics_dir(self):
        worktree_root, worktree_tests_dir = _make_worktree_helpers_copy(self)
        main_root = _make_fake_main_checkout(self)

        probe_dir = helpers.make_empty_tmp_dir(self)
        probe_script = probe_dir / "probe.py"
        probe_script.write_text(_PROBE_TEMPLATE, encoding="utf-8")

        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(main_root)
        result = subprocess.run(
            [sys.executable, str(probe_script), str(worktree_tests_dir)],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"probe failed -- {result.stdout!r} {result.stderr!r}")
        # Compared via .resolve() on BOTH sides -- symlink-tolerant
        # regardless of whether the real implementation itself resolves
        # CLAUDE_PROJECT_DIR (macOS's /tmp -> /private/tmp, /var ->
        # /private/var would otherwise produce a spurious mismatch in
        # either direction).
        resolved = Path(result.stdout.strip()).resolve()
        self.assertEqual(
            resolved, (main_root / "process" / "cairn" / "metrics").resolve(),
            f"with CLAUDE_PROJECT_DIR set, the worktree's own copy of helpers.py must still "
            f"resolve to the MAIN CHECKOUT's metrics dir, not its own worktree-local one -- "
            f"got {resolved!r} (worktree's own would have been "
            f"{(worktree_root / 'process' / 'cairn' / 'metrics').resolve()!r})",
        )

    def test_without_claude_project_dir_set_it_falls_back_to_the_current_derivation(self):
        worktree_root, worktree_tests_dir = _make_worktree_helpers_copy(self)

        probe_dir = helpers.make_empty_tmp_dir(self)
        probe_script = probe_dir / "probe.py"
        probe_script.write_text(_PROBE_TEMPLATE, encoding="utf-8")

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        result = subprocess.run(
            [sys.executable, str(probe_script), str(worktree_tests_dir)],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"probe failed -- {result.stdout!r} {result.stderr!r}")
        # Compared via .resolve() on BOTH sides -- see the sibling test's
        # identical comment; macOS's /tmp -> /private/tmp (and /var ->
        # /private/var) symlink would otherwise produce a spurious
        # mismatch even when the derivation is correct.
        resolved = Path(result.stdout.strip()).resolve()
        self.assertEqual(
            resolved, (worktree_root / "process" / "cairn" / "metrics").resolve(),
            f"without CLAUDE_PROJECT_DIR, resolution must fall back to the current "
            f"TESTS_DIR-relative derivation (the worktree copy's OWN location) -- got {resolved!r}",
        )


# --------------------------------------------------------------------------
# Spike finding (team-lead, process/reviews/PT-82/spike.md @ 1d25274, step
# 9): from a real worktree, a gated `run_tests.py` run wrote a record into
# BOTH the resolved (main checkout) test-runs.jsonl AND the script-local
# (worktree) copy -- the worktree's own copy gained a stray `who: null`
# line, dirtying a git-tracked file in every teammate worktree and
# inviting a bad commit. `run_tests.py:_self_record` (PT-82.md @
# 6316a9b/b0287db, item (c)) is supposed to write to exactly ONE path --
# the resolved `override` when `--gate` + `CLAUDE_PROJECT_DIR` make one
# available, else the script-local default -- never both. Mutation: write
# both (append to the script-local path unconditionally, in addition to
# the resolved one).
#
# Real subprocess of the REAL run_tests.py (no local imports beyond
# stdlib, so a minimal two-file copy -- run_tests.py + one trivial test
# file -- is a legitimate, self-contained "worktree" for this purpose;
# no need to copy the whole scripts/cairn tree).
# --------------------------------------------------------------------------

_TRIVIAL_TEST_FILE = """
import unittest


class TrivialPassingTests(unittest.TestCase):
    def test_trivial(self):
        self.assertTrue(True)
"""


def _make_worktree_run_tests_copy(testcase):
    """(worktree_root, run_tests_py_path) -- a minimal, self-contained
    copy of run_tests.py plus one trivial test file, laid out at
    <worktree_root>/scripts/cairn/{run_tests.py,tests/test_trivial.py}
    so `SCRIPT_DIR.parent.parent` inside it resolves to `worktree_root`,
    matching the real repo's own scripts/cairn -> scripts -> root shape."""
    worktree_root = helpers.make_empty_tmp_dir(testcase)
    cairn_dir = worktree_root / "scripts" / "cairn"
    tests_dir = cairn_dir / "tests"
    tests_dir.mkdir(parents=True)
    real_run_tests_py = helpers.CAIRN_DIR / "run_tests.py"
    shutil.copy(real_run_tests_py, cairn_dir / "run_tests.py")
    (tests_dir / "test_trivial.py").write_text(_TRIVIAL_TEST_FILE, encoding="utf-8")
    return worktree_root, cairn_dir / "run_tests.py"


class GatedRunFromAWorktreeWritesExactlyOneRecordTests(unittest.TestCase):
    def test_the_script_local_copy_is_untouched_when_the_resolved_path_differs(self):
        worktree_root, run_tests_py = _make_worktree_run_tests_copy(self)
        main_root = helpers.make_empty_tmp_dir(self)

        # Pre-seed the worktree's own local records file, as a real
        # git-tracked copy would already have committed content --
        # "byte-identical before/after" is a meaningful claim only
        # against a file that already exists with real bytes in it.
        local_records_path = worktree_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        local_records_path.parent.mkdir(parents=True)
        seed_bytes = b'{"ts":"2026-01-01T00:00:00.000Z","who":null,"gate":null,"seed":true}\n'
        local_records_path.write_bytes(seed_bytes)

        resolved_records_path = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertFalse(resolved_records_path.exists(), "sanity: the resolved path must start absent")

        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(main_root)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(run_tests_py), "--gate", "green"],
            cwd=str(run_tests_py.parent), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"the gated run itself must succeed (one trivial passing test) -- {result.stdout!r} {result.stderr!r}")

        self.assertTrue(resolved_records_path.is_file(), "the resolved (main checkout) records file must gain the record")
        resolved_lines = resolved_records_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(resolved_lines), 1, f"expected exactly one new record in the resolved file -- got {resolved_lines!r}")

        after_bytes = local_records_path.read_bytes()
        self.assertEqual(
            after_bytes, seed_bytes,
            f"the script-local (worktree) copy must be BYTE-IDENTICAL before and after a gated "
            f"run whose resolved path differs -- it must never also gain a line -- got "
            f"{after_bytes!r}, seeded with {seed_bytes!r}",
        )


if __name__ == "__main__":
    unittest.main()
