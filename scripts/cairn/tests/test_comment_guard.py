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


if __name__ == "__main__":
    unittest.main()
