"""PT-61 guards: dashboard-01 Block anatomy's non-chart half (sidebar nav +
Dashboard-scale/status-card non-regression). The chart panel guard is
gated on the architect's chart-data-source ruling and is NOT in this
file -- see the PT-61 issue thread.

Source-text guards against App.svelte, in this suite's established shape
(test_dashboard_polish.py's `_read_app_svelte` + scoped regex,
test_dashboard_board_embed.py's docstring convention of naming which
tests are red-first TDD vs. which are regression fences).

Two postures in this one file, named explicitly per class so a reader
doesn't have to guess:

- `SidebarNavContractTests` is TDD RED-FIRST: nothing under test exists
  yet. App.svelte has no `$lib/components/ui/sidebar` import, no
  `<Sidebar` usage, no `href="/"` "Board" nav entry, no `href="/dashboard"`
  "Dashboard" nav entry. Every failure is a genuinely-absent construct,
  never an import error.
- `DashboardScaleAndStatusCardNonRegressionTests` is a REGRESSION FENCE,
  same posture as test_dashboard_board_embed.py's payload-boundary guards:
  it is GREEN today (the four status cards and the spec's Dashboard-scale
  spacing already exist, landed by PT-54/PT-60/PT-62) and stays in this
  suite so that the sidebar restructuring PT-61 is about to do can't
  silently drop a status card or the 28px/24px spacing values while
  reshaping the top-level layout to fit a sidebar.

Both classes are deliberately loose about the sidebar's INTERNAL
composition (menu grouping, icons, collapse behavior) -- design-system-
spec.md's own Sidebar row describes a fuller
`Sidebar.Provider > Sidebar.Root > Sidebar.Header, Sidebar.Content
(Sidebar.Group x n), Sidebar.Footer` shape than PT-61's filed scope
(Dashboard + Board entries only, no majors/milestones tree yet) --
that's implementation-lead's call within the AC, not something this
guard should pin down to one composition.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"


def _read_app_svelte() -> str:
    return DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")


class SidebarNavContractTests(unittest.TestCase):
    def test_sidebar_component_is_imported(self):
        source = _read_app_svelte()
        match = re.search(r"from\s+['\"]\$lib/components/ui/sidebar", source)
        self.assertIsNotNone(
            match,
            "App.svelte does not import the shadcn-svelte Sidebar component -- "
            "PT-61 AC #1 calls for the dashboard-01 Sidebar block as the "
            "cross-surface nav, not a hand-rolled nav element",
        )

    def test_sidebar_is_actually_used(self):
        source = _read_app_svelte()
        match = re.search(r"<Sidebar\.", source)
        self.assertIsNotNone(
            match,
            "no <Sidebar.*> usage found in App.svelte -- importing the component "
            "isn't enough, it has to actually be mounted",
        )

    def test_board_nav_entry_links_to_the_board(self):
        # Same-tag pairing (href immediately followed by the exact label,
        # no intervening `<` tag boundary) -- deliberately excludes the
        # pre-existing embedded-board-panel's Card.Title text "Board"
        # (no href on that tag at all) and its "Open full board" Button
        # (href="/", but the text is "Open full board", not the exact
        # capitalized standalone label "Board" the AC names).
        source = _read_app_svelte()
        match = re.search(r'href=["\']/["\'][^<]*>Board<', source)
        self.assertIsNotNone(
            match,
            "no sidebar nav entry found linking href=\"/\" to the exact label "
            "\"Board\" -- PT-61 AC #1 names Dashboard/Board/future-surfaces as "
            "the sidebar's nav entries",
        )

    def test_dashboard_nav_entry_links_to_the_dashboard(self):
        source = _read_app_svelte()
        match = re.search(r'href=["\']/dashboard["\'][^<]*>Dashboard<', source)
        self.assertIsNotNone(
            match,
            "no sidebar nav entry found linking href=\"/dashboard\" to the exact "
            "label \"Dashboard\" -- board.html's existing top-nav tab links to "
            "the same /dashboard URL (see #tab-dashboard), the sidebar entry "
            "should be consistent with it",
        )

    def test_boards_own_top_nav_link_role_is_addressed_not_silently_untouched(self):
        # AC #1's own wording: the sidebar "replaces the board's top-nav
        # link as the cross-surface nav". This guard only pins that
        # board.html's #tab-dashboard anchor still exists somewhere in
        # this codebase (it should NOT vanish outright -- a bare board.html
        # visit with no dashboard sidebar rendered needs *some* way back) --
        # it deliberately does NOT prescribe removal/hiding/restyling of
        # that link, since whether it's retired, kept as a fallback, or
        # left alone is a design call outside a source-text guard's
        # competence. See the QA hand-off note on this issue for the open
        # question.
        board_html = (REPO_ROOT / "scripts" / "cairn" / "board" / "board.html").read_text(encoding="utf-8")
        self.assertIn(
            'id="tab-dashboard"', board_html,
            "board.html's #tab-dashboard top-nav link is gone entirely -- if that "
            "was deliberate per the AC's 'replaces' wording, update this guard "
            "alongside the removal rather than letting it silently pass",
        )


class DashboardScaleAndStatusCardNonRegressionTests(unittest.TestCase):
    """Green today; must stay green through the PT-61 sidebar restructuring."""

    def test_all_four_status_cards_are_still_present(self):
        source = _read_app_svelte()
        for eyebrow in ("Build", "Release", "Active Feature", "Tracker"):
            self.assertIn(
                f'eyebrow="{eyebrow}"', source,
                f"StatusCard eyebrow={eyebrow!r} is missing -- PT-61 AC #3 forbids "
                f"regressing the four status cards while adopting the sidebar layout",
            )

    def test_status_card_component_still_renders_exactly_four_times(self):
        source = _read_app_svelte()
        usages = re.findall(r"<StatusCard\b", source)
        self.assertEqual(
            len(usages), 4,
            f"expected exactly 4 <StatusCard> usages, found {len(usages)} -- PT-61 must "
            f"not add, drop, or duplicate a status card while restructuring for the sidebar",
        )

    def test_dashboard_scale_page_margin_and_card_gap_values_are_still_present(self):
        # Weak but real signal (same posture as this suite's other
        # spacing checks): design-system-spec.md's Dashboard scale table
        # fixes page margins at 28px (Tailwind px-7/py-7) and the
        # card-to-card gap at 24px (gap-6) -- confirms the sidebar
        # restructuring didn't silently respace the page while adding a
        # nav rail.
        source = _read_app_svelte()
        self.assertIn("px-7", source, "28px page-margin utility (px-7) is gone from App.svelte")
        self.assertIn("py-7", source, "28px page-margin utility (py-7) is gone from App.svelte")
        self.assertIn("gap-6", source, "24px card-gap utility (gap-6) is gone from App.svelte")


if __name__ == "__main__":
    unittest.main()
