"""Unit tests for the PT-1 fs-scan watcher's pure scan/diff logic --
`cairn.scan_data_dir` + `cairn.diff_scans`. Deliberately synchronous and
free of threading/sleeping beyond one tiny mtime-separation sleep: these
pin the snapshot-then-diff contract the periodic background thread will
call on a timer, not the timing/threading itself -- that's exercised at
the HTTP level in test_server.py's SSEEventsTests, with hard read
timeouts so a broken implementation can never hang the suite.

Naming note for implementation-lead: `scan_data_dir` / `diff_scans` are
QA's proposed API shape, inferred from TRACKER.md's "Live push (SSE)"
design note ("a background thread os.scandirs the data dir every 500ms
and diffs (path, mtime_ns)") -- not a contract handed down elsewhere. If a
different shape is more natural for the watcher thread's own internals,
rename freely; these tests exist to pin *behavior* (what counts as
changed/created/removed, and quiet-on-no-change), not to lock in names.
Flagged to team-lead in the hand-off report as a call QA made, not impl.
"""
from __future__ import annotations

import time
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def _write(path: Path, text: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ScanDataDirTests(unittest.TestCase):
    """cairn.scan_data_dir(data_dir) -> {relative_path: mtime_ns} across
    the four tracked subdirs (majors/milestones/issues/archive) -- the
    same directory set check_repo and build_board_payload already walk.
    Missing subdirs are tolerated (mirrors _dir_glob's "if d.exists() else
    []"), since not every data dir has an archive/ yet."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)

    def test_empty_data_dir_scans_to_an_empty_snapshot(self):
        for sub in ("majors", "milestones", "issues", "archive"):
            (self.tmp / sub).mkdir()
        snapshot = cairn.scan_data_dir(self.tmp)
        self.assertEqual(snapshot, {})

    def test_missing_subdirs_do_not_raise(self):
        # No subdirs created at all -- a brand new data dir mid-setup.
        snapshot = cairn.scan_data_dir(self.tmp)
        self.assertEqual(snapshot, {})

    def test_scan_picks_up_files_in_every_tracked_subdir(self):
        _write(self.tmp / "issues" / "PT-1.md")
        _write(self.tmp / "archive" / "PT-9.md")
        _write(self.tmp / "milestones" / "1.0.md")
        _write(self.tmp / "majors" / "V1.md")
        snapshot = cairn.scan_data_dir(self.tmp)
        self.assertEqual(
            set(snapshot.keys()),
            {"issues/PT-1.md", "archive/PT-9.md", "milestones/1.0.md", "majors/V1.md"},
        )

    def test_scan_value_is_the_real_mtime_ns(self):
        path = self.tmp / "issues" / "PT-1.md"
        _write(path)
        snapshot = cairn.scan_data_dir(self.tmp)
        self.assertEqual(snapshot["issues/PT-1.md"], path.stat().st_mtime_ns)

    def test_scan_ignores_config_yml_and_non_md_files(self):
        # config.yml and any stray non-.md file under a tracked dir must
        # not show up as a "change" -- only issue/milestone/major content
        # matters to the board.
        (self.tmp / "config.yml").write_text("prefix: PT\n", encoding="utf-8")
        (self.tmp / "issues").mkdir()
        (self.tmp / "issues" / "notes.txt").write_text("scratch", encoding="utf-8")
        snapshot = cairn.scan_data_dir(self.tmp)
        self.assertEqual(snapshot, {})


class DiffScansTests(unittest.TestCase):
    """cairn.diff_scans(previous, current) -> {"created": [...],
    "changed": [...], "removed": [...]} of relative path strings, sorted."""

    def test_identical_snapshots_are_quiet(self):
        snap = {"issues/PT-1.md": 100, "milestones/1.0.md": 200}
        diff = cairn.diff_scans(snap, dict(snap))
        self.assertEqual(diff, {"created": [], "changed": [], "removed": []})

    def test_changed_mtime_is_reported_as_changed(self):
        old = {"issues/PT-1.md": 100}
        new = {"issues/PT-1.md": 200}
        diff = cairn.diff_scans(old, new)
        self.assertEqual(diff["changed"], ["issues/PT-1.md"])
        self.assertEqual(diff["created"], [])
        self.assertEqual(diff["removed"], [])

    def test_new_key_is_reported_as_created(self):
        diff = cairn.diff_scans({}, {"issues/PT-1.md": 100})
        self.assertEqual(diff["created"], ["issues/PT-1.md"])
        self.assertEqual(diff["changed"], [])
        self.assertEqual(diff["removed"], [])

    def test_missing_key_is_reported_as_removed(self):
        diff = cairn.diff_scans({"issues/PT-1.md": 100}, {})
        self.assertEqual(diff["removed"], ["issues/PT-1.md"])
        self.assertEqual(diff["created"], [])
        self.assertEqual(diff["changed"], [])

    def test_mixed_change_set_reports_each_correctly(self):
        old = {"issues/PT-1.md": 100, "issues/PT-2.md": 100, "issues/PT-3.md": 100}
        new = {"issues/PT-1.md": 100, "issues/PT-2.md": 200, "issues/PT-4.md": 100}
        diff = cairn.diff_scans(old, new)
        self.assertEqual(diff["changed"], ["issues/PT-2.md"])
        self.assertEqual(diff["created"], ["issues/PT-4.md"])
        self.assertEqual(diff["removed"], ["issues/PT-3.md"])

    def test_diff_has_a_cheap_any_changed_signal(self):
        # The watcher's own loop needs a cheap "did anything happen at
        # all" check before it bothers building/sending an SSE frame --
        # pin that any(diff.values()) is the obvious signal rather than
        # requiring a separate boolean field callers might forget to set.
        quiet = cairn.diff_scans({"a": 1}, {"a": 1})
        active = cairn.diff_scans({"a": 1}, {"a": 2})
        self.assertFalse(any(quiet.values()))
        self.assertTrue(any(active.values()))


class ScanThenDiffIntegrationTests(unittest.TestCase):
    """Combines the two pure functions against a real filesystem -- still
    no threading/timing beyond one small mtime-separation sleep: scan,
    mutate, scan again, diff. This is the "change detected / quiet on no
    change / file added / file removed" matrix PT-1's AC asks for."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        for sub in ("majors", "milestones", "issues", "archive"):
            (self.tmp / sub).mkdir()

    def test_file_added_between_two_scans_is_detected(self):
        before = cairn.scan_data_dir(self.tmp)
        _write(self.tmp / "issues" / "PT-1.md")
        after = cairn.scan_data_dir(self.tmp)
        diff = cairn.diff_scans(before, after)
        self.assertEqual(diff["created"], ["issues/PT-1.md"])

    def test_file_removed_between_two_scans_is_detected(self):
        path = self.tmp / "issues" / "PT-1.md"
        _write(path)
        before = cairn.scan_data_dir(self.tmp)
        path.unlink()
        after = cairn.scan_data_dir(self.tmp)
        diff = cairn.diff_scans(before, after)
        self.assertEqual(diff["removed"], ["issues/PT-1.md"])

    def test_file_content_edit_between_two_scans_is_detected(self):
        path = self.tmp / "issues" / "PT-1.md"
        _write(path, "v1")
        before = cairn.scan_data_dir(self.tmp)
        time.sleep(0.01)  # ensure a distinct mtime_ns on fast filesystems
        _write(path, "v2")
        after = cairn.scan_data_dir(self.tmp)
        diff = cairn.diff_scans(before, after)
        self.assertEqual(diff["changed"], ["issues/PT-1.md"])

    def test_two_consecutive_scans_with_no_edits_are_quiet(self):
        _write(self.tmp / "issues" / "PT-1.md")
        first = cairn.scan_data_dir(self.tmp)
        second = cairn.scan_data_dir(self.tmp)
        diff = cairn.diff_scans(first, second)
        self.assertEqual(diff, {"created": [], "changed": [], "removed": []})


if __name__ == "__main__":
    unittest.main()
