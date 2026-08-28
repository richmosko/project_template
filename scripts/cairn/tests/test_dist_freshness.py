"""PT-58 failing acceptance tests: the `/finish-feature` dashboard dist-
freshness gate.

Design contract this file establishes (QA-proposed, per team-lead's "qa
tests first" + "implementer's call" framing -- implementation-lead
negotiates with me before touching these tests if the natural shape
differs, same posture as every other payload/module contract this
milestone):

`check_dist_freshness.py` (new top-level script, sibling of `cairn.py`,
not a new cairn subcommand -- it's dashboard-specific, not tracker
functionality) exports `check_dist_freshness(repo_root: Path) -> dict`
with `{"stale": bool, "reason": str, "message": str}`, PLUS a CLI entry
point (`python3 scripts/cairn/check_dist_freshness.py`) that prints
`message` and exits 1 if `stale` else 0 -- the concrete "runnable script
the skill invokes" the issue asks for.

**Git-aware, not raw mtime** -- the architect's own caveat, taken
seriously: a checkout/clone resets file mtimes arbitrarily, so comparing
`dist/`'s mtime against `src/`'s mtime would be unreliable the moment
anyone re-clones or re-checks-out the branch. Instead: the latest commit
that touches dashboard SOURCE (src/, index.html, package.json/lock,
vite/svelte/tsconfig*.json, components.json, public/) versus the latest
commit that touches `dist/`, compared by COMMIT TIMESTAMP, not the
working tree. This also naturally handles "a doc-only PR touching no
dashboard src must pass untouched" (team-lead's explicit requirement)
with no special-casing: if no commit in the compared range touches
source, there's nothing to compare against `dist/`'s own history, so the
gate reports fresh.

Stated failure modes, honestly (per the architect's own ask):
- Assumes COMMITTED state. Uncommitted working-tree modifications to
  source paths are treated as `stale` (reason `uncommitted-src-changes`)
  -- the tool cannot know whether an uncommitted edit is reflected in the
  committed `dist/`, and `/finish-feature` runs before a PR is opened, so
  "commit your dashboard changes first" is a reasonable, honest ask at
  that point in the workflow, not a limitation to route around.
- A `dist/` with NO commit history at all (never built/committed) is its
  own distinct reason (`dist-never-built`), not lumped into `stale` --
  the fix ("build and commit dist/") is different from "rebuild dist/",
  and the message should say so.

Nothing under test exists yet: no `check_dist_freshness.py` file at all.
Every test below is expected to fail at import time (ModuleNotFoundError)
until implementation-lead creates it -- an unusually strong but honest RED
for a genuinely new script, not a broken test (see this file's own
`setUp`, which surfaces that failure per-test rather than as one opaque
collection error).
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
CHECK_SCRIPT_PATH = helpers.CAIRN_DIR / "check_dist_freshness.py"


def _run_git(cwd: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def _commit(cwd: Path, message: str, *, when: str) -> str:
    """A commit with a controlled, deterministic timestamp -- `when` is
    any `git commit --date`-accepted string (e.g. "2026-08-20T10:00:00").
    Both author and committer date are pinned so ordering is unambiguous
    regardless of wall-clock time between test steps."""
    import os

    env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    _run_git(cwd, "add", "-A", env=env)
    _run_git(cwd, "commit", "-q", "-m", message, "--date", when, env=env)
    return _run_git(cwd, "rev-parse", "HEAD")


def make_dashboard_repo(testcase) -> Path:
    """A fresh git repo shaped like the real one, scoped to just the
    scripts/cairn/dashboard/ subtree this check cares about. Returns
    repo_root."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    _run_git(tmp, "init", "-q")
    _run_git(tmp, "config", "user.email", "test@example.com")
    _run_git(tmp, "config", "user.name", "Test")

    dashboard = tmp / "scripts" / "cairn" / "dashboard"
    (dashboard / "src").mkdir(parents=True)
    (dashboard / "dist" / "assets").mkdir(parents=True)
    (dashboard / "src" / "App.svelte").write_text("<div>v1</div>\n", encoding="utf-8")
    (dashboard / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (dashboard / "package.json").write_text('{"name": "dashboard"}\n', encoding="utf-8")
    (dashboard / "dist" / "index.html").write_text("<html>built v1</html>\n", encoding="utf-8")
    (dashboard / "dist" / "assets" / "index.js").write_text("console.log('v1');\n", encoding="utf-8")
    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")

    _commit(tmp, "initial: src + matching dist", when="2026-08-20T10:00:00")
    return tmp


class DistFreshnessModuleTests(unittest.TestCase):
    """Imports the module fresh in setUp (not at file-collection time) so
    a genuinely-missing module fails each test individually and clearly,
    rather than as one opaque collection error for the whole file."""

    def setUp(self):
        if str(helpers.CAIRN_DIR) not in sys.path:
            sys.path.insert(0, str(helpers.CAIRN_DIR))
        try:
            self.module = importlib.import_module("check_dist_freshness")
            importlib.reload(self.module)  # in case an earlier test's sys.modules cache is stale
        except ModuleNotFoundError as e:
            self.fail(
                f"scripts/cairn/check_dist_freshness.py does not exist yet ({e!r}) -- "
                f"implementation-lead's PT-58 slice creates it; see this file's module "
                f"docstring for the exact contract these tests pin."
            )

    def test_fresh_dist_is_not_stale(self):
        repo_root = make_dashboard_repo(self)
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], False, result)
        self.assertEqual(result["reason"], "fresh", result)

    def test_stale_dist_is_detected_when_src_committed_after_dist(self):
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "src" / "App.svelte").write_text("<div>v2 -- a real change</div>\n", encoding="utf-8")
        _commit(repo_root, "src: change without rebuilding dist", when="2026-08-21T10:00:00")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], True, result)
        self.assertEqual(result["reason"], "stale", result)
        self.assertTrue(result["message"], "a stale result must carry a non-empty explanatory message")

    def test_dist_rebuilt_after_src_change_is_fresh_again(self):
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "src" / "App.svelte").write_text("<div>v2</div>\n", encoding="utf-8")
        _commit(repo_root, "src: change", when="2026-08-21T10:00:00")
        (dashboard / "dist" / "assets" / "index.js").write_text("console.log('v2');\n", encoding="utf-8")
        _commit(repo_root, "dist: rebuild", when="2026-08-21T11:00:00")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], False, result)

    def test_same_second_commits_resolve_toward_stale_not_fresh(self):
        # Architect's blocking peer-review finding (8bd6896), first
        # defect: dist committed, then src committed at the exact SAME
        # second -- a plain `>` timestamp comparison ties and a tie
        # resolves to "not stale", exactly backwards for a gate (src DID
        # change after dist was last built, even if the clock can't tell
        # them apart). The correct mechanism is ancestry (`git merge-base
        # --is-ancestor`), not a clock reading: src's commit is NOT an
        # ancestor of dist's commit here (it comes strictly after in the
        # DAG), so the gate must report stale regardless of what the two
        # commits' timestamps happen to say.
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        same_instant = "2026-08-21T09:00:00+0000"
        (dashboard / "dist" / "index.html").write_text("<html>rebuilt, same second as the src change below</html>\n", encoding="utf-8")
        _commit(repo_root, "dist: rebuild", when=same_instant)
        (dashboard / "src" / "App.svelte").write_text("<div>v2 -- committed the same second as the dist rebuild above</div>\n", encoding="utf-8")
        _commit(repo_root, "src: change, same instant as the dist rebuild", when=same_instant)
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(
            result["stale"], True,
            f"{result} -- src's commit comes strictly AFTER dist's rebuild commit in the DAG, "
            f"even though both carry the identical timestamp -- a tie must not resolve to "
            f"fresh; ancestry (not clock comparison) is the correct mechanism",
        )

    def test_a_confusing_timestamp_does_not_override_the_real_commit_order(self):
        # Architect's second defect: ISO-8601-with-offset timestamps sort
        # LEXICALLY, not chronologically, so a naive string/int compare
        # can invert real ordering across timezones. Constructed so the
        # RIGHT answer (fresh -- dist's rebuild commit is a direct
        # descendant of the src-change commit, i.e. it genuinely reflects
        # that change) would come out backwards under a timestamp-based
        # comparison: dist's rebuild commit is stamped with a timezone
        # offset that makes it look "earlier" than src's commit, even
        # though it is literally the NEXT commit after src's in history.
        # Ancestry doesn't care what clock reading is attached to a
        # commit, only where it sits in the graph -- so this must read
        # fresh regardless.
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "src" / "App.svelte").write_text("<div>v2 -- tz-confusing timestamp follows</div>\n", encoding="utf-8")
        _commit(repo_root, "src: change (committed with a LATE-looking -0700 stamp)", when="2026-08-20T23:00:00-0700")
        (dashboard / "dist" / "index.html").write_text("<html>rebuilt immediately after the src change above</html>\n", encoding="utf-8")
        _commit(repo_root, "dist: rebuild (committed with an EARLIER-looking +0000 stamp, but it's the NEXT commit)", when="2026-08-21T00:30:00+0000")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(
            result["stale"], False,
            f"{result} -- dist's rebuild commit is the direct child of (i.e. genuinely reflects) "
            f"the src-change commit -- it must read fresh regardless of the confusing timezone "
            f"offsets attached to each commit's timestamp; only DAG ancestry should decide this",
        )

    def test_a_doc_only_pr_touching_no_dashboard_src_passes_untouched(self):
        # team-lead's explicit requirement: a commit that touches NEITHER
        # dashboard src NOR dist (e.g. a README/docs-only change) must
        # never flip a previously-fresh repo to stale.
        repo_root = make_dashboard_repo(self)
        (repo_root / "README.md").write_text("updated docs, nothing dashboard-related\n", encoding="utf-8")
        _commit(repo_root, "docs: unrelated change", when="2026-08-22T10:00:00")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], False, result)

    def test_dist_with_no_commit_history_is_a_distinct_reason_from_stale(self):
        tmp = helpers.make_empty_tmp_dir(self)
        _run_git(tmp, "init", "-q")
        _run_git(tmp, "config", "user.email", "test@example.com")
        _run_git(tmp, "config", "user.name", "Test")
        dashboard = tmp / "scripts" / "cairn" / "dashboard"
        (dashboard / "src").mkdir(parents=True)
        (dashboard / "src" / "App.svelte").write_text("<div>v1</div>\n", encoding="utf-8")
        # Deliberately no dist/ directory committed at all.
        (tmp / "README.md").write_text("x\n", encoding="utf-8")
        _commit(tmp, "src only, dist never built", when="2026-08-20T10:00:00")
        result = self.module.check_dist_freshness(tmp)
        self.assertIs(result["stale"], True, result)
        self.assertEqual(result["reason"], "dist-never-built", result)

    def test_uncommitted_src_changes_are_treated_as_stale_honestly(self):
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        # Modify src WITHOUT committing -- the tool cannot know whether
        # this uncommitted edit is reflected in the committed dist/.
        (dashboard / "src" / "App.svelte").write_text("<div>uncommitted change</div>\n", encoding="utf-8")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], True, result)
        self.assertEqual(result["reason"], "uncommitted-src-changes", result)

    def test_uncommitted_changes_to_unrelated_files_do_not_trigger_staleness(self):
        repo_root = make_dashboard_repo(self)
        (repo_root / "README.md").write_text("uncommitted, unrelated\n", encoding="utf-8")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], False, result)

    def test_a_brand_new_untracked_source_file_also_counts_as_uncommitted(self):
        # Architect's non-blocking peer-review suggestion, taken: an
        # untracked (never `git add`ed) new component file is the
        # STRONGEST signal that dist is out of date -- deliberately the
        # opposite scoping from read_git_state's "dirty" check (where an
        # untracked issue file mid-`cairn new` is the routine, ignorable
        # case). Untracked source files must count here.
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "src" / "NewComponent.svelte").write_text("<div>never git added</div>\n", encoding="utf-8")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], True, result)
        self.assertEqual(result["reason"], "uncommitted-src-changes", result)

    def test_never_raises_on_a_repo_with_no_dashboard_directory_at_all(self):
        # A spin-off / a repo that never had the dashboard at all --
        # never-raises posture, matching every other engine-adjacent
        # reader in this codebase (read_git_tags, build_roster_payload).
        tmp = helpers.make_empty_tmp_dir(self)
        _run_git(tmp, "init", "-q")
        _run_git(tmp, "config", "user.email", "test@example.com")
        _run_git(tmp, "config", "user.name", "Test")
        (tmp / "README.md").write_text("x\n", encoding="utf-8")
        _commit(tmp, "no dashboard here", when="2026-08-20T10:00:00")
        try:
            result = self.module.check_dist_freshness(tmp)
        except Exception as e:  # noqa: BLE001
            self.fail(f"check_dist_freshness must never raise when the dashboard dir is missing, got {e!r}")
        self.assertIs(result["stale"], False, result)


class DistFreshnessCLITests(unittest.TestCase):
    """The runnable-script half of the contract -- /finish-feature (a
    markdown skill, not Python) needs an exit code to gate on, not a
    Python return value."""

    def setUp(self):
        if not CHECK_SCRIPT_PATH.is_file():
            self.skipTest(f"{CHECK_SCRIPT_PATH} does not exist yet")

    def _run_cli(self, repo_root: Path):
        return subprocess.run(
            [sys.executable, str(CHECK_SCRIPT_PATH), str(repo_root)],
            capture_output=True, text=True,
        )

    def test_cli_exits_0_on_a_fresh_repo(self):
        repo_root = make_dashboard_repo(self)
        result = self._run_cli(repo_root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_exits_nonzero_and_prints_a_message_on_a_stale_repo(self):
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "src" / "App.svelte").write_text("<div>v2</div>\n", encoding="utf-8")
        _commit(repo_root, "src change, no rebuild", when="2026-08-21T10:00:00")
        result = self._run_cli(repo_root)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((result.stdout + result.stderr).strip(), "a stale CLI run must print something explaining why")


if __name__ == "__main__":
    unittest.main()
