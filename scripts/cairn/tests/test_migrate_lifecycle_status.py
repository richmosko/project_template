"""PASS 1 (engine/CLI) tests for PT-39 §1/§2: the unified milestone/major
status vocabulary and `cairn migrate lifecycle-status`. Architect's ruling:
temp/arch-ruling-pt39-lifecycle.md (landed as an @architect comment on
process/cairn/issues/PT-39.md). team-lead's sequencing: engine/CLI reviewed
first, lint+spec (§3) second -- test_check_lint_record_status.py is that
Pass 2 file; deliberately NOT in this one, so this file's tests are green
as soon as implementation-lead's Pass 1 lands, without waiting on Pass 2.

Vocabulary (§1): one enum for BOTH milestones and majors --
    planned | in-progress | paused | done | cancelled
`completed` -> `done`, `active` -> `in-progress`. A new constant
`RECORD_STATUSES`, separate from the issue-only `STATUSES` (milestones have
no `in-review`; majors have no `backlog`). Plus the two new field-order
constants implementation-lead's Pass-1 message names (needed by §6's
cmd_set, not exercised via the CLI here -- see test_set_records.py --
but pinned directly since they're part of the vocabulary/schema surface).

Migration (§2): `cairn migrate lifecycle-status [--dry-run]` -- PT-28's
named-migration precedent verbatim. Rewrites `status:` in majors/*.md and
milestones/*.md ONLY. Any value other than completed/active is left
untouched (a lint concern, not this command's). Value-keyed -> idempotent
by construction, no crash-recovery phase needed. Does NOT gate on
`cairn check` first (same reason as prefix-ids: it exists to fix a failing
lint) -- proven below against a lint failure UNRELATED to record status
(a malformed id shape), specifically so this Pass-1 test doesn't depend on
Pass 2's not-yet-existing status lint rule.

Nothing under test exists yet: `RECORD_STATUSES`/`MILESTONE_FIELD_ORDER`/
`MAJOR_FIELD_ORDER` are not defined in cairn.py, and `cairn migrate
lifecycle-status` is an unrecognized migration name. Every test below is
expected to fail until implementation-lead's Pass-1 slice lands
(AttributeError on the new constants, or nonzero/argparse-error from the CLI).
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


def make_repo(testcase, major_status: str = "active", milestone_statuses: dict | None = None) -> Path:
    """A self-contained PT-prefixed tree (post-PT-28 shape -- prefixing is
    orthogonal to this migration) with one major and, by default, two
    milestones: one `completed` (letter/process-kind), one `active`
    (version/product-kind) -- the two OLD vocabulary values this migration
    exists to rewrite, on both milestone kinds so neither the definition
    nor development shape is accidentally left uncovered.
    """
    if milestone_statuses is None:
        milestone_statuses = {"PT-A": "completed", "PT-1.0": "active"}
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")

    (data_dir / "majors" / "PT-V1.md").write_text(
        MAJOR_TMPL.format(id="PT-V1", status=major_status), encoding="utf-8"
    )
    if "PT-A" in milestone_statuses:
        (data_dir / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(
                id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                status=milestone_statuses["PT-A"], target_tag="null", ga="false",
            ),
            encoding="utf-8",
        )
    if "PT-1.0" in milestone_statuses:
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(
                id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                status=milestone_statuses["PT-1.0"], target_tag="v1.0.0", ga="true",
            ),
            encoding="utf-8",
        )
    return data_dir


def snapshot_tree(data_dir: Path) -> dict:
    return {
        str(p.relative_to(data_dir)): p.read_bytes()
        for p in sorted(data_dir.rglob("*.md")) + sorted(data_dir.rglob("*.yml"))
    }


def status_of(data_dir: Path, rel_path: str) -> str:
    fm, _ = cairn.parse_frontmatter((data_dir / rel_path).read_text(encoding="utf-8"))
    return fm["status"]


class RecordStatusesConstantTests(unittest.TestCase):
    """Reds for §1: the vocabulary itself, independent of the CLI/lint."""

    def test_record_statuses_is_the_five_value_unified_enum(self):
        self.assertEqual(
            set(cairn.RECORD_STATUSES),
            {"planned", "in-progress", "paused", "done", "cancelled"},
        )

    def test_record_statuses_is_not_an_alias_of_the_issue_only_statuses_set(self):
        # Milestones have no in-review; majors have no backlog -- these
        # must be two DIFFERENT sets, not the same object under two names
        # (which would silently let a milestone carry status: backlog).
        self.assertIsNot(cairn.RECORD_STATUSES, cairn.STATUSES)
        self.assertNotIn("backlog", cairn.RECORD_STATUSES)
        self.assertNotIn("in-review", cairn.RECORD_STATUSES)


class FieldOrderConstantTests(unittest.TestCase):
    """Reds for the per-schema field-order constants §6's cmd_set needs
    (implementation-lead's Pass-1 message): dump_frontmatter's canonical-
    order-then-extras contract (see _is_issue_shaped's docstring) generalizes
    to milestones/majors only once these exist. Pinned by NAME AND VALUE
    here (matching each schema's real frontmatter keys, per the fixture
    files under tests/fixtures/process/cairn/{milestones,majors}/) so a
    typo'd key silently dropped from dump_frontmatter's extras tail would
    show up here first, not as a mysteriously-reordered file in a later
    integration test.
    """

    def test_milestone_field_order_matches_the_milestone_schema(self):
        self.assertEqual(
            cairn.MILESTONE_FIELD_ORDER,
            ["id", "name", "kind", "major", "status", "target_tag", "ga"],
        )

    def test_major_field_order_matches_the_major_schema(self):
        self.assertEqual(
            cairn.MAJOR_FIELD_ORDER,
            ["id", "status", "owner", "target_ship", "health"],
        )

    def test_milestone_and_major_field_orders_are_distinct_objects(self):
        # Same hazard class as RECORD_STATUSES-vs-STATUSES above: two
        # different schemas must never accidentally share one list object
        # (a mutation meant for one schema's order would then leak into
        # the other's).
        self.assertIsNot(cairn.MILESTONE_FIELD_ORDER, cairn.MAJOR_FIELD_ORDER)
        self.assertIsNot(cairn.MILESTONE_FIELD_ORDER, cairn.ISSUE_FIELD_ORDER)
        self.assertIsNot(cairn.MAJOR_FIELD_ORDER, cairn.ISSUE_FIELD_ORDER)


class MigrateDryRunTests(unittest.TestCase):
    def test_dry_run_writes_nothing_to_disk(self):
        data_dir = make_repo(self)
        before = snapshot_tree(data_dir)
        result = run_cairn(["migrate", "lifecycle-status", "--dry-run", "--data-dir", str(data_dir)])
        after = snapshot_tree(data_dir)
        self.assertEqual(before, after, "dry-run must not modify any file")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_output_is_non_empty_and_describes_the_plan(self):
        data_dir = make_repo(self)
        result = run_cairn(["migrate", "lifecycle-status", "--dry-run", "--data-dir", str(data_dir)])
        output = result.stdout + result.stderr
        self.assertTrue(output.strip(), "a --dry-run with real work to preview must not be silent")
        self.assertIn("PT-A", output)


class MigrationCorrectnessTests(unittest.TestCase):
    def test_real_run_exits_zero(self):
        data_dir = make_repo(self)
        result = run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_completed_milestone_becomes_done(self):
        data_dir = make_repo(self, milestone_statuses={"PT-A": "completed"})
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(status_of(data_dir, "milestones/PT-A.md"), "done")

    def test_active_milestone_becomes_in_progress(self):
        data_dir = make_repo(self, milestone_statuses={"PT-1.0": "active"})
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(status_of(data_dir, "milestones/PT-1.0.md"), "in-progress")

    def test_active_major_becomes_in_progress(self):
        data_dir = make_repo(self, major_status="active", milestone_statuses={})
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(status_of(data_dir, "majors/PT-V1.md"), "in-progress")

    def test_any_other_status_value_is_left_untouched(self):
        # `paused` is already valid new-vocabulary -- must survive
        # byte-identical in its status field, not get coerced to
        # anything else just because it went through the migration.
        data_dir = make_repo(self, major_status="paused", milestone_statuses={"PT-A": "done"})
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(status_of(data_dir, "majors/PT-V1.md"), "paused")
        self.assertEqual(status_of(data_dir, "milestones/PT-A.md"), "done")

    def test_a_garbage_status_value_is_left_untouched_not_coerced(self):
        # The migration only knows two specific old->new mappings -- it
        # must not guess at anything else (that's the lint's job to flag,
        # a human's job to fix).
        data_dir = make_repo(self, major_status="in-progress", milestone_statuses={"PT-A": "wip"})
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(status_of(data_dir, "milestones/PT-A.md"), "wip")

    def test_migration_does_not_touch_issues_directory_at_all(self):
        data_dir = make_repo(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            '---\nid: PT-1\ntitle: First\nstatus: done\nmilestone: "PT-A"\nparent: null\n'
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        before_issue = (data_dir / "issues" / "PT-1.md").read_bytes()
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        after_issue = (data_dir / "issues" / "PT-1.md").read_bytes()
        self.assertEqual(before_issue, after_issue, "issues/*.md must be untouched by this migration")

    def test_migration_runs_despite_the_pre_migration_repo_failing_lint(self):
        # Same ruling as prefix-ids (§2): must not gate on `cairn check`
        # first -- that would deadlock the exact situation it exists to fix.
        # Deliberately fails lint for a reason that has NOTHING to do with
        # record status (an issue with a dangling milestone reference --
        # already-enforced, pre-existing check_repo behaviour), not by
        # relying on Pass 2's not-yet-existing status-vocabulary lint rule
        # -- this Pass-1 test must go green as soon as Pass 1 lands, without
        # waiting on Pass 2.
        data_dir = make_repo(self)
        (data_dir / "issues").mkdir(parents=True, exist_ok=True)
        (data_dir / "issues" / "PT-1.md").write_text(
            '---\nid: PT-1\ntitle: Dangling milestone ref\nstatus: todo\nmilestone: "PT-9.9"\n'
            "parent: null\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        pre_errors = cairn.check_repo(data_dir)
        self.assertTrue(pre_errors, "test sanity: the pre-migration tree must fail lint (dangling milestone ref)")
        result = run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class IdempotencyTests(unittest.TestCase):
    def test_second_run_on_an_already_migrated_repo_is_a_no_op(self):
        data_dir = make_repo(self)
        run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        after_first = snapshot_tree(data_dir)

        result = run_cairn(["migrate", "lifecycle-status", "--data-dir", str(data_dir)])
        after_second = snapshot_tree(data_dir)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(after_first, after_second, "a second run on an already-migrated repo must change nothing")


if __name__ == "__main__":
    unittest.main()
