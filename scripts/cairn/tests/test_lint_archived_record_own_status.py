"""PT-46 failing tests: a milestone/major file living in `archive/milestones/`
or `archive/majors/` whose OWN status isn't done/cancelled goes undetected
today -- the hand-`git mv` bypass catch PT-39 §3 item 2 built for ISSUES
(an archived issue's milestone must be done/cancelled) has no sibling for
the record itself. `cairn archive --milestone`/`--major` refuses unless
the record's own status is already done/cancelled (test_archive_records.py
pins that precondition) -- but nothing stops a human from `git mv`-ing a
still-`in-progress` milestone/major file straight into archive/milestones/
or archive/majors/, skipping the precondition entirely. The board then
silently loses that lane with no lint signal at all.

Root cause, confirmed by reading check_repo directly: `known_majors`/
`known_milestones` already resolve archive/majors/, archive/milestones/
for REFERENCE purposes (PT-39 §3 item 3), but the comment there is
explicit: "id-shape/title/status validation is NOT re-run on archived
files ... re-validating here would be redundant at best" -- true for the
GENERAL RECORD_STATUSES check (§3 item 1, which trusts that whatever
passed validation at archive time is still valid), false for THIS
specific check (an archived record's status must be done/cancelled,
which is a stricter, archive-location-specific rule the general check
never asserted in the first place).

Message convention mirrors PT-39 §3 item 2's issue-level wording exactly
(cairn.py's check_repo, the "archived issue's milestone ... is not
done/cancelled ... looks like it was moved into archive/ by hand,
bypassing `cairn archive`'s precondition" string) -- same bypass, same
vocabulary, one record type over.

Nothing under test exists yet: check_repo has no check at all for an
archive/milestones|majors file's own status. Every red test below is
expected to fail (no error where one is now required) until
implementation-lead's PT-46 slice lands.
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


def make_repo(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "archive" / "milestones").mkdir(parents=True)
    (data_dir / "archive" / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "majors" / "PT-V1.md").write_text(
        MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8"
    )
    return data_dir


def status_errors_for(errors: list[str], stem: str) -> list[str]:
    return [e for e in errors if e.startswith(f"{stem}:")]


class ArchivedMilestoneOwnStatusLintTests(unittest.TestCase):
    def test_an_archived_milestone_with_in_progress_status_is_a_lint_error(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Hand-moved", kind="process", major="PT-V1",
                                   status="in-progress", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        matching = status_errors_for(errors, "PT-Z")
        self.assertTrue(matching, f"expected a PT-Z status error, got: {errors}")
        self.assertTrue(
            any("not done/cancelled" in e for e in matching),
            f"expected 'not done/cancelled' wording, got: {matching}",
        )
        self.assertTrue(
            any("hand" in e and "bypass" in e for e in matching),
            f"expected the hand-mv bypass hint (mirroring PT-39's issue-level message), got: {matching}",
        )

    def test_an_archived_milestone_with_planned_status_is_also_a_lint_error(self):
        # "planned" IS a valid RECORD_STATUSES value (the general §3 item 1
        # check would pass it) -- this rule is stricter than that one,
        # archive-location-specific.
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Never started", kind="process", major="PT-V1",
                                   status="planned", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(status_errors_for(errors, "PT-Z"), errors)

    def test_an_archived_milestone_with_done_status_lints_clean(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Properly archived", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(status_errors_for(errors, "PT-Z"), [])

    def test_an_archived_milestone_with_cancelled_status_lints_clean(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            MILESTONE_TMPL.format(id="PT-Z", name="Dropped", kind="process", major="PT-V1",
                                   status="cancelled", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(status_errors_for(errors, "PT-Z"), [])

    def test_a_live_in_progress_milestone_is_not_flagged_by_this_rule_regression_guard(self):
        # Scoped to the ARCHIVE location only -- a live milestone that's
        # simply in-progress (the normal, expected shape of unfinished
        # work) must never trip this.
        data_dir = make_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="in-progress", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(status_errors_for(errors, "PT-1.0"), [])


class ArchivedMajorOwnStatusLintTests(unittest.TestCase):
    def test_an_archived_major_with_in_progress_status_is_a_lint_error(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "majors" / "PT-V9.md").write_text(
            MAJOR_TMPL.format(id="PT-V9", status="in-progress"), encoding="utf-8"
        )
        errors = cairn.check_repo(data_dir)
        matching = status_errors_for(errors, "PT-V9")
        self.assertTrue(matching, f"expected a PT-V9 status error, got: {errors}")
        self.assertTrue(any("not done/cancelled" in e for e in matching), matching)
        self.assertTrue(any("hand" in e and "bypass" in e for e in matching), matching)

    def test_an_archived_major_with_paused_status_is_also_a_lint_error(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "majors" / "PT-V9.md").write_text(
            MAJOR_TMPL.format(id="PT-V9", status="paused"), encoding="utf-8"
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(status_errors_for(errors, "PT-V9"), errors)

    def test_an_archived_major_with_done_status_lints_clean(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "majors" / "PT-V9.md").write_text(
            MAJOR_TMPL.format(id="PT-V9", status="done"), encoding="utf-8"
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(status_errors_for(errors, "PT-V9"), [])

    def test_an_archived_major_with_cancelled_status_lints_clean(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "majors" / "PT-V9.md").write_text(
            MAJOR_TMPL.format(id="PT-V9", status="cancelled"), encoding="utf-8"
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual(status_errors_for(errors, "PT-V9"), [])

    def test_a_live_in_progress_major_is_not_flagged_by_this_rule_regression_guard(self):
        # make_repo's own PT-V1 (majors/PT-V1.md) is already in-progress
        # and every other test in this suite implicitly relies on it not
        # being flagged -- explicit regression pin.
        data_dir = make_repo(self)
        errors = cairn.check_repo(data_dir)
        self.assertEqual(status_errors_for(errors, "PT-V1"), [])


class MissingStatusOnArchivedRecordTests(unittest.TestCase):
    """A missing status trivially satisfies 'not in {done, cancelled}' too
    -- must be caught by this same rule, not silently pass because it's a
    different failure shape than an explicit bad value."""

    def test_an_archived_milestone_with_no_status_field_at_all_is_a_lint_error(self):
        data_dir = make_repo(self)
        (data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            "---\nid: PT-Z\nname: No status\nkind: process\nmajor: PT-V1\n"
            "target_tag: null\nga: false\n---\n\nDoD.\n",
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertTrue(status_errors_for(errors, "PT-Z"), errors)


if __name__ == "__main__":
    unittest.main()
