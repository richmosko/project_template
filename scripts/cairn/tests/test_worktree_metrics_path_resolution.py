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

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"


def _load_hook_module(script: str):
    # .claude/hooks/ is outside the normal package path -- load by file
    # location, matching test_test_run_hooks.py's own helper.
    spec = importlib.util.spec_from_file_location(f"pt107_{script[:-3]}", HOOKS_DIR / script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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
# Superseded (never a subject of any commit past this file's current
# one): an earlier draft here assumed `_self_record` would prefer
# `CLAUDE_PROJECT_DIR` when set, and tested that by setting it directly
# in the subprocess env. The re-issued ruling (PT-82.md @ 69e9664)
# removed that mechanism entirely -- `CLAUDE_PROJECT_DIR` is unset in a
# teammate's own Bash tool calls (only set for hook shells), so it can
# never be the discriminator; see the git-common-dir section below,
# which is what actually shipped (run_tests.py @ 3909de2).
# --------------------------------------------------------------------------

_TRIVIAL_TEST_FILE = """
import unittest


class TrivialPassingTests(unittest.TestCase):
    def test_trivial(self):
        self.assertTrue(True)
"""


# --------------------------------------------------------------------------
# Spike delta (team-lead, process/reviews/PT-82/spike.md @ 3b10267,
# "step 9 corrected"): a REAL full `--gate red` run from a REAL worktree
# still wrote the stray `who: null` line into the worktree's own tracked
# copy -- the test above (which explicitly sets `CLAUDE_PROJECT_DIR` in
# the subprocess env) modelled the WRONG case. `CLAUDE_PROJECT_DIR` is
# set for hook shells, not for a teammate's own Bash tool calls, so the
# `--gate`-gated preference never engages in the scenario that actually
# occurs, and `_self_record` falls through to the script-local
# (worktree) path every time.
#
# Ruled fix (this test's assumption): when `CLAUDE_PROJECT_DIR` is
# ABSENT but `--gate` is present, resolve the main checkout via
# `git rev-parse --git-common-dir` (run from cwd, which follows the
# worktree) -- the git-native way to find the shared main checkout from
# ANY worktree, with no environment dependency at all. Mutation:
# resolve from `__file__` only (today's behaviour -- this is what
# currently happens and is exactly the defect).
#
# Real git: a real bare-free local repo as the "main checkout", a real
# `git worktree add` second checkout -- never a synthetic stand-in for
# either.
# --------------------------------------------------------------------------


def _git_env() -> dict:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    return env


def _make_main_checkout_with_worktree(testcase):
    """(main_root, worktree_path) -- a REAL git repo carrying a minimal,
    self-contained copy of run_tests.py + one trivial test file
    (committed, so a real `git worktree add` checkout shares them), plus
    a REAL second worktree created from it via `git worktree add`."""
    main_root = helpers.make_empty_tmp_dir(testcase)
    genv = _git_env()
    subprocess.run(["git", "init", "-q"], cwd=str(main_root), check=True, env=genv)

    cairn_dir = main_root / "scripts" / "cairn"
    tests_dir = cairn_dir / "tests"
    tests_dir.mkdir(parents=True)
    shutil.copy(helpers.CAIRN_DIR / "run_tests.py", cairn_dir / "run_tests.py")
    (tests_dir / "test_trivial.py").write_text(_TRIVIAL_TEST_FILE, encoding="utf-8")

    subprocess.run(["git", "add", "-A"], cwd=str(main_root), check=True, env=genv)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(main_root), check=True, env=genv)

    worktree_parent = helpers.make_empty_tmp_dir(testcase)
    worktree_path = worktree_parent / "x"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "worktree-x", str(worktree_path)],
        cwd=str(main_root), check=True, env=genv,
    )
    return main_root, worktree_path


class RealWorktreeGatedRunResolvesViaGitCommonDirTests(unittest.TestCase):
    def test_a_gated_run_from_a_real_worktree_with_no_claude_project_dir_writes_only_the_main_checkout(self):
        main_root, worktree_path = _make_main_checkout_with_worktree(self)
        worktree_run_tests_py = worktree_path / "scripts" / "cairn" / "run_tests.py"

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)  # the real teammate-Bash scenario -- absent, not set
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(worktree_run_tests_py), "--gate", "red"],
            cwd=str(worktree_run_tests_py.parent), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"the gated run itself must succeed -- {result.stdout!r} {result.stderr!r}")

        main_records = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        worktree_records = worktree_path / "process" / "cairn" / "metrics" / "test-runs.jsonl"

        self.assertTrue(
            main_records.is_file(),
            f"the MAIN checkout's records file must gain the record (resolved via `git rev-parse "
            f"--git-common-dir`, no CLAUDE_PROJECT_DIR needed) -- got nothing at {main_records}",
        )
        main_lines = main_records.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(main_lines), 1, f"expected exactly one record in the main checkout's file -- got {main_lines!r}")

        self.assertFalse(
            worktree_records.exists(),
            f"the worktree's own tracked copy must gain ZERO lines -- a stray write there dirties "
            f"a git-tracked file in every teammate worktree -- got {worktree_records.read_text(encoding='utf-8') if worktree_records.exists() else None!r}",
        )


# --------------------------------------------------------------------------
# PT-82 gate-1 ruling, RE-ISSUED WHOLE (architect, process/cairn/issues/
# PT-82.md @ 69e9664, superseding @6316a9b and addenda @b0287db/@07576af):
# "the records-path discriminator... the load-bearing one." `run_tests.py`
# may use the `--git-common-dir` root ONLY when `--git-dir != --git-
# common-dir` -- true SOLELY in a linked worktree. Bare common-dir
# resolution (no inequality check) is UNSAFE: from a fake engine root
# INSIDE the repo, `--git-dir` and `--git-common-dir` are also EQUAL (both
# resolve to the enclosing repo's real `.git`), so the unguarded form
# would redirect a test copy's self-record into the REAL test-runs.jsonl
# -- the exact regression the file-location default was written to
# prevent, and the one PT-100's guards exist to catch.
#
# Four contexts, real git and real subprocesses throughout (never
# simulated): linked worktree (differ -> common-dir), main checkout
# (equal -> file-location default), fake engine root INSIDE the repo
# (equal -> file-location default -- the decisive case), outside any
# repo (git fails -> file-location default, never raises).
# --------------------------------------------------------------------------


class RecordsPathDiscriminatorTests(unittest.TestCase):
    def test_context_1_linked_worktree_uses_the_common_dir_root(self):
        # Already the exact scenario RealWorktreeGatedRunResolvesViaGit
        # CommonDirTests covers above -- restated here as context 1 of
        # 4 for a single, complete discriminator record in one place.
        main_root, worktree_path = _make_main_checkout_with_worktree(self)
        run_tests_py = worktree_path / "scripts" / "cairn" / "run_tests.py"
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(run_tests_py), "--gate", "red"],
            cwd=str(run_tests_py.parent), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout!r} {result.stderr!r}")
        main_records = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        worktree_records = worktree_path / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertTrue(main_records.is_file(), "context 1 (linked worktree): the MAIN checkout must gain the record")
        self.assertFalse(worktree_records.exists(), "context 1 (linked worktree): the worktree's own copy must gain nothing")

    def test_context_2_main_checkout_uses_the_file_location_default(self):
        # git-dir == git-common-dir here (both are the repo's own .git) --
        # the two candidate roots COINCIDE, so this context can't by
        # itself distinguish a correct implementation from the unguarded
        # mutation; included as the "ordinary case is unaffected" sanity
        # leg the other three contexts don't cover.
        main_root = helpers.make_empty_tmp_dir(self)
        genv = _git_env()
        subprocess.run(["git", "init", "-q"], cwd=str(main_root), check=True, env=genv)
        cairn_dir = main_root / "scripts" / "cairn"
        tests_dir = cairn_dir / "tests"
        tests_dir.mkdir(parents=True)
        shutil.copy(helpers.CAIRN_DIR / "run_tests.py", cairn_dir / "run_tests.py")
        (tests_dir / "test_trivial.py").write_text(_TRIVIAL_TEST_FILE, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(main_root), check=True, env=genv)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(main_root), check=True, env=genv)

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(cairn_dir / "run_tests.py"), "--gate", "red"],
            cwd=str(cairn_dir), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout!r} {result.stderr!r}")
        own_records = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertTrue(own_records.is_file(), "context 2 (main checkout): its own tree must gain the record")
        lines = own_records.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1, f"expected exactly one record -- got {lines!r}")

    def test_context_3_fake_engine_root_inside_the_repo_stays_local_the_decisive_case(self):
        # THE decisive context, per the ruling: a fake engine root
        # NESTED inside a real repo's working tree (no .git of its own)
        # has git-dir == git-common-dir, EQUAL to each other but
        # DIFFERENT from the fake root itself -- the unguarded ("drop
        # the inequality check") mutation would still resolve common-dir
        # (the ENCLOSING repo) and wrongly redirect the fake root's
        # self-record into the enclosing repo's real test-runs.jsonl.
        enclosing_root = helpers.make_empty_tmp_dir(self)
        genv = _git_env()
        subprocess.run(["git", "init", "-q"], cwd=str(enclosing_root), check=True, env=genv)
        (enclosing_root / "README.md").write_text("placeholder\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(enclosing_root), check=True, env=genv)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(enclosing_root), check=True, env=genv)

        fake_root = enclosing_root / "nested" / "fake_engine_root"
        cairn_dir = fake_root / "scripts" / "cairn"
        tests_dir = cairn_dir / "tests"
        tests_dir.mkdir(parents=True)
        shutil.copy(helpers.CAIRN_DIR / "run_tests.py", cairn_dir / "run_tests.py")
        (tests_dir / "test_trivial.py").write_text(_TRIVIAL_TEST_FILE, encoding="utf-8")
        # Deliberately NOT committed -- a fake engine root is scratch,
        # exactly PT-100's own "never the real committed file" fixtures.

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(cairn_dir / "run_tests.py"), "--gate", "red"],
            cwd=str(cairn_dir), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout!r} {result.stderr!r}")

        fake_root_records = fake_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        enclosing_records = enclosing_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertTrue(
            fake_root_records.is_file(),
            "context 3 (fake root inside a repo): the fake root's OWN tree must gain the record "
            "(git-dir == git-common-dir here, so the common-dir root must NOT be preferred)",
        )
        self.assertFalse(
            enclosing_records.exists(),
            f"context 3 (fake root inside a repo): the ENCLOSING repo's real test-runs.jsonl must "
            f"gain NOTHING -- a write there is exactly the regression PT-100's guards exist to "
            f"catch -- got {enclosing_records.read_text(encoding='utf-8') if enclosing_records.exists() else None!r}",
        )

    def test_context_4_outside_any_repo_falls_back_without_raising(self):
        fake_root = helpers.make_empty_tmp_dir(self)
        cairn_dir = fake_root / "scripts" / "cairn"
        tests_dir = cairn_dir / "tests"
        tests_dir.mkdir(parents=True)
        shutil.copy(helpers.CAIRN_DIR / "run_tests.py", cairn_dir / "run_tests.py")
        (tests_dir / "test_trivial.py").write_text(_TRIVIAL_TEST_FILE, encoding="utf-8")
        # No `git init` anywhere in this fixture's ancestry -- helpers.
        # make_empty_tmp_dir's own tmp root is never inside a git repo
        # (verified: /tmp and /private/var/folders/... on this machine
        # both report "fatal: not a git repository").

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(cairn_dir / "run_tests.py"), "--gate", "red"],
            cwd=str(cairn_dir), capture_output=True, text=True, env=env,
        )
        self.assertEqual(
            result.returncode, 0,
            f"a run outside any git repo must still succeed -- the recorder never raises -- "
            f"{result.stdout!r} {result.stderr!r}",
        )
        own_records = fake_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertTrue(own_records.is_file(), "context 4 (outside any repo): the fake root's own tree must still gain the record")
        lines = own_records.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1, f"expected exactly one record -- got {lines!r}")


# --------------------------------------------------------------------------
# PT-107 gate-1 ruling (architect, process/cairn/issues/PT-107.md @
# 1aa5a71): the `args.gate and` clause guarding _resolve_worktree_main_
# checkout's use in _self_record is a leftover of the superseded PT-82
# ruling -- the `--git-dir != --git-common-dir` discriminator IS the
# safety property, with no `--gate` condition needed. Deleting the
# clause makes a NARROWED (`-p`) run from a linked worktree also record
# to the main checkout, and (since the runner's own null-who line is now
# the ledger's last line) the PostToolUse hook PATCHES it instead of
# falling back to its scrape-and-append path -- one record per run, not
# two. `branch`/`sha` are resolved from the main checkout throughout, so
# no record can ever carry a `worktree-*` branch. Real git, real
# subprocesses, no stand-ins.
# --------------------------------------------------------------------------


class NarrowedWorktreeRunRecordsOnceInTheMainCheckoutTests(unittest.TestCase):
    def test_a_narrowed_run_from_a_real_worktree_writes_only_the_main_checkout(self):
        """Mutation: restore `args.gate and` -- the main checkout gains no
        file at all, and the worktree's own tracked copy gains a line
        (`who=null`, `branch=worktree-x`) instead."""
        main_root, worktree_path = _make_main_checkout_with_worktree(self)
        worktree_run_tests_py = worktree_path / "scripts" / "cairn" / "run_tests.py"

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        result = subprocess.run(
            [sys.executable, str(worktree_run_tests_py), "-p", "test_trivial.py"],
            cwd=str(worktree_run_tests_py.parent), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"the narrowed run itself must succeed -- {result.stdout!r} {result.stderr!r}")

        main_records = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        worktree_records = worktree_path / "process" / "cairn" / "metrics" / "test-runs.jsonl"

        self.assertTrue(
            main_records.is_file(),
            "a narrowed (-p) run from the linked worktree must still record to the MAIN checkout",
        )
        main_lines = [l for l in main_records.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(main_lines), 1, f"expected exactly one record -- got {main_lines!r}")
        rec = json.loads(main_lines[0])
        self.assertFalse(rec["full"], f"a -p run must record full=false -- got {rec!r}")
        self.assertIsNone(rec["gate"], f"a -p run must record gate=null -- got {rec!r}")

        main_branch = subprocess.run(
            ["git", "-C", str(main_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, env=_git_env(),
        ).stdout.strip()
        self.assertEqual(
            rec["branch"], main_branch,
            f"branch must resolve to the MAIN checkout's own branch, not the worktree's -- got {rec!r}",
        )

        self.assertFalse(
            worktree_records.exists(),
            f"the worktree's own tracked copy must gain ZERO lines -- got "
            f"{worktree_records.read_text(encoding='utf-8') if worktree_records.exists() else None!r}",
        )


class NoRecordCarriesAWorktreePrefixedBranchTests(unittest.TestCase):
    def test_narrowed_and_gated_runs_from_the_worktree_never_record_a_worktree_prefixed_branch(self):
        """Standing invariant across both the narrowed and gated cases --
        cheap, and catches any future re-resolution from the worktree's
        own root rather than the main checkout."""
        main_root, worktree_path = _make_main_checkout_with_worktree(self)
        worktree_run_tests_py = worktree_path / "scripts" / "cairn" / "run_tests.py"
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)

        for extra_args in (["-p", "test_trivial.py"], ["--gate", "red"]):
            result = subprocess.run(
                [sys.executable, str(worktree_run_tests_py), *extra_args],
                cwd=str(worktree_run_tests_py.parent), capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, f"{extra_args} -- {result.stdout!r} {result.stderr!r}")

        main_records = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        worktree_records = worktree_path / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        all_lines = []
        for p in (main_records, worktree_records):
            if p.exists():
                all_lines += [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(all_lines, "expected at least one record across the two files")
        for line in all_lines:
            rec = json.loads(line)
            self.assertFalse(
                (rec.get("branch") or "").startswith("worktree-"),
                f"no record, in either file, may carry a worktree-prefixed branch -- got {rec!r}",
            )


class HookPatchesTheNarrowedWorktreeRunsRecordTests(unittest.TestCase):
    def test_the_post_hook_patches_who_in_place_rather_than_appending_a_second_record(self):
        """This is the "one record per run" property itself -- the
        preceding test proves the runner's own line lands in the main
        checkout, but not that the hook leaves it alone. Mutation: the
        hook appends instead of patching (its pre-PT-82 scrape-and-append
        fallback) -- 2 lines, the second `who=null`.

        Addendum 1 to the gate-1 ruling (PT-107.md @ ab936fa): the hook's
        real input is a teammate's TYPED Bash command -- measured, 4/4
        real hook-scraped records name the literal `python3`, never a
        versioned interpreter path. `sys.executable` (used below only for
        the actual spawn, never the payload) is unfaithful to that and
        must not appear in the hook's `tool_input.command`."""
        main_root, worktree_path = _make_main_checkout_with_worktree(self)
        worktree_run_tests_py = worktree_path / "scripts" / "cairn" / "run_tests.py"

        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        command = f"python3 {worktree_run_tests_py} -p test_trivial.py"
        shared = _load_hook_module("_test_run_shared.py")
        self.assertTrue(
            shared.is_test_invocation(command),
            f"addendum guard: the payload command must actually be recognised as a test "
            f"invocation by the hook's own shared tokeniser, or this test is a silent no-op "
            f"with a null `who` -- got {command!r}",
        )
        result = subprocess.run(
            [sys.executable, str(worktree_run_tests_py), "-p", "test_trivial.py"],
            cwd=str(worktree_run_tests_py.parent), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout!r} {result.stderr!r}")

        main_records = main_root / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertEqual(
            len([l for l in main_records.read_text(encoding="utf-8").splitlines() if l.strip()]), 1,
            "precondition: the runner's own record must already be the ledger's last line",
        )

        hook_payload = {
            "session_id": "pt107-hook-leg", "cwd": str(worktree_run_tests_py.parent),
            "agent_type": "architect", "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "Ran 1 tests in 0.010s (1 files, 1 workers)\nOK\n", "stderr": "", "interrupted": False},
            "duration_ms": 42, "tool_use_id": "pt107-toolu",
        }
        hook_env = dict(os.environ)
        hook_env["CLAUDE_PROJECT_DIR"] = str(main_root)
        hook_result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "test_run_record.py")],
            input=json.dumps(hook_payload), capture_output=True, text=True, env=hook_env,
        )
        self.assertEqual(hook_result.returncode, 0, f"{hook_result.stdout!r} {hook_result.stderr!r}")

        main_lines = [l for l in main_records.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(
            len(main_lines), 1,
            f"the hook must PATCH the runner's own line, not append a second one -- got {main_lines!r}",
        )
        rec = json.loads(main_lines[0])
        self.assertEqual(rec["who"], "architect", f"the patched line must carry the hook's agent_type -- got {rec!r}")


if __name__ == "__main__":
    unittest.main()
