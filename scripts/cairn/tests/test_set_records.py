"""PASS 1 (engine/CLI) tests for PT-39 §6: `cairn set` resolving milestone
and major ids, not just issues. Architect's ruling:
temp/arch-ruling-pt39-lifecycle.md. Signatures per implementation-lead's
Pass-1 message (2026-08-23):

- `find_record_path(data_dir, record_id) -> Optional[Path]` -- NEW, resolves
  issues/ -> archive/ -> milestones/ -> archive/milestones/ -> majors/ ->
  archive/majors/, in that order. `find_issue_path` is explicitly
  UNCHANGED -- stays the only path the HTTP write path can reach (PT-3's
  read-only guarantee stays structural, not widened). Tested directly
  below, not just through cmd_set, so a regression in the HTTP-reachable
  surface can never hide behind a cmd_set-level pass.
- `cmd_set` now resolves via `find_record_path`, picks
  ISSUE_FIELD_ORDER/MILESTONE_FIELD_ORDER/MAJOR_FIELD_ORDER by schema, and
  validates `status=` against STATUSES (issue) or RECORD_STATUSES
  (milestone/major) -- new: cmd_set does zero status validation today,
  relying entirely on a later `cairn check` to catch a bad value.

This file's fixtures use the NEW (RECORD_STATUSES) vocabulary throughout,
same convention as test_archive_records.py -- not the shared
tests/fixtures/process/cairn/ tree, which still carries pre-PT-39 values
(separate tracked regression).

Nothing under test exists yet: `cairn.find_record_path` is undefined, and
`cmd_set` only ever resolves via `find_issue_path` -- every milestone/major
`cairn set` invocation below currently errors "no such issue" against an
id that IS a real file, just not one `find_issue_path` looks for. Expected
to fail (AttributeError, or a wrong/missing error message and an untouched
file) until implementation-lead's PT-39 §6 slice lands.
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


MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: {target_ship}\nhealth: on-track\n---\n\nBody.\n"
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
        MAJOR_TMPL.format(id="PT-V1", status="in-progress", target_ship="null"), encoding="utf-8"
    )
    (data_dir / "milestones" / "PT-1.0.md").write_text(
        MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                               status="in-progress", target_tag="v1.0.0", ga="true"),
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-1.md").write_text(
        ISSUE_TMPL.format(id="PT-1", title="A live issue", status="todo", milestone="PT-1.0"),
        encoding="utf-8",
    )
    # Archived counterparts, for the archive/-resolution tests.
    (data_dir / "archive" / "milestones" / "PT-A.md").write_text(
        MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                               status="done", target_tag="null", ga="false"),
        encoding="utf-8",
    )
    (data_dir / "archive" / "majors" / "PT-V0.md").write_text(
        MAJOR_TMPL.format(id="PT-V0", status="done", target_ship="2026-01-01"), encoding="utf-8"
    )
    (data_dir / "archive" / "issues" / "PT-9.md").write_text(
        ISSUE_TMPL.format(id="PT-9", title="A long-done issue", status="done", milestone="null"),
        encoding="utf-8",
    )
    return data_dir


class FindRecordPathResolutionOrderTests(unittest.TestCase):
    def test_resolves_a_live_issue(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.find_record_path(data_dir, "PT-1"), data_dir / "issues" / "PT-1.md")

    def test_resolves_an_archived_issue(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.find_record_path(data_dir, "PT-9"), data_dir / "archive" / "issues" / "PT-9.md")

    def test_resolves_a_live_milestone(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.find_record_path(data_dir, "PT-1.0"), data_dir / "milestones" / "PT-1.0.md")

    def test_resolves_an_archived_milestone(self):
        data_dir = make_repo(self)
        self.assertEqual(
            cairn.find_record_path(data_dir, "PT-A"), data_dir / "archive" / "milestones" / "PT-A.md"
        )

    def test_resolves_a_live_major(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.find_record_path(data_dir, "PT-V1"), data_dir / "majors" / "PT-V1.md")

    def test_resolves_an_archived_major(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.find_record_path(data_dir, "PT-V0"), data_dir / "archive" / "majors" / "PT-V0.md")

    def test_unknown_id_resolves_to_none(self):
        data_dir = make_repo(self)
        self.assertIsNone(cairn.find_record_path(data_dir, "PT-9999"))

    def test_a_live_issue_shadows_a_same_named_archived_milestone_per_the_documented_order(self):
        # Pathological but pins the ORDER explicitly: issues/ ->
        # archive/issues/ -> milestones/ -> archive/milestones/ -> majors/
        # -> archive/majors/ (PT-52: the legacy bare "archive" leg dropped
        # from _RECORD_SEARCH_SUBDIRS). Real ids never collide across
        # schemas in practice, but the resolution order is a real contract
        # worth pinning directly rather than only trusting it holds by
        # construction.
        data_dir = make_repo(self)
        (data_dir / "issues" / "PT-A.md").write_text(
            ISSUE_TMPL.format(id="PT-A", title="Collides with archived milestone PT-A", status="todo",
                               milestone="null"),
            encoding="utf-8",
        )
        self.assertEqual(cairn.find_record_path(data_dir, "PT-A"), data_dir / "issues" / "PT-A.md")


class FindIssuePathUnaffectedTests(unittest.TestCase):
    """PT-3's read-only guarantee is structural: find_issue_path must stay
    resolving issues/ and archive/issues/ only (PT-52: the legacy bare
    archive/ leg is gone), never widened to resolve milestones/majors --
    that's the boundary the HTTP write path can reach."""

    def test_find_issue_path_still_resolves_only_issues_and_archive_issues(self):
        data_dir = make_repo(self)
        self.assertEqual(cairn.find_issue_path(data_dir, "PT-1"), data_dir / "issues" / "PT-1.md")
        self.assertEqual(cairn.find_issue_path(data_dir, "PT-9"), data_dir / "archive" / "issues" / "PT-9.md")

    def test_find_issue_path_does_not_resolve_a_milestone_id(self):
        data_dir = make_repo(self)
        self.assertIsNone(cairn.find_issue_path(data_dir, "PT-1.0"))

    def test_find_issue_path_does_not_resolve_a_major_id(self):
        data_dir = make_repo(self)
        self.assertIsNone(cairn.find_issue_path(data_dir, "PT-V1"))


class CmdSetMilestoneTests(unittest.TestCase):
    def test_set_status_done_on_a_live_milestone(self):
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-1.0", "status=done", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "milestones" / "PT-1.0.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["status"], "done")

    def test_set_status_on_a_milestone_rejects_an_issue_only_status_value(self):
        # "backlog"/"in-review" are STATUSES (issue), not RECORD_STATUSES
        # (milestone/major) -- must be rejected, not silently written.
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-1.0", "status=backlog", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "milestones" / "PT-1.0.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["status"], "in-progress", "the file must be unchanged when validation fails")

    def test_set_an_issue_only_field_on_a_milestone_is_rejected(self):
        # "title" is issue-schema only -- MILESTONE_FIELD_ORDER has no such key.
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-1.0", "title=New name", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_set_on_an_archived_milestone_resolves_and_writes(self):
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-A", "status=cancelled", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter(
            (data_dir / "archive" / "milestones" / "PT-A.md").read_text(encoding="utf-8")
        )
        self.assertEqual(fm["status"], "cancelled")


class CmdSetMajorTests(unittest.TestCase):
    def test_set_status_and_target_ship_on_a_live_major_in_one_call(self):
        data_dir = make_repo(self)
        result = run_cairn(
            ["set", "PT-V1", "status=done", "target_ship=2026-12-01", "--data-dir", str(data_dir)]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "majors" / "PT-V1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["status"], "done")
        self.assertEqual(str(fm["target_ship"]), "2026-12-01")

    def test_set_status_on_a_major_rejects_an_issue_only_status_value(self):
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-V1", "status=in-review", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "majors" / "PT-V1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["status"], "in-progress")

    def test_set_a_milestone_only_field_on_a_major_is_rejected(self):
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-V1", "target_tag=v2.0.0", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


class CmdSetIssueRegressionTests(unittest.TestCase):
    """Regression guard: cmd_set's existing issue-schema behaviour must be
    completely unaffected by the find_issue_path -> find_record_path
    switch and the new per-schema validation branch."""

    def test_set_status_on_an_issue_still_works_unchanged(self):
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-1", "status=done", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["status"], "done")

    def test_set_status_on_an_issue_still_rejects_a_record_only_status_value(self):
        # "planned"/"paused" are RECORD_STATUSES (milestone/major), not
        # STATUSES (issue) -- an issue must still reject them.
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-1", "status=planned", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


class UnknownIdTests(unittest.TestCase):
    def test_set_on_a_completely_unknown_id_errors_and_writes_nothing(self):
        data_dir = make_repo(self)
        result = run_cairn(["set", "PT-9999", "status=done", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        # Loosely pinned (INTERFACE.md convention, and implementation-lead's
        # own caveat: no test pins the exact old "no such issue" wording) --
        # the id itself must appear in the error, not the exact phrasing.
        self.assertIn("PT-9999", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
