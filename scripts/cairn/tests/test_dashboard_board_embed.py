"""PT-55 (Dashboard: embed live kanban/list board) -- guards written before
and after the architect's embed-strategy ruling landed (same-origin iframe
at `/?embed=1`, PT-55 comment 2026-08-27).

The payload-boundary guards below were written BEFORE the ruling, when
PT-55's three embed candidates (iframe of the root board, board.js mounted
into a Svelte DOM node, or a Svelte component re-consuming `/api/board`)
still produced fundamentally different DOM shapes -- a test asserting
anything about DOM structure or interaction wiring at that point would
either be meaningless or bake in a guess team-lead/architect explicitly
asked me not to make. What WAS testable regardless of which strategy was
chosen is the data-path half of AC #1: "no second fetch layer, no
duplicated column list -- PT-36's single-sourcing holds."

The `EmbedQueryParamRoutingTests` class below was added AFTER the ruling --
it pins the one piece of the ruling's test shape that's pure Python
(routing), independent of both the DOM-visibility question and the
URLSearchParams sandbox gap (both escalated to architect/implementation-
lead rather than worked around unilaterally -- see the PT-55 thread).

Mixed red/green is expected and correct here, same posture as
test_column_parity.py's own docstring: these are GUARDS against a future
regression, not red-then-green feature tests -- `/api/dashboard` (PT-54)
already exists and already doesn't duplicate board data, so
`test_dashboard_payload_carries_no_board_data` is GREEN today. It stays in
this suite so that if a future PT-55 implementation widens
`build_dashboard_payload` to also carry issues/majors/milestones (a second,
parallel data path -- exactly what AC #1 forbids), this test goes RED
immediately rather than the drift surviving to a manual review.

`test_column_parity.py`'s existing PT-36 guard (BOARD_COLUMNS/STATUS_ORDER
parity) is not duplicated here -- it already covers "PT-36's single-sourcing
holds" for board-logic.js itself, regardless of how/whether PT-55 embeds it.
"""
from __future__ import annotations

import re
import threading
import time
import unittest
import urllib.request

import helpers  # noqa: F401

import cairn

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"
DASHBOARD_DIST_INDEX_JS = helpers.CAIRN_DIR / "dashboard" / "dist" / "assets" / "index.js"


class DashboardPayloadDoesNotDuplicateBoardDataTests(unittest.TestCase):
    """AC #1 ("no second fetch layer, no duplicated column list"): whatever
    PT-55's embed strategy turns out to be, `/api/dashboard`'s OWN payload
    (`build_dashboard_payload`, PT-54) must stay a status-summary API --
    counts, git state, release, lint -- never a second copy of the
    issues/majors/milestones data `/api/board` already serves. A component
    fetching board content for the embedded lane section must hit
    `/api/board` itself (or reuse whatever board.js already fetches), not
    a parallel field `/api/dashboard` grows for convenience.
    """

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)

    def test_dashboard_payload_carries_no_board_data(self):
        payload = cairn.build_dashboard_payload(self.data_dir)
        for forbidden_key in ("issues", "majors", "milestones", "board"):
            self.assertNotIn(
                forbidden_key, payload,
                f"/api/dashboard must not carry {forbidden_key!r} -- that would be a "
                f"second, duplicated data path for content /api/board already serves "
                f"(PT-55 AC #1 / PT-36 single-sourcing)",
            )

    def test_dashboard_payload_top_level_keys_are_exactly_the_pt54_contract(self):
        # Stronger than the negative check above: pins the WHOLE key set,
        # so a future addition of ANY new top-level group (not just the
        # four obviously-board-shaped names checked individually above)
        # is a deliberate, reviewed change to this test, not a silent
        # payload-shape drift.
        payload = cairn.build_dashboard_payload(self.data_dir)
        self.assertEqual(
            set(payload.keys()),
            {"git", "tracker", "check", "release", "generated_at"},
            "build_dashboard_payload's top-level shape changed -- if this is PT-55 "
            "adding board data to it, that violates AC #1's single-fetch-layer "
            "constraint; if it's a legitimate new field, update this pin deliberately",
        )


class EmbedQueryParamRoutingTests(unittest.TestCase):
    """Ruling's own words: "`/?embed=1` and `/list?embed=1` both return
    board.html 200 (the query string is already stripped by `urlparse`
    before routing)." Verified independently against the running server
    (not taken on the architect's report alone) -- already true today, so
    this is a guard (green now), same posture as the payload-boundary
    tests above: it fails loudly if a future change ever makes routing
    query-string-sensitive.
    """

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.server = cairn.make_server(self.data_dir, port=0)
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

    def _get_html(self, path):
        resp = urllib.request.urlopen(f"{self.base_url}{path}", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        return resp.read().decode("utf-8")

    def test_kanban_root_with_embed_1_serves_board_html(self):
        body = self._get_html("/?embed=1")
        self.assertIn("<html", body.lower())

    def test_list_view_with_embed_1_serves_board_html(self):
        body = self._get_html("/list?embed=1")
        self.assertIn("<html", body.lower())

    def test_embed_query_param_never_reaches_routing_regardless_of_value(self):
        # The routing-level claim, stated strongly: garbage/absent/zero
        # values must 200 exactly the same as embed=1 -- the query string
        # plays no role in whether routing succeeds at all (isEmbedMode's
        # own on/off semantics are a client-side, board.js/board-logic.js
        # concern, tested separately in the JS harness).
        for path in ("/", "/?embed=1", "/?embed=0", "/?embed=garbage", "/?foo=bar"):
            self._get_html(path)


class DashboardIframeEmbedTests(unittest.TestCase):
    """Architect's ruling § 2 ("iframe attributes -- convert the part that
    can be behavioural"): the `<iframe>`'s attribute claims (exactly one,
    has a `title`, no `sandbox`) stay source-text checks against
    App.svelte -- there's no jsdom/vitest harness to render the Svelte
    component for real (same limitation as the board.js DOM checks). The
    `src` literal is different: it's taken from source as text, then fed
    to a REAL running server, converting "does this URL resolve" from a
    source claim into a behavioural one, exactly as ruled.
    """

    def setUp(self):
        self.source = DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")
        iframe_tags = re.findall(r"<iframe\b[^>]*>", self.source)
        self.assertEqual(
            len(iframe_tags), 1,
            f"expected exactly one <iframe> in {DASHBOARD_APP_SVELTE}, found {len(iframe_tags)}: {iframe_tags}",
        )
        self.iframe_tag = iframe_tags[0]

    def test_exactly_one_iframe_present(self):
        # The assertion already ran in setUp (it must hold before any
        # other test in this class can meaningfully run) -- this test
        # exists so "exactly one iframe" has its own named, independently
        # reportable pass/fail line rather than being an implicit
        # side-effect of setUp.
        pass

    def test_iframe_has_a_title_attribute(self):
        self.assertRegex(
            self.iframe_tag, r'\btitle\s*=\s*"[^"]+"',
            f"<iframe> must have a non-empty title attribute for screen-reader traversal "
            f"across the document boundary (ruling): {self.iframe_tag}",
        )

    def test_iframe_has_no_sandbox_attribute(self):
        self.assertNotRegex(
            self.iframe_tag, r"\bsandbox\b",
            f"<iframe> must NOT carry a sandbox attribute -- it would break same-origin "
            f"storage/access for our own same-origin code (ruling, explicit): {self.iframe_tag}",
        )

    def _iframe_src(self) -> str:
        match = re.search(r'\bsrc\s*=\s*"([^"]+)"', self.iframe_tag)
        self.assertIsNotNone(match, f"<iframe> has no src attribute: {self.iframe_tag}")
        return match.group(1)

    def test_iframe_src_resolves_to_200_on_a_live_server(self):
        src = self._iframe_src()
        data_dir = helpers.make_tmp_data_dir(self)
        server = cairn.make_server(data_dir, port=0)
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def _shutdown():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(_shutdown)

        last_exc = None
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base_url}/api/board", timeout=5).close()
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        else:
            raise AssertionError(f"server never came up: {last_exc}")

        resp = urllib.request.urlopen(f"{base_url}{src}", timeout=5)
        self.assertEqual(resp.status, 200, f"iframe src {src!r} did not resolve to 200")

    def test_committed_dist_contains_the_same_src_literal(self):
        # PT-54 §3's committed-dist staleness risk (general fix: PT-58),
        # caught here specifically for this feature: if App.svelte's src
        # ever changes without a rebuild+recommit of dist/, this fails
        # loudly instead of silently shipping a stale embed URL.
        src = self._iframe_src()
        self.assertTrue(
            DASHBOARD_DIST_INDEX_JS.is_file(),
            f"{DASHBOARD_DIST_INDEX_JS} missing -- dist/ not built/committed",
        )
        dist_js = DASHBOARD_DIST_INDEX_JS.read_text(encoding="utf-8")
        self.assertIn(
            src, dist_js,
            f"committed dist/assets/index.js does not contain the iframe src literal {src!r} "
            f"-- stale or half-committed dist (PT-54 §3 staleness risk)",
        )


if __name__ == "__main__":
    unittest.main()
