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
        "---\nid: V1\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
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


def read_fm(testcase, path: Path) -> dict:
    """parse_frontmatter with an existence assertion first -- gives a clean
    assertion failure ("expected file at this path") instead of a raw
    FileNotFoundError traceback when the migrated file doesn't exist yet
    (i.e. every one of these tests, until implementation-lead's slice lands)."""
    testcase.assertTrue(path.exists(), f"expected the migrated file at {path}")
    fm, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
    return fm


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

    def test_archived_issues_milestone_ref_is_also_rewritten(self):
        # QA gap, added at Validate time (c2c896f): my original reds never
        # exercised archive/ at all -- implementation-lead found this
        # dogfooding the migration against this repo's own real tracker
        # data (an archived issue with a bare milestone: ref). check_repo's
        # known_ids/parsed_issues loop reads BOTH issues/ and archive/
        # identically, so an archived issue left un-rewritten would dangle
        # the moment its milestone file is renamed -- a repo with any
        # archived history could then never reach a clean post-migration
        # state. This test is the regression guard that gap was missing.
        data_dir = make_bare_repo(self)
        # PT-39 (§3 item 2): an archived issue's milestone must resolve to
        # a done/cancelled status, or check_repo's new hand-`git mv`-bypass
        # guard flags it -- "A" (done) is used here rather than "1.0"
        # (in-progress in this fixture) so this test keeps pinning ONLY
        # the prefix-rewrite behaviour it's named for, not accidentally
        # tripping an unrelated lint rule that postdates it.
        #
        # PT-50: fixture built at the NEW archive/issues/ layout (not the
        # legacy flat archive/) for the same reason -- the legacy-layout
        # lint error is a separate, deliberately-pinned concern (see
        # test_migrate_archive_issues.py), not this test's.
        (data_dir / "archive" / "issues").mkdir(parents=True)
        (data_dir / "archive" / "issues" / "PT-9.md").write_text(
            "---\nid: PT-9\ntitle: Long done\nstatus: done\nmilestone: A\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "archive" / "issues" / "PT-9.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["milestone"], "PT-A")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_archived_issue_with_null_milestone_survives_untouched(self):
        data_dir = make_bare_repo(self)
        (data_dir / "archive" / "PT-9.md").write_text(
            "---\nid: PT-9\ntitle: Long done, never milestoned\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        fm, _ = cairn.parse_frontmatter((data_dir / "archive" / "PT-9.md").read_text(encoding="utf-8"))
        self.assertIsNone(fm["milestone"])

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
        # The airtightness argument survives the addendum's id->filename
        # correction unchanged (A.2: "For each *.md whose filename stem
        # does not start with <P>-") -- it's the hyphen that makes a bare
        # FILENAME that happens to START WITH the prefix's letters
        # unmistakable for an already-prefixed one. A milestone literally
        # named "PTX.md" (no hyphen) must still be recognized as UNMIGRATED
        # and renamed to "PT-PTX.md", not skipped because its stem merely
        # starts with "PT".
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
    """THE mandatory red, per the architect's addendum (4ac505e, § A.2/A.3
    -- CORRECTING the original finalization's id-keyed resume predicate,
    which cannot survive an interruption: migrating one majors/milestones
    file is two observable actions (an atomic content-write to the NEW
    filename, then an unlink of the OLD one), and an id-based check can't
    tell those apart. The corrected predicate is FILENAME-keyed: "the
    old-named file is still present" stays true exactly until that file's
    work is finished. A milestone file's `id:` and `major:` are rewritten
    together in ONE atomic write (never two), so "new file exists with the
    right id but a stale major:" is NOT a reachable crash state under the
    corrected algorithm -- my original fixture for this class assumed
    exactly that unreachable state and has been rebuilt to match A.2.

    Each test below constructs a DIRECT, hand-built simulation of a valid
    crash point (not by killing a running process, which isn't reliably
    reproducible) and asserts (a) `cairn check` fails loudly on the partial
    state (A.3's "not all-or-nothing, and deliberately so" -- partial must
    never lint clean) and (b) re-running migrate completes the job and
    leaves the repo lint-clean.
    """

    def _base_repo(self, testcase) -> Path:
        tmp = helpers.make_empty_tmp_dir(testcase)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        return data_dir

    def _write_major(self, data_dir, filename, major_id):
        (data_dir / "majors" / filename).write_text(
            f"---\nid: {major_id}\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
            encoding="utf-8",
        )

    def _write_milestone(self, data_dir, filename, milestone_id, major):
        (data_dir / "milestones" / filename).write_text(
            f'---\nid: "{milestone_id}"\nname: MVP\nkind: product\nmajor: {major}\nstatus: in-progress\n'
            "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
            encoding="utf-8",
        )

    def _write_issue(self, data_dir, filename, issue_id, milestone):
        (data_dir / "issues" / filename).write_text(
            f'---\nid: {issue_id}\ntitle: Thing\nstatus: todo\nmilestone: "{milestone}"\nparent: null\n'
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )

    # ---- crash point 1: mid-file in phase 1 -- both old and new filenames
    # present simultaneously (crash after the atomic write, before the
    # unlink). A.2 step 5: the new file is complete and must not be
    # rewritten, only the stale old one unlinked. ----

    def test_old_and_new_filename_coexisting_starts_lint_dirty(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "V1.md", "V1")  # never touched
        self._write_major(data_dir, "PT-V1.md", "PT-V1")  # write succeeded, unlink didn't
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "test sanity: two majors/id V1-and-PT-V1 coexisting must not lint clean")

    def test_rerun_unlinks_the_stale_old_file_without_rewriting_the_complete_new_one(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "V1.md", "V1")
        self._write_major(data_dir, "PT-V1.md", "PT-V1")
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((data_dir / "majors" / "V1.md").exists(), "the stale old-named file must be unlinked")
        self.assertTrue((data_dir / "majors" / "PT-V1.md").exists())
        fm, _ = cairn.parse_frontmatter((data_dir / "majors" / "PT-V1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["id"], "PT-V1")

    # ---- crash point 2: phase 1 partially done across files -- one
    # majors/milestones file fully migrated, another not started at all. ----

    def test_partial_phase_1_across_files_starts_lint_dirty(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "PT-V1.md", "PT-V1")  # major: done
        self._write_milestone(data_dir, "1.0.md", "1.0", major="V1")  # milestone: not started
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "test sanity: an untouched bare milestone must fail lint even if the major is already done")

    def test_rerun_finishes_the_untouched_milestone_and_rewrites_its_major_ref_atomically(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "PT-V1.md", "PT-V1")
        self._write_milestone(data_dir, "1.0.md", "1.0", major="V1")
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_ms = data_dir / "milestones" / "PT-1.0.md"
        self.assertTrue(new_ms.exists())
        fm, _ = cairn.parse_frontmatter(new_ms.read_text(encoding="utf-8"))
        self.assertEqual(fm["id"], "PT-1.0")
        self.assertEqual(fm["major"], "PT-V1", "id: and major: are rewritten together in the same atomic write")
        self.assertEqual(cairn.check_repo(data_dir), [])

    # ---- crash point 3: phase 1 fully complete, phase 2 (issues) not
    # started -- the transition point between the two phases. ----

    def test_phase_1_complete_phase_2_not_started_starts_lint_dirty(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "PT-V1.md", "PT-V1")
        self._write_milestone(data_dir, "PT-1.0.md", "PT-1.0", major="PT-V1")
        self._write_issue(data_dir, "PT-1.md", "PT-1", milestone="1.0")  # ref still bare
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "test sanity: a bare milestone: ref must dangle once the milestone id is prefixed-only")

    def test_rerun_finishes_phase_2_when_phase_1_was_already_complete(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "PT-V1.md", "PT-V1")
        self._write_milestone(data_dir, "PT-1.0.md", "PT-1.0", major="PT-V1")
        self._write_issue(data_dir, "PT-1.md", "PT-1", milestone="1.0")
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        self.assertEqual(fm["milestone"], "PT-1.0")
        self.assertEqual(cairn.check_repo(data_dir), [])

    # ---- crash point 4: phase 2 partially done -- one issue's ref
    # rewritten, another not. ----

    def test_partial_phase_2_starts_lint_dirty(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "PT-V1.md", "PT-V1")
        self._write_milestone(data_dir, "PT-1.0.md", "PT-1.0", major="PT-V1")
        self._write_issue(data_dir, "PT-1.md", "PT-1", milestone="PT-1.0")  # done
        self._write_issue(data_dir, "PT-2.md", "PT-2", milestone="1.0")  # not done
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors, "test sanity: PT-2's still-bare ref must dangle")

    def test_rerun_finishes_the_remaining_issue_and_leaves_the_already_done_one_untouched(self):
        data_dir = self._base_repo(self)
        self._write_major(data_dir, "PT-V1.md", "PT-V1")
        self._write_milestone(data_dir, "PT-1.0.md", "PT-1.0", major="PT-V1")
        self._write_issue(data_dir, "PT-1.md", "PT-1", milestone="PT-1.0")
        self._write_issue(data_dir, "PT-2.md", "PT-2", milestone="1.0")
        result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm1, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-1.md").read_text(encoding="utf-8"))
        fm2, _ = cairn.parse_frontmatter((data_dir / "issues" / "PT-2.md").read_text(encoding="utf-8"))
        self.assertEqual(fm1["milestone"], "PT-1.0", "already-migrated ref must be unchanged, idempotent by construction")
        self.assertEqual(fm2["milestone"], "PT-1.0", "the remaining bare ref must now be fixed")
        self.assertEqual(cairn.check_repo(data_dir), [])

    def test_order_between_majors_and_milestones_is_not_pinned(self):
        # Architect's explicit ruling: the major: rewrite is a pure string
        # transform that never READS the major file, so there is no
        # dependency to sequence. This test proves the property by
        # constructing the two plausible orderings' RESULT states (major
        # done first vs milestone done first, everything else untouched)
        # and confirming migrate reaches the identical clean end-state from
        # either -- not by inspecting any internal processing order.
        for order in ("major-first", "milestone-first"):
            with self.subTest(order=order):
                data_dir = self._base_repo(self)
                if order == "major-first":
                    self._write_major(data_dir, "PT-V1.md", "PT-V1")
                    self._write_milestone(data_dir, "1.0.md", "1.0", major="V1")
                else:
                    self._write_major(data_dir, "V1.md", "V1")
                    self._write_milestone(data_dir, "PT-1.0.md", "PT-1.0", major="PT-V1")
                result = run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(cairn.check_repo(data_dir), [])


class TargetTagPreservationTests(unittest.TestCase):
    """Architect's addendum § A.1 (mandatory): target_tag is a GIT TAG
    NAME, not a cairn id -- it must NOT be touched by the migration, which
    is scoped to exactly three fields (id:/major:/milestone:). A
    "consistency" pass that prefixed it would break the release process,
    which reads that field verbatim to know what to tag."""

    def test_target_tag_is_byte_identical_across_migration(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        fm = read_fm(self, data_dir / "milestones" / "PT-1.0.md")
        self.assertEqual(fm["target_tag"], "v1.0.0", "target_tag must never be prefixed -- it names a git tag, not a cairn id")

    def test_ga_kind_status_are_also_untouched_by_migration(self):
        # Belt-and-suspenders on the "exactly three fields" scope limit --
        # every OTHER field on the migrated milestone must survive as-is too.
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        fm = read_fm(self, data_dir / "milestones" / "PT-1.0.md")
        self.assertEqual(fm["kind"], "product")
        self.assertEqual(fm["status"], "in-progress")
        self.assertEqual(fm["ga"], True)

    def test_null_target_tag_stays_null(self):
        data_dir = make_bare_repo(self)
        run_cairn(["migrate", "prefix-ids", "--data-dir", str(data_dir)])
        fm = read_fm(self, data_dir / "milestones" / "PT-A.md")
        self.assertIsNone(fm["target_tag"])


class ExitCodeTests(unittest.TestCase):
    def test_missing_config_yml_is_a_hard_error_nothing_written(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors" / "V1.md").write_text(
            "---\nid: V1\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
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
