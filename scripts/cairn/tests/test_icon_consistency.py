"""PT-71 guard (Mosko's post-merge live-test findings #3 and #6,
2026-08-29/30, issue thread): two icon-consistency gaps, both confirmed by
reading source directly before writing anything below.

**Finding #3 -- collapse rail has no icons.** `App.svelte`'s Sidebar nav
(`<Sidebar.Menu>`, ~line 196) renders the Dashboard and Board `<a>` tags
with LABEL TEXT ONLY -- no icon import, no icon element -- confirmed by
reading the file. Collapsing the sidebar to its icon rail then leaves two
empty, unusable rows. ux's ruled picks (issue thread, 2026-08-30): Dashboard
= `LayoutDashboard`, Board = `Kanban` ("better rail-size silhouette than
ListTodo, distinct from LayoutDashboard's grid").

**Finding #6 -- theme-settings trigger icon isn't Lucide on the board.**
`board.html`'s trigger currently reads `⚙ Appearance` -- a unicode gear
character plus a text label, confirmed by reading the file -- not the
Lucide `settings-2` glyph ux ruled for both surfaces. The dashboard side of
this finding is ALREADY satisfied (landed in PT-69): `ThemeSettings.svelte`
already imports the real `Settings2` component from `@lucide/svelte/icons/
settings-2` -- this file adds a REGRESSION pin for that (not a red guard),
plus the genuinely-red guard for the board's still-unicode trigger.

**Ground truth for the settings-2 glyph** -- extracted directly from the
installed `@lucide/svelte` v1.37.0 package (`dashboard/node_modules/
@lucide/svelte/dist/icons/settings-2.svelte`, `Icon.svelte`,
`defaultAttributes.js`), verified 2026-08-30, not invented or approximated
(same "extract from the real thing" discipline as this project's font/
preset-token vendoring precedents):

- `iconNode`: `[["path", {"d": "M14 17H5"}], ["path", {"d": "M19 7h-9"}],
  ["circle", {"cx": "17", "cy": "17", "r": "3"}], ["circle", {"cx": "7",
  "cy": "7", "r": "3"}]]`
- Wrapper `<svg>` defaults: `viewBox="0 0 24 24"`, `stroke-width="2"` (ux:
  "Lucide default 24px/2px-stroke... do not thin the stroke"),
  `stroke-linecap="round"`, `stroke-linejoin="round"`, `fill="none"`.

The board's vendored inline SVG must reproduce this real path/circle data
-- not a lookalike gear glyph, not a thinned stroke.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"
DASHBOARD_THEME_SETTINGS = helpers.CAIRN_DIR / "dashboard" / "src" / "lib" / "components" / "ThemeSettings.svelte"
BOARD_HTML = helpers.CAIRN_DIR / "board" / "board.html"
BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"

# Ground truth, verbatim from the installed @lucide/svelte v1.37.0
# settings-2 icon (see module docstring for the exact source paths).
SETTINGS_2_SHAPES = (
    ("path", "M14 17H5"),
    ("path", "M19 7h-9"),
    ("circle", {"cx": "17", "cy": "17", "r": "3"}),
    ("circle", {"cx": "7", "cy": "7", "r": "3"}),
)


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


def _strip_js_style_comments(source: str) -> str:
    # Reused approach from test_theme_bootstrap_and_dropdown.py's
    # _strip_js_comments, duplicated locally per this suite's own
    # import-light precedent -- board.js/App.svelte's <script> blocks can
    # equally contain an explanatory comment mentioning the very icon
    # name being searched for.
    out = []
    i, n = 0, len(source)
    in_string = None
    in_line_comment = False
    in_block_comment = False
    while i < n:
        two = source[i : i + 2]
        ch = source[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue
        if in_block_comment:
            if two == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(source[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if two == "//":
            in_line_comment = True
            i += 2
            continue
        if two == "/*":
            in_block_comment = True
            i += 2
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class SidebarNavIconsTests(unittest.TestCase):
    """Finding #3: the sidebar's Dashboard/Board nav items need Lucide
    icons so the collapsed icon rail isn't empty."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        source = DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")
        self.source = _strip_html_comments(source)
        nav_match = re.search(r"<Sidebar\.Menu>(.*?)</Sidebar\.Menu>", self.source, re.DOTALL)
        self.assertIsNotNone(nav_match, f"{DASHBOARD_APP_SVELTE}: no <Sidebar.Menu>...</Sidebar.Menu> block found")
        self.nav_block = nav_match.group(1)

    def test_layout_dashboard_icon_is_imported(self):
        match = re.search(
            r"import\s+LayoutDashboard\s+from\s+['\"]@lucide/svelte/icons/layout-dashboard['\"]",
            self.source,
        )
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: no `import LayoutDashboard from "
            f"'@lucide/svelte/icons/layout-dashboard'` found -- ux's ruled icon for the "
            f"Dashboard nav item.",
        )

    def test_kanban_icon_is_imported(self):
        match = re.search(
            r"import\s+Kanban\s+from\s+['\"]@lucide/svelte/icons/kanban['\"]",
            self.source,
        )
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: no `import Kanban from '@lucide/svelte/icons/kanban'` "
            f"found -- ux's ruled icon for the Board nav item ('better rail-size silhouette "
            f"than ListTodo, distinct from LayoutDashboard's grid').",
        )

    def test_dashboard_nav_item_renders_the_layout_dashboard_icon(self):
        dashboard_link_match = re.search(r'<a\s+href="/dashboard"[^>]*>.*?</a>', self.nav_block, re.DOTALL)
        self.assertIsNotNone(dashboard_link_match, f"{DASHBOARD_APP_SVELTE}: no <a href=\"/dashboard\"> found in the nav block")
        # The icon may render as a sibling inside the same MenuButton
        # rather than strictly inside the <a> -- widen the search to the
        # whole MenuItem containing this link, not just the <a> itself.
        item_match = re.search(
            r"<Sidebar\.MenuItem>(?:(?!</Sidebar\.MenuItem>).)*?/dashboard(?:(?!</Sidebar\.MenuItem>).)*?</Sidebar\.MenuItem>",
            self.nav_block, re.DOTALL,
        )
        self.assertIsNotNone(item_match, f"{DASHBOARD_APP_SVELTE}: no <Sidebar.MenuItem> wrapping the /dashboard link found")
        self.assertTrue(
            "<LayoutDashboard" in item_match.group(0),
            f"{DASHBOARD_APP_SVELTE}: the Dashboard nav item's <Sidebar.MenuItem> doesn't "
            f"render <LayoutDashboard ... /> -- an import alone isn't wiring.",
        )

    def test_board_nav_item_renders_the_kanban_icon(self):
        # RETARGETED (PT-72, architect's unified-shell ruling + ux-
        # designer's paired spec): the Board nav item's href moved from
        # "/" to "/dashboard/issues" (renamed to "Issue Tracking") --
        # confirmed live in App.svelte. The Kanban icon itself is
        # unaffected by the rename (PT-71's icon choice stands; PT-72
        # only moved the href/label), so this test only needs to key off
        # the new href, not re-litigate the icon choice.
        item_match = re.search(
            r'<Sidebar\.MenuItem>(?:(?!</Sidebar\.MenuItem>).)*?href="/dashboard/issues"(?:(?!</Sidebar\.MenuItem>).)*?</Sidebar\.MenuItem>',
            self.nav_block, re.DOTALL,
        )
        self.assertIsNotNone(
            item_match,
            f'{DASHBOARD_APP_SVELTE}: no <Sidebar.MenuItem> wrapping the href="/dashboard/issues" '
            f"link found -- PT-72 renamed this nav entry's target from the old bare \"/\".",
        )
        self.assertTrue(
            "<Kanban" in item_match.group(0),
            f"{DASHBOARD_APP_SVELTE}: the Issue Tracking nav item's <Sidebar.MenuItem> doesn't "
            f"render <Kanban ... /> -- an import alone isn't wiring.",
        )


class DashboardSettings2RegressionTests(unittest.TestCase):
    """Finding #6, dashboard half -- ALREADY satisfied (landed in PT-69).
    Regression pin only, not a red guard."""

    def test_theme_settings_imports_the_real_lucide_settings2_component(self):
        self.assertTrue(DASHBOARD_THEME_SETTINGS.is_file(), f"{DASHBOARD_THEME_SETTINGS} does not exist")
        source = DASHBOARD_THEME_SETTINGS.read_text(encoding="utf-8")
        match = re.search(
            r"import\s+Settings2\s+from\s+['\"]@lucide/svelte/icons/settings-2['\"]",
            source,
        )
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_THEME_SETTINGS}: no `import Settings2 from "
            f"'@lucide/svelte/icons/settings-2'` found -- this regressed from PT-69.",
        )


class BoardVendoredSettings2Tests(unittest.TestCase):
    """Finding #6, board half -- genuinely absent. board.html currently
    reads `⚙ Appearance` (confirmed by reading the file); ux's ruling:
    vendor the REAL Lucide settings-2 SVG path data inline."""

    def setUp(self):
        self.assertTrue(BOARD_HTML.is_file(), f"{BOARD_HTML} does not exist")
        html = BOARD_HTML.read_text(encoding="utf-8")
        self.html = _strip_html_comments(html)
        js = BOARD_JS.read_text(encoding="utf-8") if BOARD_JS.is_file() else ""
        self.js = _strip_js_style_comments(js)
        self.haystack = self.html + "\n" + self.js

    def test_trigger_no_longer_uses_a_unicode_gear_character(self):
        # The specific character being replaced -- ⚙ (U+2699 GEAR).
        trigger_match = re.search(r'<button\s+id="theme-settings-trigger"[^>]*>(.*?)</button>', self.html, re.DOTALL)
        self.assertIsNotNone(trigger_match, f"{BOARD_HTML}: no #theme-settings-trigger <button> found")
        self.assertNotIn(
            "⚙", trigger_match.group(1),
            f"{BOARD_HTML}: the trigger still contains the unicode gear character (U+2699) -- "
            f"ux's ruling is the real vendored Lucide settings-2 SVG, not a unicode stand-in.",
        )

    def test_trigger_contains_an_inline_svg(self):
        trigger_match = re.search(r'<button\s+id="theme-settings-trigger"[^>]*>(.*?)</button>', self.html, re.DOTALL)
        self.assertIsNotNone(trigger_match, f"{BOARD_HTML}: no #theme-settings-trigger <button> found")
        self.assertIn(
            "<svg", trigger_match.group(1),
            f"{BOARD_HTML}: the trigger's button markup contains no inline <svg> -- ux's ruling "
            f"requires the board to vendor the real Lucide settings-2 SVG inline (or board.js "
            f"inserts it at render time -- checked below too).",
        )

    def test_settings2_svg_has_the_correct_viewbox_and_stroke_width(self):
        svg_match = re.search(r"<svg\b([^>]*)>", self.haystack)
        # Board.js might construct the SVG via DOM APIs (createElementNS +
        # setAttribute) rather than a literal <svg ...> string -- widen
        # the acceptable shape if the literal tag isn't found.
        if svg_match is None:
            has_viewbox = re.search(r"viewBox['\"]?\s*[,:]?\s*['\"]0 0 24 24['\"]", self.haystack) is not None
            has_stroke_width = re.search(r"stroke-?[Ww]idth['\"]?\s*[,:]?\s*['\"]?2['\"]?", self.haystack) is not None
            self.assertTrue(
                has_viewbox and has_stroke_width,
                f"{BOARD_HTML}/{BOARD_JS}: no literal <svg viewBox=\"0 0 24 24\" ...> tag found, "
                f"and no DOM-API-constructed equivalent (viewBox '0 0 24 24' + stroke-width 2) "
                f"found either -- ux: 'Lucide default 24px/2px-stroke... do not thin the stroke.'",
            )
            return
        attrs = svg_match.group(1)
        self.assertIn('viewBox="0 0 24 24"', attrs, f"{BOARD_HTML}: vendored <svg> is missing viewBox=\"0 0 24 24\"")
        self.assertIn(
            'stroke-width="2"', attrs,
            f"{BOARD_HTML}: vendored <svg> doesn't set stroke-width=\"2\" -- ux: 'do not thin "
            f"the stroke.'",
        )

    def test_settings2_shape_data_matches_the_real_lucide_glyph(self):
        # Every shape (2 paths, 2 circles) from the real installed icon's
        # iconNode must appear somewhere in the vendored markup/JS --
        # doesn't require exact tag adjacency (attribute order can vary),
        # only that each real shape's defining data is present verbatim.
        missing = []
        for tag, data in SETTINGS_2_SHAPES:
            if tag == "path":
                pattern = re.escape(data)
            else:  # circle
                pattern = (
                    r'cx=["\']' + re.escape(data["cx"]) + r'["\']'
                    r'[^>]*cy=["\']' + re.escape(data["cy"]) + r'["\']'
                    r'[^>]*r=["\']' + re.escape(data["r"]) + r'["\']'
                )
            if re.search(pattern, self.haystack) is None:
                missing.append((tag, data))
        self.assertEqual(
            missing, [],
            f"{BOARD_HTML}/{BOARD_JS}: missing real Lucide settings-2 shape data: {missing} -- "
            f"extracted directly from the installed @lucide/svelte package (see this file's "
            f"module docstring for provenance), not invented or approximated.",
        )


class ExtractorSelfTests(unittest.TestCase):
    """Proves the HTML/JS comment strippers used above CAN remove
    comments while leaving real code/string content alone -- not just
    that real files currently read a particular way. Same discipline as
    the identically-shaped self-tests in test_theme_bootstrap_and_dropdown.py."""

    def test_strip_html_comments_removes_comment_but_keeps_code(self):
        source = "<!-- a comment mentioning <LayoutDashboard /> --><a>real</a>"
        stripped = _strip_html_comments(source)
        self.assertNotIn("a comment", stripped)
        self.assertIn("<a>real</a>", stripped)

    def test_strip_js_style_comments_leaves_strings_alone(self):
        source = '// mentions "settings-2" in a comment\nvar x = "settings-2";'
        stripped = _strip_js_style_comments(source)
        self.assertNotIn("mentions", stripped)
        self.assertIn('"settings-2"', stripped)


if __name__ == "__main__":
    unittest.main()
