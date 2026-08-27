"""PT-54 failing acceptance tests: the `/dashboard` shell's data + serve
contract, per the architect's ruling (PT-54 comment, 2026-08-26 — four
numbered sections; §4 "Testing shape (for qa-engineer)" is the checklist
this file works from verbatim):

  - `GET /api/dashboard` — new endpoint, `git: {branch, dirty, head,
    latest_tag}` (subprocess against the primary root's data_dir, same
    "-C <data_dir>, walk up to find the repo" contract `read_git_tags`
    already uses; NEVER raises -- degrades every git field to null when
    git is unavailable/not-a-worktree), `tracker: {counts_by_status}`,
    `check: {ok, errors}` (`check_repo`), `release` (the join: latest tag
    -> the milestone whose `target_tag` matches -> its id/name/status/ga,
    or null -- deliberately NOT parsed from STATE.md, see the ruling's
    §4), `generated_at`. ETag'd + `Cache-Control: no-store`, matching
    `/api/board`'s posture.
  - `GET /dashboard` (and `/dashboard/`) serves `dist/index.html`;
    `/dashboard/<rel>` serves a real dist asset; a `<rel>` with a file
    suffix that doesn't exist is a 404 (never falls back to index.html --
    "returning HTML for a missing .js is the classic hours-lost debugging
    trap"); a `<rel>` with NO suffix falls back to `index.html` (SPA
    routing). Missing dist -> 503 with a small HTML page naming the literal
    fix command, and `/api/dashboard` keeps working regardless (pure
    python, no build dependency).
  - `make_server(..., dashboard_dir: Path = DASHBOARD_DIR)` is the ruled
    test seam for the missing-dist branch -- every serve test below builds
    its own throwaway dist fixture and passes it in explicitly, never
    depending on (or mutating) the real committed
    `scripts/cairn/dashboard/dist/`.
  - Build smoke -- "assert dist/index.html exists and that the asset URLs
    it references resolve to real files under dist" (ruling's own words;
    deliberately NOT `npm run build` from the test -- the committed-dist
    policy (§3) means this is a filesystem/HTML check against what SHOULD
    already be committed, not a build trigger). `svelte-check`/`npm run
    build` succeeding is the app-side gate per the ruling, out of scope
    here.

Nothing under test exists yet: no `cairn.build_dashboard_payload`, no
`/api/dashboard` or `/dashboard` route, no `dashboard_dir` kwarg on
`make_server`, no committed `scripts/cairn/dashboard/dist/`. Every test
below is expected to fail for one of those concrete reasons (AttributeError
/ TypeError on the kwarg / 404 / missing dist file) -- never an import
error, never a fixture-setup error.
"""
from __future__ import annotations

import html.parser
import json
import re
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

import cairn


REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
DASHBOARD_SRC_DIR = helpers.CAIRN_DIR / "dashboard"  # scripts/cairn/dashboard (ruling §1)
DASHBOARD_DIST_DIR = DASHBOARD_SRC_DIR / "dist"


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\ncreated: 2026-08-26\nupdated: 2026-08-26\n"
    "---\n\nBody.\n"
)
MILESTONE_TMPL = (
    "---\nid: {id}\nname: {name}\nkind: {kind}\nmajor: {major}\nstatus: {status}\n"
    "target_tag: {target_tag}\nga: {ga}\n---\n\nDoD.\n"
)
MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"


def make_git_repo(testcase, *, branch: str | None = None) -> Path:
    """Fresh git repo (init'd, one commit) with a `process/cairn` data dir
    inside it, matching real project layout. Returns data_dir
    (repo_root/process/cairn); repo_root is `data_dir.parent.parent`.
    """
    tmp = helpers.make_empty_tmp_dir(testcase)
    _run_git(tmp, "init", "-q")
    _run_git(tmp, "config", "user.email", "test@example.com")
    _run_git(tmp, "config", "user.name", "Test")
    data_dir = tmp / "process" / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text(
        "prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8"
    )
    (data_dir / "majors" / "PT-V1.md").write_text(
        MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8"
    )
    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")
    _run_git(tmp, "add", ".")
    _run_git(tmp, "commit", "-q", "-m", "initial")
    if branch:
        _run_git(tmp, "checkout", "-q", "-b", branch)
    return data_dir


def make_non_git_data_dir(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text(
        "prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8"
    )
    return data_dir


def make_dist_dir(testcase, *, index_body: str = "<p>dashboard shell</p>") -> Path:
    """A throwaway dist/ fixture: index.html + one real asset it
    references -- the shape build-smoke tests below also check for the
    real committed dist. Never touches the real
    scripts/cairn/dashboard/dist/."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    dist = tmp / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index.js").write_text("console.log('dashboard');\n", encoding="utf-8")
    (dist / "index.html").write_text(
        "<!doctype html><html><head></head><body>"
        f"{index_body}"
        '<script type="module" src="/dashboard/assets/index.js"></script>'
        "</body></html>\n",
        encoding="utf-8",
    )
    return dist


class _RunningServer:
    """Shared start/stop/wait-until-up scaffolding, matching
    ServerTestCase in test_server.py -- duplicated here (not imported)
    because every other *_test.py module in this dir is self-contained
    the same way (see test_milestone_release_state.py's own `_run_git`)."""

    def _start(self, data_dir: Path, **kwargs) -> None:
        self.server = cairn.make_server(data_dir, port=0, **kwargs)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        self._wait_until_up()

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _wait_until_up(self) -> None:
        last_exc = None
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{self.base_url}/api/board", timeout=5).close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")


# ---------------------------------------------------------------------------
# _latest_semver_tag -- pure-function unit tests (no server needed)
# ---------------------------------------------------------------------------

class LatestSemverTagTests(unittest.TestCase):
    """Architect's diff-review blocking fix: a pre-release tag must rank
    BELOW its own final release, not above it -- (major, minor, patch)
    alone ties `v1.0.0`/`v1.0.0-rc1`, and a bare string tiebreak put the
    rc ahead (backwards per semver §11, and the exact scenario
    WORKFLOW.md's own -alpha/-beta/-rc procedure produces)."""

    def test_none_and_empty_input_returns_none(self):
        self.assertIsNone(cairn._latest_semver_tag(None))
        self.assertIsNone(cairn._latest_semver_tag(set()))

    def test_final_release_outranks_its_own_release_candidate(self):
        self.assertEqual(cairn._latest_semver_tag({"v1.0.0", "v1.0.0-rc1"}), "v1.0.0")
        self.assertEqual(cairn._latest_semver_tag({"v1.0.0", "v1.0.0-rc.1"}), "v1.0.0")
        self.assertEqual(cairn._latest_semver_tag({"v2.3.1-beta", "v2.3.1"}), "v2.3.1")

    def test_highest_semver_wins_among_final_releases(self):
        self.assertEqual(
            cairn._latest_semver_tag({"v0.6.0", "v0.7.1", "v0.7.0", "v1.0.0"}),
            "v1.0.0",
        )

    def test_non_semver_tag_sorts_lowest_without_raising(self):
        self.assertEqual(cairn._latest_semver_tag({"v1.0.0", "not-a-version"}), "v1.0.0")
        self.assertEqual(cairn._latest_semver_tag({"not-a-version"}), "not-a-version")


# ---------------------------------------------------------------------------
# GET /api/dashboard -- payload shape + degradation + caching
# ---------------------------------------------------------------------------

class DashboardApiPayloadTests(_RunningServer, unittest.TestCase):
    def setUp(self):
        self.data_dir = make_git_repo(self, branch="feature/pt-54-dashboard-shell")
        (self.data_dir / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(
                id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                status="done", target_tag="v1.0.0", ga="true",
            ),
            encoding="utf-8",
        )
        self.expected_head = _run_git(self.data_dir, "rev-parse", "--short", "HEAD")
        _run_git(self.data_dir, "tag", "v1.0.0")
        (self.data_dir / "issues" / "PT-1.md").write_text(
            ISSUE_TMPL.format(id="PT-1", title="One", status="backlog", milestone="PT-1.0"),
            encoding="utf-8",
        )
        (self.data_dir / "issues" / "PT-2.md").write_text(
            ISSUE_TMPL.format(id="PT-2", title="Two", status="backlog", milestone="PT-1.0"),
            encoding="utf-8",
        )
        (self.data_dir / "issues" / "PT-3.md").write_text(
            ISSUE_TMPL.format(id="PT-3", title="Three", status="done", milestone="PT-1.0"),
            encoding="utf-8",
        )
        self._start(self.data_dir)

    def _get(self, path: str = "/api/dashboard", headers: dict | None = None):
        req = urllib.request.Request(f"{self.base_url}{path}", headers=headers or {})
        return urllib.request.urlopen(req, timeout=5)

    def test_returns_200_json_with_the_top_level_groups(self):
        resp = self._get()
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        payload = json.loads(resp.read())
        for key in ("git", "release", "tracker", "check", "generated_at"):
            self.assertIn(key, payload, payload)

    def test_git_group_reports_branch_dirty_head_latest_tag(self):
        payload = json.loads(self._get().read())
        git = payload["git"]
        self.assertEqual(git["branch"], "feature/pt-54-dashboard-shell")
        self.assertIs(git["dirty"], False)
        self.assertEqual(git["head"], self.expected_head)
        self.assertEqual(git["latest_tag"], "v1.0.0")

    def test_git_group_reports_dirty_true_for_an_uncommitted_change(self):
        (self.data_dir.parent.parent / "README.md").write_text("changed\n", encoding="utf-8")
        payload = json.loads(self._get().read())
        self.assertIs(payload["git"]["dirty"], True)

    def test_release_group_is_the_milestone_matching_the_latest_tag(self):
        payload = json.loads(self._get().read())
        release = payload["release"]
        self.assertIsNotNone(release)
        self.assertEqual(release["id"], "PT-1.0")
        self.assertEqual(release["name"], "MVP")
        self.assertEqual(release["status"], "done")
        self.assertIs(release["ga"], True)

    def test_tracker_group_counts_issues_by_status(self):
        payload = json.loads(self._get().read())
        counts = payload["tracker"]["counts_by_status"]
        self.assertEqual(set(counts), set(cairn.STATUS_ORDER))
        self.assertEqual(counts["backlog"], 2)
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["todo"], 0)

    def test_check_group_reports_cairn_check_result(self):
        payload = json.loads(self._get().read())
        self.assertIs(payload["check"]["ok"], True)
        self.assertEqual(payload["check"]["errors"], [])

    def test_check_group_surfaces_a_real_lint_error(self):
        (self.data_dir / "issues" / "PT-4.md").write_text(
            ISSUE_TMPL.format(id="PT-4", title="Dangling", status="backlog", milestone="PT-404"),
            encoding="utf-8",
        )
        payload = json.loads(self._get().read())
        self.assertIs(payload["check"]["ok"], False)
        self.assertTrue(payload["check"]["errors"])

    def test_response_is_never_cached(self):
        resp = self._get()
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")

    def test_etag_supports_304(self):
        resp = self._get()
        etag = resp.headers.get("ETag")
        self.assertTrue(etag)
        resp.close()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get(headers={"If-None-Match": etag})
        self.assertEqual(ctx.exception.code, 304)

    def test_etag_changes_after_a_tracker_mutation(self):
        resp = self._get()
        old_etag = resp.headers.get("ETag")
        resp.close()
        cairn.apply_patch(self.data_dir / "issues" / "PT-1.md", {"status": "done"})
        resp2 = self._get(headers={"If-None-Match": old_etag})
        self.assertEqual(resp2.status, 200, "stale ETag must not be honored as a 304 after a mutation")
        self.assertNotEqual(resp2.headers.get("ETag"), old_etag)


class DashboardApiReleaseArchivedMilestoneTests(_RunningServer, unittest.TestCase):
    """Regression guard for a deliberate widening implementation-lead made
    beyond the ruling's literal text (flagged in a PT-54 comment for
    architect/team-lead, accepted by team-lead as within scope): the
    release join searches archive/milestones/ too, not just live ones --
    this project's own workflow archives a milestone shortly after its
    tag ships (see WORKFLOW.md's archive-on-done convention), so a
    live-only search would make `release` null for almost every real
    shipped tag (verified against this very repo's own v0.7.1). Locking
    this in with its own test now that it's implemented, since the
    original suite (written before the code existed) had no way to pin
    it.
    """

    def setUp(self):
        self.data_dir = make_git_repo(self)
        (self.data_dir / "archive" / "milestones").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "archive" / "milestones" / "PT-1.0.md").write_text(
            MILESTONE_TMPL.format(
                id="PT-1.0", name="MVP", kind="product", major="PT-V1",
                status="done", target_tag="v1.0.0", ga="true",
            ),
            encoding="utf-8",
        )
        _run_git(self.data_dir, "tag", "v1.0.0")
        self._start(self.data_dir)

    def test_release_group_matches_an_archived_milestone(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        payload = json.loads(resp.read())
        release = payload["release"]
        self.assertIsNotNone(release, "an archived milestone matching the latest tag must still populate release")
        self.assertEqual(release["id"], "PT-1.0")
        self.assertEqual(release["name"], "MVP")


class DashboardApiGitUnavailableTests(_RunningServer, unittest.TestCase):
    """The git-unavailable-degradation item on the ruling's explicit
    testing-shape checklist: a data_dir with no enclosing .git must not
    take the endpoint down -- same `read_git_tags` / `_git_mv_or_rename`
    "fall back, don't crash" posture, applied to the new subprocess calls
    (branch/dirty/head)."""

    def setUp(self):
        self.data_dir = make_non_git_data_dir(self)
        self._start(self.data_dir)

    def test_get_api_dashboard_never_raises_and_degrades_git_fields_to_null(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        self.assertEqual(resp.status, 200)
        payload = json.loads(resp.read())
        self.assertIsNone(payload["git"]["branch"])
        self.assertIsNone(payload["git"]["dirty"])
        self.assertIsNone(payload["git"]["head"])
        self.assertIsNone(payload["git"]["latest_tag"])
        self.assertIsNone(payload["release"])

    def test_tracker_and_check_groups_are_unaffected_by_git_being_unavailable(self):
        # git and tracker/check are independent data sources -- a broken
        # git worktree must not also blank out the parts of the payload
        # that never needed git in the first place.
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        payload = json.loads(resp.read())
        self.assertIn("counts_by_status", payload["tracker"])
        self.assertIn("ok", payload["check"])


# ---------------------------------------------------------------------------
# GET /dashboard(/...) -- serve the built app, via the `dashboard_dir` seam
# ---------------------------------------------------------------------------

class DashboardServeWithDistPresentTests(_RunningServer, unittest.TestCase):
    def setUp(self):
        self.data_dir = make_git_repo(self)
        self.dist_dir = make_dist_dir(self)
        self._start(self.data_dir, dashboard_dir=self.dist_dir)

    def test_dashboard_root_serves_index_html(self):
        resp = urllib.request.urlopen(f"{self.base_url}/dashboard", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        self.assertIn("dashboard shell", resp.read().decode("utf-8"))

    def test_dashboard_root_with_trailing_slash_also_serves_index_html(self):
        resp = urllib.request.urlopen(f"{self.base_url}/dashboard/", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("dashboard shell", resp.read().decode("utf-8"))

    def test_real_dist_asset_is_served(self):
        resp = urllib.request.urlopen(f"{self.base_url}/dashboard/assets/index.js", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("dashboard", resp.read().decode("utf-8"))

    def test_suffixed_path_that_does_not_exist_is_a_404_not_a_spa_fallback(self):
        # "Returning HTML for a missing .js is the classic hours-lost
        # debugging trap" -- the ruling's own words. A `.js`/`.css`/etc.
        # request that 404s must stay a 404, never silently become
        # index.html.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base_url}/dashboard/assets/missing.js", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_extensionless_path_falls_back_to_index_html_for_client_routing(self):
        resp = urllib.request.urlopen(f"{self.base_url}/dashboard/some/client/route", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("dashboard shell", resp.read().decode("utf-8"))

    def test_api_dashboard_is_unaffected_by_dashboard_dir_kwarg(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        self.assertEqual(resp.status, 200)


class DashboardServeMissingDistTests(_RunningServer, unittest.TestCase):
    """The missing-dist branch, exercised via the ruled `dashboard_dir`
    seam rather than deleting/hiding the real committed dist -- a
    nonexistent directory is the honest way to simulate "never built"."""

    def setUp(self):
        self.data_dir = make_git_repo(self)
        empty_tmp = helpers.make_empty_tmp_dir(self)
        self.missing_dist_dir = empty_tmp / "dist"  # deliberately never created
        self._start(self.data_dir, dashboard_dir=self.missing_dist_dir)

    def test_dashboard_root_returns_503_naming_the_fix(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base_url}/dashboard", timeout=5)
        self.assertEqual(ctx.exception.code, 503)
        body = ctx.exception.read().decode("utf-8")
        self.assertIn("npm run build", body)

    def test_api_dashboard_keeps_working_when_dist_is_missing(self):
        # "pure python and has no build dependency" -- the payload
        # endpoint must not couple its availability to the frontend build.
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        self.assertEqual(resp.status, 200)

    def test_cairn_check_does_not_lint_on_dist_presence(self):
        # "a lint error on a clean clone of a repo whose dashboard was
        # never built is noise" -- pin that check_repo has no opinion on
        # scripts/cairn/dashboard/dist at all.
        errors = cairn.check_repo(self.data_dir)
        self.assertEqual(errors, [], "cairn check must not lint on dashboard dist presence")


# ---------------------------------------------------------------------------
# Build smoke -- the committed dist is internally consistent
# ---------------------------------------------------------------------------

class _AssetRefCollector(html.parser.HTMLParser):
    """Collects every src=/href= this repo's dist/index.html could
    plausibly reference (script/link/img) -- deliberately permissive
    (collects all of them, not just module scripts) since the point is
    "nothing referenced is missing," not "only these tags are allowed."""

    ATTRS = ("src", "href")

    def __init__(self):
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for attr in self.ATTRS:
            value = attrs.get(attr)
            if value and not re.match(r"^([a-z]+:)?//|^data:", value):
                self.refs.append(value)


class DashboardBuildSmokeTests(unittest.TestCase):
    """Defined now, checked for real now (the app is already scaffolded
    under scripts/cairn/dashboard/ -- only `dist/` is what's missing/not
    yet committed) -- per the ruling, this is a filesystem + HTML check
    against the COMMITTED dist, never an `npm run build` invocation from
    the test itself."""

    def test_dist_index_html_exists(self):
        self.assertTrue(
            DASHBOARD_DIST_DIR.is_dir(),
            f"{DASHBOARD_DIST_DIR} does not exist -- run `cd {DASHBOARD_SRC_DIR} && "
            "npm ci && npm run build` and commit dist/ per PT-54 ruling #3",
        )
        entry = DASHBOARD_DIST_DIR / "index.html"
        self.assertTrue(entry.is_file(), f"missing {entry}")

    def test_dist_asset_references_all_resolve_to_real_files(self):
        entry = DASHBOARD_DIST_DIR / "index.html"
        if not entry.is_file():
            self.skipTest(f"{entry} not built/committed yet -- see test_dist_index_html_exists")
        parser = _AssetRefCollector()
        parser.feed(entry.read_text(encoding="utf-8"))
        self.assertTrue(parser.refs, "index.html referenced no assets at all -- parser or build looks wrong")
        for ref in parser.refs:
            rel = ref.split("?", 1)[0].lstrip("/")
            if rel.startswith("dashboard/"):
                rel = rel[len("dashboard/"):]  # base: '/dashboard/' prefix (ruling §1)
            target = DASHBOARD_DIST_DIR / rel
            self.assertTrue(target.is_file(), f"{entry} references {ref!r} -> {target} which does not exist")

    def test_asset_filenames_carry_no_content_hash(self):
        # Ruling §3: "Disable content hashing... Stable names mean a
        # rebuild overwrites the same paths." A hashed filename (an
        # 8-char+ hex/base64 chunk before the extension) is the concrete,
        # greppable symptom of that setting having been skipped.
        assets_dir = DASHBOARD_DIST_DIR / "assets"
        if not assets_dir.is_dir():
            self.skipTest(f"{assets_dir} not built/committed yet -- see test_dist_index_html_exists")
        hash_like = re.compile(r"[.\-][0-9a-fA-F]{8,}\.\w+$")
        offenders = [p.name for p in assets_dir.iterdir() if hash_like.search(p.name)]
        self.assertEqual(offenders, [], f"hashed-looking asset filenames (build.rollupOptions not applied?): {offenders}")


if __name__ == "__main__":
    unittest.main()
