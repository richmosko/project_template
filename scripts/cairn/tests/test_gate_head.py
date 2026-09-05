"""`cairn gate --head <verified-sha>` (PT-94 C8): the head-match check
that replaces a "re-verify" round -- pass when everything between the
verified sha and HEAD is docs or tracker, fail otherwise."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class GateHeadTests(unittest.TestCase):
    def setUp(self):
        self.root = helpers.make_empty_tmp_dir(self)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        (self.root / "app.py").write_text("x = 1\n")
        (self.root / "process" / "cairn" / "issues").mkdir(parents=True)
        (self.root / "docs").mkdir()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "verified")
        self.verified = git(self.root, "rev-parse", "HEAD")

    def test_docs_and_tracker_only_passes(self):
        """Mutation: drop `process/` from the docs prefixes -> fail."""
        (self.root / "process" / "cairn" / "issues" / "PT-1.md").write_text("---\nid: PT-1\n---\n")
        (self.root / "docs" / "notes.md").write_text("n\n")
        (self.root / "README.md").write_text("r\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "docs")
        ok, changed, stat = cairn.gate_head_match(self.root, self.verified)
        self.assertTrue(ok)
        self.assertEqual(sorted(changed), ["README.md", "docs/notes.md", "process/cairn/issues/PT-1.md"])
        self.assertIn("3 files changed", stat)

    def test_a_code_change_after_the_verified_sha_fails(self):
        """Mutation: match on suffix `.py` as docs -> pass."""
        (self.root / "app.py").write_text("x = 2\n")
        git(self.root, "commit", "-q", "-am", "code")
        ok, changed, _ = cairn.gate_head_match(self.root, self.verified)
        self.assertFalse(ok)
        self.assertEqual(changed, ["app.py"])

    def test_cli_exit_code_follows_the_verdict(self):
        (self.root / "app.py").write_text("x = 3\n")
        git(self.root, "commit", "-q", "-am", "code")
        r = subprocess.run([str(helpers.CAIRN_BIN), "gate", "--head", self.verified], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL", r.stdout)
        self.assertIn("app.py", r.stdout)
        r2 = subprocess.run([str(helpers.CAIRN_BIN), "gate", "--head", git(self.root, "rev-parse", "HEAD")], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("PASS", r2.stdout)


if __name__ == "__main__":
    unittest.main()
