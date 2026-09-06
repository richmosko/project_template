"""`cairn check` budgets (PT-94 B6, D13, D14): comment-length and
issue-size WARNINGS (exit code unchanged), and the docs phrase lint on
process/TRACKER.md + process/WORKFLOW.md (an ERROR, fails the check)."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn
from test_check_lint import GOOD_FRONTMATTER, make_tree


def _issue(data_dir: Path, body: str) -> Path:
    p = data_dir / "issues" / "PT-1.md"
    p.write_text("---\n" + GOOD_FRONTMATTER.format(id="PT-1", status="todo", milestone="null", parent="null", priority="null") + "---\n\n" + body, encoding="utf-8")
    return p


class CommentAndSizeWarningTests(unittest.TestCase):
    def test_a_comment_over_forty_lines_warns_and_names_it(self):
        """Mutation: count lines of the whole file instead of the comment
        -> a 41-line comment in a short file still warns, but a 20-line
        comment in a long file warns too (second assertion)."""
        data_dir = make_tree(self)
        long_comment = "\n".join(f"line {i}" for i in range(41))
        _issue(data_dir, "Body.\n\n## Comments\n\n### @architect — 2026-09-05\n\n" + long_comment + "\n")
        warnings = cairn.check_budgets(data_dir)
        self.assertEqual(len(warnings), 1)
        self.assertIn("PT-1.md: comment by @architect (2026-09-05) is 41 lines", warnings[0])
        short = "\n".join(f"l{i}" for i in range(20))
        _issue(data_dir, "\n".join(f"body {i}" for i in range(60)) + "\n\n## Comments\n\n### @qa-engineer — 2026-09-05\n\n" + short + "\n")
        self.assertEqual(cairn.check_budgets(data_dir), [])

    def test_an_issue_file_over_the_size_cap_warns(self):
        """Mutation: compare against the cap in bytes of body only."""
        data_dir = make_tree(self)
        p = _issue(data_dir, "x" * (cairn.ISSUE_SIZE_CAP_BYTES + 10) + "\n")
        warnings = cairn.check_budgets(data_dir)
        self.assertEqual(len(warnings), 1)
        self.assertIn("PT-1.md is", warnings[0])
        self.assertIn("KB", warnings[0])
        self.assertTrue(p.exists())

    def test_archived_issues_are_not_budgeted(self):
        data_dir = make_tree(self)
        (data_dir / "archive" / "issues").mkdir(parents=True)
        (data_dir / "archive" / "issues" / "PT-9.md").write_text("---\nid: PT-9\n---\n\n" + "x" * (cairn.ISSUE_SIZE_CAP_BYTES + 10), encoding="utf-8")
        self.assertEqual(cairn.check_budgets(data_dir), [])

    def test_cli_prints_warnings_to_stderr_and_still_exits_zero(self):
        data_dir = make_tree(self)
        _issue(data_dir, "Body.\n\n## Comments\n\n### @architect — 2026-09-05\n\n" + "\n".join(["l"] * 41) + "\n")
        r = subprocess.run([str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("warning:", r.stderr)
        self.assertIn("ok", r.stdout)


class DocsPhraseLintTests(unittest.TestCase):
    """The docs live two levels above the data dir (process/cairn ->
    process/). A tree with no process/WORKFLOW.md skips the lint."""

    def _docs(self, data_dir: Path, tracker: str, workflow: str = "Fine.\n") -> None:
        (data_dir.parent / "TRACKER.md").write_text(tracker, encoding="utf-8")
        (data_dir.parent / "WORKFLOW.md").write_text(workflow, encoding="utf-8")

    def test_an_instruction_shaped_phrase_is_an_error(self):
        """Mutation: drop 'not just' from DOC_PHRASES -> no error."""
        data_dir = make_tree(self)
        self._docs(data_dir, "The lint checks shape, not just presence.\n")
        errors = cairn.check_docs(data_dir)
        self.assertEqual(len(errors), 1)
        self.assertIn("TRACKER.md:1", errors[0])
        self.assertIn("not just", errors[0])

    def test_quoted_and_code_span_mentions_are_exempt(self):
        """Mutation: drop the quote/code-span exemption -> two errors."""
        data_dir = make_tree(self)
        self._docs(data_dir, 'Reviewer notes ("say why", `state both`) never ship in docs.\n')
        self.assertEqual(cairn.check_docs(data_dir), [])

    def test_fenced_code_is_exempt(self):
        data_dir = make_tree(self)
        self._docs(data_dir, "```\nsay why here\n```\n")
        self.assertEqual(cairn.check_docs(data_dir), [])

    def test_a_paragraph_over_eight_sentences_is_a_warning_not_an_error(self):
        """Mutation: emit the paragraph warning as an error -> check fails."""
        data_dir = make_tree(self)
        self._docs(data_dir, " ".join(f"Sentence {i}." for i in range(9)) + "\n")
        self.assertEqual(cairn.check_docs(data_dir), [])
        warnings = cairn.check_budgets(data_dir)
        self.assertEqual(len(warnings), 1)
        self.assertIn("TRACKER.md:1: paragraph has 9 sentences", warnings[0])

    def test_missing_docs_skip_the_lint(self):
        data_dir = make_tree(self)
        self.assertEqual(cairn.check_docs(data_dir), [])

    def test_check_repo_includes_the_docs_errors(self):
        data_dir = make_tree(self)
        self._docs(data_dir, "Worth noting that this fails.\n")
        r = subprocess.run([str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("worth noting", r.stderr.lower())


if __name__ == "__main__":
    unittest.main()
