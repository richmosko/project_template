"""PT-82 gate-1 ruling, RE-ISSUED WHOLE (architect, process/cairn/issues/
PT-82.md @ 69e9664, item (c2), "unchanged from addendum 1"):

    "PT-100's guard, unchanged from addendum 1. It snapshots both trees:
    the worktree's copy byte-exact -- which is now viable precisely
    because the runner no longer writes there -- and the main checkout's
    copy under PT-100's containment tolerance. Resolving only via
    CLAUDE_PROJECT_DIR would reintroduce the daemon-flush false positive
    PT-100 fixed, and is not done."

The defect this corrects: PT-100's six real callers (test_otel_receiver.py
L98, and siblings) derive their watched `process/cairn/metrics/` from
`helpers.TESTS_DIR`-relative paths -- this file's own on-disk location.
From a worktree that resolves to the WORKTREE's tree, never the main
checkout's, so the guard would watch a copy the live otel receiver never
writes (vacuous pass) while the real, daemon-written main-checkout copy
goes unwatched entirely. Swapping to `helpers.real_metrics_dir()` (prefers
`CLAUDE_PROJECT_DIR`) alone is explicitly NOT the fix -- ruled out by name
above -- because it would only ever watch ONE tree, reintroducing exactly
the false-positive PT-100's own guard was built to avoid (a real daemon
flush hitting the unwatched tree would go undetected too, just the other
one).

Assumed seam (the ruling fixes the OUTCOME -- both trees, different
tolerances -- not this exact name/shape; flag to the architect if
implementation-lead's diverges):

    helpers.snapshot_real_state_both_trees(
        worktree_token_usage_path: Path, main_token_usage_path: Path,
        pidfile_path: Path, sessions_dir: Path, data_dir: Path,
    ) -> <opaque snapshot>
        Takes a `snapshot_real_state`-shaped "before" picture of BOTH
        token-usage.jsonl copies. `pidfile_path`/`sessions_dir` are the
        main checkout's only -- the receiver's pidfile/session registry
        have no worktree-local counterpart to watch.

    helpers.diagnose_real_state_both_trees(snapshot) -> List[str]
        `[]` when nothing changed or the main-tree change classifies as
        a tolerated daemon flush (PT-100's raw-line multiset containment,
        unchanged). Any change AT ALL to the worktree's own tracked copy
        is a finding, byte-exact, with NO containment tolerance --
        nothing legitimately writes there once the records-path
        discriminator (PT-82's other qa-owned test) redirects a gated
        worktree run to the main checkout, so any diff, however
        "backed" the added line's issue id, means something wrote where
        nothing should.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401
from test_real_state_guard import line_for, make_fixture, usage_row, write_lines


def _both_trees_snapshot(worktree_path, main_path, pidfile_path, sessions_dir, data_dir):
    assert hasattr(helpers, "snapshot_real_state_both_trees"), (
        "helpers.snapshot_real_state_both_trees does not exist yet -- PT-82's ruled "
        "(c2) both-trees real-file guard (process/cairn/issues/PT-82.md @ 69e9664) is "
        "unimplemented"
    )
    return helpers.snapshot_real_state_both_trees(
        worktree_path, main_path, pidfile_path, sessions_dir, data_dir,
    )


def _both_trees_diagnose(snap):
    assert hasattr(helpers, "diagnose_real_state_both_trees"), (
        "helpers.diagnose_real_state_both_trees does not exist yet -- PT-82's ruled "
        "(c2) both-trees real-file guard is unimplemented"
    )
    return helpers.diagnose_real_state_both_trees(snap)


def _make_worktree_shaped_pair(testcase):
    """(worktree_token_usage_path, main_token_usage_path, pidfile_path,
    sessions_dir, data_dir) -- two independent token-usage.jsonl copies
    under separate tmp roots, mirroring a real worktree's fully-cloned
    tracked file sitting alongside the main checkout's own. `pidfile_path`
    and `sessions_dir` live only under the main root, matching the real
    shape (the receiver's pidfile/session registry are main-checkout-only
    state; a worktree carries no counterpart)."""
    _, pidfile_path, sessions_dir, data_dir = make_fixture(testcase)
    main_root = pidfile_path.parent
    worktree_root = helpers.make_empty_tmp_dir(testcase)
    main_token_usage_path = main_root / "token-usage.jsonl"
    worktree_token_usage_path = worktree_root / "token-usage.jsonl"
    return worktree_token_usage_path, main_token_usage_path, pidfile_path, sessions_dir, data_dir


class BothTreesGuardWatchesTheMainCheckoutWithTolerance(unittest.TestCase):
    """The main checkout's copy keeps PT-100's existing behavior exactly:
    a re-sort is silent, a backed-issue addition is silent, a missing
    pre-existing line is a finding."""

    def test_a_daemon_style_resort_of_the_main_copy_is_silent(self):
        worktree_path, main_path, pidfile_path, sessions_dir, data_dir = _make_worktree_shaped_pair(self)
        row_a = usage_row(issue="PT-1")
        row_b = usage_row(issue="PT-3", generated="2026-09-08T01:00:00Z")
        write_lines(worktree_path, [])
        write_lines(main_path, [line_for(row_a), line_for(row_b)])
        snap = _both_trees_snapshot(worktree_path, main_path, pidfile_path, sessions_dir, data_dir)

        write_lines(main_path, [line_for(row_b), line_for(row_a)])  # positions swapped, both survive verbatim
        findings = _both_trees_diagnose(snap)
        self.assertEqual(findings, [], f"a same-content re-sort of the main copy must be silent -- got {findings!r}")

    def test_a_backed_issue_addition_to_the_main_copy_is_silent(self):
        worktree_path, main_path, pidfile_path, sessions_dir, data_dir = _make_worktree_shaped_pair(self)
        kept = usage_row(issue="PT-1")
        write_lines(worktree_path, [])
        write_lines(main_path, [line_for(kept)])
        snap = _both_trees_snapshot(worktree_path, main_path, pidfile_path, sessions_dir, data_dir)

        new_row = usage_row(issue="PT-3", generated="2026-09-08T02:00:00Z")
        write_lines(main_path, [line_for(kept), line_for(new_row)])
        findings = _both_trees_diagnose(snap)
        self.assertEqual(findings, [], f"a backed-issue addition to the main copy must be silent -- got {findings!r}")

    def test_a_missing_pre_existing_line_in_the_main_copy_is_a_finding(self):
        worktree_path, main_path, pidfile_path, sessions_dir, data_dir = _make_worktree_shaped_pair(self)
        keep = usage_row(issue="PT-1")
        dropped = usage_row(issue="PT-3", generated="2026-09-08T03:00:00Z")
        write_lines(worktree_path, [])
        write_lines(main_path, [line_for(keep), line_for(dropped)])
        snap = _both_trees_snapshot(worktree_path, main_path, pidfile_path, sessions_dir, data_dir)

        write_lines(main_path, [line_for(keep)])  # dropped vanished
        findings = _both_trees_diagnose(snap)
        self.assertTrue(
            any("main" in f.lower() or "token-usage" in f.lower() for f in findings),
            f"a missing pre-existing line in the main copy must be flagged -- got {findings!r}",
        )


class BothTreesGuardWatchesTheWorktreeCopyByteExact(unittest.TestCase):
    """This is the decisive leg: (c2) requires the WORKTREE's own tracked
    copy to be watched byte-exact -- no containment tolerance, since
    nothing legitimately writes there once a gated run redirects to the
    main checkout (PT-82's records-path discriminator). A guard that
    reuses PT-100's tolerant `diagnose_real_state` unmodified for the
    worktree tree too would silently accept a backed-issue addition
    there -- exactly the stray write the spike caught (process/reviews/
    PT-82/spike.md, step 9) -- so that mutation must go red here."""

    def test_any_addition_to_the_worktree_copy_is_a_finding_even_with_a_backed_issue(self):
        worktree_path, main_path, pidfile_path, sessions_dir, data_dir = _make_worktree_shaped_pair(self)
        write_lines(worktree_path, [])
        write_lines(main_path, [])
        snap = _both_trees_snapshot(worktree_path, main_path, pidfile_path, sessions_dir, data_dir)

        stray = usage_row(issue="PT-1")  # backed issue id -- would be silently tolerated by PT-100's own rule
        write_lines(worktree_path, [line_for(stray)])
        findings = _both_trees_diagnose(snap)
        self.assertTrue(
            findings,
            "a single addition to the worktree's own tracked copy must ALWAYS be flagged, "
            "byte-exact, even when the added line's issue id is backed by a real issue file -- "
            "this is the mutation PT-100's own containment tolerance would wrongly pass",
        )

    def test_the_worktree_copy_untouched_is_silent(self):
        worktree_path, main_path, pidfile_path, sessions_dir, data_dir = _make_worktree_shaped_pair(self)
        seed = usage_row(issue="PT-1")
        write_lines(worktree_path, [line_for(seed)])
        write_lines(main_path, [])
        snap = _both_trees_snapshot(worktree_path, main_path, pidfile_path, sessions_dir, data_dir)

        # no write to worktree_path at all
        findings = _both_trees_diagnose(snap)
        self.assertEqual(findings, [], f"an untouched worktree copy must be silent -- got {findings!r}")


if __name__ == "__main__":
    unittest.main()
