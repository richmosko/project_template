"""PT-72 guard (architect's consolidated unified-shell ruling, issue
thread, 2026-08-30) -- the dashboard (Svelte) side: soft nav via
`history.pushState`/`popstate` (not a router library, not full-page
loads), the `/dashboard/issues` route hosting a full-height, full-edit
board embed, the home preview's iframe gaining `&readonly=1`, and the
sidebar nav rename ("Board" -> "Issue Tracking", href `/` ->
`/dashboard/issues`).

Nothing under test exists yet -- confirmed by reading `App.svelte`/
`main.ts` directly before writing anything below: `currentPath` is a
plain, non-reactive `const` computed once at module load (`const
currentPath = window.location.pathname;`), no `pushState`/`popstate`
anywhere, the sidebar's Board nav item still reads label "Board" / href
"/", and the home preview iframe is still `src="/?embed=1"` (no
`readonly=1`).

**Predictable PT-71 conflict, flagged in advance rather than surprising
whoever lands this:** `test_icon_consistency.py`'s
`SidebarNavIconsTests.test_board_nav_item_renders_the_kanban_icon` and
`test_dashboard_sidebar_nav.py`'s `test_board_nav_entry_links_to_the_board`
both currently assert the Board nav item's href is `/` and its label is
"Board" -- both of those assumptions are EXACTLY what this ruling
supersedes. Per this project's own established practice (PT-69's
Sidebar.Footer retarget, PT-69's cross-dimension-pair retarget), the
right sequencing is: land THIS ruling's change, watch those two tests go
red for the RIGHT reason (the old assumption is now wrong), then retarget
them -- not retarget them preemptively before the change exists, and not
leave them stale afterward. Not touched by this file.

**Soft-nav mechanics, architect's own spec:** "intercept sidebar anchor
clicks, `history.pushState`, hold the route in a `$state` variable, listen
for `popstate`. The anchors remain real `<a href>` values." This file
checks for exactly those four pieces, source-text only -- it cannot verify
that chrome genuinely persists without a remount in a real browser (that
confirmation is team-lead's leg, same split as every prior PT-69/70/71
rendered claim in this feature).
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"
DASHBOARD_MAIN_TS = helpers.CAIRN_DIR / "dashboard" / "src" / "main.ts"
DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


def _dashboard_src_haystack() -> str:
    parts = []
    if DASHBOARD_SRC.is_dir():
        for p in DASHBOARD_SRC.rglob("*"):
            if p.is_file() and p.suffix in (".svelte", ".ts"):
                parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


class SoftNavMechanicsTests(unittest.TestCase):
    """Architect's exact spec: pushState + popstate + a reactive ($state)
    route variable + real <a href> anchors preserved (deep links/no-JS
    still work through PT-54's existing SPA fallback)."""

    def setUp(self):
        self.haystack = _dashboard_src_haystack()
        self.assertTrue(self.haystack, "no .svelte/.ts source found under dashboard/src")

    def test_history_pushstate_is_used(self):
        self.assertIn(
            "pushState", self.haystack,
            "no `history.pushState` (or `pushState(`) usage found anywhere under dashboard/src "
            "-- architect's ruling: soft nav via ~15 lines, not a router library.",
        )

    def test_popstate_listener_is_registered(self):
        match = re.search(r"addEventListener\(\s*['\"]popstate['\"]", self.haystack)
        self.assertIsNotNone(
            match,
            "no `addEventListener('popstate', ...)` found anywhere under dashboard/src -- "
            "back/forward navigation needs to update the held route.",
        )

    def test_the_route_is_held_in_reactive_state_not_a_plain_const(self):
        # Confirmed currently: `const currentPath = window.location.pathname;`
        # -- a plain const, computed once, never reactive. The fix must
        # be a $state-backed variable (Svelte 5 rune) that pushState-based
        # navigation can update to trigger a re-render without a remount.
        #
        # Scoped to a variable NAME suggestive of path/route -- App.svelte
        # and ThemeSettings.svelte already use `$state` for unrelated
        # things (`data`, `topOpen`, etc.), so a bare "`$state` appears
        # somewhere" search is a false green here (caught while writing
        # this file: the unscoped version passed today, before anything
        # route-related existed at all).
        match = re.search(r"\b(\w*(?:path|route)\w*)\s*=\s*\$state[<(]", self.haystack, re.IGNORECASE)
        self.assertIsNotNone(
            match,
            "no `<name> = $state(...)` declaration found where <name> looks route/path-related "
            "-- architect: 'hold the route in a $state variable'. (Confirmed: App.svelte's "
            "`currentPath` is currently a plain, non-reactive `const`; other `$state` usages "
            "under dashboard/src are for unrelated things -- e.g. the dashboard payload, a "
            "Popover's open flag -- so this test deliberately doesn't accept just any $state.)",
        )


class NavRenameAndHrefTests(unittest.TestCase):
    """Sidebar 'Board' (currently href="/") becomes 'Issue Tracking'
    (href="/dashboard/issues") -- Mosko's actual complaint per the
    architect's own framing: the old href 'navigates OUT of the shell'."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_a_nav_entry_links_to_dashboard_issues_with_the_label_issue_tracking(self):
        match = re.search(r'<a\s+href=["\']/dashboard/issues["\'][^>]*>(.*?)</a>', self.source, re.DOTALL)
        label = re.sub(r"<[^>]*>", "", match.group(1)).strip() if match else None
        self.assertEqual(
            label, "Issue Tracking",
            f"no sidebar nav <a href=\"/dashboard/issues\">...</a> found whose text content "
            f"(tags stripped) is exactly \"Issue Tracking\" -- architect's ruling §6, ux-"
            f"designer's confirmed label. Found: {label!r}.",
        )

    def test_the_old_bare_board_href_is_no_longer_the_nav_entrys_target(self):
        # Scoped to the <Sidebar.Menu> block specifically -- the home
        # preview's OWN "Open/View full board" escape hatch also needs to
        # move off bare `/` per ux's spec (covered separately below by
        # EscapeHatchLinkTests), so this test doesn't assert `/` vanishes
        # from the whole file, only from the sidebar nav item.
        nav_match = re.search(r"<Sidebar\.Menu>(.*?)</Sidebar\.Menu>", self.source, re.DOTALL)
        self.assertIsNotNone(nav_match, f"{DASHBOARD_APP_SVELTE}: no <Sidebar.Menu>...</Sidebar.Menu> block found")
        self.assertNotIn(
            'href="/"', nav_match.group(1),
            f"{DASHBOARD_APP_SVELTE}: the sidebar nav block still contains href=\"/\" -- "
            f"architect's ruling: the Board nav entry's target moves to /dashboard/issues, "
            f"replacing the old bare `/` (which 'currently navigates OUT of the shell').",
        )


class EscapeHatchLinkTests(unittest.TestCase):
    """ux's spec: 'an explicit "View full board" link/button at the top
    of the section, independent of card-click.' Confirmed currently:
    `<Button variant="secondary" size="sm" href="/">Open full board</Button>`
    -- still targets bare `/`, which (same reasoning as the sidebar nav
    item) navigates OUT of the shell entirely rather than to the soft-nav
    Issue Tracking route. Not just a label question -- the href itself
    needs to move."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_the_escape_hatch_button_targets_dashboard_issues_not_bare_root(self):
        match = re.search(r'<Button\b[^>]*href=["\']([^"\']*)["\'][^>]*>([^<]*)</Button>', self.source)
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: no <Button href=\"...\">...</Button> found in the home "
            f"preview section at all.",
        )
        href, label = match.group(1), match.group(2)
        self.assertEqual(
            href, "/dashboard/issues",
            f"{DASHBOARD_APP_SVELTE}: the escape-hatch button (label {label!r}) still targets "
            f"{href!r} -- ux's spec: 'View full board' navigates to the shell's Issue Tracking "
            f"route, not the bare `/` which exits the shell entirely (same reasoning as the "
            f"sidebar nav item's own href move).",
        )


class HomePreviewReadonlyEmbedTests(unittest.TestCase):
    """Dashboard home's kanban preview: `/?embed=1` -> `/?embed=1&readonly=1`."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_home_preview_iframe_src_includes_readonly_flag(self):
        match = re.search(r'<iframe\b[^>]*src=["\']([^"\']*)["\']', self.source)
        self.assertIsNotNone(match, f"{DASHBOARD_APP_SVELTE}: no <iframe src=\"...\"> found at all")
        self.assertIn(
            "readonly=1", match.group(1),
            f"{DASHBOARD_APP_SVELTE}: the home preview's iframe src is {match.group(1)!r} -- "
            f"architect's ruling §2: 'Dashboard home preview -> /?embed=1&readonly=1'.",
        )

    def test_home_preview_iframe_still_has_embed_flag_too(self):
        # Sanity: readonly=1 is ADDITIVE, not a replacement for embed=1.
        match = re.search(r'<iframe\b[^>]*src=["\']([^"\']*)["\']', self.source)
        if match is None:
            self.skipTest("no <iframe src=\"...\"> found -- see test_home_preview_iframe_src_includes_readonly_flag")
        self.assertIn("embed=1", match.group(1))


class IssueTrackingFullEditEmbedTests(unittest.TestCase):
    """The /dashboard/issues page hosts a FULL-EDIT (no readonly=1),
    FULL-HEIGHT (not h-[70vh]) board embed -- distinct from the home
    preview's readonly, fixed-height one."""

    def setUp(self):
        self.haystack = _dashboard_src_haystack()
        self.assertTrue(self.haystack, "no .svelte/.ts source found under dashboard/src")

    def test_a_full_edit_board_embed_exists_somewhere(self):
        # Every DISTINCT embed=1 iframe src found under dashboard/src.
        # Requires >= 2 distinct srcs (proving a genuinely SEPARATE embed
        # was added, not just re-finding the pre-existing home-preview
        # iframe) AND at least one lacking readonly=1. The >= 2 check
        # matters: right now there is exactly ONE iframe (the home
        # preview) and it doesn't have readonly=1 YET either -- an
        # unscoped "some non-readonly embed=1 src exists" check passes
        # vacuously against that single pre-existing iframe, before the
        # Issue Tracking page's OWN embed exists at all (caught while
        # writing this file).
        srcs = re.findall(r'<iframe\b[^>]*src=["\']([^"\']*embed=1[^"\']*)["\']', self.haystack)
        distinct_srcs = sorted(set(srcs))
        self.assertGreaterEqual(
            len(distinct_srcs), 2,
            f"found only {len(distinct_srcs)} distinct embed=1 iframe src(s) ({distinct_srcs}) "
            f"under dashboard/src -- the Issue Tracking page (/dashboard/issues) needs its OWN "
            f"full-edit embed, SEPARATE from the home preview's. Right now there's only the "
            f"pre-existing home-preview iframe.",
        )
        full_edit_srcs = [s for s in distinct_srcs if "readonly=1" not in s]
        self.assertTrue(
            full_edit_srcs,
            f"found {len(distinct_srcs)} distinct embed=1 iframe src(s) ({distinct_srcs}), but "
            f"every one carries readonly=1 -- the Issue Tracking page's embed must be full-edit.",
        )

    def test_the_full_edit_embed_is_not_capped_to_the_home_preview_height(self):
        srcs_with_context = re.finditer(r'<iframe\b([^>]*src=["\'][^"\']*embed=1[^"\']*["\'][^>]*)>', self.haystack)
        full_edit_tags = [m.group(1) for m in srcs_with_context if "readonly=1" not in m.group(1)]
        if not full_edit_tags:
            self.skipTest("no full-edit embed found yet -- see test_a_full_edit_board_embed_exists_somewhere")
        self.assertTrue(
            all("h-[70vh]" not in tag for tag in full_edit_tags),
            f"the full-edit embed's <iframe> tag still carries the home preview's fixed "
            f"h-[70vh] height class -- architect's ruling: the Issue Tracking page's embed is "
            f"'full height', not the home card's constrained preview height.",
        )


if __name__ == "__main__":
    unittest.main()
