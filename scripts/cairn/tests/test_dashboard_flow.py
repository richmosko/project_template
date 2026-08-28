"""PT-61 failing tests: `GET /api/flow` / `build_flow_payload(data_dir)` --
the chart panel's data source, per the architect's committed ruling
(process/cairn/issues/PT-61.md, commit 1eae1b2, "chart data source: (a)
git reconstruction, blob-based").

Unlike this feature's sidebar-nav half (test_dashboard_sidebar_nav.py,
source-text guards against a Svelte file), this is server-engine logic
crossing a real process boundary (git subprocesses) -- per this suite's
own working principle, that gets REAL fixtures (actual git repos, actual
commits), never a mocked git. The one deliberate exception is the
caching tests' `subprocess.run` spy, which WRAPS the real call (records
invocation count, never replaces the behavior) -- it's verifying the
memoization CONTRACT ("same HEAD -> no new git walk"), not standing in
for git itself.

Five things the ruling calls out as "worth aiming tests at" (quoted
verbatim from the issue thread), one test class each below:
1. Degradation -- git missing / data_dir outside a worktree -> always
   `series: []` + warning, HTTP 200 never 500 (`read_git_state`'s
   whole-group-degrades posture).
2. Archive-move immunity -- an issue `git mv`'d into `archive/issues/`
   keeps its identity (stem-keyed, not path-keyed) -- doesn't double-
   count or vanish.
3. Byte-slicing -- a blob containing non-ASCII (em dash) must parse
   correctly; the ruling names this a KNOWN-LIVE failure mode from the
   first prototype, not a hypothetical.
4. Taxonomy coupling -- every point's count keys come from
   `cairn.STATUS_ORDER` itself (imported, not hardcoded), so a future
   status addition can't silently leave the chart's key set behind.
5. Cache key -- same HEAD -> memo hit (zero new git subprocesses); a new
   commit -> recompute (at least one new git subprocess).

Nothing under test exists yet: `cairn` has no `build_flow_payload`
attribute at all, and the server has no `/api/flow` route. Every test
below is expected to fail on a genuinely-missing function/route --
either a clear, explicitly-asserted `hasattr` failure (not a bare,
confusing AttributeError from deep in a test body) or a 404 from the
server -- never an import error.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401

import cairn

ISSUE_TMPL = (
    "---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: null\nparent: null\n"
    "assignee: null\nlabels: []\npriority: null\npr: null\ncreated: 2026-08-10\nupdated: 2026-08-10\n"
    "---\n\n{body}\n"
)
MAJOR_TMPL = "---\nid: {id}\nstatus: {status}\nowner: mosko\ntarget_ship: null\nhealth: on-track\n---\n\nBody.\n"


def _git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _commit_at(repo_root: Path, message: str, when: str) -> None:
    """`when`: git raw date format, e.g. '2026-08-10 10:00:00 +0000' --
    always UTC (+0000) so 'which day' is unambiguous regardless of which
    reasonable timezone interpretation build_flow_payload picks."""
    import os

    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = when
    env["GIT_COMMITTER_DATE"] = when
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    _git(repo_root, "add", "-A", env=env)
    _git(repo_root, "commit", "-q", "-m", message, env=env)


def make_flow_git_repo(testcase) -> Path:
    """Fresh git repo (init'd, one commit) with a `process/cairn` data
    dir inside it, same shape test_dashboard.py's make_git_repo uses --
    matches real project layout so `git -C data_dir` discovers the repo
    by walking up, same as production."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "test@example.com")
    _git(tmp, "config", "user.name", "Test")
    data_dir = tmp / "process" / "cairn"
    for sub in ("issues", "archive/issues", "archive/milestones", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    (data_dir / "majors" / "PT-V1.md").write_text(MAJOR_TMPL.format(id="PT-V1", status="in-progress"), encoding="utf-8")
    (tmp / "README.md").write_text("placeholder\n", encoding="utf-8")
    _commit_at(tmp, "initial", "2026-08-09 09:00:00 +0000")
    return data_dir


def make_non_git_data_dir(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive/issues", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
    return data_dir


def _write_issue(data_dir: Path, *, id: str, status: str, title: str = "An issue", body: str = "Body.", archived: bool = False) -> Path:
    rel = ("archive/issues" if archived else "issues")
    path = data_dir / rel / f"{id}.md"
    path.write_text(ISSUE_TMPL.format(id=id, title=title, status=status, body=body), encoding="utf-8")
    return path


def _call_build_flow_payload(data_dir: Path):
    """Every test routes through here so a missing `build_flow_payload`
    fails with one clear, explicit message instead of an opaque
    AttributeError surfacing from inside an unrelated assertion."""
    assert hasattr(cairn, "build_flow_payload"), (
        "cairn.build_flow_payload does not exist yet -- PT-61's ruled chart "
        "data source (git reconstruction, blob-based) is unimplemented"
    )
    return cairn.build_flow_payload(data_dir)


class FlowPayloadDegradationTests(unittest.TestCase):
    def test_non_git_data_dir_returns_empty_series_with_a_warning_not_a_raise(self):
        data_dir = make_non_git_data_dir(self)
        payload = _call_build_flow_payload(data_dir)
        self.assertEqual(payload.get("series"), [])
        self.assertTrue(
            payload.get("warning"),
            "expected a non-empty warning when data_dir isn't inside a git worktree -- "
            "read_git_state's whole-group-degrades posture, not a silent empty series",
        )

    def test_fresh_repo_with_zero_issue_history_returns_empty_series_without_raising(self):
        # A legitimate empty state (matches every fresh template clone),
        # distinct from the degradation case above -- git IS available
        # and data_dir IS a worktree, there's just nothing to plot yet.
        data_dir = make_flow_git_repo(self)
        payload = _call_build_flow_payload(data_dir)
        self.assertEqual(payload.get("series"), [])

    def test_http_endpoint_degrades_to_200_never_500(self):
        data_dir = helpers.make_tmp_data_dir(self)  # fixture copy, not a git worktree
        server = cairn.make_server(data_dir, port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=5)))
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base_url}/api/board", timeout=5).close()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
        try:
            resp = urllib.request.urlopen(f"{base_url}/api/flow", timeout=5)
        except urllib.error.HTTPError as exc:
            self.fail(f"GET /api/flow on a non-git data_dir raised HTTP {exc.code}, expected 200 with an empty series")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body.get("series"), [])


class FlowTaxonomyCouplingTests(unittest.TestCase):
    def test_every_points_counts_keys_match_status_order_exactly(self):
        data_dir = make_flow_git_repo(self)
        _write_issue(data_dir, id="PT-1", status="backlog")
        _commit_at(data_dir.parent.parent, "add PT-1", "2026-08-10 10:00:00 +0000")
        _write_issue(data_dir, id="PT-1", status="in-progress")
        _commit_at(data_dir.parent.parent, "PT-1 -> in-progress", "2026-08-11 10:00:00 +0000")

        payload = _call_build_flow_payload(data_dir)
        self.assertTrue(payload["series"], "expected at least one point after committing issue history")
        expected_keys = set(cairn.STATUS_ORDER)
        for point in payload["series"]:
            self.assertEqual(
                set(point["counts"].keys()), expected_keys,
                f"point {point!r} count keys don't match cairn.STATUS_ORDER exactly -- "
                f"the chart's taxonomy must come from STATUS_ORDER, not a hardcoded/partial key set",
            )


class FlowSameDayFoldingTests(unittest.TestCase):
    def test_two_commits_on_the_same_utc_day_fold_into_one_point_with_the_later_status(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-1", status="backlog")
        _commit_at(repo_root, "add PT-1 backlog", "2026-08-10 10:00:00 +0000")
        _write_issue(data_dir, id="PT-1", status="in-progress")
        _commit_at(repo_root, "PT-1 -> in-progress, same day", "2026-08-10 15:00:00 +0000")

        payload = _call_build_flow_payload(data_dir)
        same_day_points = [p for p in payload["series"] if p["date"] == "2026-08-10"]
        self.assertEqual(
            len(same_day_points), 1,
            f"expected exactly one point for 2026-08-10 (two commits, same day, last wins), "
            f"got {same_day_points!r}",
        )
        self.assertEqual(same_day_points[0]["counts"]["in-progress"], 1)
        self.assertEqual(same_day_points[0]["counts"]["backlog"], 0)


class FlowArchiveMoveImmunityTests(unittest.TestCase):
    def test_an_issue_moved_into_archive_issues_keeps_its_identity_no_double_count_no_vanish(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-2", status="todo")
        _commit_at(repo_root, "add PT-2", "2026-08-10 10:00:00 +0000")

        # git mv, same filename/stem, issues/ -> archive/issues/ -- the
        # exact move the ruling names as the recurring defect class
        # ("keying on the wrong dimension").
        _git(repo_root, "mv", "process/cairn/issues/PT-2.md", "process/cairn/archive/issues/PT-2.md")
        _commit_at(repo_root, "archive PT-2", "2026-08-11 10:00:00 +0000")

        payload = _call_build_flow_payload(data_dir)
        points_by_date = {p["date"]: p for p in payload["series"]}
        self.assertIn("2026-08-10", points_by_date)
        self.assertIn("2026-08-11", points_by_date)
        # Present (not vanished) and counted exactly once (not doubled)
        # on the day of the move -- stem-keying is what makes this hold
        # across the directory change.
        self.assertEqual(
            points_by_date["2026-08-11"]["counts"]["todo"], 1,
            f"PT-2 either vanished or double-counted after its archive/issues/ move: "
            f"{points_by_date['2026-08-11']!r}",
        )

    def test_a_deleted_issue_drops_out_of_later_points(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-3", status="backlog")
        _commit_at(repo_root, "add PT-3", "2026-08-10 10:00:00 +0000")
        (data_dir / "issues" / "PT-3.md").unlink()
        _commit_at(repo_root, "delete PT-3", "2026-08-11 10:00:00 +0000")

        payload = _call_build_flow_payload(data_dir)
        points_by_date = {p["date"]: p for p in payload["series"]}
        self.assertEqual(points_by_date["2026-08-10"]["counts"]["backlog"], 1)
        self.assertEqual(
            points_by_date["2026-08-11"]["counts"]["backlog"], 0,
            "a deleted issue should drop out of the count on the day it was deleted, "
            "per the ruling's 'deletes drop the entity'",
        )


class FlowNonAsciiByteSlicingTests(unittest.TestCase):
    def test_an_em_dash_in_frontmatter_and_body_does_not_corrupt_parsing(self):
        # The ruling names this a KNOWN-LIVE failure mode (the first
        # prototype broke here specifically): git cat-file --batch's size
        # header is a BYTE count, and text-mode slicing on a multi-byte
        # UTF-8 char (em dash, 3 bytes, common in this repo's own issue
        # bodies) mis-slices the blob boundary.
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(
            data_dir, id="PT-4", status="in-review",
            title="Fix the flow endpoint — byte slicing",
            body="See the ruling — em dashes are common in this repo's prose.",
        )
        # A second issue immediately after PT-4 in the batch stream --
        # if PT-4's blob is mis-sliced, this one desyncs and fails to
        # parse too. That desync, not PT-4's own field, is the real
        # regression this test is aimed at.
        _write_issue(data_dir, id="PT-5", status="todo", title="Plain ascii issue")
        _commit_at(repo_root, "add PT-4 and PT-5", "2026-08-10 10:00:00 +0000")

        payload = _call_build_flow_payload(data_dir)
        point = next(p for p in payload["series"] if p["date"] == "2026-08-10")
        self.assertEqual(point["counts"]["in-review"], 1, f"PT-4 (em-dash content) failed to parse correctly: {point!r}")
        self.assertEqual(point["counts"]["todo"], 1, f"PT-5 (after the em-dash blob in the batch) desynced: {point!r}")


class FlowCachingTests(unittest.TestCase):
    def test_repeated_calls_at_the_same_head_add_no_new_git_subprocesses(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-6", status="backlog")
        _commit_at(repo_root, "add PT-6", "2026-08-10 10:00:00 +0000")

        with mock.patch("subprocess.run", wraps=subprocess.run) as spy:
            _call_build_flow_payload(data_dir)
            after_first = spy.call_count
            _call_build_flow_payload(data_dir)
            after_second = spy.call_count
        self.assertEqual(
            after_second, after_first,
            "a second call at the same HEAD triggered new git subprocess(es) -- "
            "the ruling calls for an in-process memo keyed by HEAD sha",
        )

    def test_a_new_commit_invalidates_the_memo_and_triggers_recompute(self):
        data_dir = make_flow_git_repo(self)
        repo_root = data_dir.parent.parent
        _write_issue(data_dir, id="PT-7", status="backlog")
        _commit_at(repo_root, "add PT-7", "2026-08-10 10:00:00 +0000")
        _call_build_flow_payload(data_dir)  # warm the memo at this HEAD

        _write_issue(data_dir, id="PT-7", status="done")
        _commit_at(repo_root, "PT-7 -> done", "2026-08-11 10:00:00 +0000")

        with mock.patch("subprocess.run", wraps=subprocess.run) as spy:
            payload = _call_build_flow_payload(data_dir)
        self.assertGreater(
            spy.call_count, 0,
            "a call at a NEW HEAD triggered zero git subprocesses -- looks like the memo "
            "isn't keyed by HEAD sha (stale data would be served forever)",
        )
        point = next(p for p in payload["series"] if p["date"] == "2026-08-11")
        self.assertEqual(point["counts"]["done"], 1, "the recompute after the new commit didn't pick up the status change")


class FlowEndpointHTTPHeadersTests(unittest.TestCase):
    """`GET /api/flow` on a real git-backed data_dir -- separate endpoint
    (never a key on /api/dashboard), ETag + no-store per the ruling."""

    def setUp(self):
        data_dir = make_flow_git_repo(self)
        _write_issue(data_dir, id="PT-8", status="backlog")
        _commit_at(data_dir.parent.parent, "add PT-8", "2026-08-10 10:00:00 +0000")
        self.server = cairn.make_server(data_dir, port=0)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        self._wait_until_up()

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _wait_until_up(self):
        last_exc = None
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{self.base_url}/api/board", timeout=5).close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")

    def test_flow_endpoint_serves_200_json_with_etag_and_no_store(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/flow", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        self.assertTrue(resp.headers.get("ETag"), "expected an ETag header on /api/flow, per the ruling")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        body = json.loads(resp.read().decode("utf-8"))
        self.assertIn("series", body)
        self.assertIn("as_of", body)

    def test_flow_endpoint_is_not_a_key_on_the_dashboard_payload(self):
        resp = urllib.request.urlopen(f"{self.base_url}/api/dashboard", timeout=5)
        body = json.loads(resp.read().decode("utf-8"))
        self.assertNotIn(
            "flow", body,
            "/api/dashboard must not gain a 'flow' key -- the ruling is explicit that this "
            "is a SEPARATE endpoint (different cost profile/cache key/freshness cadence)",
        )


if __name__ == "__main__":
    unittest.main()
