"""Tests for cairn.check_repo (the `cairn check` lint) and its CLI wrapper.

Each broken-tree test builds its own minimal tmp tree rather than reusing
the shared fixtures, so each case isolates exactly one defect.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

GOOD_FRONTMATTER = (
    "id: {id}\ntitle: Thing\nstatus: {status}\nmilestone: {milestone}\nparent: {parent}\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\n"
    "created: 2026-08-01\nupdated: 2026-08-01\n"
)


def make_tree(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "issues").mkdir(parents=True)
    (data_dir / "archive").mkdir(parents=True)
    (data_dir / "milestones").mkdir(parents=True)
    (data_dir / "majors").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "milestones" / "1.0.md").write_text(
        '---\nid: "1.0"\nname: MVP\nkind: product\nmajor: V1\nstatus: planned\n'
        "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
        encoding="utf-8",
    )
    return data_dir


def write_issue(data_dir: Path, filename: str, **overrides) -> None:
    fields = dict(id="PT-1", status="todo", milestone="null", parent="null")
    fields.update(overrides)
    text = "---\n" + GOOD_FRONTMATTER.format(**fields) + "---\n\nBody.\n"
    (data_dir / "issues" / filename).write_text(text, encoding="utf-8")


class CheckRepoTests(unittest.TestCase):
    def test_clean_fixture_tree_has_no_errors(self):
        data_dir = helpers.make_tmp_data_dir(self)
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [])

    def test_id_filename_mismatch(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-5.md", id="PT-6")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-5" in e and "PT-6" in e for e in errors), errors)

    def test_dangling_parent(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", parent='"PT-999"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e and "parent" in e.lower() for e in errors), errors)

    def test_unknown_milestone(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", milestone='"9.9"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e and "milestone" in e.lower() for e in errors), errors)

    def test_bad_status(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", status="in-orbit")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e and "status" in e.lower() for e in errors), errors)

    def test_unsupported_yaml_is_reported_not_raised(self):
        data_dir = make_tree(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: &anchor null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)  # must not raise
        self.assertTrue(errors)
        self.assertTrue(any("PT-1" in e for e in errors), errors)

    def test_multiple_issues_each_reported(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", status="bogus")
        write_issue(data_dir, "PT-2.md", id="PT-2", milestone='"nope"')
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("PT-1" in e for e in errors))
        self.assertTrue(any("PT-2" in e for e in errors))


class CheckCliTests(unittest.TestCase):
    def test_clean_tree_exits_zero(self):
        data_dir = helpers.make_tmp_data_dir(self)
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_broken_tree_exits_nonzero_with_pointed_message(self):
        data_dir = make_tree(self)
        write_issue(data_dir, "PT-1.md", id="PT-1", status="bogus")
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "check", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined)


if __name__ == "__main__":
    unittest.main()
