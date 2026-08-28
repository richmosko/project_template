"""PT-66 failing tests: `archived_milestone_paths(data_dir)`, a sibling
helper mirroring the existing `archived_issue_paths` (architect's non-
blocking PT-60-review suggestion, approved 666dcd3 -- full ask in
process/cairn/issues/PT-66.md). `check_repo`'s PT-59 target_tag
uniqueness lint should call `_dir_glob(data_dir / "milestones")` (live)
plus this new helper (archived) instead of inlining
`_dir_glob(data_dir / "archive" / "milestones")` itself -- single-
sourcing the archive/milestones/ spelling while keeping the per-file
live-vs-archived distinction the lint still needs (to run archive-only
checks like the done/cancelled-status requirement on the archived half
only -- see `milestone_paths`'s own docstring for why THAT helper,
which flattens both into one list, was deliberately not used here).

Two classes:

- `ArchivedMilestonePathsHelperTests` pins the new helper's own contract,
  same shape as `archived_issue_paths`: archive/milestones/ only, sorted,
  empty list (never a raise) when the directory doesn't exist at all.
- `CheckRepoUsesTheHelperTests` is a source-text guard (this suite's
  established shape) confirming `check_repo`'s own function body no
  longer inlines the `_dir_glob(data_dir / "archive" / "milestones")`
  pattern -- scoped to check_repo's body specifically (from `def
  check_repo(` to the next top-level `def`), since that inline call
  legitimately still lives inside `milestone_paths()` itself elsewhere in
  the file (the single-source implementation, not a duplicate to purge).

Behavior-unchanged regression fence: this refactor must not alter what
`check_repo` reports. `test_check_lint.py`'s
`CheckRepoTargetTagUniquenessTests` (already green, PT-59) is the fence
-- not duplicated here, just re-run alongside this file as part of the
same PT-66 acceptance pass.

Nothing under test exists yet: `cairn.archived_milestone_paths` doesn't
exist, and `check_repo`'s body still inlines the glob. Every test below
is expected to fail on an explicit `hasattr` assertion or a genuinely-
still-present source pattern, never an import error.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
CAIRN_PY = helpers.CAIRN_PY

INLINE_ARCHIVE_MILESTONES_GLOB_RE = re.compile(
    r"_dir_glob\(\s*data_dir\s*/\s*[\"']archive[\"']\s*/\s*[\"']milestones[\"']\s*\)"
)


def _make_empty_data_dir(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    return data_dir


def _write_milestone(data_dir: Path, sub: str, filename: str, milestone_id: str) -> None:
    (data_dir / sub).mkdir(parents=True, exist_ok=True)
    text = (
        f"---\nid: {milestone_id!r}\nname: X\nkind: product\nmajor: PT-V1\nstatus: done\n"
        "target_tag: null\nga: false\n---\n\nDoD.\n"
    )
    (data_dir / sub / filename).write_text(text, encoding="utf-8")


def _require_helper():
    assert hasattr(cairn, "archived_milestone_paths"), (
        "cairn.archived_milestone_paths does not exist yet -- PT-66's ruled sibling "
        "to archived_issue_paths is unimplemented"
    )


class ArchivedMilestonePathsHelperTests(unittest.TestCase):
    def test_helper_exists(self):
        self.assertTrue(
            hasattr(cairn, "archived_milestone_paths"),
            "cairn.archived_milestone_paths does not exist yet",
        )

    def test_returns_only_archive_milestones_files_not_live_ones(self):
        _require_helper()
        data_dir = _make_empty_data_dir(self)
        _write_milestone(data_dir, "milestones", "PT-1.0.md", "PT-1.0")
        _write_milestone(data_dir, "archive/milestones", "PT-9.0.md", "PT-9.0")
        result = cairn.archived_milestone_paths(data_dir)
        self.assertEqual([p.stem for p in result], ["PT-9.0"], result)

    def test_never_touches_archive_majors_or_archive_issues(self):
        # Non-recursive glob, same as archived_issue_paths -- a sibling
        # archive/majors/ or archive/issues/ file must not leak in.
        _require_helper()
        data_dir = _make_empty_data_dir(self)
        _write_milestone(data_dir, "archive/milestones", "PT-9.0.md", "PT-9.0")
        (data_dir / "archive" / "majors").mkdir(parents=True, exist_ok=True)
        (data_dir / "archive" / "majors" / "PT-V1.md").write_text(
            "---\nid: PT-V1\nstatus: done\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (data_dir / "archive" / "issues").mkdir(parents=True, exist_ok=True)
        (data_dir / "archive" / "issues" / "PT-2.md").write_text(
            "---\nid: PT-2\ntitle: X\nstatus: done\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        result = cairn.archived_milestone_paths(data_dir)
        self.assertEqual([p.stem for p in result], ["PT-9.0"], result)

    def test_returns_empty_list_never_raises_when_archive_milestones_dir_is_missing(self):
        # Mirrors archived_issue_paths's contract for a data_dir that has
        # an `archive/` directory but no `archive/milestones/` subdir at
        # all (make_tree()-shaped trees, the common test-fixture case) --
        # `_dir_glob`'s own `.exists()` guard, inherited for free if this
        # helper is implemented the same way archived_issue_paths is.
        _require_helper()
        data_dir = _make_empty_data_dir(self)
        self.assertFalse((data_dir / "archive" / "milestones").exists())
        try:
            result = cairn.archived_milestone_paths(data_dir)
        except Exception as e:  # noqa: BLE001
            self.fail(f"archived_milestone_paths must never raise on a missing archive/milestones/ dir, got {e!r}")
        self.assertEqual(result, [])

    def test_results_are_sorted(self):
        _require_helper()
        data_dir = _make_empty_data_dir(self)
        _write_milestone(data_dir, "archive/milestones", "PT-9.0.md", "PT-9.0")
        _write_milestone(data_dir, "archive/milestones", "PT-2.0.md", "PT-2.0")
        result = cairn.archived_milestone_paths(data_dir)
        self.assertEqual(result, sorted(result), result)


class CheckRepoUsesTheHelperTests(unittest.TestCase):
    def test_check_repo_body_no_longer_inlines_the_archive_milestones_glob(self):
        source = CAIRN_PY.read_text(encoding="utf-8")
        match = re.search(r"\ndef check_repo\(", source)
        self.assertIsNotNone(match, "could not find def check_repo( in cairn.py")
        start = match.start() + 1
        next_def = re.search(r"\ndef \w", source[start + 1:])
        end = start + 1 + next_def.start() if next_def else len(source)
        body = source[start:end]

        offender = INLINE_ARCHIVE_MILESTONES_GLOB_RE.search(body)
        self.assertIsNone(
            offender,
            f"check_repo's body still inlines {offender.group(0) if offender else None!r} -- "
            f"PT-66 wants it calling archived_milestone_paths(data_dir) instead, single-"
            f"sourcing the archive/milestones/ spelling (the SAME inline call is expected "
            f"to remain inside milestone_paths() elsewhere in the file -- that's the actual "
            f"single-source implementation, not a duplicate to remove)",
        )

    def test_check_repo_body_calls_the_new_helper(self):
        source = CAIRN_PY.read_text(encoding="utf-8")
        match = re.search(r"\ndef check_repo\(", source)
        self.assertIsNotNone(match)
        start = match.start() + 1
        next_def = re.search(r"\ndef \w", source[start + 1:])
        end = start + 1 + next_def.start() if next_def else len(source)
        body = source[start:end]
        self.assertIn(
            "archived_milestone_paths(", body,
            "check_repo's body never calls archived_milestone_paths(...) -- the refactor "
            "this issue asks for hasn't landed",
        )


if __name__ == "__main__":
    unittest.main()
