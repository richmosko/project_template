"""PT-106 (architect's gate-1 ruling, process/cairn/issues/PT-106.md @
f26390c): six measured builds isolated the real variable -- not the
build's path, not run-to-run randomness, but whether a PREVIOUS `dist/`
exists at build time. Root `.gitignore:35` ignores `dist/`, `:45`
negates it so this app's build output can be committed -- Tailwind v4's
automatic source detection respects `.gitignore`, so the negation makes
the previous build's own emitted JS/CSS a content source: the build
output becomes an input to the next build. `index.css` is the only file
that ever differs (65 others byte-identical across all six builds).

Fix: `@source not "../dist";` in `src/app.css`, right after the leading
`@import` block.

**Guard -- one build, not two** (measured: two-tmpdir and two-in-place
already agree with each other today; only dist-present-vs-absent
differs). Copy the dashboard to an isolated tmpdir WITH its `dist/`
LEFT IN PLACE (the opposite of check_dist_freshness.py's own rescue
recipe, which removes dist first -- that recipe already reproduces the
committed artifact and is not what's under test here), build, and
assert every `dist/assets/*` + `index.html` is byte-identical to the
committed `dist/`. Equality against the committed artifact doubles as
"no utility class lost" -- the same check the ruling used to validate
the fix. Skipped with a named reason when the dashboard's node_modules
is absent.

Second guard: a source-text scan pinning the `@source not "../dist";`
line in app.css, PT-83/PT-104 pattern.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
DASHBOARD_DIR = REPO_ROOT / "scripts" / "cairn" / "dashboard"
DASHBOARD_NODE_MODULES = DASHBOARD_DIR / "node_modules"
COMMITTED_DIST = DASHBOARD_DIR / "dist"
APP_CSS = DASHBOARD_DIR / "src" / "app.css"


class IsolatedBuildWithPriorDistIsByteIdenticalTests(unittest.TestCase):
    def test_a_build_with_a_previous_dist_present_matches_the_committed_dist_byte_for_byte(self):
        """Mutation: revert `@source not \"../dist\";` from app.css --
        Tailwind's source scan picks up the copied dist/'s own emitted
        class-name strings again and `assets/index.css` reshuffles away
        from the committed artifact (measured: `e84ee3e64bdd` vs the
        committed `be226fc41df6`)."""
        if not DASHBOARD_NODE_MODULES.is_dir():
            self.skipTest(f"{DASHBOARD_NODE_MODULES} absent -- dashboard dependencies not installed in this checkout")
        self.assertTrue(COMMITTED_DIST.is_dir(), f"expected a committed {COMMITTED_DIST}")

        tmp = Path(tempfile.mkdtemp(prefix="cairn-dist-repro-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        target = tmp / "dashboard"
        # Deliberately the OPPOSITE of check_dist_freshness.py's own
        # rescue recipe: dist/ is copied ALONG WITH the rest of the
        # source tree and left in place -- that is the state under test
        # (a previous build's output already on disk when the next
        # build runs), not the freshness checker's clean-copy recipe.
        shutil.copytree(DASHBOARD_DIR, target, symlinks=True)
        self.assertTrue((target / "dist").is_dir(), "the copy must have carried dist/ along -- that is the scenario under test")

        result = subprocess.run(
            ["npm", "run", "build"], cwd=str(target), capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(
            result.returncode, 0,
            f"the isolated build (dist/ present) must itself succeed -- {(result.stderr or result.stdout)[-2000:]}",
        )

        rebuilt_dist = target / "dist"
        committed_files = {p.relative_to(COMMITTED_DIST) for p in COMMITTED_DIST.rglob("*") if p.is_file()}
        rebuilt_files = {p.relative_to(rebuilt_dist) for p in rebuilt_dist.rglob("*") if p.is_file()}
        self.assertEqual(
            committed_files, rebuilt_files,
            "the rebuild (with a previous dist/ present) must produce the exact same file SET as the committed dist/",
        )
        diffs = [
            str(rel) for rel in sorted(committed_files)
            if (COMMITTED_DIST / rel).read_bytes() != (rebuilt_dist / rel).read_bytes()
        ]
        self.assertEqual(
            diffs, [],
            f"a build with a previous dist/ on disk must still reproduce the committed dist/ "
            f"byte-for-byte (PT-106: the build output must not be an input to the next build) -- "
            f"differing files: {diffs}",
        )


class AppCssPinsTheSourceNotDistDeclarationTests(unittest.TestCase):
    """Mutation: delete the `@source not \"../dist\";` line -> red."""

    def test_app_css_declares_source_not_dist_after_the_import_block(self):
        self.assertTrue(APP_CSS.is_file(), f"expected {APP_CSS}")
        source = APP_CSS.read_text(encoding="utf-8")
        self.assertRegex(
            source, r'@source\s+not\s+"\.\./dist"\s*;',
            "app.css must declare `@source not \"../dist\";` so Tailwind's content scan excludes "
            "the committed dist/ -- otherwise the build output becomes an input to the next build (PT-106)",
        )

    def test_the_source_not_declaration_comes_after_the_leading_import_block(self):
        # Tailwind v4 requires @import statements to lead the file -- the
        # ruling places @source right after them, matching the existing
        # convention (PT-69's variant import already sits in that slot).
        source = APP_CSS.read_text(encoding="utf-8")
        m = re.search(r'@source\s+not\s+"\.\./dist"\s*;', source)
        self.assertIsNotNone(m, "no @source not declaration found")
        preceding = source[:m.start()]
        import_lines = [l for l in preceding.splitlines() if l.strip().startswith("@import")]
        self.assertTrue(import_lines, "expected at least one @import line before @source not -- none found")


if __name__ == "__main__":
    unittest.main()
