"""Tests for cairn.dump_frontmatter, cairn.apply_patch, cairn.append_comment.

The core guarantee under test: after a frontmatter-only rewrite, every byte
after the closing `---` fence is untouched -- byte-for-byte, not just
text-equal (CRLF, trailing whitespace, no-trailing-newline, and unicode
bodies are all exercised explicitly).
"""
from __future__ import annotations

import datetime
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def write_issue(path: Path, frontmatter_text: str, body: str) -> None:
    path.write_bytes(("---\n" + frontmatter_text + "---\n" + body).encode("utf-8"))


def tail_bytes_after_second_fence(raw: bytes) -> bytes:
    """Everything after the second `---\n` line, as raw bytes."""
    first = raw.index(b"---\n")
    second = raw.index(b"---\n", first + len(b"---\n"))
    return raw[second + len(b"---\n"):]


class DumpFrontmatterTests(unittest.TestCase):
    def test_canonical_key_order_regardless_of_input_order(self):
        fields = {
            "updated": "2026-08-19",
            "id": "PT-1",
            "title": "Thing",
            "created": "2026-08-14",
            "status": "todo",
            "milestone": None,
            "parent": None,
            "assignee": None,
            "labels": [],
            "priority": None,
            "pr": None,
        }
        text = cairn.dump_frontmatter(fields)
        lines = [line for line in text.splitlines() if ":" in line]
        keys_in_order = [line.split(":", 1)[0] for line in lines]
        self.assertEqual(keys_in_order, cairn.ISSUE_FIELD_ORDER)

    def test_fenced_by_triple_dash(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[])
        text = cairn.dump_frontmatter(fields)
        self.assertTrue(text.startswith("---\n"))
        self.assertTrue(text.endswith("---\n"))

    def test_numeric_looking_milestone_is_quoted(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[], milestone="1.0")
        text = cairn.dump_frontmatter(fields)
        self.assertIn('milestone: "1.0"', text)

    def test_null_is_bare_not_quoted(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[])
        text = cairn.dump_frontmatter(fields)
        self.assertIn("parent: null", text)
        self.assertNotIn('parent: "null"', text)

    def test_labels_render_as_flow_list(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=["auth", "api"])
        text = cairn.dump_frontmatter(fields)
        self.assertIn("labels: [auth, api]", text)

    def test_empty_labels_render_as_empty_flow_list(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[])
        text = cairn.dump_frontmatter(fields)
        self.assertIn("labels: []", text)

    def test_round_trip_through_parse_yaml_subset(self):
        fields = {
            "id": "PT-7",
            "title": "Round trip me",
            "status": "in-review",
            "milestone": "1.0",
            "parent": "PT-1",
            "assignee": "qa-engineer",
            "labels": ["auth", "api"],
            "priority": "P2",
            "pr": "https://example.com/pr/7",
            "created": "2026-08-01",
            "updated": "2026-08-19",
        }
        text = cairn.dump_frontmatter(fields)
        inner = text[len("---\n"):-len("---\n")]
        self.assertEqual(cairn.parse_yaml_subset(inner), fields)


class ApplyPatchByteBoundaryTests(unittest.TestCase):
    """Each test writes a deliberately awkward body, patches the frontmatter,
    and asserts the tail bytes after the closing fence are identical before
    and after -- not just string-equal, but byte-identical."""

    def _run(self, body: str) -> None:
        tmp = helpers.make_empty_tmp_dir(self)
        path = tmp / "PT-1.md"
        frontmatter_text = (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )
        write_issue(path, frontmatter_text, body)
        before_raw = path.read_bytes()
        before_tail = tail_bytes_after_second_fence(before_raw)

        cairn.apply_patch(path, {"status": "in-review"})

        after_raw = path.read_bytes()
        after_tail = tail_bytes_after_second_fence(after_raw)
        self.assertEqual(before_tail, after_tail, "body bytes changed across a frontmatter-only rewrite")

        # And the patch itself did take effect.
        new_frontmatter, _ = cairn.parse_frontmatter(after_raw.decode("utf-8"))
        self.assertEqual(new_frontmatter["status"], "in-review")

    def test_body_with_trailing_whitespace_on_lines(self):
        self._run("Some text.   \nAnother line.\t\n\nTrailing blank line above.\n")

    def test_body_with_no_trailing_newline(self):
        self._run("Body with no trailing newline at all")

    def test_body_with_unicode(self):
        self._run("Uses unicode: café, 日本語, emoji 🎉, em dash —.\n")

    def test_body_with_code_fence_and_delimiter_lookalike(self):
        self._run("## Comments\n\n### @a — 2026-01-01\n\n```\n### @fake — 2026-01-01\n```\n")

    def test_body_that_is_empty(self):
        self._run("")


class ApplyPatchBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "PT-1.md"
        frontmatter_text = (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )
        write_issue(self.path, frontmatter_text, "Body text.\n")

    def test_patch_bumps_updated_to_today_by_default(self):
        cairn.apply_patch(self.path, {"status": "in-review"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())

    def test_explicit_updated_in_patch_is_honored(self):
        cairn.apply_patch(self.path, {"status": "done", "updated": "2026-01-01"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["updated"], "2026-01-01")

    def test_patch_only_touches_given_fields(self):
        cairn.apply_patch(self.path, {"status": "in-review"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["title"], "Thing")
        self.assertEqual(frontmatter["id"], "PT-1")

    def test_patch_returns_new_frontmatter_dict(self):
        result = cairn.apply_patch(self.path, {"status": "in-review"})
        self.assertEqual(result["status"], "in-review")

    def test_no_stray_temp_files_left_behind(self):
        cairn.apply_patch(self.path, {"status": "in-review"})
        leftovers = [p for p in self.tmp.iterdir() if p.name != "PT-1.md"]
        self.assertEqual(leftovers, [], f"unexpected leftover files: {leftovers}")


class AppendCommentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "PT-1.md"

    def _frontmatter_text(self):
        return (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )

    def test_append_to_file_with_existing_comments_section(self):
        write_issue(self.path, self._frontmatter_text(), "Body.\n\n## Comments\n\n### @a — 2026-08-01\n\nFirst.\n")
        cairn.append_comment(self.path, "mosko", "Second comment.", comment_date="2026-08-19")
        _, body = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[1]["author"], "mosko")
        self.assertEqual(comments[1]["date"], "2026-08-19")
        self.assertEqual(comments[1]["body"].strip(), "Second comment.")

    def test_append_to_file_with_no_comments_section_yet(self):
        write_issue(self.path, self._frontmatter_text(), "Body with no comments section at all.\n")
        cairn.append_comment(self.path, "mosko", "First ever comment.", comment_date="2026-08-19")
        _, body = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertIn("## Comments", body)
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["author"], "mosko")

    def test_append_preserves_earlier_comment_bodies_byte_for_byte(self):
        original_body = "Body.\n\n## Comments\n\n### @a — 2026-08-01\n\nFirst, with trailing space.   \n"
        write_issue(self.path, self._frontmatter_text(), original_body)
        cairn.append_comment(self.path, "mosko", "Second.", comment_date="2026-08-19")
        raw = self.path.read_bytes()
        self.assertIn(b"First, with trailing space.   \n", raw)

    def test_append_bumps_updated(self):
        write_issue(self.path, self._frontmatter_text(), "Body.\n")
        cairn.append_comment(self.path, "mosko", "A comment.", comment_date="2026-08-19")
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())

    def test_append_defaults_date_to_today(self):
        write_issue(self.path, self._frontmatter_text(), "Body.\n")
        cairn.append_comment(self.path, "mosko", "A comment.")
        _, body = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        _, comments = cairn.split_comments(body)
        self.assertEqual(comments[-1]["date"], datetime.date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
