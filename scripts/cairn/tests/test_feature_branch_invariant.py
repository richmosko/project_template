"""PT-82 gate-1 ruling (architect, process/cairn/issues/PT-82.md @
6316a9b, item (e)/(f)): AC5's invariant, enforced not advised --
`/finish-feature` and `/merge-pr` each fail loudly unless origin holds
exactly one `feature/<id>-*` branch, ZERO `worktree-*` branches, and
exactly one open PR for the issue. The worktree-branch check is the one
that matters (architect, verbatim): "a pushed worktree-* branch is what
would produce a second PR."

Drives the check script -- `scripts/cairn/check_feature_branch_
invariant.py`, NOT YET BUILT (implementation-lead's, per the ruling's
writers line) -- as a REAL subprocess against a BARE fixture git repo
standing in for `origin` (a real local bare repo, added as a remote by
file path; no network) plus a FAKE `gh` executable prepended onto PATH
that returns a controllable canned `gh pr list --json ...` response,
since a fixture remote has no real GitHub PRs to query.

Assumed CLI (the ruling fixes the CONTRACT -- one branch, zero
worktree branches, one open PR -- not this exact shape; flag to the
architect if implementation-lead's script diverges):

    check_feature_branch_invariant(repo_root: Path) -> dict
        {"ok": bool, "reason": str, "message": str}. Derives the issue
        id from `repo_root`'s CURRENT BRANCH (`feature/<id>-<slug>`),
        then checks origin (`git ls-remote --heads`) for exactly one
        `feature/<id>-*` branch and zero `worktree-*` branches, and
        (via `gh pr list --head <branch> --state open --json number`)
        exactly one open PR.
    main(argv) -> int -- argv[0] optional repo_root, same convention as
        check_dist_freshness.py's own `main`; prints result["message"];
        returns 0 if result["ok"] else 1.

Every fail-expected test also asserts the failure message names the
SPECIFIC violation (not just "the script exited non-zero") -- otherwise
a fail-expected test would pass trivially today for the wrong reason
(the script doesn't exist yet, so any invocation exits non-zero
regardless of what it would have checked)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Optional

# "pr" as a whole word only -- "project_template" (this repo's own path)
# contains "pr" as a substring, which would make a bare `"pr" in combined`
# check pass trivially even when the script doesn't exist at all (a
# FileNotFoundError message naming this repo's path already contains
# "pr" inside "project_template", for the wrong reason entirely).
_PR_WORD_RE = re.compile(r"\bprs?\b", re.IGNORECASE)

import helpers  # noqa: F401

SCRIPT_PATH = helpers.CAIRN_DIR / "check_feature_branch_invariant.py"


def _git(cwd: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _git_env() -> dict:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    return env


def make_bare_origin(testcase) -> Path:
    """A real, local bare git repo -- `origin`, added to the fixture
    clone by file path. No network anywhere in this file."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    bare = tmp / "origin.git"
    _git(tmp, "init", "--bare", "-q", str(bare))
    return bare


def make_feature_clone(testcase, bare_origin: Path, issue_id: str, slug: str = "test-slug") -> Path:
    """A clone of `bare_origin`, checked out on a real
    `feature/<issue_id>-<slug>` branch, pushed to origin -- the shape
    `/finish-feature`/`/merge-pr` run against."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    clone = tmp / "clone"
    env = _git_env()
    _git(tmp, "clone", "-q", str(bare_origin), str(clone), env=env)
    (clone / "README.md").write_text("placeholder\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "-q", "-m", "initial", env=env)
    _git(clone, "push", "-q", "-u", "origin", "HEAD:main", env=env)

    branch = f"feature/{issue_id}-{slug}"
    _git(clone, "checkout", "-q", "-b", branch, env=env)
    (clone / "work.txt").write_text("work\n", encoding="utf-8")
    _git(clone, "add", "-A", env=env)
    _git(clone, "commit", "-q", "-m", "work", env=env)
    _git(clone, "push", "-q", "-u", "origin", branch, env=env)
    return clone


def push_extra_branch(clone: Path, branch_name: str) -> None:
    """Pushes a new branch to origin, from the clone's current tip,
    without moving the clone's own checked-out branch."""
    env = _git_env()
    _git(clone, "push", "-q", "origin", f"HEAD:{branch_name}", env=env)


_FAKE_GH_TEMPLATE = """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
if len(args) >= 2 and args[0] == "pr" and args[1] == "list":
    count = int(os.environ.get("FAKE_GH_OPEN_PR_COUNT", "1"))
    head_ref = os.environ.get("FAKE_GH_HEAD_REF", "feature/PT-1-test-slug")
    prs = [{"number": 100 + i, "headRefName": head_ref} for i in range(count)]
    print(json.dumps(prs))
    sys.exit(0)
sys.stderr.write(f"fake gh: unhandled invocation {args!r}\\n")
sys.exit(1)
"""


def make_fake_gh_dir(testcase) -> Path:
    """A scratch dir containing an executable `gh` shim -- prepended
    onto PATH so the check script's own `gh pr list ...` calls resolve
    to this fake instead of the real GitHub CLI. Recognizes only
    `gh pr list ...`; the open-PR count and head ref it reports are
    read from FAKE_GH_OPEN_PR_COUNT / FAKE_GH_HEAD_REF at call time."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    gh_path = tmp / "gh"
    gh_path.write_text(_FAKE_GH_TEMPLATE, encoding="utf-8")
    gh_path.chmod(0o755)
    return tmp


def run_invariant_check(
    clone: Path, fake_gh_dir: Path, open_pr_count: int = 1, head_ref: Optional[str] = None,
    phase: Optional[str] = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{fake_gh_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_GH_OPEN_PR_COUNT"] = str(open_pr_count)
    if head_ref is not None:
        env["FAKE_GH_HEAD_REF"] = head_ref
    phase_args = ["--phase", phase] if phase else []
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *phase_args, str(clone)],
        cwd=str(clone), capture_output=True, text=True, env=env,
    )


class InvariantPassesOnTheCleanShapeTests(unittest.TestCase):
    """Positive control: exactly one feature/<id>-* branch, zero
    worktree-* branches, exactly one open PR -- must exit 0."""

    def test_passes_with_one_feature_branch_no_worktree_branch_one_open_pr(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=1, head_ref="feature/PT-1-test-slug")
        self.assertEqual(result.returncode, 0, f"expected the clean shape to pass -- got rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")


class SecondFeatureBranchFailsTests(unittest.TestCase):
    """Mutation target 1: a second feature/<id>-* branch for the SAME
    issue on origin must fail loudly, naming the duplication."""

    def test_a_second_feature_branch_for_the_same_issue_fails(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        push_extra_branch(clone, "feature/PT-1-a-second-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=1, head_ref="feature/PT-1-test-slug")
        self.assertNotEqual(result.returncode, 0, "a second feature/PT-1-* branch on origin must fail the check")
        combined = result.stdout + result.stderr
        self.assertIn("PT-1", combined, f"the failure must name the issue/branches involved -- got: {combined!r}")
        self.assertIn("branch", combined.lower(), f"the failure must be about the branch duplication, not some other reason -- got: {combined!r}")


class WorktreeBranchOnOriginFailsTests(unittest.TestCase):
    """Mutation target 2, THE ONE THAT MATTERS (architect, verbatim: "a
    pushed worktree-* branch is what would produce a second PR"): any
    worktree-* branch reaching origin must fail loudly, regardless of
    the feature/PT-1-* branch and PR both being otherwise clean."""

    def test_a_worktree_branch_on_origin_fails_even_though_everything_else_is_clean(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        push_extra_branch(clone, "worktree-some-teammate-session")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=1, head_ref="feature/PT-1-test-slug")
        self.assertNotEqual(result.returncode, 0, "a worktree-* branch reaching origin must fail the check")
        combined = result.stdout + result.stderr
        self.assertIn("worktree", combined.lower(), f"the failure must name the worktree-* branch specifically -- got: {combined!r}")


class OpenPrCountTests(unittest.TestCase):
    """Mutation target 3: zero open PRs and two open PRs both fail --
    'exactly one', not 'at least one'. No `--phase` flag is passed here,
    so this ALSO is the decisive "default is the strict predicate" case
    from PT-82.md @ 778300b's post-verdict delta 2 (architect): "Mutation
    for the last: make the default `pre-pr` -- the finish-phase test
    must go red." `test_zero_open_prs_fails` is exactly that finish-phase
    (zero-PRs) case, run with no phase flag -- a default that silently
    weakens to pre-pr's 'at most one' would wrongly pass zero PRs here."""

    def test_zero_open_prs_fails(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=0, head_ref="feature/PT-1-test-slug")
        self.assertNotEqual(result.returncode, 0, "zero open PRs must fail the check")
        combined = result.stdout + result.stderr
        self.assertRegex(combined, _PR_WORD_RE, f"the failure must be about the PR count -- got: {combined!r}")

    def test_two_open_prs_fails(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=2, head_ref="feature/PT-1-test-slug")
        self.assertNotEqual(result.returncode, 0, "two open PRs must fail the check")
        combined = result.stdout + result.stderr
        self.assertRegex(combined, _PR_WORD_RE, f"the failure must be about the PR count -- got: {combined!r}")


class PrePrPhaseTests(unittest.TestCase):
    """PT-82.md @ 778300b (architect, post-verdict delta 2): the
    `--phase pre-pr` variant is for sanity checks made BEFORE `gh pr
    create` runs -- 'at most one' open PR, not 'exactly one', so a
    re-run after the PR exists is not a false failure. The worktree-*
    clause stays strict in every phase (architect, verbatim: "it is the
    failure that matters and it is never relaxed")."""

    def test_pre_pr_phase_passes_with_zero_open_prs(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=0, head_ref="feature/PT-1-test-slug", phase="pre-pr")
        self.assertEqual(
            result.returncode, 0,
            f"--phase pre-pr with zero open PRs (before gh pr create) must pass -- "
            f"got rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_pre_pr_phase_passes_with_one_open_pr(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=1, head_ref="feature/PT-1-test-slug", phase="pre-pr")
        self.assertEqual(
            result.returncode, 0,
            f"--phase pre-pr with exactly one open PR (a re-run after gh pr create) must still "
            f"pass -- got rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_pre_pr_phase_fails_with_two_open_prs(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=2, head_ref="feature/PT-1-test-slug", phase="pre-pr")
        self.assertNotEqual(result.returncode, 0, "--phase pre-pr with two open PRs must still fail -- 'at most one', not 'any'")
        combined = result.stdout + result.stderr
        self.assertRegex(combined, _PR_WORD_RE, f"the failure must be about the PR count -- got: {combined!r}")

    def test_pre_pr_phase_still_fails_on_a_worktree_branch(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        push_extra_branch(clone, "worktree-some-teammate-session")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=0, head_ref="feature/PT-1-test-slug", phase="pre-pr")
        self.assertNotEqual(result.returncode, 0, "a worktree-* branch on origin must fail even in --phase pre-pr")
        combined = result.stdout + result.stderr
        self.assertIn("worktree", combined.lower(), f"the failure must name the worktree-* branch specifically -- got: {combined!r}")


class FinishAndMergePhasesMatchTheStrictDefaultTests(unittest.TestCase):
    """`--phase finish` and `--phase merge` keep today's strict predicate
    (exactly one open PR) -- identical to /finish-feature's own call site
    (after `gh pr create`) and /merge-pr's, per PT-82.md @ 778300b."""

    def test_phase_finish_fails_with_zero_open_prs(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=0, head_ref="feature/PT-1-test-slug", phase="finish")
        self.assertNotEqual(result.returncode, 0, "--phase finish with zero open PRs must fail -- exactly one, matching the real call site's timing (after gh pr create)")

    def test_phase_finish_passes_with_one_open_pr(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=1, head_ref="feature/PT-1-test-slug", phase="finish")
        self.assertEqual(
            result.returncode, 0,
            f"--phase finish with exactly one open PR must pass -- got rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_phase_finish_fails_with_two_open_prs(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        result = run_invariant_check(clone, fake_gh_dir, open_pr_count=2, head_ref="feature/PT-1-test-slug", phase="finish")
        self.assertNotEqual(result.returncode, 0, "--phase finish with two open PRs must fail")

    def test_phase_merge_matches_phase_finish(self):
        bare = make_bare_origin(self)
        clone = make_feature_clone(self, bare, "PT-1", "test-slug")
        fake_gh_dir = make_fake_gh_dir(self)
        zero = run_invariant_check(clone, fake_gh_dir, open_pr_count=0, head_ref="feature/PT-1-test-slug", phase="merge")
        one = run_invariant_check(clone, fake_gh_dir, open_pr_count=1, head_ref="feature/PT-1-test-slug", phase="merge")
        two = run_invariant_check(clone, fake_gh_dir, open_pr_count=2, head_ref="feature/PT-1-test-slug", phase="merge")
        self.assertNotEqual(zero.returncode, 0, "--phase merge with zero open PRs must fail")
        self.assertEqual(one.returncode, 0, f"--phase merge with exactly one open PR must pass -- {one.stdout!r} {one.stderr!r}")
        self.assertNotEqual(two.returncode, 0, "--phase merge with two open PRs must fail")


if __name__ == "__main__":
    unittest.main()
