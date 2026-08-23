"""Tests for PT-2's `cairn snapshot` -- a point-in-time markdown rendering
of the tracker (majors, milestones/roadmap, issues grouped by status),
meant to be appended to STATE.md for offline reading (a plane, a phone, a
cold session before the board is up). It is a RENDERING, never an input --
cairn must never parse it back (see SnapshotNonIngestionTests).

Interface assumed (see INTERFACE.md -- implementation may rename; update
INTERFACE.md in the same commit if so, per that file's own note):
    cairn.build_snapshot_markdown(data_dir: Path, generated_at: str | None = None) -> str
    cmd_snapshot(args) -> int  -- CLI `cairn snapshot`, prints the above to stdout

`generated_at` lets tests pin the one genuinely time-varying line
(everything else must be deterministic given an unchanged tree -- that's
the whole point of "diff cleanly" in the acceptance criteria) without
fighting wall-clock noise. A real `cairn snapshot` invocation still sources
a real timestamp when `generated_at` isn't given -- see SnapshotCliTests.

Status grouping order pinned by these tests: cairn.STATUS_ORDER (PT-36 --
backlog, todo, in-progress, in-review, done, cancelled) -- this is the one
existing canonical status sequence in the codebase (also board.js's
BOARD_COLUMNS/STATUS_LABELS order, guarded against drift by
test_column_parity.py), not a new invention.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

STATUS_ORDER = cairn.STATUS_ORDER


def make_tree(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    return data_dir


def write_major(data_dir: Path, filename: str, major_id: str, status: str = "active", health: str = "on-track") -> None:
    text = (
        f"---\nid: {major_id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\n"
        f"health: {health}\n---\n\nBody.\n"
    )
    (data_dir / "majors" / filename).write_text(text, encoding="utf-8")


def write_milestone(data_dir: Path, filename: str, milestone_id: str, name: str, major: str = "V1") -> None:
    text = (
        f"---\nid: {milestone_id}\nname: {name}\nkind: product\nmajor: {major}\nstatus: planned\n"
        "target_tag: null\nga: false\n---\n\nDoD.\n"
    )
    (data_dir / "milestones" / filename).write_text(text, encoding="utf-8")


def write_issue(data_dir: Path, filename: str, issue_id: str, title: str, status: str, milestone: str = "null") -> None:
    text = (
        "---\n"
        f"id: {issue_id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n"
        "---\n\nBody.\n"
    )
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


GENERATED_AT = "2026-08-20T00:00:00Z"


class SnapshotContentTests(unittest.TestCase):
    def _tree_with_mixed_statuses(self, testcase):
        data_dir = make_tree(testcase)
        write_major(data_dir, "V1.md", "V1")
        write_milestone(data_dir, "1.0.md", '"1.0"', "MVP", major="V1")
        write_issue(data_dir, "PT-2.md", "PT-2", "Second issue", status="todo", milestone='"1.0"')
        write_issue(data_dir, "PT-9.md", "PT-9", "Ninth issue", status="todo", milestone='"1.0"')
        write_issue(data_dir, "PT-10.md", "PT-10", "Tenth issue", status="todo", milestone='"1.0"')
        write_issue(data_dir, "PT-1.md", "PT-1", "First issue", status="backlog")
        write_issue(data_dir, "PT-3.md", "PT-3", "Cancelled issue", status="cancelled")
        return data_dir

    def test_snapshot_includes_generated_header_marking_it_non_editable(self):
        data_dir = self._tree_with_mixed_statuses(self)
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        lower = text.lower()
        self.assertIn("generated", lower)
        self.assertIn("do not edit", lower)
        self.assertIn("cairn snapshot", lower)

    def test_snapshot_includes_the_generated_at_marker_verbatim(self):
        data_dir = self._tree_with_mixed_statuses(self)
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        self.assertIn(GENERATED_AT, text)

    def test_snapshot_lists_majors(self):
        data_dir = self._tree_with_mixed_statuses(self)
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        self.assertIn("V1", text)

    def test_snapshot_lists_milestones_with_name(self):
        data_dir = self._tree_with_mixed_statuses(self)
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        self.assertIn("1.0", text)
        self.assertIn("MVP", text)

    def test_snapshot_lists_every_issue_with_id_and_title(self):
        data_dir = self._tree_with_mixed_statuses(self)
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        for issue_id, title in [
            ("PT-1", "First issue"), ("PT-2", "Second issue"), ("PT-9", "Ninth issue"),
            ("PT-10", "Tenth issue"), ("PT-3", "Cancelled issue"),
        ]:
            self.assertIn(issue_id, text)
            self.assertIn(title, text)


class SnapshotGroupingOrderTests(unittest.TestCase):
    """PT-2: issues grouped by status, sorted by id within each status group
    -- "by id" must be numeric (PT-2 < PT-9 < PT-10), not the lexicographic
    filename order _dir_glob returns (which would put PT-10 before PT-2).
    """

    def test_issues_appear_after_their_own_status_heading(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", "PT-1", "Backlog item", status="backlog")
        write_issue(data_dir, "PT-2.md", "PT-2", "Todo item", status="todo")
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        lower = text.lower()
        backlog_idx = lower.index("backlog")
        todo_idx = lower.index("todo")
        pt1_idx = text.index("PT-1")
        pt2_idx = text.index("PT-2")
        self.assertTrue(backlog_idx < pt1_idx < todo_idx, text)
        self.assertTrue(todo_idx < pt2_idx, text)

    def test_status_headings_appear_in_canonical_workflow_order(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", "PT-1", "A", status="cancelled")
        write_issue(data_dir, "PT-2.md", "PT-2", "B", status="done")
        write_issue(data_dir, "PT-3.md", "PT-3", "C", status="backlog")
        write_issue(data_dir, "PT-4.md", "PT-4", "D", status="in-review")
        write_issue(data_dir, "PT-5.md", "PT-5", "E", status="todo")
        write_issue(data_dir, "PT-6.md", "PT-6", "F", status="in-progress")
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        lower = text.lower()
        indices = [lower.index(s) for s in STATUS_ORDER]
        self.assertEqual(indices, sorted(indices), text)

    def test_issues_within_a_status_are_sorted_numerically_by_id_not_lexicographically(self):
        # Lexicographic filename order (what _dir_glob returns) would put
        # PT-10 before PT-2 ('1' < '2'). The snapshot must not do that.
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-10.md", "PT-10", "Tenth", status="todo")
        write_issue(data_dir, "PT-2.md", "PT-2", "Second", status="todo")
        write_issue(data_dir, "PT-9.md", "PT-9", "Ninth", status="todo")
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        pt2_idx = text.index("PT-2")
        pt9_idx = text.index("PT-9")
        pt10_idx = text.index("PT-10")
        self.assertTrue(pt2_idx < pt9_idx < pt10_idx, text)


class SnapshotDeterminismTests(unittest.TestCase):
    def test_snapshot_is_deterministic_given_the_same_generated_at(self):
        data_dir = make_tree(self)
        write_major(data_dir, "V1.md", "V1")
        write_milestone(data_dir, "1.0.md", '"1.0"', "MVP")
        write_issue(data_dir, "PT-1.md", "PT-1", "Thing", status="todo", milestone='"1.0"')
        first = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        second = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        self.assertEqual(first, second)

    def test_snapshot_ordering_is_stable_regardless_of_disk_scan_order(self):
        # Same content (majors, milestones, issues), deliberately written in
        # a different order across two trees -- output must still match,
        # proving the ordering is computed, not incidentally inherited from
        # filesystem iteration order.
        data_dir_a = make_tree(self)
        write_major(data_dir_a, "V1.md", "V1")
        write_major(data_dir_a, "V2.md", "V2")
        write_milestone(data_dir_a, "1.0.md", '"1.0"', "MVP", major="V1")
        write_milestone(data_dir_a, "2.0.md", '"2.0"', "Next", major="V2")
        write_issue(data_dir_a, "PT-1.md", "PT-1", "A", status="todo")
        write_issue(data_dir_a, "PT-2.md", "PT-2", "B", status="backlog")
        out_a = cairn.build_snapshot_markdown(data_dir_a, generated_at=GENERATED_AT)

        data_dir_b = make_tree(self)
        write_milestone(data_dir_b, "2.0.md", '"2.0"', "Next", major="V2")
        write_major(data_dir_b, "V2.md", "V2")
        write_issue(data_dir_b, "PT-2.md", "PT-2", "B", status="backlog")
        write_milestone(data_dir_b, "1.0.md", '"1.0"', "MVP", major="V1")
        write_major(data_dir_b, "V1.md", "V1")
        write_issue(data_dir_b, "PT-1.md", "PT-1", "A", status="todo")
        out_b = cairn.build_snapshot_markdown(data_dir_b, generated_at=GENERATED_AT)

        self.assertEqual(out_a, out_b)


class SnapshotNonIngestionTests(unittest.TestCase):
    """PT-2: the snapshot is a rendering, never an input -- cairn must never
    parse it back. It's written to STDOUT (never to a file under data_dir),
    and its own shape must not be mistakable for tracker frontmatter even
    if it were misplaced.
    """

    def test_build_snapshot_markdown_does_not_write_any_file(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", "PT-1", "Thing", status="todo")
        before = sorted(p.relative_to(data_dir) for p in data_dir.rglob("*") if p.is_file())
        cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        after = sorted(p.relative_to(data_dir) for p in data_dir.rglob("*") if p.is_file())
        self.assertEqual(before, after)

    def test_snapshot_output_does_not_open_with_frontmatter_fences(self):
        # If this text were ever misplaced into issues/, milestones/, or
        # majors/ (adversarially or by accident), parse_frontmatter must
        # fail loudly on it rather than silently ingest it as tracker data
        # -- that requires the snapshot to not open with the exact "---"
        # fence parse_frontmatter looks for.
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", "PT-1", "Thing", status="todo")
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        self.assertFalse(text.startswith("---"), text[:50])

    def test_snapshot_misplaced_into_issues_dir_is_rejected_by_check_repo_not_silently_ingested(self):
        # Belt-and-suspenders: actually write the rendered snapshot into
        # issues/ under a plausible filename and confirm check_repo reports
        # a parse error for it (per-file CairnError caught, not a crash,
        # not silent success) rather than treating it as a real issue.
        data_dir = make_tree(self)
        text = cairn.build_snapshot_markdown(data_dir, generated_at=GENERATED_AT)
        (data_dir / "issues" / "PT-999.md").write_text(text, encoding="utf-8")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("PT-999" in e for e in errors), errors)


class SnapshotDataDirTests(unittest.TestCase):
    """PT-2: `cairn snapshot` must respect --data-dir, both top-level and
    after the subcommand (per PT-9's precedent -- see test_cli.py's
    PT9DataDirTopLevelOptionTests for the general contract this mirrors)."""

    def test_cli_snapshot_respects_top_level_data_dir(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", "PT-1", "Marker Title Unique 12345", status="todo")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "--data-dir", str(data_dir), "snapshot"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Marker Title Unique 12345", result.stdout)

    def test_cli_snapshot_respects_subcommand_position_data_dir(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", "PT-1", "Another Unique Marker 67890", status="todo")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "snapshot", "--data-dir", str(data_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Another Unique Marker 67890", result.stdout)


class SnapshotCliTests(unittest.TestCase):
    def test_cli_snapshot_exits_zero_and_prints_generated_header(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "snapshot", "--data-dir", str(data_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("generated", result.stdout.lower())

    def test_cli_snapshot_wall_clock_generated_at_is_a_real_iso_date(self):
        # The CLI path (unlike build_snapshot_markdown's injectable
        # generated_at, used everywhere else in this file for determinism)
        # sources a real wall-clock timestamp per team-lead's note on this
        # feature -- confirm *something* date-shaped landed, without
        # pinning the exact value (that would make this test itself
        # non-deterministic).
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "snapshot", "--data-dir", str(data_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"\d{4}-\d{2}-\d{2}")

    def test_cli_snapshot_help_is_documented(self):
        result = subprocess.run([str(helpers.CAIRN_BIN), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("snapshot", result.stdout)


if __name__ == "__main__":
    unittest.main()
