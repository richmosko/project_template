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
    can be behavioural"): the `<iframe>`'s attribute claims (has a
    `title`, no `sandbox`) stay source-text checks against App.svelte --
    there's no jsdom/vitest harness to render the Svelte component for
    real (same limitation as the board.js DOM checks). The `src` literal
    is different: it's taken from source as text, then fed to a REAL
    running server, converting "does this URL resolve" from a source
    claim into a behavioural one, exactly as ruled.

    RETARGETED (PT-72, architect's unified-shell ruling): the original
    "exactly one <iframe>" assumption is superseded, not violated --
    App.svelte legitimately carries TWO now: the read-only home preview
    (`/?embed=1&readonly=1`) and the Issue Tracking page's own full-edit
    embed (`/?embed=1{issueTrackingOpenSuffix}`, a Svelte template literal
    whose dynamic suffix is empty at rest -- no `?issue=` in the shell
    URL). Every test below now walks ALL iframes rather than assuming one;
    src resolution/dist-containment checks operate on each iframe's STATIC
    prefix (the part before any `{...}` interpolation), which is what the
    iframe actually requests with no issue param set -- the dynamic
    `&open=<id>` suffix itself is board.js's own concern
    (`test_shell_readonly_embed.py`'s `OpenIdDeepLinkTests`), not
    re-tested here.
    """

    def setUp(self):
        self.source = DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")
        self.iframe_tags = re.findall(r"<iframe\b[^>]*>", self.source, re.DOTALL)
        self.assertGreaterEqual(
            len(self.iframe_tags), 2,
            f"expected at least 2 <iframe>s in {DASHBOARD_APP_SVELTE} (PT-72: the read-only "
            f"home preview + the Issue Tracking page's own full-edit embed), found "
            f"{len(self.iframe_tags)}: {self.iframe_tags}",
        )

    def test_at_least_two_iframes_present(self):
        # The assertion already ran in setUp (it must hold before any
        # other test in this class can meaningfully run) -- this test
        # exists so "at least two iframes" has its own named,
        # independently reportable pass/fail line rather than being an
        # implicit side-effect of setUp.
        pass

    def test_every_iframe_has_a_title_attribute(self):
        for tag in self.iframe_tags:
            self.assertRegex(
                tag, r'\btitle\s*=\s*"[^"]+"',
                f"<iframe> must have a non-empty title attribute for screen-reader traversal "
                f"across the document boundary (ruling): {tag}",
            )

    def test_no_iframe_has_a_sandbox_attribute(self):
        for tag in self.iframe_tags:
            self.assertNotRegex(
                tag, r"\bsandbox\b",
                f"<iframe> must NOT carry a sandbox attribute -- it would break same-origin "
                f"storage/access for our own same-origin code (ruling, explicit): {tag}",
            )

    def _static_iframe_srcs(self) -> list:
        # `src="..."` for each iframe, truncated at the first `{` --
        # i.e. the STATIC prefix, ignoring any Svelte template
        # interpolation. For the home preview this is the whole literal
        # unchanged (`/?embed=1&readonly=1`, no interpolation at all);
        # for the Issue Tracking embed it strips the dynamic
        # `{issueTrackingOpenSuffix}` down to `/?embed=1`, which is
        # exactly what that iframe requests when no `?issue=` is present
        # in the shell URL (the suffix is empty at rest).
        srcs = []
        for tag in self.iframe_tags:
            match = re.search(r'src="([^"]*)"', tag)
            self.assertIsNotNone(match, f"<iframe> has no src attribute: {tag}")
            srcs.append(match.group(1).split("{")[0])
        return srcs

    def test_every_iframe_src_resolves_to_200_on_a_live_server(self):
        srcs = self._static_iframe_srcs()
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

        for src in srcs:
            resp = urllib.request.urlopen(f"{base_url}{src}", timeout=5)
            self.assertEqual(resp.status, 200, f"iframe src {src!r} did not resolve to 200")

    def test_committed_dist_contains_every_iframe_src_static_prefix(self):
        # PT-54 §3's committed-dist staleness risk (general fix: PT-58),
        # caught here specifically for this feature: if App.svelte's src
        # ever changes without a rebuild+recommit of dist/, this fails
        # loudly instead of silently shipping a stale embed URL.
        srcs = self._static_iframe_srcs()
        self.assertTrue(
            DASHBOARD_DIST_INDEX_JS.is_file(),
            f"{DASHBOARD_DIST_INDEX_JS} missing -- dist/ not built/committed",
        )
        dist_js = DASHBOARD_DIST_INDEX_JS.read_text(encoding="utf-8")
        for src in set(srcs):
            # Svelte's compiler HTML-entity-escapes `&` in static
            # attribute text (`&` -> `&amp;`) -- never surfaced by the
            # original single-iframe test since its only src (`/?embed=1`)
            # had no `&` at all. The home preview's new
            # `/?embed=1&readonly=1` does, so accept either form: this is
            # a real compile-time transform, not staleness.
            escaped = src.replace("&", "&amp;")
            self.assertTrue(
                src in dist_js or escaped in dist_js,
                f"committed dist/assets/index.js does not contain the iframe src static "
                f"prefix {src!r} (checked both the raw literal and its HTML-entity-escaped "
                f"form {escaped!r}) -- stale or half-committed dist (PT-54 §3 staleness risk)",
            )


if __name__ == "__main__":
    unittest.main()
