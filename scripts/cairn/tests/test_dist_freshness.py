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
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
CHECK_SCRIPT_PATH = helpers.CAIRN_DIR / "check_dist_freshness.py"

# A tiny, dependency-free "build" -- not the real dashboard's vite build,
# never invoked via a real `npm install` -- deterministic purely from
# src/App.svelte's content, so a package.json-only edit (the shape of the
# real PT-82 finding, 037e6aa) can never change its output, and a real
# src/ edit always does. Node, not npm, is the only runtime dependency
# (matches PT-82 delta 3's own build script shape, `node <path-to-script>`).
_BUILD_JS = """
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, 'src', 'App.svelte'), 'utf8').trim();
fs.mkdirSync(path.join(__dirname, 'dist', 'assets'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'dist', 'index.html'), '<html>built: ' + src + '</html>\\n');
fs.writeFileSync(path.join(__dirname, 'dist', 'assets', 'index.js'), 'console.log(' + JSON.stringify(src) + ');\\n');
"""


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


def make_buildable_dashboard_repo(testcase) -> Path:
    """Like `make_dashboard_repo`, but with a REAL, runnable (if tiny)
    build: `package.json`'s `scripts.build` plus `build.js` (`_BUILD_JS`).
    The committed dist/ is generated by actually invoking `node build.js`
    once here -- never hand-typed -- so "rebuild reproduces committed
    dist/ byte-for-byte" is guaranteed true by construction at the initial
    commit, the same property the rebuild-rescue path must detect later."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    _run_git(tmp, "init", "-q")
    _run_git(tmp, "config", "user.email", "test@example.com")
    _run_git(tmp, "config", "user.name", "Test")

    dashboard = tmp / "scripts" / "cairn" / "dashboard"
    (dashboard / "src").mkdir(parents=True)
    (dashboard / "src" / "App.svelte").write_text("<div>v1</div>\n", encoding="utf-8")
    (dashboard / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (dashboard / "package.json").write_text(
        json.dumps({"name": "dashboard", "scripts": {"build": "node ./build.js"}}) + "\n", encoding="utf-8"
    )
    (dashboard / "build.js").write_text(_BUILD_JS, encoding="utf-8")

    build_result = subprocess.run(
        ["node", "build.js"], cwd=str(dashboard), capture_output=True, text=True,
    )
    assert build_result.returncode == 0, f"fixture's own build.js failed: {build_result.stderr}"

    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")
    _commit(tmp, "initial: src + build script + matching dist", when="2026-08-20T10:00:00")
    return tmp


def _snapshot_dir(d: Path) -> dict:
    """{relpath: bytes} for every file under `d`, recursive -- the
    byte-for-byte comparison guard 3 (PT-82.md @ dc98ff4) needs to prove
    the rebuild-and-compare step never touches the committed dist/."""
    return {str(p.relative_to(d)): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def _make_git_only_path_dir(testcase) -> Path:
    """A scratch PATH dir containing ONLY a `git` symlink (to whatever
    real git binary this test environment already resolves) -- simulates
    node/npm being entirely ABSENT from PATH while keeping
    check_dist_freshness's own pre-existing git subprocess calls working,
    so a failure here is attributable to the missing build toolchain
    specifically, never to a broken git."""
    real_git = shutil.which("git")
    assert real_git, "this test environment has no git on PATH at all -- cannot build the fixture"
    tmp = helpers.make_empty_tmp_dir(testcase)
    (tmp / "git").symlink_to(real_git)
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

    def test_a_build_config_file_never_enumerated_by_name_still_triggers_stale(self):
        # Team-lead's ruling (adopting the architect's non-blocking
        # suggestion as in-scope): the watch set is the INVERSE
        # formulation -- the whole dashboard/ subtree except dist/ --
        # specifically so a config file an earlier by-name enumeration
        # never anticipated (postcss.config.js here; equally .env,
        # tailwind.config.js, .browserslistrc) can't silently escape the
        # gate. A by-name list (src/, index.html, package.json, vite/
        # svelte/tsconfig configs, components.json, public/) would never
        # have watched this file; the exclude-dist formulation always
        # does, because it isn't dist/.
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "postcss.config.js").write_text("module.exports = {};\n", encoding="utf-8")
        _commit(repo_root, "build config: add postcss.config.js", when="2026-08-21T10:00:00")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], True, result)
        self.assertEqual(result["reason"], "stale", result)

    def test_editing_the_dashboard_readme_does_not_trigger_a_pointless_rebuild(self):
        # Architect's non-blocking follow-up on the inverse formulation:
        # excluding only dist/ means README.md/.gitignore/.vscode inside
        # the dashboard dir would otherwise count as build inputs --
        # noise, since a doc edit can't affect what Vite builds, and the
        # README is exactly the file most likely to get edited BECAUSE it
        # documents this very rebuild discipline. A gate that cries wolf
        # on its own documentation teaches people to bypass it.
        repo_root = make_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "README.md").write_text("# Dashboard\n\nHow to build/rebuild dist/.\n", encoding="utf-8")
        _commit(repo_root, "docs: add dashboard README", when="2026-08-21T10:00:00")
        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(result["stale"], False, result)

    def test_ancestry_stale_but_a_byte_identical_rebuild_is_reported_fresh(self):
        # Pre-flight finding, team-lead @ 4efcd1d: /finish-feature's gate
        # FAILED on PT-82's delta 3 (037e6aa) -- package.json's `build`
        # script changed (invocation only), dist/ was never re-committed,
        # so ancestry alone says stale -- but the rebuild is measured
        # byte-identical (spike step 8 @156993b), so no dist commit is
        # even possible and the gate can't honestly be satisfied by
        # ancestry alone. Assumed contract (the finding fixes the
        # OUTCOME -- a byte-identical rebuild must read fresh -- not the
        # exact rebuild mechanism; flag to the architect if implementation-
        # lead's diverges): when ancestry says stale, `check_dist_
        # freshness` builds the dashboard into an ISOLATED tmp dir (never
        # mutating the working tree's own dist/) and compares the result
        # to the committed dist/ file-for-file, byte-for-byte; identical
        # output overrides ancestry and the gate reports fresh.
        repo_root = make_buildable_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        pkg = json.loads((dashboard / "package.json").read_text(encoding="utf-8"))
        pkg["scripts"]["build"] = "node build.js"  # invocation-only edit -- build.js itself, and its output, are unchanged
        (dashboard / "package.json").write_text(json.dumps(pkg) + "\n", encoding="utf-8")
        _commit(repo_root, "package.json: cosmetic build-script edit, no rebuild", when="2026-08-21T10:00:00")

        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(
            result["stale"], False,
            f"a rebuild that reproduces committed dist/ byte-for-byte must read fresh even when "
            f"git ancestry alone says stale (a package.json-only edit that can't change build "
            f"output must never demand an impossible no-op dist commit) -- {result}",
        )

    def test_ancestry_stale_and_a_genuinely_different_rebuild_stays_stale(self):
        # Control for the test above: the rebuild-rescue path must not
        # swallow a REAL staleness. A rebuild whose output genuinely
        # differs from the committed dist/ must still fail the gate.
        repo_root = make_buildable_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "src" / "App.svelte").write_text("<div>v2 -- a real change</div>\n", encoding="utf-8")
        _commit(repo_root, "src: real change, dist not rebuilt", when="2026-08-21T10:00:00")

        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(
            result["stale"], True,
            f"a rebuild whose output genuinely differs from the committed dist/ must stay stale "
            f"-- the rescue path must not swallow a real staleness -- {result}",
        )
        self.assertEqual(result["reason"], "stale", result)

    def test_a_failing_build_command_cannot_verify_and_stays_stale(self):
        # Architect's post-verdict delta 1, guard 2 (PT-82.md @ dc98ff4,
        # verbatim): "An absent or failing toolchain fails, it does not
        # skip. If node/npm is missing or the build exits non-zero, the
        # result is stale with a reason saying the gate could not verify
        # -- not a pass." This leg: the toolchain is present, but the
        # CURRENTLY COMMITTED build script itself is broken, so any
        # rebuild attempt fails. Mutation this must catch: treating a
        # failed rebuild as fresh (silently skipping the comparison).
        repo_root = make_buildable_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        (dashboard / "build.js").write_text("process.exit(7);\n", encoding="utf-8")
        _commit(repo_root, "build.js: deliberately broken (simulates a failing build)", when="2026-08-21T10:00:00")

        result = self.module.check_dist_freshness(repo_root)
        self.assertIs(
            result["stale"], True,
            f"a rebuild that cannot even run must never be treated as a pass -- a broken build "
            f"command must stay stale, not silently rescued -- {result}",
        )
        self.assertTrue(result["message"], "the failure must explain the gate could not verify freshness")

    def test_a_missing_toolchain_cannot_verify_and_stays_stale(self):
        # Same guard 2, the other half: node/npm absent from PATH
        # entirely (not merely a failing script). check_dist_freshness's
        # OWN git calls must still work (PATH still has git via
        # `_make_git_only_path_dir`) -- only the build toolchain is gone.
        repo_root = make_buildable_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        pkg = json.loads((dashboard / "package.json").read_text(encoding="utf-8"))
        pkg["scripts"]["build"] = "node build.js"  # invocation-only edit -- ancestry alone says stale
        (dashboard / "package.json").write_text(json.dumps(pkg) + "\n", encoding="utf-8")
        _commit(repo_root, "package.json: cosmetic build-script edit, no rebuild", when="2026-08-21T10:00:00")

        git_only_dir = _make_git_only_path_dir(self)
        with unittest.mock.patch.dict(os.environ, {"PATH": str(git_only_dir)}, clear=False):
            result = self.module.check_dist_freshness(repo_root)
        self.assertIs(
            result["stale"], True,
            f"an absent toolchain (node/npm not on PATH) must FAIL, never silently pass or skip "
            f"the comparison -- {result}",
        )
        combined = result.get("message", "")
        self.assertTrue(
            re.search(r"\b(node|npm|toolchain|build)\b", combined, re.IGNORECASE),
            f"the failure message must name the toolchain / build problem -- got: {combined!r}",
        )

    def test_the_rebuild_never_touches_the_committed_dist_directory(self):
        # Guard 3 (PT-82.md @ dc98ff4): "The rebuild goes to a temp dir
        # outside the repository and is removed afterwards. Building
        # anywhere inside the tree would dirty it, and could trip both
        # this gate and PT-100's real-state guards." Exercises the
        # rescue scenario (ancestry-stale, byte-identical rebuild), which
        # is guaranteed to trigger a rebuild attempt.
        repo_root = make_buildable_dashboard_repo(self)
        dashboard = repo_root / "scripts" / "cairn" / "dashboard"
        dist_dir = dashboard / "dist"
        before = _snapshot_dir(dist_dir)

        pkg = json.loads((dashboard / "package.json").read_text(encoding="utf-8"))
        pkg["scripts"]["build"] = "node build.js"
        (dashboard / "package.json").write_text(json.dumps(pkg) + "\n", encoding="utf-8")
        _commit(repo_root, "package.json: cosmetic build-script edit, no rebuild", when="2026-08-21T10:00:00")

        self.module.check_dist_freshness(repo_root)  # ancestry-stale -> triggers a rebuild attempt

        after = _snapshot_dir(dist_dir)
        self.assertEqual(
            before, after,
            "the rebuild-and-compare step must run entirely in a temp dir outside the repo -- the "
            "committed dist/ directory must be byte-for-byte unchanged after a check run",
        )

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
