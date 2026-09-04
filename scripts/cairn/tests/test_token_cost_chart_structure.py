"""PT-79 failing acceptance tests: `TokenCostChart.svelte`'s structural
contract, per the architect's ruling (process/cairn/issues/PT-79.md,
commit 3836ce6, §§3-5).

Source-text guards against App.svelte + the new component file, this
suite's established shape for Svelte (test_dashboard_sidebar_nav.py's own
docstring: "Source-text guards... in this suite's established shape").
This repo has NO real component-render test harness for the Svelte
dashboard (checked: no `.test.js`/`.spec.js` under `dashboard/src`, no
`test` script in `dashboard/package.json`, IssueFlowChart.svelte itself
has zero render-level test coverage anywhere in this suite) -- these
tests can only pin STRUCTURE (imports, markers, source order), never
actual rendered output. That gap is exactly what the PT-32/PT-57
browser-visibility protocol exists to close at Validate; see this
feature's manual checklist (parked separately, run by team-lead).

**Discrepancy flagged, not silently encoded as a test:** the ruling's §3
says the new Card.Root should match "the flow chart's own `sm:col-span-2
lg:col-span-4` span" -- but as committed today, `IssueFlowChart` is
rendered OUTSIDE the grid `<section>` that class lives on (that section
closes before `{#if IssueFlowChart}` appears), so IssueFlowChart itself
does not currently carry that class anywhere. Asserting TokenCostChart
has it would pin an accurate reading of a ruling built on an inaccurate
premise. This file tests placement (after IssueFlowChart, same dynamic-
import shape) and leaves the exact spanning class unpinned; flag to
team-lead/architect before merge.

Nothing under test exists yet: no
`dashboard/src/lib/components/TokenCostChart.svelte` file, and App.svelte
has no reference to it at all.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"
TOKEN_COST_CHART_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "lib" / "components" / "TokenCostChart.svelte"


def _read_app_svelte() -> str:
    return DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")


def _read_token_cost_chart() -> str:
    if not TOKEN_COST_CHART_SVELTE.is_file():
        raise AssertionError(
            f"{TOKEN_COST_CHART_SVELTE} does not exist yet -- PT-79's ruled "
            f"TokenCostChart.svelte (ruling §3) is unimplemented"
        )
    return TOKEN_COST_CHART_SVELTE.read_text(encoding="utf-8")


class PlacementAndLazyLoadTests(unittest.TestCase):
    def test_component_file_exists(self):
        self.assertTrue(
            TOKEN_COST_CHART_SVELTE.is_file(),
            f"{TOKEN_COST_CHART_SVELTE} does not exist yet",
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
            "IssueFlowChart is loaded ($state<typeof import(...)> | null, not an "
            "eager static import) -- ruling §3: 'lazy-loaded by the same dynamic-import "
            "pattern IssueFlowChart already uses... a second eager chart import would "
            "undo that'",
        )

    def test_component_is_mounted_conditionally_after_the_flow_chart_in_source_order(self):
        source = _read_app_svelte()
        flow_chart_mount = re.search(r"\{#if IssueFlowChart\}\s*<IssueFlowChart\s*/>", source)
        token_chart_mount = re.search(r"\{#if TokenCostChart\}\s*<TokenCostChart\s*/>", source)
        self.assertIsNotNone(flow_chart_mount, "sanity check: IssueFlowChart's own mount point must still exist")
        self.assertIsNotNone(
            token_chart_mount,
            "no {#if TokenCostChart}<TokenCostChart />{/if} mount found in App.svelte -- "
            "ruling §3: 'placed directly below the PT-61 IssueFlowChart'",
        )
        if flow_chart_mount and token_chart_mount:
            self.assertLess(
                flow_chart_mount.start(), token_chart_mount.start(),
                "TokenCostChart must be mounted AFTER IssueFlowChart in source order -- "
                "ruling §3's explicit 'directly below'",
            )


class TokensModeSeriesTests(unittest.TestCase):
    """AC2: input/output separate, cache read/write distinguishable from
    fresh input -- ruling §4's four-series encoding."""

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
        self.assertIn(
            "cost_usd", source,
            "TokenCostChart.svelte never references cost_usd -- ruling §4's cost-mode toggle "
            "renders a single cost_usd series per role",
        )


class ToggleAndLabellingTests(unittest.TestCase):
    def test_estimated_label_is_present_for_the_cost_caveat(self):
        source = _read_token_cost_chart()
        self.assertIn(
            "estimated", source.lower(),
            "the component must carry the word 'estimated' somewhere -- ruling §5/AC3: "
            "only the dollar view is labelled estimated, the token view is not",
        )

    def test_show_all_control_marker_is_present(self):
        source = _read_token_cost_chart()
        # Loose, deliberately -- the exact control shape (button, link,
        # toggle) is implementation-lead's call; this only confirms SOME
        # "show all" affordance exists, matching this suite's stated
        # posture of staying loose about internal composition where the
        # ruling doesn't pin an exact DOM shape.
        self.assertRegex(
            source.lower(), r"show\s*all",
            "no 'show all' control marker found -- ruling §4: 'A \"Show all\" control expands to all 69'",
        )

    def test_caption_template_references_window_start_and_retention_language(self):
        source = _read_token_cost_chart()
        self.assertIn(
            "window_start", source,
            "caption must interpolate window_start from the payload -- ruling §5's caption "
            "template, 'History begins {window_start}'",
        )
        self.assertRegex(
            source.lower(), r"retention|predates",
            "caption must carry the retention-floor caveat language ('predates the local "
            "transcript retention window') -- ruling §5",
        )


class MainBarNotClickableTests(unittest.TestCase):
    def test_main_bucket_has_no_drawer_link_marker(self):
        # Structural-only: confirms the source distinguishes "main" from
        # a real issue somewhere (a conditional excluding it from
        # whatever click/link handling real issue bars get). Cannot
        # verify actual click behavior without a render harness -- see
        # this file's module docstring; the browser-visibility leg is
        # load-bearing here, not this test.
        source = _read_token_cost_chart()
        self.assertIn(
            "main", source.lower(),
            "TokenCostChart.svelte never references 'main' at all -- ruling §4: "
            "'main gets its own bar... no drawer link'",
        )


if __name__ == "__main__":
    unittest.main()
