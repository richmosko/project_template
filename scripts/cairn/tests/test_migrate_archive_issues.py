"""Tests for `cairn migrate archive-issues` -- the PT-50 one-shot,
filesystem-only migration that moves legacy flat `archive/*.md` issues
into `archive/issues/`, matching milestones/majors' existing
`archive/<schema>/` shape. Architect's ruling: process/cairn/issues/
PT-50.md (`### @architect -- 2026-08-24` comment), § 1/§ 3/§ 4/§ 6.

    cairn migrate archive-issues [--dry-run] [--data-dir DIR]

Unlike prefix-ids/lifecycle-status, this migration touches ZERO bytes
inside any file -- it is a pure rename (`_git_mv_or_rename`), so every
frontmatter field (including `id:`, which stays byte-identical -- only
the file's *location* moves) must survive untouched.

Order of operations (§ 1): (1) glob every `archive/*.md` (legacy, flat --
non-recursive, so archive/milestones/ and archive/majors/ are never
touched); (2) validate the WHOLE set before moving anything -- a
differing destination refuses the entire run; (3) move each file via
`_git_mv_or_rename` (or, for an already-fully-written destination, just
unlink the stale source -- `resumed: True`); (4) run the lint and report.

Invoked via subprocess against the bash shim, mirroring test_cli.py's own
convention ("closer to real agent usage than calling cairn.main() in-
process") -- same convention test_migrate_prefix_ids.py already
established. Each test builds its own minimal, isolated tmp tree with the
LEGACY flat layout -- deliberately distinct from the shared fixtures
(tests/fixtures/process/cairn/archive/PT-9.md is itself flat-layout and
gets migrated for real, in the same PR, per the hand-off report).

No `cairn migrate archive-issues` subcommand exists at all as of this
commit -- every test below is expected to fail (nonzero/parse-error exit
from an unrecognized subcommand, or files simply unchanged where a move
was expected) until implementation-lead's PT-50 slice lands.
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


ISSUE_TEMPLATE = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\n"
    "created: 2026-08-01\nupdated: 2026-08-01\n---\n\n{body}\n"
)


def make_legacy_repo(testcase, prefix: str = "PT") -> Path:
    """A self-contained pre-migration tree: issues/, archive/ (flat,
    legacy layout), milestones/, majors/ -- mirrors make_bare_repo's
    convention in test_migrate_prefix_ids.py. One live issue, two
    archived issues at the legacy flat path."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text(f"prefix: {prefix}\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")

    (data_dir / "majors" / f"{prefix}-V1.md").write_text(
        f"---\nid: {prefix}-V1\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (data_dir / "milestones" / f"{prefix}-1.0.md").write_text(
        f'---\nid: "{prefix}-1.0"\nname: MVP\nkind: product\nmajor: {prefix}-V1\nstatus: done\n'
        "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
        encoding="utf-8",
    )
    (data_dir / "issues" / f"{prefix}-1.md").write_text(
        ISSUE_TEMPLATE.format(id=f"{prefix}-1", title="Live", status="todo", milestone="null", body="Body."),
        encoding="utf-8",
    )
    (data_dir / "archive" / f"{prefix}-9.md").write_text(
        ISSUE_TEMPLATE.format(
            id=f"{prefix}-9", title="Long done", status="done", milestone=f'"{prefix}-1.0"', body="Body.",
        ),
        encoding="utf-8",
    )
    (data_dir / "archive" / f"{prefix}-10.md").write_text(
        ISSUE_TEMPLATE.format(id=f"{prefix}-10", title="Also done", status="done", milestone="null", body="Body."),
        encoding="utf-8",
    )
    return data_dir


def snapshot_tree(data_dir: Path) -> dict:
    """{relative_path: bytes} for every file under data_dir -- a byte-exact
    fingerprint, same convention as test_migrate_prefix_ids.py."""
    return {
        str(p.relative_to(data_dir)): p.read_bytes()
        for p in sorted(data_dir.rglob("*.md")) + sorted(data_dir.rglob("*.yml"))
    }


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_nothing_to_disk(self):
        data_dir = make_legacy_repo(self)
        before = snapshot_tree(data_dir)
        result = run_cairn(["migrate", "archive-issues", "--dry-run", "--data-dir", str(data_dir)])
        after = snapshot_tree(data_dir)
        self.assertEqual(before, after, "dry-run must not move or rewrite any file")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_does_not_create_archive_issues_dir(self):
        data_dir = make_legacy_repo(self)
        run_cairn(["migrate", "archive-issues", "--dry-run", "--data-dir", str(data_dir)])
        self.assertFalse((data_dir / "archive" / "issues").exists())

    def test_dry_run_output_describes_the_plan(self):
        data_dir = make_legacy_repo(self)
        result = run_cairn(["migrate", "archive-issues", "--dry-run", "--data-dir", str(data_dir)])
        output = result.stdout + result.stderr
        self.assertTrue(output.strip(), "a --dry-run with real work to preview must not be silent")
        self.assertIn("PT-9", output)
        self.assertIn("PT-10", output)

    def test_dry_run_on_an_already_migrated_repo_reports_nothing_to_do(self):
        data_dir = make_legacy_repo(self)
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])  # real run first
        result = run_cairn(["migrate", "archive-issues", "--dry-run", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do", (result.stdout + result.stderr).lower())


class MigrationCorrectnessTests(unittest.TestCase):
    def test_real_run_exits_zero(self):
        data_dir = make_legacy_repo(self)
        result = run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_files_moved_to_archive_issues(self):
        data_dir = make_legacy_repo(self)
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertFalse((data_dir / "archive" / "PT-9.md").exists())
        self.assertFalse((data_dir / "archive" / "PT-10.md").exists())
        self.assertTrue((data_dir / "archive" / "issues" / "PT-9.md").exists())
        self.assertTrue((data_dir / "archive" / "issues" / "PT-10.md").exists())

    def test_content_is_byte_identical_after_the_move(self):
        # Filesystem-only migration: unlike prefix-ids/lifecycle-status,
        # this one must not touch a single byte inside any file.
        data_dir = make_legacy_repo(self)
        before = (data_dir / "archive" / "PT-9.md").read_bytes()
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        after = (data_dir / "archive" / "issues" / "PT-9.md").read_bytes()
        self.assertEqual(before, after)

    def test_never_touches_archive_milestones_or_majors(self):
        data_dir = make_legacy_repo(self)
        (data_dir / "archive" / "milestones").mkdir(parents=True)
        (data_dir / "archive" / "milestones" / "PT-A.md").write_text(
            "---\nid: PT-A\nname: Bootstrap\nkind: process\nmajor: PT-V1\nstatus: done\n"
            "target_tag: null\nga: false\n---\n\nDoD.\n",
            encoding="utf-8",
        )
        before = (data_dir / "archive" / "milestones" / "PT-A.md").read_bytes()
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-A.md").exists())
        self.assertEqual(before, (data_dir / "archive" / "milestones" / "PT-A.md").read_bytes())

    def test_repo_is_lint_clean_after_migration(self):
        data_dir = make_legacy_repo(self)
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_migration_runs_despite_the_pre_migration_repo_failing_lint(self):
        # § 4's explicit point: migrate must NOT gate itself behind a
        # clean `cairn check` first -- the legacy layout IS what makes the
        # pre-migration tree fail lint (the very error this exists to fix).
        data_dir = make_legacy_repo(self)
        pre_errors = cairn.check_repo(data_dir)
        self.assertTrue(pre_errors, "test sanity: the pre-migration tree must fail lint (legacy archive/*.md)")
        result = run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_empty_archive_dir_is_a_zero_error_no_op(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        result = run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do", (result.stdout + result.stderr).lower())


class IdempotencyTests(unittest.TestCase):
    def test_second_run_on_an_already_migrated_repo_is_a_no_op(self):
        data_dir = make_legacy_repo(self)
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        after_first = snapshot_tree(data_dir)

        result = run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        after_second = snapshot_tree(data_dir)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(after_first, after_second, "a second run on an already-migrated repo must change nothing")

    def test_resumed_when_destination_already_exists_byte_identical(self):
        # Simulates a crash between the atomic write to the new path and
        # the unlink of the old one: both old and new exist, byte-identical.
        data_dir = make_legacy_repo(self)
        (data_dir / "archive" / "issues").mkdir(parents=True)
        content = (data_dir / "archive" / "PT-9.md").read_bytes()
        (data_dir / "archive" / "issues" / "PT-9.md").write_bytes(content)

        result = run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((data_dir / "archive" / "PT-9.md").exists(), "the stale duplicate source must be unlinked")
        self.assertTrue((data_dir / "archive" / "issues" / "PT-9.md").exists())
        self.assertIn("resuming", (result.stdout + result.stderr).lower())


class DifferingDestinationRefusalTests(unittest.TestCase):
    def test_differing_destination_refuses_the_entire_run(self):
        data_dir = make_legacy_repo(self)
        (data_dir / "archive" / "issues").mkdir(parents=True)
        # A human put a genuinely DIFFERENT file at the destination -- a
        # rename can never produce this on its own.
        (data_dir / "archive" / "issues" / "PT-9.md").write_text(
            "---\nid: PT-9\ntitle: Some other content entirely\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2020-01-01\nupdated: 2020-01-01\n---\n\nDifferent.\n",
            encoding="utf-8",
        )
        result = run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PT-9", result.stdout + result.stderr)

    def test_differing_destination_moves_nothing_not_even_unrelated_files(self):
        # All-or-nothing: PT-10 (no conflict) must NOT be moved either,
        # even though only PT-9 has a conflicting destination.
        data_dir = make_legacy_repo(self)
        (data_dir / "archive" / "issues").mkdir(parents=True)
        (data_dir / "archive" / "issues" / "PT-9.md").write_text(
            "---\nid: PT-9\ntitle: Conflicting\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2020-01-01\nupdated: 2020-01-01\n---\n\nDifferent.\n",
            encoding="utf-8",
        )
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        self.assertTrue((data_dir / "archive" / "PT-9.md").exists(), "PT-9 (the conflict) must not be touched")
        self.assertTrue((data_dir / "archive" / "PT-10.md").exists(), "PT-10 (no conflict) must also not be moved")
        self.assertFalse((data_dir / "archive" / "issues" / "PT-10.md").exists())


class LegacyLayoutFixtureBehaviorTests(unittest.TestCase):
    """§ 6 (b): a repo carrying a legacy flat archive/*.md issue -- these
    pin that, absent the migration, the four archived-issue-aware read
    sites still see it correctly (both layouts accepted during the
    transition, per § 4). Built via make_legacy_repo (this file's own
    self-contained fixture), not the shared tests/fixtures/process/cairn
    tree -- that tree is itself migrated to archive/issues/ in this same
    PR (see the hand-off report), so it can no longer stand in for "a
    repo that hasn't migrated yet"."""

    def test_a_next_id_allocation_skips_a_legacy_archived_id(self):
        data_dir = make_legacy_repo(self)  # archive/PT-9.md, archive/PT-10.md, issues/PT-1.md
        self.assertTrue((data_dir / "archive" / "PT-9.md").exists(), "test sanity: fixture is still legacy-layout")
        path = cairn.allocate_and_create_issue(
            data_dir,
            {
                "title": "New", "status": "backlog", "milestone": None, "parent": None,
                "assignee": None, "labels": [], "priority": None, "pr": None,
            },
        )
        self.assertEqual(path.name, "PT-11.md", "must not re-allocate PT-9/PT-10, held by legacy-archived issues")

    def test_b_check_repo_resolves_refs_against_a_legacy_archived_issue(self):
        data_dir = make_legacy_repo(self)
        (data_dir / "issues" / "PT-2.md").write_text(
            ISSUE_TEMPLATE.format(id="PT-2", title="Blocks on archived", status="todo", milestone="null", body="Body."),
            encoding="utf-8",
        )
        fm, body = cairn.parse_frontmatter((data_dir / "issues" / "PT-2.md").read_text(encoding="utf-8"))
        fm = dict(fm)
        fm["parent"] = "PT-9"  # PT-9 lives ONLY at the legacy archive/PT-9.md path
        (data_dir / "issues" / "PT-2.md").write_text(cairn.dump_frontmatter(fm) + body, encoding="utf-8")
        errors = cairn.check_repo(data_dir)
        self.assertFalse(
            any("PT-2" in e and "dangling parent" in e for e in errors),
            f"a legacy-archived issue must still resolve as a valid parent ref: {errors}",
        )

    def test_c_legacy_archived_issue_renders_under_archived_true(self):
        data_dir = make_legacy_repo(self)
        payload = cairn.build_board_payload(data_dir, archived=True)
        ids = {issue["id"] for issue in payload["issues"]}
        self.assertIn("PT-9", ids)
        archived_flags = {issue["id"]: issue["archived"] for issue in payload["issues"]}
        self.assertTrue(archived_flags["PT-9"])

    def test_d_etag_changes_when_a_legacy_archived_file_changes(self):
        import time

        data_dir = make_legacy_repo(self)
        before = cairn.compute_etag(data_dir, archived=True)
        time.sleep(0.01)  # ensure a distinct mtime_ns on fast filesystems
        p = data_dir / "archive" / "PT-9.md"
        p.write_text(p.read_text(encoding="utf-8") + "\nedited.\n", encoding="utf-8")
        after = cairn.compute_etag(data_dir, archived=True)
        self.assertNotEqual(before, after)


class CheckLegacyLayoutErrorTests(unittest.TestCase):
    def test_check_errors_on_legacy_layout_with_the_migrate_command_in_the_message(self):
        data_dir = make_legacy_repo(self)
        errors = cairn.check_repo(data_dir)
        matching = [e for e in errors if "scripts/cairn/cairn migrate archive-issues --dry-run" in e]
        self.assertEqual(len(matching), 1, f"expected exactly one legacy-layout error, got: {errors}")
        self.assertIn("2", matching[0], "the error must carry the count of legacy files (2 in this fixture)")

    def test_check_is_clean_on_that_axis_once_migrated(self):
        data_dir = make_legacy_repo(self)
        run_cairn(["migrate", "archive-issues", "--data-dir", str(data_dir)])
        errors = cairn.check_repo(data_dir)
        self.assertFalse(
            any("archive-issues" in e for e in errors),
            f"the legacy-layout error must not survive a completed migration: {errors}",
        )

    def test_check_is_clean_when_no_archive_at_all(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        errors = cairn.check_repo(data_dir)
        self.assertFalse(any("archive-issues" in e for e in errors), errors)


class WriteTargetTests(unittest.TestCase):
    """§ 6: both write selectors land in archive/issues/, never bare
    archive/, even though reads still accept the legacy layout too."""

    def _repo_with_done_issue(self, testcase) -> Path:
        tmp = helpers.make_empty_tmp_dir(testcase)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2020-01-01\nupdated: 2020-01-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        return data_dir

    def test_done_before_selector_writes_to_archive_issues(self):
        data_dir = self._repo_with_done_issue(self)
        result = run_cairn(["archive", "--done-before", "2026-01-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "issues" / "PT-1.md").exists())
        self.assertFalse((data_dir / "archive" / "PT-1.md").exists())

    def test_milestone_selector_writes_its_issues_to_archive_issues(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            '---\nid: "PT-1.0"\nname: MVP\nkind: product\nmajor: PT-V1\nstatus: done\n'
            "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
            encoding="utf-8",
        )
        (data_dir / "majors" / "PT-V1.md").write_text(
            "---\nid: PT-V1\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-1.md").write_text(
            '---\nid: PT-1\ntitle: Done\nstatus: done\nmilestone: "PT-1.0"\nparent: null\n'
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = run_cairn(["archive", "--milestone", "PT-1.0", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "issues" / "PT-1.md").exists())
        self.assertFalse((data_dir / "archive" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "milestones" / "PT-1.0.md").exists())


if __name__ == "__main__":
    unittest.main()
