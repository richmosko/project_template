"""PT-44 failing tests (§4 of the joint PT-40/43/44 ruling,
temp/arch-ruling-pt40-43-44-milestone-cards.md): each milestone record on
`/api/board` gains a `released` field -- `true` / `false` / `null` -- read
from the repo's git tags, server-side, once per payload build.

Rules pinned here:
- `null` when `target_tag` is null (definition milestones make no claim),
  OR when git is unavailable / this isn't a repo at all.
- `false` when `target_tag` is set but no matching tag exists (not yet
  released).
- `true` when `target_tag` matches a real tag in the repo (`git -C
  <data_dir's repo> for-each-ref --format=%(refname:short) refs/tags`).
- Failure posture: git missing / not a repo => ALL milestones read
  `released: null`, plus exactly one stderr line -- never crash (the
  `_git_mv_or_rename` precedent).
- One producer: the server ships the boolean predicate per milestone, not
  the raw tag list (a client re-deriving "is this tag present" from a
  shipped tag list would be the duplicated-expression class).
- NOT folded into the ETag (ruling's own stated tradeoff -- staleness
  until the next unrelated file change is accepted, not tested here since
  it's explicitly a non-goal, not a bug).

Nothing under test exists yet: no milestone record carries a `released`
key at all. Every test below is expected to fail until implementation-
lead's PT-44 slice lands.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


MILESTONE_TMPL = (
    "---\nid: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
    "target_tag: {target_tag}\nga: {ga}\n---\n\nDoD.\n"
)
MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"


def _run_git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"


def make_git_repo(testcase) -> Path:
    """A fresh git repo (init'd, one commit so tags have something to
    point at) with a `process/cairn` data dir inside it, matching real
    project layout -- `git -C <data_dir>` discovers the repo by walking
    up from there, same as it would in a real checkout."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    _run_git(tmp, "init", "-q")
    _run_git(tmp, "config", "user.email", "test@example.com")
    _run_git(tmp, "config", "user.name", "Test")
    data_dir = tmp / "process" / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")
    _run_git(tmp, "add", ".")
    _run_git(tmp, "commit", "-q", "-m", "initial")
    (data_dir / "majors" / "PT-V1.md").write_text(MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8")
    return data_dir


def make_non_git_repo(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    return data_dir


class ReleasedFieldTests(unittest.TestCase):
    def test_a_milestone_whose_target_tag_matches_a_real_git_tag_is_released_true(self):
        data_dir = make_git_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="done", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        _run_git(data_dir, "tag", "v1.0.0")
        payload = cairn.build_board_payload(data_dir)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-1.0")
        self.assertIs(milestone["released"], True)

    def test_a_milestone_whose_target_tag_has_no_matching_git_tag_is_released_false(self):
        data_dir = make_git_repo(self)
        (data_dir / "milestones" / "PT-1.1.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.1", name="Next", kind="product", major="PT-V1",
                                   status="in-progress", target_tag="v1.1.0", ga="false"),
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-1.1")
        self.assertIs(milestone["released"], False)

    def test_a_milestone_with_a_null_target_tag_is_released_null(self):
        data_dir = make_git_repo(self)
        (data_dir / "milestones" / "PT-A.md").write_text(
            MILESTONE_TMPL.format(id="PT-A", name="Bootstrap", kind="process", major="PT-V1",
                                   status="done", target_tag="null", ga="false"),
            encoding="utf-8",
        )
        payload = cairn.build_board_payload(data_dir)
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-A")
        self.assertIsNone(milestone["released"])

    def test_every_milestone_is_released_null_when_not_a_git_repo_and_never_raises(self):
        data_dir = make_non_git_repo(self)
        (data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                                   status="done", target_tag="v1.0.0", ga="true"),
            encoding="utf-8",
        )
        try:
            payload = cairn.build_board_payload(data_dir)
        except Exception as e:  # noqa: BLE001
            self.fail(f"build_board_payload must never raise when git is unavailable/not a repo, got {e!r}")
        milestone = next(m for m in payload["milestones"] if m["id"] == "PT-1.0")
        self.assertIsNone(milestone["released"])

    def test_majors_are_unaffected_regression_guard(self):
        # `released` is a MILESTONE-only field -- majors have no target_tag
        # at all (the field doesn't exist on that schema), so they must
        # never carry a released key.
        data_dir = make_git_repo(self)
        payload = cairn.build_board_payload(data_dir)
        major = next(m for m in payload["majors"] if m["id"] == "PT-V1")
        self.assertNotIn("released", major)


if __name__ == "__main__":
    unittest.main()
