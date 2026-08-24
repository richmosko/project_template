"""PT-53 failing tests: `_git_mv_or_rename` silently falls back to a
plain filesystem move (untracked add + unstaged delete, not a staged
rename) when called with RELATIVE `src`/`dest` paths -- the shape every
real invocation with a relative `--data-dir` actually produces
(`resolve_data_dir` never calls `.resolve()` on an explicit `--data-dir`).

Root cause (process/cairn/issues/PT-53.md, found during PT-50's real-repo
migration): the subprocess call sets `cwd=str(src.parent)` but passes the
ORIGINAL (possibly relative) path strings as `git mv`'s arguments --
relative to the wrong base once the subprocess's cwd has changed. `git
mv` then fails to find the file, the failure is swallowed (only
`returncode == 0` is checked, stderr is discarded), and the code
silently falls through to the `os.replace` fallback.

Affects every caller (archive_milestone, archive_major, cmd_archive
--done-before, migrate_archive_issues) -- tested ONCE here, at the
shared helper, not once per caller.

Nothing under test exists yet: `_git_mv_or_rename` doesn't resolve its
arguments and logs no stderr on a git-mv failure. Every red test below
is expected to fail until implementation-lead's PT-53 fix lands.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


class GitMvOrRenameRelativePathTests(unittest.TestCase):
    """A relative --data-dir flows straight into every caller as a
    relative Path -- _git_mv_or_rename must stage a real git rename in
    that case too, not silently degrade to an unstaged move."""

    def setUp(self):
        self.repo_root = helpers.make_empty_tmp_dir(self)
        _git(["init", "-q"], self.repo_root)
        _git(["config", "user.email", "qa@example.com"], self.repo_root)
        _git(["config", "user.name", "qa"], self.repo_root)
        (self.repo_root / "sub").mkdir()
        (self.repo_root / "sub" / "old.md").write_text("content\n", encoding="utf-8")
        _git(["add", "-A"], self.repo_root)
        _git(["commit", "-q", "-m", "seed"], self.repo_root)

        self._original_cwd = os.getcwd()
        self.addCleanup(os.chdir, self._original_cwd)

    def test_a_relative_src_and_dest_from_the_repo_root_still_stage_a_git_rename(self):
        # The bug's exact trigger: RELATIVE Path arguments, the process
        # cwd being the repo root -- the normal "ran from the repo root
        # with a relative --data-dir" shape -- not pre-resolved to
        # absolute by the caller.
        os.chdir(self.repo_root)
        src = Path("sub/old.md")
        dest = Path("sub/new.md")
        cairn._git_mv_or_rename(src, dest)

        self.assertFalse((self.repo_root / "sub" / "old.md").exists())
        self.assertTrue((self.repo_root / "sub" / "new.md").exists())

        status = _git(["status", "--porcelain"], self.repo_root).stdout
        self.assertIn("R  ", status, f"expected a staged rename, got:\n{status}")
        self.assertNotIn("??", status, f"expected no untracked entries (a plain move symptom), got:\n{status}")

    def test_relative_paths_resolve_correctly_from_a_different_cwd_too(self):
        # A second angle on the same bug: the caller's cwd need not be
        # the repo root at all -- a relative --data-dir is resolved
        # against WHATEVER the process's cwd happens to be at invocation
        # time, and _git_mv_or_rename must get it right regardless.
        os.chdir(self.repo_root / "sub")
        src = Path("old.md")
        dest = Path("new.md")
        cairn._git_mv_or_rename(src, dest)

        self.assertFalse((self.repo_root / "sub" / "old.md").exists())
        self.assertTrue((self.repo_root / "sub" / "new.md").exists())
        status = _git(["status", "--porcelain"], self.repo_root).stdout
        self.assertIn("R  ", status, f"expected a staged rename, got:\n{status}")


class GitMvOrRenameFallbackTests(unittest.TestCase):
    def test_fallback_still_works_in_a_non_git_directory(self):
        # The fallback ITSELF stays legitimate for a non-git data dir --
        # this must keep working (no crash), only the SILENT-failure-
        # inside-a-real-repo half of the bug is what PT-53 fixes.
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "old.md").write_text("content\n", encoding="utf-8")
        cairn._git_mv_or_rename(tmp / "old.md", tmp / "new.md")
        self.assertFalse((tmp / "old.md").exists())
        self.assertTrue((tmp / "new.md").exists())

    def test_a_genuine_git_mv_failure_logs_a_warning_but_still_falls_back(self):
        # A real git-mv failure (here: no .git anywhere up the tree, so
        # "fatal: not a git repository") must be surfaced on stderr as a
        # warning -- but never raised; the plain-move fallback still has
        # to complete (this fallback is a LEGITIMATE outcome for a
        # non-git data dir, not an error condition).
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "old.md").write_text("content\n", encoding="utf-8")
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            cairn._git_mv_or_rename(tmp / "old.md", tmp / "new.md")
        self.assertTrue((tmp / "new.md").exists())
        self.assertIn("cairn: warning:", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
