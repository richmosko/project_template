"""PT-43 acceptance verification (Validate-phase pass, requested by team-
lead once PT-44 landed): "a completed, fully-archived milestone never
displays 0/0" and "counts remain correct for the mixed case."

This is NOT a new feature's red-then-green test file -- PT-43 was never
implemented as its own slice. Its acceptance criteria are claimed by the
joint PT-40/43/44 ruling to be satisfied STRUCTURALLY by PT-44's work
(§3's isComplete branch) plus PT-39's archive precondition/lint. This file
builds PT-43's own reported bug scenario byte-for-byte (from its issue
file: "PT-0.4 · v0.4.0 · 0/0 done -- it shipped 13") against the real,
now-landed code and asserts the property holds -- the composition proof
team-lead asked for, not a re-argument of the ruling.

§1 -- "never 0/0": proven via build_board_payload (server-side truth) +
milestoneProgress's isComplete flag (client-side, already exhaustively
unit-tested in tests/js/milestone-progress.test.js). isComplete is
computed from `milestone.status` ALONE -- never from issue counts -- so a
done/cancelled milestone's isComplete is `true` regardless of how many of
its issues are archived, live, or absent from the payload entirely. This
file proves the SERVER half: a done milestone's `status` field survives
archival of every one of its issues unchanged, in both Show-archived
states -- the fact isComplete's true-ness structurally depends on.

§2 -- "mixed case is structurally unreachable": cites the existing tests
that jointly close every path to it, rather than re-testing them here
(they already pass in this suite):
  - Sanctioned path (`cairn archive --milestone`): refuses unless the
    milestone AND every one of its issues are already done/cancelled --
    test_archive_records.py::ArchiveMilestoneEngineTests::
    test_refuses_when_milestone_itself_is_not_done_or_cancelled,
    test_refuses_when_a_referencing_issue_is_not_done_or_cancelled.
  - Hand-`git mv` bypass, issue-level (one issue moved into archive/
    while its milestone stays non-done): test_lint_archive_milestone_status.py::
    ArchivedIssueMilestoneMustBeDoneTests::
    test_archived_issue_under_a_live_in_progress_milestone_is_a_lint_error.
  - Hand-`git mv` bypass, record-level (the milestone FILE itself moved
    into archive/milestones/ while still carrying a non-done status):
    test_lint_archived_record_own_status.py::
    ArchivedMilestoneOwnStatusLintTests::
    test_an_archived_milestone_with_in_progress_status_is_a_lint_error
    (+ the sibling ...with_planned_status_is_also_a_lint_error).
Together: in a lint-clean repo, an issue can be in archive/ ONLY if its
milestone's status is done/cancelled -- there is no code path (sanctioned
or hand-edited-but-lint-clean) that produces an in-progress milestone with
even one archived issue. The "mixed case" needing correct n/m counting
across live+archived issues therefore only ever arises for a NON-done
milestone -- and a non-done milestone, by the above, never has archived
issues to mix in the first place. A done/cancelled milestone CAN
legitimately have a live+archived mix (e.g. a new issue filed against an
already-shipped milestone -- test_lint_archive_milestone_status.py::
test_a_live_issue_referencing_an_archived_milestone_also_does_not_dangle
pins this is allowed), but isComplete suppresses the ratio for it
entirely, so that mix's count-correctness is moot -- nothing ever renders
it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


MILESTONE_TMPL = (
    "---\nid: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
    "target_tag: {target_tag}\nga: {ga}\n---\n\nDoD.\n"
)
MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"
ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\n"
    "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nBody.\n"
)


def build_shipped_and_archived_milestone(testcase) -> Path:
    """PT-43's own reported scenario, reproduced exactly: a milestone
    that's DONE and every one of its issues has been archived -- the
    precise shape that read '0/0 done' before this fix (per the issue's
    own wording: 'it shipped 13'). 13 issues, matching the report."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "majors" / "PT-V1.md").write_text(MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8")
    (data_dir / "milestones" / "PT-0.4.md").write_text(
        MILESTONE_TMPL.format(id="PT-0.4", name="Polish pass", kind="product", major="PT-V1",
                               status="done", target_tag="v0.4.0", ga="false"),
        encoding="utf-8",
    )
    for n in range(1, 14):  # 13 issues, all archived, all done -- "it shipped 13"
        (data_dir / "archive" / f"PT-{n}.md").write_text(
            ISSUE_TMPL.format(id=f"PT-{n}", title=f"Shipped task {n}", status="done", milestone="PT-0.4"),
            encoding="utf-8",
        )
    return data_dir


class PT43NeverZeroZeroTests(unittest.TestCase):
    """§1: build_board_payload's half of the property isComplete depends on."""

    def test_the_milestone_reproduces_the_reported_0_of_0_shape_in_the_default_off_payload(self):
        # Sanity: with Show-archived off (default), the milestone's own
        # issues array-derived count really would be 0/0 today if nothing
        # else compensated -- confirms this fixture actually reproduces
        # PT-43's reported bug shape, not a fixture that never had it.
        data_dir = build_shipped_and_archived_milestone(self)
        payload = cairn.build_board_payload(data_dir, archived=False)
        milestone_issues = [i for i in payload["issues"] if i["milestone"] == "PT-0.4"]
        self.assertEqual(
            milestone_issues, [],
            "test sanity: with Show-archived off, PT-0.4 must have zero issues in the payload "
            "-- this is the exact pre-fix 0/0 shape the milestone's status field must override",
        )

    def test_the_milestone_status_is_done_in_the_default_off_payload_the_isComplete_predicate_needs(self):
        data_dir = build_shipped_and_archived_milestone(self)
        payload = cairn.build_board_payload(data_dir, archived=False)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-0.4")
        self.assertEqual(
            milestone["status"], "done",
            "the milestone record's own status must be 'done' regardless of the archived flag -- "
            "this is what CairnLogic.milestoneProgress's isComplete branch (exhaustively unit-"
            "tested in tests/js/milestone-progress.test.js) keys off to suppress the ratio "
            "entirely, independent of how many of its issues are in the payload",
        )

    def test_the_milestone_status_is_still_done_in_the_show_archived_on_payload_too(self):
        # Same fact must hold in BOTH toggle states -- the milestone
        # record's status doesn't change based on which issues happen to
        # be included.
        data_dir = build_shipped_and_archived_milestone(self)
        payload = cairn.build_board_payload(data_dir, archived=True)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-0.4")
        self.assertEqual(milestone["status"], "done")

    def test_show_archived_on_surfaces_all_13_shipped_issues_under_the_milestone(self):
        # The OTHER half of "no information loss" -- Show-archived on
        # must actually reveal the 13 issues, not just avoid showing 0/0.
        data_dir = build_shipped_and_archived_milestone(self)
        payload = cairn.build_board_payload(data_dir, archived=True)
        milestone_issues = [i for i in payload["issues"] if i["milestone"] == "PT-0.4"]
        self.assertEqual(len(milestone_issues), 13)
        self.assertTrue(all(i["archived"] for i in milestone_issues))
        self.assertTrue(all(i["status"] == "done" for i in milestone_issues))

    def test_the_repo_lints_clean_confirming_this_is_a_reachable_valid_state_not_a_hand_edited_fixture_artifact(self):
        # This fixture must represent a state the REAL system can actually
        # produce (via cairn archive --milestone, which this test doesn't
        # invoke directly, but whose precondition this fixture satisfies:
        # milestone done, every one of its issues done) -- not an invalid
        # or unreachable shape that happens to dodge the bug by accident.
        data_dir = build_shipped_and_archived_milestone(self)
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)


if __name__ == "__main__":
    unittest.main()
