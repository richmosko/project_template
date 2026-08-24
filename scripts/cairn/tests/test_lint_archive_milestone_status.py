"""PASS 2 (lint) tests for PT-39 §3 items 2 and 3 -- the last red-green
cycle in PT-39. Architect's ruling: temp/arch-ruling-pt39-lifecycle.md.

Item 3 (read first -- item 2 depends on it): `known_milestones` /
`known_majors` must resolve against the archive subdirs too (§4's new
archive/milestones/, archive/majors/), not just the live milestones/,
majors/ dirs. Without this, archiving a milestone would dangle every issue
that references it (its own now-archived issues, whose `milestone:` ref
didn't change) -- self-defeating for a command whose whole point is a
clean post-archive lint.

Item 2: an issue in `archive/` whose `milestone:` is non-null and resolves
(via item 3's now-widened known_milestones) to a milestone that is NOT
done/cancelled is a NEW check_repo error. This is the hand-`git mv` bypass
catch: `cairn archive --milestone` refuses unless every issue under a
milestone AND the milestone itself are done/cancelled (test_archive_records.py
pins that precondition) -- but nothing stops a human from `git mv`-ing an
issue into archive/ directly, skipping the precondition entirely. This
lint rule is what makes PT-43's counting invariant (every archived issue
belongs to a done/cancelled milestone) structural rather than "true
because the CLI path happens to enforce it today."

Scope: item 2 applies ONLY to issues actually living in `archive/` -- a
live issue (in `issues/`) referencing an in-progress milestone is the
NORMAL, expected shape of every unfinished milestone's issues and must
never be flagged by this rule (see NoOverfireOnLiveIssuesTests below).

Nothing under test exists yet: known_milestones/known_majors only scan
milestones/majors, never their archive/ counterparts, and check_repo has
no notion of "this issue is archived, so its milestone must be
done/cancelled" at all. Every test below is expected to fail (a spurious
"unknown milestone"/"unknown major" dangling-ref error item 3 should have
prevented, or a missing item-2 error where one is now expected) until
implementation-lead's slice lands.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


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
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "archive" / "issues").mkdir(parents=True)
    (data_dir / "archive" / "milestones").mkdir(parents=True)
    (data_dir / "archive" / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "majors" / "PT-V1.md").write_text(
        MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8"
    )
    return data_dir


def milestone_errors(errors: list[str], stem: str) -> list[str]:
    return [e for e in errors if e.startswith(f"{stem}:") or (stem in e and "milestone" in e.lower())]


class KnownMilestonesResolveAgainstArchiveTests(unittest.TestCase):
    """§3 item 3, milestones half."""

    def test_an_archived_issue_referencing_an_archived_milestone_does_not_dangle(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        (data_dir / "archive" / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Old bootstrap task", status="done", milestone="PT-A"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertFalse(
            any("unknown milestone" in e and "PT-A" in e for e in errors),
            f"PT-A must resolve via archive/milestones/, got: {errors}",
        )

    def test_a_live_issue_referencing_an_archived_milestone_also_does_not_dangle(self):
        # Less common (normally every issue under an archived milestone was
        # archived alongside it) but the resolution itself must not care
        # WHERE the referencing issue lives -- known_milestones is one set,
        # read by both the live and archived issue loops identically.
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-2.md").write_text(
            ISSUE_TMPL.format(id="PT-2", title="A new followup task", status="todo", milestone="PT-A"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertFalse(
            any("unknown milestone" in e and "PT-A" in e for e in errors),
            f"PT-A must resolve via archive/milestones/ for a live issue too, got: {errors}",
        )

    def test_a_genuinely_unknown_milestone_still_dangles_regression_guard(self):
        # The widened resolution must not become "anything goes" -- an id
        # that exists NOWHERE (live or archived) is still an error.
        data_dir = make_repo(self)
        (data_dir / "issues" / "PT-3.md").write_text(
            ISSUE_TMPL.format(id="PT-3", title="Bogus ref", status="todo", milestone="PT-9.9"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(
            any("unknown milestone" in e and "PT-9.9" in e for e in errors),
            f"a truly nonexistent milestone must still dangle, got: {errors}",
        )


class KnownMajorsResolveAgainstArchiveTests(unittest.TestCase):
    """§3 item 3, majors half."""

    def test_a_milestone_referencing_an_archived_major_does_not_dangle(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "majors" / "PT-V0.md").write_text(
            MAJOR_TMPL.format(id="PT-V0", status="done"), encoding="utf-8"
        )
        (data_dir / "milestones" / "PT-B.md").write_text(
            MILESTONE_TMPL.format(id="PT-B", name="Legacy work", kind="process", major="PT-V0",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertFalse(
            any("unknown major" in e and "PT-V0" in e for e in errors),
            f"PT-V0 must resolve via archive/majors/, got: {errors}",
        )

    def test_a_genuinely_unknown_major_still_dangles_regression_guard(self):
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-B.md").write_text(
            MILESTONE_TMPL.format(id="PT-B", name="Orphaned", kind="process", major="PT-V9",
                                   status="planned", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(
            any("unknown major" in e and "PT-V9" in e for e in errors),
            f"a truly nonexistent major must still dangle, got: {errors}",
        )


class ArchivedIssueMilestoneMustBeDoneTests(unittest.TestCase):
    """§3 item 2 -- the hand-`git mv` bypass catch."""

    def test_archived_issue_under_a_live_in_progress_milestone_is_a_lint_error(self):
        # The bypass scenario itself: PT-1 was `git mv`-ed into archive/ by
        # hand, but its milestone (PT-1.0) is still live and in-progress --
        # never went through archive_milestone's precondition at all.
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="in-progress", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        (data_dir / "archive" / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Hand-mv'd out from under a live milestone",
                               status="done", milestone="PT-1.0"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(
            any("PT-1" in e and "PT-1.0" in e for e in errors),
            f"expected an error naming both the archived issue and its non-done milestone, got: {errors}",
        )

    def test_archived_issue_under_a_done_milestone_is_lint_clean(self):
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        (data_dir / "archive" / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Properly archived", status="done", milestone="PT-A"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(milestone_errors(errors, "PT-1"), [], errors)

    def test_archived_issue_under_a_cancelled_milestone_is_lint_clean(self):
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(id="PT-A", name="Dropped", kind="process", major="PT-V1",
                                   status="cancelled", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        (data_dir / "archive" / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Archived alongside a cancelled milestone",
                               status="cancelled", milestone="PT-A"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(milestone_errors(errors, "PT-1"), [], errors)

    def test_archived_issue_with_null_milestone_is_unaffected(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Never milestoned", status="done", milestone="null"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(milestone_errors(errors, "PT-1"), [], errors)

    def test_archived_issue_whose_milestone_lives_in_archive_milestones_and_is_done_is_clean(self):
        # Combines items 2 and 3: the normal, correct post-archive_milestone
        # shape -- both the issue and its milestone were moved together.
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        (data_dir / "archive" / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Properly archived, milestone too", status="done",
                               milestone="PT-A"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(milestone_errors(errors, "PT-1"), [], errors)


class NoOverfireOnLiveIssuesTests(unittest.TestCase):
    """Item 2 must apply ONLY to issues actually in archive/ -- a live
    issue under an in-progress milestone is the ordinary, expected shape
    of every unfinished milestone and must never trip this rule."""

    def test_a_live_issue_under_an_in_progress_milestone_is_not_flagged(self):
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="in-progress", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Normal in-flight work", status="todo", milestone="PT-1.0"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(milestone_errors(errors, "PT-1"), [], errors)

    def test_a_live_done_issue_under_an_in_progress_milestone_is_not_flagged(self):
        # A milestone can be in-progress with SOME of its issues already
        # done -- that issue is still live (not archived), so item 2 must
        # not touch it either, regardless of the issue's own status.
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="in-progress", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="Done early, milestone still open", status="done",
                               milestone="PT-1.0"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(milestone_errors(errors, "PT-1"), [], errors)


if __name__ == "__main__":
    unittest.main()
