"""Tests for `cairn migrate prefix-ids` -- the PT-28 one-shot migration that
prefixes bare major/milestone ids and retargets every `major:`/`milestone:`
reference. Architect's finalized ruling: process/cairn/issues/PT-28.md
(dbdbb7e), section 5.

    cairn migrate prefix-ids [--dry-run] [--data-dir DIR]

Order of operations (§5): (1) read+validate prefix, hard error if missing/
malformed; (2) for each unprefixed majors/milestones file, prefix `id:` and
rename the file; (3) rewrite `major:` in every milestone; (4) rewrite
`milestone:` in every issue, skipping null; (5) run the lint and report.

Invoked via subprocess against the bash shim, mirroring test_cli.py's own
convention ("closer to real agent usage than calling cairn.main() in-
process"). Each test builds its own minimal, isolated tmp tree (same
convention as test_check_lint.py/test_id_shape_prefix.py) with BARE ids --
this is deliberately the pre-migration shape, distinct from the shared
fixtures/checked-in tree (which implementation-lead must separately migrate
-- see the hand-off report).

No `cairn migrate` subcommand exists at all as of this commit -- every test
below is expected to fail (nonzero/parse-error exit from an unrecognized
subcommand, or files simply unchanged where a rewrite was expected) until
implementation-lead's PT-28 slice lands.
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


def make_bare_repo(testcase, prefix: str = "PT") -> Path:
    """A self-contained pre-migration tree: bare major/milestone ids
    (V1, "1.0", A), matching the shape every real repo carries before this
    migration runs -- three issues, one with milestone: null (must survive
    untouched), two referencing the version milestone."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text(f"prefix: {prefix}\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")

    (data_dir / "majors" / "V1.md").write_text(
        "---\nid: V1\nstatus: active\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (data_dir / "milestones" / "1.0.md").write_text(
        '---\nid: "1.0"\nname: MVP\nkind: product\nmajor: V1\nstatus: in-progress\n'
        "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
        encoding="utf-8",
    )
    (data_dir / "milestones" / "A.md").write_text(
        "---\nid: A\nname: Bootstrap\nkind: process\nmajor: V1\nstatus: done\n"
        "target_tag: null\nga: false\n---\n\nDoD.\n",
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-1.md").write_text(
        '---\nid: PT-1\ntitle: First\nstatus: todo\nmilestone: "1.0"\nparent: null\n'
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-2.md").write_text(
        '---\nid: PT-2\ntitle: Second\nstatus: todo\nmilestone: "1.0"\nparent: null\n'
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (data_dir / "issues" / "PT-3.md").write_text(
        "---\nid: PT-3\ntitle: Unmilestoned\nstatus: backlog\nmilestone: null\nparent: null\n"
        "assignee: null\nlabels: []\npriority: null\npr: null\n"
        "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return data_dir


def snapshot_tree(data_dir: Path) -> dict:
    """{relative_path: bytes} for every file under data_dir -- a byte-exact
    fingerprint used to prove --dry-run and a no-op re-run touch nothing."""
    return {
        str(p.relative_to(data_dir)): p.read_bytes()
        for p in sorted(data_dir.rglob("*.md")) + sorted(data_dir.rglob("*.yml"))
    }


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_nothing_to_disk(self):
        data_dir = make_bare_repo(self)
        before = snapshot_tree(data_dir)
        result = run_cairn(["migrate", "prefix-ids", "--dry-run", "--data-dir", str(data_dir)])
        after = snapshot_tree(data_dir)
        self.assertEqual(before, after, "dry-run must not modify or rename any file")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_does_not_rename_files(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--dry-run", "--data-dir", str(data_dir)])
        self.assertTrue((data_dir / "majors" / "V1.md").exists())
        self.assertFalse((data_dir / "majors" / "PT-V1.md").exists())

    def test_dry_run_output_is_non_empty_and_describes_the_plan(self):
        data_dir = make_bare_repo(self)
        result = run_cairn(["migrate", "prefix-ids", "--dry-run", "--data-dir", str(data_dir)])
        output = result.stdout + result.stderr
        self.assertTrue(output.strip(), "a --dry-run with real work to preview must not be silent")
        # Loosely pin content, not exact wording (INTERFACE.md convention):
        # the plan must be legible enough to mention what's changing.
        self.assertIn("V1", output)


class MigrationCorrectnessTests(unittest.TestCase):
    def test_real_run_exits_zero(self):
        data_dir = make_bare_repo(self)
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_major_file_renamed_and_id_rewritten(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertFalse((data_dir / "majors" / "V1.md").exists())
        new_path = data_dir / "majors" / "PT-V1.md"
        self.assertTrue(new_path.exists())
        fm, _ = cairn.parse_frontmatter(new_path.read_text(encoding="utf-8"))
        self.assertEqual(fm["id"], "PT-V1")

    def test_milestone_files_renamed_and_ids_rewritten(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertFalse((data_dir / "milestones" / "1.0.md").exists())
        self.assertFalse((data_dir / "milestones" / "A.md").exists())
        version_ms = data_dir / "milestones" / "PT-1.0.md"
        letter_ms = data_dir / "milestones" / "PT-A.md"
        self.assertTrue(version_ms.exists())
        self.assertTrue(letter_ms.exists())
        fm_v, _ = cairn.parse_frontmatter(version_ms.read_text(encoding="utf-8"))
        fm_l, _ = cairn.parse_frontmatter(letter_ms.read_text(encoding="utf-8"))
        self.assertEqual(fm_v["id"], "PT-1.0")
        self.assertEqual(fm_l["id"], "PT-A")

    def test_milestone_major_field_rewritten_to_prefixed_form(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        new_path = data_dir / "milestones" / "PT-1.0.md"
        self.assertTrue(new_path.exists(), "expected the migrated file at this path")
        fm, _ = cairn.parse_frontmatter(new_path.read_text(encoding="utf-8"))
        self.assertEqual(fm["major"], "PT-V1")

    def test_issue_milestone_field_rewritten_to_prefixed_form(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        fm1, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        fm2, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-2.md").read_text(encoding="utf-8"))
        self.assertEqual(fm1["milestone"], "PT-1.0")
        self.assertEqual(fm2["milestone"], "PT-1.0")

    def test_null_milestone_ref_is_left_null_not_corrupted(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        fm3, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-3.md").read_text(encoding="utf-8"))
        self.assertIsNone(fm3["milestone"])

    def test_filename_equals_id_invariant_holds_after_migration(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        for p in list((data_dir / "majors").glob("*.md")) + list((data_dir / "milestones").glob("*.md")):
            fm, _ = cairn.parse_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(str(fm["id"]), p.stem, f"{p}: id/filename mismatch after migration")

    def test_repo_is_lint_clean_after_migration(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)

    def test_migration_runs_despite_the_pre_migration_repo_failing_lint(self):
        # The ruling's explicit point: migrate must NOT gate itself behind
        # a clean `cairn check` first -- that would deadlock the exact
        # situation it exists to resolve. Confirm the starting tree is
        # failing lint (bare ids), then confirm migrate still succeeds.
        data_dir = make_bare_repo(self)
        pre_errors = cairn.check_repo(data_dir)
        self.assertTrue(pre_errors, "test sanity: the pre-migration tree must fail lint (bare ids)")

        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(cairn.check_repo(data_dir), [])


class IdempotencyTests(unittest.TestCase):
    def test_second_run_on_an_already_migrated_repo_is_a_no_op(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        after_first = snapshot_tree(data_dir)

        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        after_second = snapshot_tree(data_dir)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(after_first, after_second, "a second run on an already-migrated repo must change nothing")

    def test_idempotency_detection_is_hyphen_qualified_not_a_bare_startswith(self):
        # The ruling's own airtightness argument: id.startswith(prefix + "-")
        # is what makes a bare id that happens to START WITH the prefix's
        # letters unmistakable for an already-prefixed one. A milestone
        # literally named "PTX" (no hyphen) must still be recognized as
        # UNMIGRATED and get prefixed to "PT-PTX", not skipped because it
        # merely starts with "PT".
        data_dir = make_bare_repo(self)
        (data_dir / "milestones" / "PTX.md").write_text(
            '---\nid: PTX\nname: Edge Case\nkind: process\nmajor: V1\nstatus: planned\n'
            "target_tag: null\nga: false\n---\n\nDoD.\n",
            encoding="utf-8",
        )
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertFalse((data_dir / "milestones" / "PTX.md").exists(), "PTX must not be mistaken for already-prefixed")
        new_path = data_dir / "milestones" / "PT-PTX.md"
        self.assertTrue(new_path.exists(), "PTX must be migrated to PT-PTX")
        fm, _ = cairn.parse_frontmatter(new_path.read_text(encoding="utf-8"))
        self.assertEqual(fm["id"], "PT-PTX")


class InterruptedStateRecoveryTests(unittest.TestCase):
    """THE mandatory red per the architect's/team-lead's explicit ruling:
    idempotency detection is PER-FILE (id.startswith(prefix + "-")), which
    is the crash-recovery story -- an implementation that hoists this to
    one whole-repo up-front decision ("are all majors/milestones already
    prefixed? if so, nothing to do") would wrongly stop before finishing
    steps 3/4 (rewriting major:/milestone: refs) on a repo interrupted
    right after step 2 completed but before those ref-rewrites ran.

    Constructed directly (not by running migrate and killing it mid-way,
    which isn't reliably reproducible) -- this tree simulates EXACTLY that
    interruption point: majors/milestones are already renamed with
    prefixed ids, but the milestone's major: field and the issues'
    milestone: fields still hold the OLD bare values.
    """

    def _make_interrupted_repo(self, testcase) -> Path:
        tmp = helpers.make_empty_tmp_dir(testcase)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")

        # Step 2 already completed: files renamed, id: already prefixed.
        (data_dir / "majors" / "PT-V1.md").write_text(
            "---\nid: PT-V1\nstatus: active\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
            encoding="utf-8",
        )
        # Step 3 NOT completed: major: still says the bare "V1".
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            '---\nid: "PT-1.0"\nname: MVP\nkind: product\nmajor: V1\nstatus: in-progress\n'
            "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
            encoding="utf-8",
        )
        # Step 4 NOT completed: milestone: still says the bare "1.0".
        (data_dir / "issues" / "PT-1.md").write_text(
            '---\nid: PT-1\ntitle: First\nstatus: todo\nmilestone: "1.0"\nparent: null\n'
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        return data_dir

    def test_interrupted_repo_starts_with_dangling_refs(self):
        # Sanity check on the fixture itself: known_majors/known_milestones
        # are prefixed-only post-migration-of-files, so the still-bare
        # major:/milestone: refs must dangle -- confirms this fixture
        # actually reproduces the interrupted state, not an already-clean one.
        data_dir = self._make_interrupted_repo(self)
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "test sanity: the interrupted fixture must start lint-dirty")

    def test_rerun_completes_the_ref_rewrites_the_first_run_was_interrupted_before(self):
        data_dir = self._make_interrupted_repo(self)
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        # The files were already renamed (nothing to do at step 2) -- but
        # the STALE refs inside them must now be fixed.
        ms_fm, _ = cairn.parse_frontmatter((data_dir / "milestones" / "PT-1.0.md").read_text(encoding="utf-8"))
        issue_fm, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertEqual(ms_fm["major"], "PT-V1", "major: ref must be fixed even though the file itself needed no rename")
        self.assertEqual(issue_fm["milestone"], "PT-1.0", "milestone: ref must be fixed even though the file itself needed no rename")

    def test_rerun_leaves_the_repo_lint_clean(self):
        data_dir = self._make_interrupted_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], errors)


class ExitCodeTests(unittest.TestCase):
    def test_missing_config_yml_is_a_hard_error_nothing_written(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors" / "V1.md").write_text(
            "---\nid: V1\nstatus: active\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "majors" / "V1.md").exists(), "nothing may be written when the prefix can't be read")

    def test_malformed_prefix_is_a_hard_error_nothing_written(self):
        data_dir = make_bare_repo(self, prefix="pt")  # lowercase -- fails ^[A-Z]{2,5}$
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "majors" / "V1.md").exists(), "nothing may be written when the prefix is malformed")

    def test_dry_run_with_a_malformed_prefix_also_hard_errors(self):
        data_dir = make_bare_repo(self, prefix="pt")
        result = run_cairn(["migrate", "prefix-ids", "--dry-run", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
