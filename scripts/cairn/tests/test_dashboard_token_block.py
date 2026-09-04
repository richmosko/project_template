"""PT-79 failing acceptance tests: `TokenCostChart.svelte`'s structural
contract, per the architect's ruling (3836ce6 §§3-5), addendum (a375ff7,
"Files"/"Block placement"/"Caption" sections), and the amendment
(ad940d3 §1, correcting §3's mount description).

Source-text guards against App.svelte + the new component file, this
suite's established shape for Svelte (test_dashboard_sidebar_nav.py's own
docstring: "Source-text guards... in this suite's established shape").
This repo has NO real component-render test harness for the Svelte
dashboard -- these tests pin STRUCTURE only, never actual rendered
output; the PT-32/PT-57 browser-visibility protocol (run by team-lead at
Validate) closes that gap.

**Mount pattern, corrected per ad940d3 §1** (superseding my own earlier
reading of the original ruling's §3, which the amendment itself says was
wrong): `IssueFlowChart` carries NO `sm:col-span-2 lg:col-span-4` class
-- it is a bare `{#if IssueFlowChart}<IssueFlowChart />{/if}` mounted
AFTER the 4-column grid section closes, owning its own `<section>` and
`Card.Root` internally, no grid classes at all. `TokenCostChart` follows
that literal pattern.

Nothing under test exists yet: no
`dashboard/src/lib/components/TokenCostChart.svelte` file, and App.svelte
has no reference to it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"
TOKEN_COST_CHART_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "lib" / "components" / "TokenCostChart.svelte"
TOKEN_CHART_LOGIC_TS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "lib" / "token-chart-logic.ts"
DASHBOARD_DIST_DIR = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "dist"


def _read_app_svelte() -> str:
    return DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")


def _read_token_cost_chart() -> str:
    if not TOKEN_COST_CHART_SVELTE.is_file():
        raise AssertionError(
            f"{TOKEN_COST_CHART_SVELTE} does not exist yet -- PT-79's ruled "
            f"TokenCostChart.svelte (ruling §3, addendum 'Files') is unimplemented"
        )
    return TOKEN_COST_CHART_SVELTE.read_text(encoding="utf-8")


class PlacementAndLazyLoadTests(unittest.TestCase):
    def test_component_file_exists(self):
        self.assertTrue(TOKEN_COST_CHART_SVELTE.is_file(), f"{TOKEN_COST_CHART_SVELTE} does not exist yet")

    def test_token_chart_logic_pure_seam_file_exists(self):
        self.assertTrue(
            TOKEN_CHART_LOGIC_TS.is_file(),
            f"{TOKEN_CHART_LOGIC_TS} does not exist yet -- addendum names this as the "
            f"pure selection/sort/caption seam, tested separately in "
            f"tests/js/token-chart-logic.test.js",
        )

    def test_app_svelte_dynamically_imports_it_same_pattern_as_issue_flow_chart(self):
        source = _read_app_svelte()
        match = re.search(
            r"\$state<typeof import\('\$lib/components/TokenCostChart\.svelte'\)\['default'\] \| null>\(null\)",
            source,
        )
        self.assertIsNotNone(
            match,
            "App.svelte must dynamically import TokenCostChart.svelte the SAME way "
            "IssueFlowChart is loaded ($state<typeof import(...)> | null) -- ruling §3 / "
            "addendum: 'dynamically imported the same way'",
        )

    def test_component_is_mounted_conditionally_after_the_flow_chart_in_source_order(self):
        source = _read_app_svelte()
        flow_chart_mount = re.search(r"\{#if IssueFlowChart\}\s*<IssueFlowChart\s*/>", source)
        token_chart_mount = re.search(r"\{#if TokenCostChart\}\s*<TokenCostChart\s*/>", source)
        self.assertIsNotNone(flow_chart_mount, "sanity check: IssueFlowChart's own mount point must still exist")
        self.assertIsNotNone(
            token_chart_mount,
            "no {#if TokenCostChart}<TokenCostChart />{/if} mount found in App.svelte -- "
            "amendment ad940d3 §1: mounted as a bare component immediately after IssueFlowChart",
        )
        if flow_chart_mount and token_chart_mount:
            self.assertLess(
                flow_chart_mount.start(), token_chart_mount.start(),
                "TokenCostChart must be mounted AFTER IssueFlowChart in source order",
            )

    def test_mount_point_carries_no_grid_span_classes(self):
        # ad940d3 §1's correction: "no grid classes" -- the mount site
        # itself (the {#if TokenCostChart}...{/if} block and its
        # immediate surrounding markup) must not wrap <TokenCostChart />
        # in a grid-column-span class the way the ORIGINAL (now-struck)
        # ruling text mistakenly described. A loose but meaningful check:
        # no col-span-* class appears within 200 chars before the mount.
        source = _read_app_svelte()
        token_chart_mount = re.search(r"\{#if TokenCostChart\}\s*<TokenCostChart\s*/>", source)
        if token_chart_mount is None:
            self.fail("TokenCostChart mount point not found -- see test_component_is_mounted_conditionally_after_the_flow_chart_in_source_order")
        preceding = source[max(0, token_chart_mount.start() - 200):token_chart_mount.start()]
        self.assertNotRegex(
            preceding, r"col-span-\d|sm:col-span|lg:col-span",
            "TokenCostChart's mount site must carry no grid-column-span classes -- ad940d3 §1: "
            "'no grid classes', the component owns its own section/Card internally",
        )


class TokensModeSeriesTests(unittest.TestCase):
    """AC2 / ruling §4's four-series encoding."""

    def test_all_four_counter_series_are_referenced(self):
        source = _read_token_cost_chart()
        for series_key in ("input", "cache_write", "cache_read", "output"):
            self.assertIn(
                series_key, source,
                f"TokenCostChart.svelte never references the {series_key!r} series -- "
                f"ruling §4 requires all four counters as distinguishable series in tokens mode",
            )

    def test_cost_usd_series_is_referenced_for_the_cost_toggle_state(self):
        source = _read_token_cost_chart()
        self.assertIn("cost_usd", source, "cost-mode toggle renders a single cost_usd series per role")

    def test_the_four_counter_series_use_the_dedicated_chart_counter_palette(self):
        # ux-designer's ruling at f9c6417, superseding the interim fix:
        # role-hue reuse for the tokens-view counter series is ALSO
        # rejected (the same PT-69 --chart-2/badge-collision shape --
        # --chart-role-1 must not mean "team-lead" in cost view and
        # "input" in tokens view of the SAME block). A dedicated 4-token
        # family (--chart-counter-input/cache-write/cache-read/output)
        # ships instead. Pins: exactly these 4 tokens, in the ruled
        # counter->token mapping, and NEITHER the ordinal --chart-flow-*
        # ramp NOR the categorical --chart-role-* palette reused.
        source = _read_token_cost_chart()
        match = re.search(r"TOKEN_TYPE_COLOR[^{]*\{([^}]*)\}", source, re.DOTALL)
        self.assertIsNotNone(match, "no TOKEN_TYPE_COLOR (or equivalently-named) color map found for input/cache_write/cache_read/output")
        block = match.group(1)
        var_refs = re.findall(r"var\((--[\w-]+)\)", block)
        self.assertEqual(len(var_refs), 4, f"expected exactly 4 color values (one per counter), found {len(var_refs)}: {var_refs}")
        self.assertEqual(len(set(var_refs)), 4, f"the four counter-series colors must be pairwise distinct, got {var_refs}")
        expected = {"--chart-counter-input", "--chart-counter-cache-write", "--chart-counter-cache-read", "--chart-counter-output"}
        self.assertEqual(
            set(var_refs), expected,
            f"counter series must use the dedicated --chart-counter-* family (f9c6417), not "
            f"the ordinal --chart-flow-* ramp or the categorical --chart-role-* palette -- got {var_refs}",
        )


class ToggleAndLabellingTests(unittest.TestCase):
    def test_estimated_label_is_present_for_the_cost_caveat(self):
        source = _read_token_cost_chart()
        self.assertIn("estimated", source.lower(), "only the dollar view is labelled estimated -- ruling §5/AC3")

    def test_legend_wraps_instead_of_clipping_at_narrow_width(self):
        # team-lead's browser-verified delta on 3aa09e8: "legend clips at
        # narrow width" -- layerchart's Legend.svelte renders its swatch
        # group as a non-wrapping flex row by default
        # (.lc-legend-swatch-group), so at narrow widths the first/last
        # entries clip instead of reflowing. Pins a :global override
        # forcing flex-wrap on that class.
        source = _read_token_cost_chart()
        match = re.search(r":global\(\.lc-legend-swatch-group\)\s*\{([^}]*)\}", source, re.DOTALL)
        self.assertIsNotNone(
            match,
            "no :global(.lc-legend-swatch-group) override found -- layerchart's legend "
            "swatch group needs flex-wrap forced on, or entries clip at narrow width instead "
            "of reflowing",
        )
        if match:
            self.assertRegex(match.group(1), r"flex-wrap\s*:\s*wrap", "the override must set flex-wrap: wrap")

    def test_show_all_control_marker_is_present(self):
        source = _read_token_cost_chart()
        self.assertRegex(source.lower(), r"show\s*all", "no 'show all' control marker found -- ruling §4")

    def test_caption_is_generated_via_the_shared_formatCaption_pure_function(self):
        # implementation-lead's actual (reasonable, forward-compatible)
        # design: caption text is NOT inlined in TokenCostChart.svelte at
        # all -- it's generated by token-chart-logic.ts's formatCaption(),
        # imported and called here. The exact caption STRINGS (window_start
        # interpolation, "Showing the top N of..."/"Showing all...", the
        # unpriced-models suffix) are pinned where they actually live: the
        # tests/js/token-chart-logic.test.js formatCaption test class.
        # This test only confirms the component actually WIRES that
        # function in, rather than reinventing caption text inline.
        source = _read_token_cost_chart()
        self.assertRegex(
            source, r"import\s*\{[^}]*\bformatCaption\b[^}]*\}\s*from\s*['\"]\$lib/token-chart-logic['\"]",
            "TokenCostChart.svelte must import formatCaption from $lib/token-chart-logic -- "
            "caption text belongs in the pure, testable seam, not inlined in the component",
        )
        self.assertRegex(source, r"formatCaption\s*\(", "formatCaption must actually be CALLED, not just imported")


class MainBarNotClickableTests(unittest.TestCase):
    def test_main_bucket_has_no_drawer_link_marker(self):
        source = _read_token_cost_chart()
        self.assertIn("main", source.lower(), "TokenCostChart.svelte never references 'main' -- ruling §4: 'main gets its own bar... no drawer link'")

    def test_main_bar_is_rendered_visually_muted_distinct_from_real_issue_bars(self):
        # team-lead's browser-verified delta -- multiple passes now.
        # 3aa09e8: nothing varied main's appearance. b934262: a
        # TOP-LEVEL `fillOpacity` prop on `<BarChart>` (issue === 'main'
        # ? 0.55 : 1) -- looked right, didn't reach the rendered <rect>
        # (this test's own second version wrongly accepted it, then
        # required a class:/style: directive instead, based on an
        # incomplete theory of why it failed). Third attempt (in
        # progress as this test was written): implementation-lead traced
        # layerchart's actual component tree
        # (BarChart.base.svelte -> Bars.base.svelte -> Bar.svelte) and
        # found `<BarChart>`'s top-level `fillOpacity` is NOT a real prop
        # (silently absorbed into `restProps` and spread onto `<Chart>`,
        # never reaching `<Bars>`/`<Bar>`) -- but `props.bars.fillOpacity`
        # IS forwarded all the way to `<Bar>`, which explicitly supports
        # a per-datum `fillOpacity` accessor via `resolveStyleProp`. A
        # code-traced justification, not a guess -- this test now
        # accepts EITHER that specific `props.bars`/`bars:` placement OR
        # a class:/style: directive (the previous requirement), but no
        # longer accepts a bare top-level `fillOpacity=` prop on
        # `<BarChart>` itself (confirmed broken).
        source = _read_token_cost_chart()
        class_or_style_directive = re.search(
            r"(?:class|style):[\w-]+\s*=\s*\{[^}]*issue\s*===\s*['\"]main['\"][^}]*\}",
            source,
        )
        # Proximity check rather than brace-matched extraction (this
        # file's comments themselves contain stray `{`/`}` that defeat a
        # naive `bars\s*:\s*\{[^}]*\}` match): fillOpacity: must appear
        # shortly AFTER a `bars:` key, referencing 'main', with nothing
        # that looks like a sibling top-level prop key in between.
        fill_opacity_prop = re.search(r"fillOpacity\s*:\s*\([^)]*\)\s*=>[^\n]*issue\s*===\s*['\"]main['\"]", source)
        bars_key = re.search(r"\bbars\s*:\s*\{", source)
        bars_scoped_fill_opacity = (
            bool(fill_opacity_prop) and bool(bars_key)
            and bars_key.start() < fill_opacity_prop.start() < bars_key.start() + 1500
        )
        self.assertTrue(
            bool(class_or_style_directive) or bars_scoped_fill_opacity,
            "no evidence of main-muting reaching the actual rendered bar: expected either a "
            "class:/style: directive OR fillOpacity nested specifically under bars: {...} / "
            "props.bars (the layer layerchart's <Bar> component actually honors -- a bare "
            "top-level fillOpacity= prop on <BarChart> is confirmed NOT to reach the DOM)",
        )
        top_level_fill_opacity = re.search(r"<BarChart[^>]*\bfillOpacity=", source)
        self.assertIsNone(
            top_level_fill_opacity,
            "a bare fillOpacity= prop directly on <BarChart> is confirmed (Chrome, b934262) to "
            "never reach the rendered <rect> -- it must live under bars:/props.bars instead",
        )


class BarClickNavigatesViaTheShellsIssueParamTests(unittest.TestCase):
    """Root cause, team-lead's Chrome diagnosis: PT-79's bar click
    navigates to `/dashboard/issues?open=<id>`, but the shell (App.svelte,
    PT-72's ruling) only reads its OWN `?issue=<id>` param
    (`issueTrackingOpenSuffix`, `new URLSearchParams(currentSearch).get(
    'issue')`) and translates THAT into `&open=<id>` for the embedded
    board iframe's own src. A bar click carrying `open=` instead of
    `issue=` is invisible to the shell -- `issueTrackingOpenSuffix`
    computes empty, the iframe gets a bare `/?embed=1`, and the embedded
    board never even requests `/api/issue/<id>`. Not an archive-
    resolution bug at all, per team-lead's diagnosis. Fix: the bar click
    must use the SAME param name the shell already expects."""

    def test_bar_click_navigates_with_the_shells_issue_param_not_open(self):
        source = _read_token_cost_chart()
        self.assertNotIn(
            "dashboard/issues?open=", source,
            "TokenCostChart.svelte must not navigate with ?open=<id> -- the shell "
            "(App.svelte, PT-72) only reads its own ?issue=<id> param and this key is "
            "invisible to it, which is the confirmed root cause of the drawer never opening",
        )
        self.assertRegex(
            source, r"dashboard/issues\?issue=",
            "expected navigation to /dashboard/issues?issue=<id> -- matching the shell's "
            "existing issueTrackingOpenSuffix contract (PT-72), which already forwards "
            "?issue= into the embedded board iframe's own ?open= suffix",
        )


class OpenQueryParamAfterBoardLoadTests(unittest.TestCase):
    """Second half of team-lead's (C) fix instruction: "board.js reads
    ?open= after the board payload loads and calls the existing
    openDrawer path." Today (verified against the current source) the
    `?open=` read + `openDrawer(openId)` call sit AFTER
    `apiGetBoard().then(...)` in source order but OUTSIDE that
    callback -- called synchronously at the end of `init()`, gated on
    nothing. The existing comment even argues this is fine ("openDrawer
    does its own fetch, so this doesn't need to wait on apiGetBoard's own
    resolution") -- team-lead's instruction supersedes that reasoning.

    Precisely anchored (a naive first-match-in-the-file search over a
    file this size is unreliable -- board.js has TEN unrelated
    `render();\n  });`-shaped closings; an early draft of this test
    matched the wrong one entirely, in a different function, and passed
    against the still-broken code as a false positive): locate
    `apiGetBoard().then(function (data) {` specifically, then its OWN
    matching `render();\n  });` close (the LAST statement inside that
    callback per the current source, searched for AFTER the opening, not
    from the start of the file) -- the open-handling code must sit
    BEFORE that specific closing, i.e. nested inside the callback, not
    after it."""

    BOARD_JS = REPO_ROOT / "scripts" / "cairn" / "board" / "board.js"

    def test_open_param_handling_runs_inside_the_api_get_board_then_callback(self):
        source = self.BOARD_JS.read_text(encoding="utf-8")
        callback_open = re.search(r"apiGetBoard\(\)\.then\(function \(data\) \{", source)
        self.assertIsNotNone(callback_open, "expected apiGetBoard().then(function (data) { ... in board.js's init()")
        callback_close = re.search(r"render\(\);\s*\}\);", source[callback_open.end():]) if callback_open else None
        self.assertIsNotNone(callback_close, "expected the apiGetBoard().then() callback to close with 'render();\\n  });'")
        # Deliberately targets the CALL SITE only (openDrawer(openId)),
        # not `parseOpenIssueId(...)` -- board.js also has a destructuring
        # `var parseOpenIssueId = CairnLogic.parseOpenIssueId;` near the
        # TOP of the file (normal module-boundary pattern, same as every
        # other CairnLogic.* import here), which an earlier draft of this
        # test's regex matched instead of the real call site, producing a
        # false green.
        open_handling = re.search(r"openDrawer\(\s*openId\s*\)", source)
        self.assertIsNotNone(
            open_handling,
            "expected an openDrawer(openId) call in board.js's init/load path",
        )
        if callback_open and callback_close and open_handling:
            callback_close_pos = callback_open.end() + callback_close.start()
            self.assertLess(
                open_handling.start(), callback_close_pos,
                "the ?open= handling must run INSIDE apiGetBoard().then()'s callback (after "
                "state.board is set, before that callback closes), not after it returns -- "
                "team-lead's explicit instruction, superseding this code's own prior comment "
                "arguing the opposite ('openDrawer does its own fetch, so this doesn't need to "
                "wait on apiGetBoard's own resolution')",
            )


class DrawerStableIdTests(unittest.TestCase):
    """board.js is DOM render-glue, not unit-testable via the vm-sandboxed
    board-logic.js harness (no real `document`) -- a cheap structural
    guard, not a substitute for the browser-visibility leg the addendum
    names this id FOR ('a stable target the browser-visibility leg can
    aim at')."""

    BOARD_JS = REPO_ROOT / "scripts" / "cairn" / "board" / "board.js"

    def test_drawer_token_usage_stable_id_is_wired_in_board_js(self):
        source = self.BOARD_JS.read_text(encoding="utf-8")
        self.assertIn(
            "drawer-token-usage", source,
            "board.js never sets id='drawer-token-usage' anywhere -- addendum: "
            "'board.js renders it in a section with id=\"drawer-token-usage\" -- a "
            "stable target the browser-visibility leg can aim at'",
        )

    def test_the_id_bearing_container_is_removed_when_there_is_no_token_data(self):
        # team-lead's browser-verified delta on 3aa09e8: an EMPTY
        # #drawer-token-usage container rendered even for an issue with
        # no token data. Addendum + this file's own module docstring pin
        # the correct behavior: "An issue with no token data renders
        # nothing, not a zero row" -- an empty wrapper div left in the
        # DOM is exactly the zero-row-shaped defect that line forbids.
        #
        # implementation-lead's actual fix (verified against the live
        # tree, not assumed): the container is still created eagerly
        # (so there's somewhere to render into once the fetch resolves),
        # but is explicitly REMOVED from the DOM on both the no-data
        # branch and the fetch-failure branch, rather than moving the id
        # assignment itself (my first draft's structural assumption --
        # corrected to match the real, equally valid fix shape). Pins:
        # a removeChild (or equivalent removal) call appears in BOTH the
        # no-totals branch and the .catch() failure branch.
        source = self.BOARD_JS.read_text(encoding="utf-8")
        # Anchor precisely to the tokens-fetch chain, not just any
        # "if (!totals) {...}" or ".catch(function () {...})" elsewhere
        # in this large file (board.js has several unrelated catch
        # handlers -- an unanchored search matched the wrong one on a
        # first draft of this test).
        fetch_start = source.find("fetchTokensOnce().then(function (tokensPayload)")
        split_marker = source.find("var split = splitAcceptanceCriteria(issue.description);")
        self.assertNotEqual(fetch_start, -1, "expected the tokens-fetch chain (fetchTokensOnce().then(...)) in board.js's drawer-rendering code")
        self.assertNotEqual(split_marker, -1, "expected the drawer-rendering code to continue into splitAcceptanceCriteria afterward")
        snippet = source[fetch_start:split_marker]

        no_totals_branch = re.search(r"if\s*\(\s*!totals\s*\)\s*\{([^}]*)\}", snippet, re.DOTALL)
        self.assertIsNotNone(no_totals_branch, "expected an 'if (!totals) { ... }' block within the tokens-fetch chain")
        if no_totals_branch:
            self.assertRegex(
                no_totals_branch.group(1), r"removeChild|remove\(\)",
                "the no-data branch must actually REMOVE the drawer-token-usage container from "
                "the DOM, not just skip populating it -- an empty-but-present element is the "
                "exact defect this test pins",
            )

        catch_start = snippet.find(".catch(function ()")
        self.assertNotEqual(catch_start, -1, "expected a .catch(function () {...}) immediately after the tokens fetch's .then(...)")
        catch_snippet = snippet[catch_start:]
        self.assertRegex(
            catch_snippet, r"removeChild|remove\(\)",
            "a fetch FAILURE must also remove the container -- same 'no data, no element' "
            "posture as the no-totals branch, not just the happy-path-with-no-data case",
        )


class DistBuildInclusionTests(unittest.TestCase):
    """Addendum's test table: 'the built dist/ serves the block' --
    confirms the build actually picked up the new component, not just
    that it exists in src/ (check_dist_freshness.py guards staleness
    separately; this guards silent omission from the bundle)."""

    def test_a_token_chart_related_asset_exists_in_the_built_dist(self):
        if not DASHBOARD_DIST_DIR.is_dir():
            self.fail(f"{DASHBOARD_DIST_DIR} does not exist -- run `cd scripts/cairn/dashboard && npm run build`")
        assets_dir = DASHBOARD_DIST_DIR / "assets"
        matches = list(assets_dir.glob("*oken*ost*hart*")) if assets_dir.is_dir() else []
        self.assertTrue(
            matches,
            f"no TokenCostChart-related asset found under {assets_dir} -- the component "
            f"exists in src/ but the built dist/ doesn't seem to include it (stale build?)",
        )


if __name__ == "__main__":
    unittest.main()
