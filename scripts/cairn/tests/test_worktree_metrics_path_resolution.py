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


if __name__ == "__main__":
    unittest.main()
