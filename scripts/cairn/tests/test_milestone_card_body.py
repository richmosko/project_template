"""PT-40 failing tests (§1 of the joint PT-40/43/44 ruling,
temp/arch-ruling-pt40-43-44-milestone-cards.md): milestone/major records
in `/api/board` gain a `body` field (the markdown after the closing
frontmatter fence) so the client can render a viewable card with no
second fetch/endpoint.

`build_board_payload`'s `_stamped` helper currently reads milestone/major
frontmatter via `_read_frontmatter_dict`, which calls `parse_frontmatter`
and DISCARDS the body half of its `(frontmatter, body)` return -- the data
is one line away, never plumbed through. Issues are deliberately UNCHANGED
(the issue drawer already has its own separate `body`-carrying fetch via
`build_issue_payload`/`parse_issue` -- this ruling is milestone/major-only,
no regression risk to the issue path since nothing here touches it).

Scoped to PT-40's slice of the joint ruling only (team-lead's split: "this
loop takes the viewable cards + status indicators half") -- NOT testing
§2's lane-header redesign, §3's progress-by-status counting, or §4's
release-state git-tag reading, all of which are PT-44/PT-43's separate
loops per the task list.

Nothing under test exists yet: every milestone/major record in the
payload has no `body` key at all. Every test below is expected to fail
until implementation-lead's PT-40 slice lands.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def minimal_repo(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    return data_dir


class MilestoneMajorBodyFieldTests(unittest.TestCase):
    def test_milestone_payload_carries_its_dod_body_text(self):
        data_dir = minimal_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            "---\nid: PT-1.0\nname: MVP\nkind: product\nmajor: PT-V1\nstatus: in-progress\n"
            "target_tag: v1.0.0\nga: true\n---\n\n"
            "**Definition of done:** the core loop works end to end.\n",
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-1.0")
        self.assertIn("Definition of done", milestone["body"])
        self.assertIn("core loop works end to end", milestone["body"])

    def test_major_payload_carries_its_body_text(self):
        data_dir = minimal_repo(self)
        (data_dir / "majors" / "PT-V1.md").write_text(
            "---\nid: PT-V1\nstatus: in-progress\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\n"
            "Founding major line.\n",
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        major = next(m for m in payload["majors"] if m["id"] == "PT-V1")
        self.assertIn("Founding major line", major["body"])

    def test_milestone_with_an_empty_body_carries_an_empty_string_not_a_missing_key(self):
        data_dir = minimal_repo(self)
        (data_dir / "milestones" / "PT-A.md").write_text(
            "---\nid: PT-A\nname: Bootstrap\nkind: process\nmajor: PT-V1\nstatus: done\n"
            "target_tag: null\nga: false\n---\n",
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-A")
        self.assertIn("body", milestone)
        self.assertEqual(milestone["body"].strip(), "")

    def test_archived_milestone_also_carries_its_body(self):
        data_dir = minimal_repo(self)
        (data_dir / "archive" / "milestones").mkdir(parents=True, exist_ok=True)
        (data_dir / "archive" / "milestones" / "PT-Z.md").write_text(
            "---\nid: PT-Z\nname: Old\nkind: process\nmajor: PT-V1\nstatus: done\n"
            "target_tag: null\nga: false\n---\n\nLong finished.\n",
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir, archived=True)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-Z")
        self.assertIn("Long finished", milestone["body"])

    def test_issue_payload_is_unaffected_regression_guard(self):
        # This ruling is milestone/major-only -- the issue path already
        # has its own separate body-carrying fetch (build_issue_payload)
        # and /api/board's issue records have never carried a body at all
        # (spec: "without comment bodies" applies more broadly -- issues
        # on the board are frontmatter-only by design). Must stay that way.
        data_dir = minimal_repo(self)
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: A live issue\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nSome body text.\n",
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        issue = next(i for i in payload["issues"] if i["id"] == "PT-1")
        self.assertNotIn("body", issue)


if __name__ == "__main__":
    unittest.main()
