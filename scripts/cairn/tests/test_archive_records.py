"""PASS 1 (engine/CLI) tests for PT-39 §4/§5: the archive/milestones,
archive/majors layout and `cairn archive`'s new --milestone/--major
selectors + preconditions. Architect's ruling:
temp/arch-ruling-pt39-lifecycle.md.

§4 layout:
    archive/PT-14.md              issues        (unchanged)
    archive/milestones/PT-0.4.md  NEW
    archive/majors/PT-V0.md       NEW
Additive subdirectories, invisible to every existing non-recursive glob
until code explicitly reads them. `_WATCHED_SUBDIRS` gains
"archive/milestones", "archive/majors" (else SSE misses them).

§5 `cairn archive` selectors -- exactly one of `--done-before` (existing),
`--milestone <id>` (new), `--major <id>` (new), mutually exclusive,
required. All three accept `--dry-run` (new).

The load-bearing part (ruling's own words): "archive never sweeps issues
out from under a live milestone." A milestone/major can only be archived
if IT and every issue/milestone under it is already done/cancelled --
refuses (raises, writes nothing) otherwise. `--done-before`'s existing
path gets one new behaviour: an issue whose milestone isn't done/cancelled
is SKIPPED (printed reason, not an error), not archived.

This file uses its own isolated fixture repos, built with the NEW
(RECORD_STATUSES) vocabulary from the start -- deliberately not reusing
the shared tests/fixtures/process/cairn/ tree, which (as of this commit)
still carries pre-PT-39 status values and is a separate, tracked
regression (see team-lead/implementation-lead thread, 2026-08-23).

Nothing under test exists yet: `cairn.archive_milestone`/`archive_major`
are not defined, `--milestone`/`--major`/`--dry-run` are not recognized
CLI flags on `cairn archive`, and archive/milestones|majors are never
created. Every test below is expected to fail (AttributeError, argparse
usage error, or a file simply not having moved) until implementation-lead's
PT-39 §4/§5 slice lands.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def run_cairn(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(helpers.CAIRN_BIN), *args],
        capture_output=True,
        text=True,
    )


MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"
MILESTONE_TMPL = (
    "---\nid: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
    "target_tag: {target_tag}\nga: {ga}\n---\n\nDoD.\n"
)
ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\n"
    "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n"
)


def make_repo(testcase) -> Path:
    """One major (PT-V1, in-progress), two milestones under it:
    PT-A (done, process-kind, two done issues -- a clean archive candidate)
    and PT-1.0 (in-progress, product-kind, one todo issue -- NOT archivable,
    neither by its own status nor its issue's). A third, standalone
    milestone PT-B (done, no issues at all -- the "milestone with nothing
    under it" edge case) is added by tests that need it, not here.
    """
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")

    (data_dir / "majors" / "PT-V1.md").write_text(
        MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8"
    )
    (data_dir / "milestones" / "PT-A.md").write_text(
        MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                               status="done", target_tag="null", ga="false"),
        encoding="utf-8",
    )
    (data_dir / "milestones" / "PT-1.0.md").write_text(
        MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                               status="in-progress", target_tag="v1.0.0", ga="true"),
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-1.md").write_text(
        ISSUE_TMPL.format(id="PT-1", title="Bootstrap task one", status="done", milestone="PT-A"),
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-2.md").write_text(
        ISSUE_TMPL.format(id="PT-2", title="Bootstrap task two", status="cancelled", milestone="PT-A"),
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-3.md").write_text(
        ISSUE_TMPL.format(id="PT-3", title="Still building MVP", status="todo", milestone="PT-1.0"),
        encoding="utf-8",
    )
    return data_dir


def snapshot_tree(data_dir: Path) -> dict:
    return {
        str(p.relative_to(data_dir)): p.read_bytes()
        for p in sorted(data_dir.rglob("*.md")) + sorted(data_dir.rglob("*.yml"))
    }


class WatchedSubdirsTests(unittest.TestCase):
    def test_watched_subdirs_includes_archive_milestones_and_archive_majors(self):
        self.assertIn("archive/milestones", cairn._WATCHED_SUBDIRS)
        self.assertIn("archive/majors", cairn._WATCHED_SUBDIRS)

    def test_watched_subdirs_still_includes_the_original_four(self):
        # Regression guard -- this is an ADDITIVE change (ruling §4).
        for sub in ("majors", "milestones", "issues", "archive"):
            self.assertIn(sub, cairn._WATCHED_SUBDIRS)


class ArchiveMilestoneEngineTests(unittest.TestCase):
    """`cairn.archive_milestone(data_dir, milestone_id, dry_run=False)`."""

    def test_refuses_when_milestone_itself_is_not_done_or_cancelled(self):
        data_dir = make_repo(self)
        before = snapshot_tree(data_dir)
        with self.assertRaises(cairn.CairnError):
            cairn.archive_milestone(data_dir, "PT-1.0")  # status: in-progress
        self.assertEqual(snapshot_tree(data_dir), before, "a refused archive must write nothing")

    def test_refuses_when_a_referencing_issue_is_not_done_or_cancelled(self):
        # PT-A is done, but give it a still-open issue -- the milestone's
        # OWN status being done is not sufficient; every issue under it
        # must also be done/cancelled (the load-bearing precondition).
        data_dir = make_repo(self)
        (data_dir / "issues" / "PT-4.md").write_text(
            ISSUE_TMPL.format(id="PT-4", title="Forgot to close this one", status="todo", milestone="PT-A"),
            encoding="utf-8",
        )
        before = snapshot_tree(data_dir)
        with self.assertRaises(cairn.CairnError):
            cairn.archive_milestone(data_dir, "PT-A")
        self.assertEqual(snapshot_tree(data_dir), before, "a refused archive must write nothing")

    def test_unknown_milestone_id_raises(self):
        data_dir = make_repo(self)
        with self.assertRaises(cairn.CairnError):
            cairn.archive_milestone(data_dir, "PT-9.9")

    def test_successful_archive_moves_the_milestone_file_to_archive_milestones(self):
        data_dir = make_repo(self)
        cairn.archive_milestone(data_dir, "PT-A")
        self.assertFalse((data_dir / "milestones" / "PT-A.md").exists())
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-A.md").exists())

    def test_successful_archive_moves_every_referencing_issue(self):
        data_dir = make_repo(self)
        cairn.archive_milestone(data_dir, "PT-A")
        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())
        self.assertFalse((data_dir / "issues" / "PT-2.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-2.md").exists())

    def test_successful_archive_does_not_touch_an_unrelated_milestones_issues(self):
        data_dir = make_repo(self)
        cairn.archive_milestone(data_dir, "PT-A")
        self.assertTrue((data_dir / "issues" / "PT-3.md").exists(), "PT-1.0's issue must be untouched")
        self.assertTrue((data_dir / "milestones" / "PT-1.0.md").exists())

    def test_report_shape(self):
        data_dir = make_repo(self)
        report = cairn.archive_milestone(data_dir, "PT-A")
        self.assertEqual(report["milestone"], "PT-A")
        self.assertEqual(sorted(report["issues"]), ["PT-1", "PT-2"])

    def test_dry_run_writes_nothing(self):
        data_dir = make_repo(self)
        before = snapshot_tree(data_dir)
        report = cairn.archive_milestone(data_dir, "PT-A", dry_run=True)
        self.assertEqual(snapshot_tree(data_dir), before, "--dry-run must not modify or move any file")
        self.assertEqual(report["milestone"], "PT-A", "the report is still returned in dry-run mode")

    def test_a_milestone_with_no_issues_archives_cleanly(self):
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-B.md").write_text(
            MILESTONE_TMPL.format(id="PT-B", name="Empty", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        report = cairn.archive_milestone(data_dir, "PT-B")
        self.assertEqual(report["issues"], [])
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-B.md").exists())

    def test_archive_milestones_dir_is_created_on_first_use(self):
        data_dir = make_repo(self)
        self.assertFalse((data_dir / "archive" / "milestones").exists(), "test sanity: dir must not pre-exist")
        cairn.archive_milestone(data_dir, "PT-A")
        self.assertTrue((data_dir / "archive" / "milestones").is_dir())


class ArchiveMajorEngineTests(unittest.TestCase):
    """`cairn.archive_major(data_dir, major_id, dry_run=False)`."""

    def test_refuses_when_major_itself_is_not_done_or_cancelled(self):
        data_dir = make_repo(self)  # PT-V1: in-progress
        before = snapshot_tree(data_dir)
        with self.assertRaises(cairn.CairnError):
            cairn.archive_major(data_dir, "PT-V1")
        self.assertEqual(snapshot_tree(data_dir), before)

    def test_refuses_when_any_milestone_under_it_fails_its_own_precondition(self):
        # Major itself done, but PT-1.0 under it is still in-progress --
        # the WHOLE archive must refuse, two-phase (validate everything,
        # THEN move), so a partially-archived major is not reachable.
        data_dir = make_repo(self)
        (data_dir / "majors" / "PT-V1.md").write_text(
            MAJOR_TMPL.format(id="PT-V1", status="done"), encoding="utf-8"
        )
        before = snapshot_tree(data_dir)
        with self.assertRaises(cairn.CairnError):
            cairn.archive_major(data_dir, "PT-V1")
        self.assertEqual(snapshot_tree(data_dir), before, "a refused archive must write NOTHING -- not even PT-A")

    def test_unknown_major_id_raises(self):
        data_dir = make_repo(self)
        with self.assertRaises(cairn.CairnError):
            cairn.archive_major(data_dir, "PT-V9")

    def test_successful_archive_moves_the_major_and_every_milestone_and_issue_under_it(self):
        data_dir = make_repo(self)
        (data_dir / "majors" / "PT-V1.md").write_text(
            MAJOR_TMPL.format(id="PT-V1", status="done"), encoding="utf-8"
        )
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="done", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-3.md").write_text(
            ISSUE_TMPL.format(id="PT-3", title="Shipped", status="done", milestone="PT-1.0"),
            encoding="utf-8",
        )
        cairn.archive_major(data_dir, "PT-V1")

        self.assertTrue((data_dir / "archive" / "majors" / "PT-V1.md").exists())
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-A.md").exists())
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-1.0.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-2.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-3.md").exists())

    def test_dry_run_writes_nothing(self):
        data_dir = make_repo(self)
        (data_dir / "majors" / "PT-V1.md").write_text(
            MAJOR_TMPL.format(id="PT-V1", status="done"), encoding="utf-8"
        )
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="done", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-3.md").write_text(
            ISSUE_TMPL.format(id="PT-3", title="Shipped", status="done", milestone="PT-1.0"),
            encoding="utf-8",
        )
        before = snapshot_tree(data_dir)
        cairn.archive_major(data_dir, "PT-V1", dry_run=True)
        self.assertEqual(snapshot_tree(data_dir), before)


class LintCompositionTests(unittest.TestCase):
    """Architect's finding (2026-08-23, PT-39 review): no existing test
    composes an archive_* run with check_repo -- test_archive_records.py's
    own tests never call check_repo at all, and the lint tests
    (test_lint_archive_milestone_status.py) build already-archived fixture
    trees BY HAND rather than by actually running archive_milestone/
    archive_major. Both halves can be green while the composition is
    broken -- measured for real: `cairn archive --milestone PT-0.4` against
    a copy of this repo's own live tracker data produced 13 lint errors
    while every existing test (both files) stayed green.

    Asserts `check_repo(data_dir) == []` BOTH before and after the real
    archive_* call -- before, so a fixture that was already dirty can't
    make the "clean after" half vacuously true; after, the actual property
    this class exists to pin. This is the seam where a path-shape mismatch
    between where archive_* writes (e.g. archive/milestones/) and where
    check_repo's known_milestones/known_majors look (§3 item 3) would
    reappear silently -- exactly the defect the architect found.
    """

    def test_check_repo_is_clean_after_a_real_archive_milestone_run(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.check_repo(data_dir), [], "test sanity: fixture must start lint-clean")
        cairn.archive_milestone(data_dir, "PT-A")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_check_repo_is_clean_after_a_real_archive_major_run(self):
        data_dir = make_repo(self)
        (data_dir / "majors" / "PT-V1.md").write_text(
            MAJOR_TMPL.format(id="PT-V1", status="done"), encoding="utf-8"
        )
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="done", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-3.md").write_text(
            ISSUE_TMPL.format(id="PT-3", title="Shipped", status="done", milestone="PT-1.0"),
            encoding="utf-8",
        )
        self.assertEqual(cairn.check_repo(data_dir), [], "test sanity: fixture must start lint-clean")
        cairn.archive_major(data_dir, "PT-V1")
        self.assertEqual(cairn.check_repo(data_dir), [])


class ArchiveCliSelectorTests(unittest.TestCase):
    """`cairn archive --done-before|--milestone|--major`, mutually exclusive."""

    def test_no_selector_at_all_is_a_usage_error(self):
        data_dir = make_repo(self)
        result = run_cairn(["archive", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_two_selectors_together_is_a_usage_error(self):
        data_dir = make_repo(self)
        result = run_cairn([
            "archive", "--done-before", "2026-01-01", "--milestone", "PT-A", "--data-dir", str(data_dir),
        ])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((data_dir / "archive" / "milestones" / "PT-A.md").exists())

    def test_milestone_selector_archives_via_the_cli(self):
        data_dir = make_repo(self)
        result = run_cairn(["archive", "--milestone", "PT-A", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-A.md").exists())

    def test_milestone_selector_refuses_a_non_done_milestone_via_the_cli(self):
        data_dir = make_repo(self)
        result = run_cairn(["archive", "--milestone", "PT-1.0", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "milestones" / "PT-1.0.md").exists())

    def test_major_selector_refuses_when_a_milestone_under_it_is_not_done_via_the_cli(self):
        data_dir = make_repo(self)
        (data_dir / "majors" / "PT-V1.md").write_text(
            MAJOR_TMPL.format(id="PT-V1", status="done"), encoding="utf-8"
        )
        result = run_cairn(["archive", "--major", "PT-V1", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "majors" / "PT-V1.md").exists())

    def test_dry_run_flag_is_accepted_on_the_milestone_selector(self):
        data_dir = make_repo(self)
        before = snapshot_tree(data_dir)
        result = run_cairn(["archive", "--milestone", "PT-A", "--dry-run", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot_tree(data_dir), before)


class DoneBeforeSkipNonDoneMilestoneTests(unittest.TestCase):
    """§5 table, --done-before row, NEW column: an issue whose milestone
    isn't done/cancelled is SKIPPED (reason printed, not an error), rather
    than archived alongside every other done/cancelled-by-date issue."""

    def test_a_done_issue_under_a_non_done_milestone_is_skipped_not_archived(self):
        data_dir = make_repo(self)
        # PT-3 is todo under in-progress PT-1.0 in the base fixture -- make
        # it done (so it WOULD qualify by --done-before alone) but leave
        # PT-1.0 itself in-progress, so the milestone precondition is what
        # must block it.
        (data_dir / "issues" / "PT-3.md").write_text(
            "---\nid: PT-3\ntitle: Done but under a live milestone\nstatus: done\nmilestone: PT-1.0\n"
            "parent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = run_cairn(["archive", "--done-before", "2026-08-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            (data_dir / "issues" / "PT-3.md").exists(),
            "an issue under a non-done milestone must be SKIPPED (stays in issues/), not archived",
        )
        self.assertFalse((data_dir / "archive" / "PT-3.md").exists())

    def test_done_before_still_archives_issues_under_a_done_milestone(self):
        # Regression guard -- the existing behaviour for the normal case
        # (milestone already done) must be unaffected by this new check.
        data_dir = make_repo(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Bootstrap task one\nstatus: done\nmilestone: PT-A\n"
            "parent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = run_cairn(["archive", "--done-before", "2026-08-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "PT-1.md").exists())

    def test_done_before_still_archives_a_null_milestone_issue_unaffected(self):
        # An issue with no milestone at all has no precondition to check
        # against -- must keep archiving exactly as it does today.
        data_dir = make_repo(self)
        (data_dir / "issues" / "PT-5.md").write_text(
            "---\nid: PT-5\ntitle: Unmilestoned and done\nstatus: done\nmilestone: null\n"
            "parent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = run_cairn(["archive", "--done-before", "2026-08-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "PT-5.md").exists())


if __name__ == "__main__":
    unittest.main()
