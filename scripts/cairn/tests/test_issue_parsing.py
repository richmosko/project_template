"""Tests for cairn.parse_frontmatter, cairn.split_comments, cairn.parse_issue.

Uses both the checked-in fixtures (fixtures/process/cairn/issues/PT-1.md,
which is built specifically to hit the comment-delimiter trap cases the
spec calls out) and the spec's own worked example (PT-14, copied verbatim)
as a direct cross-check against the document of record.
"""
from __future__ import annotations

import unittest

import helpers  # noqa: F401

import cairn


# The exact example from process/TRACKER.md's "Issue file -- complete example"
# section, copied verbatim (including its two comments) as an independent
# cross-check against the spec text itself, separate from the PT-1 fixture.
SPEC_EXAMPLE_ISSUE = """---
id: PT-14
title: Google OAuth login
status: in-progress
milestone: "1.0"
parent: null
assignee: backend-lead
labels: [auth, api]
priority: P1
pr: null
created: 2026-08-14
updated: 2026-08-19
---

A returning user should be able to sign in with their Google account instead of
a password, so first-run friction drops and we stop storing credentials.

## Acceptance criteria

- [ ] `GET /auth/google` redirects to Google's consent screen with the correct scopes
- [ ] Callback exchanges the code and creates or links a local user record
- [ ] An existing email-password user signing in via Google is linked, not duplicated
- [ ] Failure path renders a recoverable error, never a stack trace

## Comments

### @qa-engineer — 2026-08-18

Failing acceptance test committed: `tests/auth/test_google.py::test_consent_redirect`.
Note the linking case needs a fixture with a pre-existing email user — added one.

### @architect — 2026-08-19

Reuse `lib/session/store.py` rather than introducing a second session abstraction.
The OAuth path should end in the same session object the password path produces.
"""


class ParseFrontmatterTests(unittest.TestCase):
    def test_extracts_fields_and_body(self):
        frontmatter, body = cairn.parse_frontmatter(SPEC_EXAMPLE_ISSUE)
        self.assertEqual(frontmatter["id"], "PT-14")
        self.assertEqual(frontmatter["title"], "Google OAuth login")
        self.assertEqual(frontmatter["status"], "in-progress")
        self.assertEqual(frontmatter["milestone"], "1.0")
        self.assertIsNone(frontmatter["parent"])
        self.assertEqual(frontmatter["assignee"], "backend-lead")
        self.assertEqual(frontmatter["labels"], ["auth", "api"])
        self.assertEqual(frontmatter["priority"], "P1")
        self.assertIsNone(frontmatter["pr"])
        self.assertEqual(frontmatter["created"], "2026-08-14")
        self.assertEqual(frontmatter["updated"], "2026-08-19")
        self.assertTrue(body.startswith("\nA returning user"))

    def test_body_is_byte_exact_after_closing_fence(self):
        frontmatter, body = cairn.parse_frontmatter(SPEC_EXAMPLE_ISSUE)
        expected_body = SPEC_EXAMPLE_ISSUE.split("---\n", 2)[2]
        self.assertEqual(body, expected_body)

    def test_missing_opening_fence_raises(self):
        with self.assertRaises(cairn.FrontmatterError):
            cairn.parse_frontmatter("id: PT-1\ntitle: x\n---\nbody\n")

    def test_missing_closing_fence_raises(self):
        with self.assertRaises(cairn.FrontmatterError):
            cairn.parse_frontmatter("---\nid: PT-1\ntitle: x\nbody with no closing fence\n")

    def test_empty_file_raises(self):
        with self.assertRaises(cairn.FrontmatterError):
            cairn.parse_frontmatter("")


class SplitCommentsTests(unittest.TestCase):
    def setUp(self):
        _, self.spec_body = cairn.parse_frontmatter(SPEC_EXAMPLE_ISSUE)
        pt1_text = (helpers.FIXTURE_DATA_DIR / "issues" / "PT-1.md").read_text(encoding="utf-8")
        _, self.pt1_body = cairn.parse_frontmatter(pt1_text)

    def test_spec_example_has_two_comments_in_order(self):
        _, comments = cairn.split_comments(self.spec_body)
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0]["author"], "qa-engineer")
        self.assertEqual(comments[0]["date"], "2026-08-18")
        self.assertIn("Failing acceptance test committed", comments[0]["body"])
        self.assertEqual(comments[1]["author"], "architect")
        self.assertEqual(comments[1]["date"], "2026-08-19")
        self.assertIn("lib/session/store.py", comments[1]["body"])

    def test_pre_comments_text_excludes_comment_log(self):
        pre, _ = cairn.split_comments(self.spec_body)
        self.assertIn("A returning user should be able to sign in", pre)
        self.assertIn("Acceptance criteria", pre)
        self.assertNotIn("## Comments", pre)
        self.assertNotIn("qa-engineer", pre)

    def test_no_comments_heading_yields_empty_comment_list(self):
        # issues/PT-3.md is a plain sub-issue with no ## Comments section at all.
        pt3_text = (helpers.FIXTURE_DATA_DIR / "issues" / "PT-3.md").read_text(encoding="utf-8")
        _, body = cairn.parse_frontmatter(pt3_text)
        pre, comments = cairn.split_comments(body)
        self.assertEqual(comments, [])
        self.assertEqual(pre, body)

    def test_comment_at_eof_with_no_trailing_newline(self):
        # issues/PT-4.md's last comment body runs to EOF with no trailing \n.
        pt4_text = (helpers.FIXTURE_DATA_DIR / "issues" / "PT-4.md").read_text(encoding="utf-8")
        self.assertFalse(pt4_text.endswith("\n"))
        _, body = cairn.parse_frontmatter(pt4_text)
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["author"], "mosko")
        self.assertEqual(comments[0]["date"], "2026-08-17")
        self.assertIn("Ship it behind a flag", comments[0]["body"])

    def test_fenced_delimiter_lookalike_is_not_a_boundary(self):
        # PT-1.md's first comment body contains, inside a ``` fence, a line
        # that matches COMMENT_DELIM_RE's shape exactly:
        #     ### @not-a-real-author — 2026-01-01
        # A naive whole-body regex scan finds it as a false third comment.
        # It must not be treated as a boundary.
        _, comments = cairn.split_comments(self.pt1_body)
        self.assertEqual(len(comments), 2, "fenced delimiter-lookalike was incorrectly split as a comment")
        authors = [c["author"] for c in comments]
        self.assertNotIn("not-a-real-author", authors)
        self.assertIn("not-a-real-author", comments[0]["body"], "the fenced line should still be in comment 1's body")

    def test_heading_without_em_dash_is_not_a_boundary(self):
        # PT-1.md's second comment body contains "### Not a delimiter" --
        # a real ### heading, but missing the required em dash + date, so
        # it must stay attached to the preceding comment's body.
        _, comments = cairn.split_comments(self.pt1_body)
        self.assertEqual(len(comments), 2)
        self.assertIn("Not a delimiter", comments[1]["body"])

    def test_hyphen_instead_of_em_dash_does_not_match(self):
        body = "## Comments\n\n### @someone - 2026-01-01\n\nBody text.\n"
        pre, comments = cairn.split_comments(body)
        self.assertEqual(comments, [])

    def test_uppercase_author_does_not_match(self):
        body = "## Comments\n\n### @Someone — 2026-01-01\n\nBody text.\n"
        _, comments = cairn.split_comments(body)
        self.assertEqual(comments, [])

    def test_comment_delim_regex_directly(self):
        self.assertRegex("### @qa-engineer — 2026-08-18", cairn.COMMENT_DELIM_RE)
        self.assertNotRegex("### @qa-engineer - 2026-08-18", cairn.COMMENT_DELIM_RE)
        self.assertNotRegex("### Not a delimiter", cairn.COMMENT_DELIM_RE)
        self.assertNotRegex("## Comments", cairn.COMMENT_DELIM_RE)


class ParseIssueTests(unittest.TestCase):
    def test_parse_issue_merges_frontmatter_description_and_comments(self):
        issue = cairn.parse_issue(SPEC_EXAMPLE_ISSUE)
        self.assertEqual(issue["id"], "PT-14")
        self.assertEqual(issue["milestone"], "1.0")
        self.assertIn("A returning user", issue["description"])
        self.assertNotIn("## Comments", issue["description"])
        self.assertEqual(len(issue["comments"]), 2)
        self.assertEqual(issue["comments"][0]["author"], "qa-engineer")

    def test_parse_issue_on_fixture_with_no_comments(self):
        pt3_text = (helpers.FIXTURE_DATA_DIR / "issues" / "PT-3.md").read_text(encoding="utf-8")
        issue = cairn.parse_issue(pt3_text)
        self.assertEqual(issue["id"], "PT-3")
        self.assertEqual(issue["parent"], "PT-1")
        self.assertEqual(issue["comments"], [])


if __name__ == "__main__":
    unittest.main()
