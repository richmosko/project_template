"""Tests for the `cairn` CLI surface, invoked via the bash shim as a
subprocess -- this exercises scripts/cairn/cairn (the shim) and cairn.py's
argparse wiring together, closer to real agent usage than calling
cairn.main() in-process.
"""
from __future__ import annotations

import datetime
import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def run_cairn(args: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(helpers.CAIRN_BIN), *args],
        capture_output=True,
        text=True,
        input=input,
    )


class NewCommandTests(unittest.TestCase):
    def test_new_with_only_a_title_uses_defaults(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "A brand new issue", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        created = sorted((data_dir / "issues").glob("PT-*.md"))
        new_files = [p for p in created if p.name not in ("PT-1.md", "PT-3.md", "PT-4.md")]
        self.assertEqual(len(new_files), 1)
        path = new_files[0]

        frontmatter, _ = cairn.parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["title"], "A brand new issue")
        self.assertEqual(frontmatter["status"], cairn.DEFAULT_STATUS)
        self.assertIsNone(frontmatter["milestone"])
        self.assertIsNone(frontmatter["parent"])
        self.assertIsNone(frontmatter["assignee"])
        self.assertEqual(frontmatter["labels"], [])
        today = datetime.date.today().isoformat()
        self.assertEqual(frontmatter["created"], today)
        self.assertEqual(frontmatter["updated"], today)

    def test_new_with_all_flags(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(
            [
                "new",
                "Sub-issue of PT-1",
                "--milestone", "1.0",
                "--assignee", "backend-lead",
                "--status", "todo",
                "--parent", "PT-1",
                "--data-dir", str(data_dir),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new_files = [
            p for p in sorted((data_dir / "issues").glob("PT-*.md"))
            if p.name not in ("PT-1.md", "PT-3.md", "PT-4.md")
        ]
        self.assertEqual(len(new_files), 1)
        frontmatter, _ = cairn.parse_frontmatter(new_files[0].read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["milestone"], "1.0")
        self.assertEqual(frontmatter["assignee"], "backend-lead")
        self.assertEqual(frontmatter["status"], "todo")
        self.assertEqual(frontmatter["parent"], "PT-1")
        # milestone "1.0" must round-trip as a string on disk too.
        raw = new_files[0].read_text(encoding="utf-8")
        self.assertIn('milestone: "1.0"', raw)

    def test_new_prints_the_new_id(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["new", "Prints its id", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("PT-10", result.stdout)


class LsCommandTests(unittest.TestCase):
    def test_ls_lists_active_issues_one_line_each(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # PT-1, PT-3, PT-4 -- PT-9 is archived
        joined = "\n".join(lines)
        self.assertIn("PT-1", joined)
        self.assertIn("PT-3", joined)
        self.assertIn("PT-4", joined)
        self.assertNotIn("PT-9", joined)

    def test_ls_filters_by_status(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--status", "todo", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("PT-3", lines[0])

    def test_ls_filters_by_milestone(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--milestone", "1.0", "--data-dir", str(data_dir)])
        joined = result.stdout
        self.assertIn("PT-1", joined)
        self.assertIn("PT-3", joined)
        self.assertNotIn("PT-4", joined)  # PT-4's milestone is null

    def test_ls_filters_by_assignee(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["ls", "--assignee", "backend-lead", "--data-dir", str(data_dir)])
        joined = result.stdout
        self.assertIn("PT-1", joined)
        self.assertIn("PT-3", joined)
        self.assertNotIn("PT-4", joined)


class SetCommandTests(unittest.TestCase):
    def test_set_updates_fields_and_bumps_updated(self):
        data_dir = helpers.make_tmp_data_dir(self)
        path = data_dir / "issues" / "PT-1.md"
        before_raw = path.read_bytes()

        result = run_cairn(
            ["set", "PT-1", "status=in-review", "pr=https://example.com/pr/1", "--data-dir", str(data_dir)]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        after_raw = path.read_bytes()
        frontmatter, _ = cairn.parse_frontmatter(after_raw.decode("utf-8"))
        self.assertEqual(frontmatter["status"], "in-review")
        self.assertEqual(frontmatter["pr"], "https://example.com/pr/1")
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())

        # Tail = everything after the closing frontmatter fence. Not a
        # second `.split(b"---\n", 1)[1]` on top of that: PT-1's fixture
        # body contains no further literal "---\n" (only ``` fences and
        # ### headings), so that extra split raised IndexError on [1] for
        # every run of this test regardless of implementation correctness.
        before_tail = before_raw.split(b"---\n", 2)[2]
        after_tail = after_raw.split(b"---\n", 2)[2]
        self.assertEqual(before_tail, after_tail)

    def test_set_on_unknown_id_fails_loudly(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["set", "PT-999", "status=done", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PT-999", result.stdout + result.stderr)


class CommentCommandTests(unittest.TestCase):
    def test_comment_appends_from_stdin_with_correct_delimiter(self):
        data_dir = helpers.make_tmp_data_dir(self)
        path = data_dir / "issues" / "PT-1.md"

        result = run_cairn(
            ["comment", "PT-1", "--author", "qa-engineer", "--body", "-", "--data-dir", str(data_dir)],
            input="Looks good, ship it.\n",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        text = path.read_text(encoding="utf-8")
        _, body = cairn.parse_frontmatter(text)
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 3)  # PT-1 fixture already has 2
        self.assertEqual(comments[-1]["author"], "qa-engineer")
        self.assertEqual(comments[-1]["date"], datetime.date.today().isoformat())
        self.assertIn("Looks good, ship it.", comments[-1]["body"])


class ShowCommandTests(unittest.TestCase):
    def test_show_renders_issue_contents(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PT-1", result.stdout)
        self.assertIn("Google OAuth login", result.stdout)
        self.assertIn("qa-engineer", result.stdout)

    def test_show_renders_full_frontmatter_not_just_title(self):
        # `show` is meant to be a complete single-issue rendering an agent
        # can read without opening the file -- not just id/title/comments.
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["show", "PT-1", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("in-progress", result.stdout)  # status
        self.assertIn("1.0", result.stdout)  # milestone
        self.assertIn("backend-lead", result.stdout)  # assignee
        self.assertIn("auth", result.stdout)  # labels
        self.assertIn("P1", result.stdout)  # priority


class NonDefaultPrefixTests(unittest.TestCase):
    """The fixture tree hard-codes prefix: PT everywhere else in this file --
    exercise a distinct prefix end-to-end through the CLI to confirm it's
    actually config-driven and not accidentally hard-coded to "PT"."""

    def _tree(self, tmp_root: Path) -> Path:
        data_dir = tmp_root / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: ZZ\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        return data_dir

    def test_new_ls_set_honor_a_non_default_prefix(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        data_dir = self._tree(tmp_root)

        result = run_cairn(["new", "Prefix-honoring issue", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ZZ-1", result.stdout)
        self.assertTrue((data_dir / "issues" / "ZZ-1.md").exists())
        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())

        ls_result = run_cairn(["ls", "--data-dir", str(data_dir)])
        self.assertIn("ZZ-1", ls_result.stdout)

        set_result = run_cairn(["set", "ZZ-1", "status=todo", "--data-dir", str(data_dir)])
        self.assertEqual(set_result.returncode, 0, set_result.stdout + set_result.stderr)
        frontmatter, _ = cairn.parse_frontmatter((data_dir / "issues" / "ZZ-1.md").read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["status"], "todo")


class ArchiveCommandTests(unittest.TestCase):
    def _tree(self):
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-3.md").write_text(
            "---\nid: PT-3\ntitle: Recently done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-10\n---\n\nDone recently.\n",
            encoding="utf-8",
        )
        (data_dir / "issues" / "PT-4.md").write_text(
            "---\nid: PT-4\ntitle: Still open\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-01\n---\n\nNot done.\n",
            encoding="utf-8",
        )
        return data_dir

    def test_archive_moves_only_done_issues_before_cutoff(self):
        data_dir = self._tree()
        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-1.md").exists())

        self.assertTrue((data_dir / "issues" / "PT-3.md").exists(), "done but updated after cutoff should stay")
        self.assertTrue((data_dir / "issues" / "PT-4.md").exists(), "not done should never be archived")


class ArchiveGitMoveTests(unittest.TestCase):
    """The spec's CLI table is explicit: `cairn archive` is a "Bulk git mv",
    and later: "Archived issues remain in git, remain greppable". A plain
    filesystem move inside a git worktree does NOT preserve that on its
    own -- git only sees a delete + an untracked add until something stages
    it as a rename. This is the gap the (unrecoverable) test_cairn.py draft
    may have covered and mine didn't: verify the move is actually staged as
    a git rename, not just a filesystem move that happens to sit in a repo."""

    def test_archive_stages_a_git_rename_inside_a_repo(self):
        tmp_root = helpers.make_empty_tmp_dir(self)
        subprocess.run(["git", "init", "-q"], cwd=tmp_root, check=True)
        subprocess.run(["git", "config", "user.email", "qa@example.com"], cwd=tmp_root, check=True)
        subprocess.run(["git", "config", "user.name", "qa"], cwd=tmp_root, check=True)

        data_dir = helpers.copy_fixture_data_dir(tmp_root)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=tmp_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_root, check=True)

        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((data_dir / "issues" / "PT-1.md").exists())
        self.assertTrue((data_dir / "archive" / "PT-1.md").exists())

        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=tmp_root, capture_output=True, text=True, check=True
        ).stdout
        # A staged rename shows as "R  <old> -> <new>". A plain filesystem
        # move that git hasn't been told about shows as a deleted line and
        # a separate untracked ("??") line instead -- that's the failure
        # mode this test exists to catch.
        self.assertIn("R  ", status, f"archive did not stage a git rename; git status was:\n{status}")
        self.assertNotIn("??", status, f"archived file is untracked, not staged as a rename:\n{status}")

    def test_archive_falls_back_to_plain_move_outside_a_repo(self):
        # Not every data_dir lives inside a git worktree in every test setup
        # -- confirm archive still works (doesn't crash on a missing git)
        # when there's no repo to stage a rename into.
        data_dir = helpers.make_tmp_data_dir(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Old and done\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-01-01\nupdated: 2026-01-15\n---\n\nDone a while ago.\n",
            encoding="utf-8",
        )
        result = run_cairn(["archive", "--done-before", "2026-02-01", "--data-dir", str(data_dir)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((data_dir / "archive" / "PT-1.md").exists())


class ErrorHandlingTests(unittest.TestCase):
    def test_unknown_subcommand_fails_loudly(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = run_cairn(["bogus-command", "--data-dir", str(data_dir)])
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
