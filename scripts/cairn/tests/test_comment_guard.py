"""Foreign-hunk guard (PT-94 E15), two layers: `cairn comment` refuses to
append while the file carries someone else's uncommitted comment, and the
pre-commit hook (.githooks/pre-commit -> `cairn guard-commit`) refuses a
staged tracker file whose added comments come from more than one author."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

HOOKS_DIR = helpers.CAIRN_DIR.parent.parent / ".githooks"


def git(cwd: Path, *args: str, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


class GuardTestBase(unittest.TestCase):
    def setUp(self):
        self.root = helpers.make_empty_tmp_dir(self)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "core.hooksPath", str(HOOKS_DIR))
        (self.root / "process").mkdir()
        self.data_dir = helpers.copy_fixture_data_dir(self.root / "process")
        self.issue = self.data_dir / "issues" / "PT-1.md"
        self.issue.write_text(
            "---\nid: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\ncreated: 2026-09-01\nupdated: 2026-09-01\n---\n\nBody.\n",
            encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed")

    def comment(self, author: str, body: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(helpers.CAIRN_BIN), "comment", "PT-1", "--author", author, "--body", body, "--data-dir", str(self.data_dir), *extra],
                              capture_output=True, text=True, cwd=self.root)


class CommentRefusesForeignUncommittedTests(GuardTestBase):
    def test_own_uncommitted_comment_does_not_block_a_second_one(self):
        """Mutation: refuse on any uncommitted header -> the second append fails."""
        self.assertEqual(self.comment("architect", "ruling").returncode, 0)
        self.assertEqual(self.comment("architect", "addendum").returncode, 0)
        self.assertEqual(self.issue.read_text().count("### @architect"), 2)

    def test_foreign_uncommitted_comment_refuses_and_names_the_author(self):
        """Mutation: compare authors case-insensitively against '' -> passes."""
        self.assertEqual(self.comment("architect", "ruling").returncode, 0)
        r = self.comment("qa-engineer", "assertion")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("@architect", r.stderr)
        self.assertIn("uncommitted", r.stderr)
        self.assertEqual(self.issue.read_text().count("### @qa-engineer"), 0)

    def test_allow_foreign_overrides(self):
        self.assertEqual(self.comment("architect", "ruling").returncode, 0)
        self.assertEqual(self.comment("qa-engineer", "assertion", "--allow-foreign").returncode, 0)

    def test_foreign_authors_helper(self):
        self.assertEqual(self.comment("architect", "ruling").returncode, 0)
        self.assertEqual(cairn.uncommitted_comment_authors(self.issue), {"architect"})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "ruling")
        self.assertEqual(cairn.uncommitted_comment_authors(self.issue), set())

    def test_outside_a_git_repo_the_guard_is_a_no_op(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = helpers.copy_fixture_data_dir(tmp)
        p = data_dir / "issues" / "PT-1.md"
        p.write_text(self.issue.read_text(), encoding="utf-8")
        r = subprocess.run([str(helpers.CAIRN_BIN), "comment", "PT-1", "--author", "qa-engineer", "--body", "x", "--data-dir", str(data_dir)],
                           capture_output=True, text=True, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)


class PreCommitHookTests(GuardTestBase):
    def test_staged_comments_by_two_authors_block_the_commit(self):
        """Mutation: block on >= 1 author instead of > 1 -> the single-author
        test below fails; mutation: count authors across the whole file
        instead of the staged diff -> a second commit by the same author
        blocks once two authors exist in history (third test)."""
        self.comment("architect", "ruling", "--allow-foreign")
        self.comment("qa-engineer", "assertion", "--allow-foreign")
        r = git(self.root, "commit", "-q", "-m", "sweep", "--", str(self.issue), check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("architect", r.stderr)
        self.assertIn("qa-engineer", r.stderr)
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD").stdout.strip(), "1")

    def test_a_single_author_commit_passes(self):
        self.comment("architect", "ruling")
        r = git(self.root, "commit", "-q", "-m", "ruling", "--", str(self.issue), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_history_with_two_authors_does_not_block_a_new_single_author_commit(self):
        self.comment("architect", "ruling")
        git(self.root, "commit", "-q", "-m", "ruling", "--", str(self.issue))
        self.comment("qa-engineer", "assertion")
        git(self.root, "commit", "-q", "-m", "assertion", "--", str(self.issue))
        self.comment("architect", "verdict")
        r = git(self.root, "commit", "-q", "-m", "verdict", "--", str(self.issue), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_guard_commit_cli_reports_on_the_staged_diff(self):
        self.comment("architect", "ruling", "--allow-foreign")
        self.comment("qa-engineer", "assertion", "--allow-foreign")
        git(self.root, "add", "--", str(self.issue))
        r = subprocess.run([str(helpers.CAIRN_BIN), "guard-commit"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("PT-1.md", r.stderr)


# --------------------------------------------------------------------------
# PT-109 (architect's gate-1 brief, process/cairn/issues/PT-109.md): a real
# `cairn archive` move (issues/X.md -> archive/issues/X.md, via `git mv`)
# diffs as 100% added lines without rename detection, so every HISTORICAL
# comment author trips E15 -- 16 false refusals on the PT-0.12.1 close.
# Real git throughout: `git mv` stages an actual rename, never a synthetic
# name-status stand-in.
# --------------------------------------------------------------------------


class RenameAwareGuardCommitTests(GuardTestBase):
    def _archive_dest(self) -> Path:
        archive_dir = self.data_dir / "archive" / "issues"
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir / self.issue.name

    def _append_comment(self, path: Path, author: str, body: str) -> None:
        # Direct file write, not the `cairn comment` CLI -- the CLI's own
        # foreign-uncommitted-comment guard is a different layer
        # (CommentRefusesForeignUncommittedTests above) and irrelevant to
        # what `guard-commit` sees in the staged diff.
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n### @{author} — 2026-09-08\n\n{body}\n")

    def test_a_pure_rename_of_a_multi_author_issue_passes(self):
        """Mutation: drop the -M/R100-skip fix -> the guard sees the whole
        moved file as newly added and refuses on architect+qa-engineer's
        HISTORICAL (already-committed) comments -- exactly PT-0.12.1's 16
        false refusals."""
        self.comment("architect", "ruling")
        git(self.root, "commit", "-q", "-m", "ruling", "--", str(self.issue))
        self.comment("qa-engineer", "assertion")
        git(self.root, "commit", "-q", "-m", "assertion", "--", str(self.issue))

        dest = self._archive_dest()
        git(self.root, "mv", str(self.issue), str(dest))

        r = subprocess.run([str(helpers.CAIRN_BIN), "guard-commit"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"a pure rename must carry no new hunk -- {r.stdout!r} {r.stderr!r}")

    def test_a_partial_rename_with_one_newly_added_comment_passes(self):
        """The rename source has ONE historical author (architect); the
        move also appends a single NEW comment by a DIFFERENT author
        (qa-engineer). Diffed against the rename source, only
        qa-engineer's comment is genuinely added -- one author, passes.
        Mutation: diff the moved file against nothing (full-add) instead
        of the rename source -> both architect (stale) and qa-engineer
        (real) count as added, len==2, wrongly refused."""
        self.comment("architect", "ruling")
        git(self.root, "commit", "-q", "-m", "ruling", "--", str(self.issue))

        dest = self._archive_dest()
        git(self.root, "mv", str(self.issue), str(dest))
        self._append_comment(dest, "qa-engineer", "moved and re-triaged")
        git(self.root, "add", "--", str(dest))

        r = subprocess.run([str(helpers.CAIRN_BIN), "guard-commit"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(
            r.returncode, 0,
            f"one genuinely new comment on a partial rename must pass -- {r.stdout!r} {r.stderr!r}",
        )

    def test_a_partial_rename_with_two_newly_added_comments_by_different_authors_refuses(self):
        """Same construction as above, but TWO new comments by two
        different authors land in the same staged change -- the rename
        must not become a blanket bypass for a genuine multi-author
        violation. Mutation: skip every R<100 entry outright (not just
        diff it against its source) -> this wrongly passes too.

        Load-bearing per the ruling (PT-109.md @ 6831854, guard 3): the
        refusal must name EXACTLY the two genuinely new authors, not the
        historical one -- proving the fix narrowed the guard rather than
        disabling it. Mutation: diff the whole file instead of pairing
        against the rename source -> 'architect' (stale) appears in the
        message too."""
        self.comment("architect", "ruling")
        git(self.root, "commit", "-q", "-m", "ruling", "--", str(self.issue))

        dest = self._archive_dest()
        git(self.root, "mv", str(self.issue), str(dest))
        self._append_comment(dest, "qa-engineer", "moved and re-triaged")
        self._append_comment(dest, "seceng", "flagging for a security pass")
        git(self.root, "add", "--", str(dest))

        r = subprocess.run([str(helpers.CAIRN_BIN), "guard-commit"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, f"two new authors on a partial rename must still refuse -- {r.stdout!r} {r.stderr!r}")
        self.assertIn("qa-engineer", r.stderr)
        self.assertIn("seceng", r.stderr)
        self.assertNotIn(
            "architect", r.stderr,
            f"the refusal must name only the genuinely NEW authors, not the historical (unchanged) one -- {r.stderr!r}",
        )

    def test_ordinary_non_rename_modification_with_two_authors_still_refuses(self):
        """Ruling guard 4: regression control for the untouched (non-
        rename) path -- an ordinary same-path modification adding two
        authors must still refuse, exactly as PreCommitHookTests already
        covers. Restated here so PT-109's whole guard set lives in one
        place; not a new behaviour."""
        self.comment("architect", "ruling", "--allow-foreign")
        self.comment("qa-engineer", "assertion", "--allow-foreign")
        git(self.root, "add", "--", str(self.issue))
        r = subprocess.run([str(helpers.CAIRN_BIN), "guard-commit"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, f"{r.stdout!r} {r.stderr!r}")

    def test_a_staged_path_containing_a_space_is_still_evaluated(self):
        """Ruling guard 5: the only thing keeping the `-z` NUL-separated
        name-status parser honest. Mutation: split the name-status output
        on whitespace instead of NUL -- a path with a space breaks the
        field boundaries and the guard silently skips the file (goes
        blind) rather than refusing or erroring."""
        spaced_issue = self.data_dir / "issues" / "PT-1 spaced.md"
        spaced_issue.write_text(self.issue.read_text(encoding="utf-8"), encoding="utf-8")
        git(self.root, "add", "--", str(spaced_issue))
        git(self.root, "commit", "-q", "-m", "seed spaced issue")

        self._append_comment(spaced_issue, "architect", "ruling")
        self._append_comment(spaced_issue, "qa-engineer", "assertion")
        git(self.root, "add", "--", str(spaced_issue))

        r = subprocess.run([str(helpers.CAIRN_BIN), "guard-commit"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(
            r.returncode, 1,
            f"a spaced path must still be evaluated (refused here, two new authors), not silently skipped -- "
            f"{r.stdout!r} {r.stderr!r}",
        )
        self.assertIn("PT-1 spaced.md", r.stderr)


if __name__ == "__main__":
    unittest.main()
