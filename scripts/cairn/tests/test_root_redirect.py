"""PT-73 scope addition (Mosko's ruling, 2026-08-31, "bare / loads the
dashboard") + architect's mechanics ruling (issue thread, 2026-08-30):
server-side redirect from `/` to `/dashboard`, with two mandatory carve-
outs (embed requests, missing/incomplete dist) plus a `/board` never-
redirecting alias to keep the standalone Kanban tab reachable.

Nothing under this file exists yet -- confirmed by reading `cairn.py`'s
route block directly before writing anything: `path in ("/", "/list")`
unconditionally serves `board.html`, no redirect logic anywhere, no
`/board` route, `board.html`'s Kanban tab is still `<a href="/">`.

**Ruled mechanics, all pinned below:**
1. **302, not 301/308** + `Cache-Control: no-store` -- the redirect's
   predicate is filesystem state that CHANGES (dist gets built/deleted);
   a permanent redirect would get cached past the point it stops being
   true, with no way for the server to correct a browser that stopped
   asking.
2. **Dist-presence check is `(dashboard_dir / "index.html").is_file()`**,
   not `dashboard_dir.is_dir()` -- a dist/ that exists but is empty or
   partially cleaned must NOT redirect users away from a serviceable
   board into a broken dashboard.
3. **Embed carve-out is a recursion guard**, not a convenience -- the
   shell iframes `/?embed=1`; if THAT redirected, the iframe would load
   `/dashboard`, which mounts an iframe at `/?embed=1`, which redirects...
   Mirrors `isEmbedMode`'s exact semantics: key `embed` present with value
   `"1"`, position/other-params irrelevant.
4. **Query strings are not forwarded** -- redirect target is bare
   `/dashboard`, dropping any non-embed query string entirely (nothing
   currently needs to survive the hop).
5. **`/list` stays a deep-link, never redirects.**
6. **New `/board` alias** -- never redirects, serves `board.html`, and
   `board.html`'s Kanban tab (`#tab-kanban`) points at it instead of the
   old bare `/` (which would now redirect standalone-Kanban users into
   the dashboard, making that view "unreachable whenever dist exists" --
   exactly the trap architect flagged).
7. **`/dashboard` itself must never gain a redirect** -- the shared
   dist-presence predicate lives in ONE helper both `/` and `/dashboard`
   call, so they can't drift into disagreeing about whether the
   dashboard exists (a loop or a dead end).
"""
from __future__ import annotations

import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

import cairn

BOARD_HTML = helpers.CAIRN_DIR / "board" / "board.html"


def make_dist_dir(testcase, *, index_body: str = "<p>dashboard shell</p>") -> Path:
    """Same shape as test_dashboard.py's own fixture helper, duplicated
    locally per this suite's established per-file self-containment
    convention (see test_dashboard.py's own docstring on why: 'every
    other *_test.py module in this dir is self-contained the same way')."""
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
    """Same shared start/stop/wait-until-up scaffolding as test_dashboard.py's
    own `_RunningServer` -- duplicated, not imported, per this suite's
    established per-file self-containment convention."""

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

    def _get_no_redirect(self, path: str):
        """urlopen with redirects disabled, so a 302 is observable as a
        302 rather than being silently followed to its target. Also
        catches HTTPError (raised by urllib for any non-2xx status,
        including a genuinely-absent route's 404) and returns it
        directly -- HTTPError is itself a valid response-like object
        with `.status`/`.headers`, so callers can assert on either a
        real response or an error response uniformly."""

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        try:
            return opener.open(f"{self.base_url}{path}", timeout=5)
        except urllib.error.HTTPError as exc:
            return exc


class RootRedirectsToDashboardWhenDistPresentTests(_RunningServer, unittest.TestCase):
    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.dist_dir = make_dist_dir(self)
        self._start(self.data_dir, dashboard_dir=self.dist_dir)

    def test_root_redirects_with_302(self):
        resp = self._get_no_redirect("/")
        self.assertEqual(resp.status, 302, f"expected 302, got {resp.status}")

    def test_root_redirect_targets_bare_dashboard(self):
        resp = self._get_no_redirect("/")
        self.assertEqual(resp.headers.get("Location"), "/dashboard")

    def test_root_redirect_carries_cache_control_no_store(self):
        # The cache header matters MORE than the status code per the
        # ruling: a cached redirect that outlives the dist/ that
        # justified it is unfixable from the server side (the browser
        # stops asking).
        resp = self._get_no_redirect("/")
        self.assertEqual(
            resp.headers.get("Cache-Control"), "no-store",
            "the root redirect must carry Cache-Control: no-store -- some browsers/proxies "
            "cache 302s too, and this redirect's validity depends on filesystem state "
            "(dist/) that can change at any time.",
        )

    def test_root_redirect_does_not_forward_query_strings(self):
        resp = self._get_no_redirect("/?foo=bar")
        self.assertEqual(
            resp.headers.get("Location"), "/dashboard",
            "a non-embed query string must be dropped, not forwarded, on redirect -- nothing "
            "currently needs to survive the hop to /dashboard.",
        )

    def test_dashboard_target_itself_never_redirects(self):
        # The loop-prevention invariant: /dashboard must serve directly,
        # never gain a redirect of its own.
        resp = urllib.request.urlopen(f"{self.base_url}/dashboard", timeout=5)
        self.assertEqual(resp.status, 200)


class EmbedRequestsNeverRedirectTests(_RunningServer, unittest.TestCase):
    """The recursion guard, named its own test class per the ruling's
    explicit ask: 'This needs its own named test, not incidental
    coverage.' Mirrors isEmbedMode's exact semantics -- key `embed`
    present with value "1", position and other params irrelevant."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.dist_dir = make_dist_dir(self)
        self._start(self.data_dir, dashboard_dir=self.dist_dir)

    def _assert_serves_board_not_redirect(self, path):
        resp = self._get_no_redirect(path)
        self.assertEqual(
            resp.status, 200,
            f"{path}: expected 200 (board HTML, no redirect) -- an embed request must never "
            f"redirect, or the shell's iframe recurses into the dashboard, which mounts "
            f"another /?embed=1 iframe, which redirects again.",
        )

    def test_bare_embed_param_serves_board(self):
        self._assert_serves_board_not_redirect("/?embed=1")

    def test_embed_alongside_readonly_serves_board(self):
        self._assert_serves_board_not_redirect("/?embed=1&readonly=1")

    def test_readonly_before_embed_in_query_order_still_serves_board(self):
        # Position in the query string is irrelevant per the ruling --
        # mirroring isEmbedMode's own JS-side semantics exactly.
        self._assert_serves_board_not_redirect("/?readonly=1&embed=1")

    def test_embed_alongside_open_serves_board(self):
        self._assert_serves_board_not_redirect("/?embed=1&open=PT-1")

    def test_embed_alongside_readonly_and_open_serves_board(self):
        self._assert_serves_board_not_redirect("/?embed=1&readonly=1&open=PT-1")


class RootServesBoardWhenDistMissingTests(_RunningServer, unittest.TestCase):
    """Zero-build fallback: a fresh clone with no `npm run build` ever
    run must still get a working board at `/`, never a redirect into a
    503."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        empty_tmp = helpers.make_empty_tmp_dir(self)
        self.missing_dist_dir = empty_tmp / "dist"  # deliberately never created
        self._start(self.data_dir, dashboard_dir=self.missing_dist_dir)

    def test_root_serves_board_html_not_a_redirect(self):
        resp = self._get_no_redirect("/")
        self.assertEqual(resp.status, 200, "expected 200 (board HTML) when dist is entirely absent")


class RootServesBoardWhenDistIsIncompleteTests(_RunningServer, unittest.TestCase):
    """Architect's explicit edge case: a dist/ directory that EXISTS but
    is empty/partially cleaned must not redirect either -- the predicate
    is `(dashboard_dir / "index.html").is_file()`, not `dashboard_dir.
    is_dir()`."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        empty_tmp = helpers.make_empty_tmp_dir(self)
        self.incomplete_dist_dir = empty_tmp / "dist"
        self.incomplete_dist_dir.mkdir()  # directory exists...
        # ...but no index.html inside it -- the "half-cleaned" state.

        self._start(self.data_dir, dashboard_dir=self.incomplete_dist_dir)

    def test_root_serves_board_html_when_dist_dir_exists_but_index_html_is_missing(self):
        resp = self._get_no_redirect("/")
        self.assertEqual(
            resp.status, 200,
            "expected 200 (board HTML) when dashboard_dir exists as a directory but has no "
            "index.html inside it -- redirecting here would send users into a 503, not a "
            "working dashboard.",
        )


class ListNeverRedirectsTests(_RunningServer, unittest.TestCase):
    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.dist_dir = make_dist_dir(self)
        self._start(self.data_dir, dashboard_dir=self.dist_dir)

    def test_list_serves_board_html_not_a_redirect(self):
        resp = self._get_no_redirect("/list")
        self.assertEqual(resp.status, 200, "/list must stay a deep-link, never redirect")


class BoardAliasNeverRedirectsTests(_RunningServer, unittest.TestCase):
    """The new /board alias: never redirects regardless of dist state,
    keeping the standalone Kanban view reachable even when the dashboard
    is built (the trap architect flagged: board.html's Kanban tab is
    `<a href="/">`, and without this alias, clicking it with dist present
    would now bounce the user into the dashboard)."""

    def test_board_serves_board_html_when_dist_present(self):
        data_dir = helpers.make_tmp_data_dir(self)
        dist_dir = make_dist_dir(self)
        self._start(data_dir, dashboard_dir=dist_dir)
        resp = self._get_no_redirect("/board")
        self.assertEqual(resp.status, 200, "/board must serve the board directly, never redirect")

    def test_board_serves_board_html_when_dist_missing(self):
        data_dir = helpers.make_tmp_data_dir(self)
        empty_tmp = helpers.make_empty_tmp_dir(self)
        missing_dist_dir = empty_tmp / "dist"
        self._start(data_dir, dashboard_dir=missing_dist_dir)
        resp = self._get_no_redirect("/board")
        self.assertEqual(resp.status, 200, "/board must work with no dist/ at all too")


class BoardHtmlKanbanTabPointsAtBoardAliasTests(unittest.TestCase):
    """Source-level pin: board.html's Kanban tab must point at the new
    `/board` alias, not the old bare `/` (which now redirects when dist
    is present -- the exact trap architect's ruling names)."""

    def test_kanban_tab_href_is_the_board_alias_not_bare_root(self):
        self.assertTrue(BOARD_HTML.is_file(), f"{BOARD_HTML} does not exist")
        source = BOARD_HTML.read_text(encoding="utf-8")
        match = re.search(r'<a\s+href="([^"]*)"\s+id="tab-kanban"', source)
        self.assertIsNotNone(match, f'{BOARD_HTML}: no <a href="..." id="tab-kanban"> found')
        self.assertEqual(
            match.group(1), "/board",
            f"{BOARD_HTML}: the Kanban tab still targets {match.group(1)!r} -- once dist is "
            f"present, bare `/` redirects into the dashboard, making standalone Kanban "
            f"unreachable from this tab. It must point at the new never-redirecting /board "
            f"alias instead.",
        )


if __name__ == "__main__":
    unittest.main()
