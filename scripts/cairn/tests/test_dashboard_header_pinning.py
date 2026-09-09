"""PT-110 (architect's gate-1 ruling, process/cairn/issues/PT-110.md @
d89288c): the dashboard header (App.svelte ~L333) stays exactly where
it is in the DOM -- no restructure to the sidebar-07 shape -- because
nothing in the shell path establishes a scroll container (grep
overflow over body/sidebar-wrapper/sidebar-inset/page-root returns
nothing), so the document scrolls and `sticky` works in place.

Pins on the `<header>` element itself:
- `sticky` + `top-0`: keeps it pinned without leaving normal flow (no
  spacer needed -- item (2) of the ruling).
- `z-40`, NOT `z-50` (addendum 2, PT-110.md @ cfa5128): measured on the
  live board -- at the equal `z-50` tier the header clipped its own
  settings popover (`elementFromPoint` in the popover's top 27px
  returned the header, not the popover). The header sits strictly
  BELOW the portal'd overlay tier (dropdown/select/popover/sheet/chart
  tooltip, all `z-50`) and strictly ABOVE ordinary content (`z-auto`)
  -- every overlay now correctly paints over the header, and the
  header still wins over scrolled content. The addendum's own escape
  hatch ("raise to z-[60] if this looks wrong") is withdrawn as
  backwards; do not resurrect it.
- `bg-muted` + `border-b`: opaque page-chrome surface (matches `body`,
  not a floating card) so scrolled content never bleeds through.
- NEGATIVE: never `fixed` -- `fixed` would satisfy a naive "stays at
  the top" reading while pulling the header out of flow, silently
  reintroducing the overlap AC2 forbids. This is the regression a scan
  test exists to catch, per the ruling's own words.

Separate negative: no spacer element was added directly below the
header. `sticky` keeps the box in normal flow, so a spacer or
`padding-top` equal to the header height would double-count and push
the first card down by a header's worth of dead space -- explicitly
rejected by the ruling ("AC2 needs no spacer, and must not get one").

Verdict delta 2 (PT-110.md @ 0b26e90): raising the header's own layer
was never going to be enough -- bits-ui's `[data-bits-floating-
content-wrapper]` computes `z-index: auto` for EVERY floating overlay
(popover/dropdown/select/tooltip), so `app.css` needs its own floor
rule. `FloatingWrapperZIndexFloorTests` scans for it, parse-level (PT-57
rule: brace-depth block extraction after comment stripping, never a
substring search that a comment could satisfy falsely). THE SCAN IS
THE FLOOR, NOT THE PROOF -- no test in either suite renders bits-ui;
the acceptance is the browser leg (elementFromPoint in the popover's
top strip must return the popover, not the header).
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"
APP_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "app.css"
DIST_ASSETS_DIR = helpers.CAIRN_DIR / "dashboard" / "dist" / "assets"


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _extract_css_rule_block(source: str, selector: str) -> str:
    """Same shape as test_base_theme_contrast_gate.py's
    `_extract_unqualified_block`: comment-strip first, locate `selector
    {`, then brace-depth-match to the closing `}` -- parse-level, so a
    selector or declaration mentioned only inside a comment (or a
    similarly-named but different rule) can never satisfy this."""
    stripped = _strip_css_comments(source)
    match = re.search(re.escape(selector) + r"\s*\{", stripped)
    if not match:
        return ""
    depth, i, n = 1, match.end(), len(stripped)
    while i < n and depth > 0:
        if stripped[i] == "{":
            depth += 1
        elif stripped[i] == "}":
            depth -= 1
        i += 1
    return stripped[match.end() : i - 1]


class HeaderStickyPositioningTests(unittest.TestCase):
    """Mutation, each independently: drop the named token from the
    header's class attribute -> red. `fixed` mutation: swap `sticky`
    for `fixed` -> the negative assertion goes red."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def _header_classes(self) -> set[str]:
        # Not anchored to the header's OLD literal class string (that
        # string is exactly what this issue changes) -- just the
        # opening <header ...> tag's class attribute, wherever the new
        # tokens land in it.
        match = re.search(r'<header\b[^>]*\bclass="([^"]*)"', self.source)
        self.assertIsNotNone(match, f"{DASHBOARD_APP_SVELTE}: no <header class=\"...\"> element found")
        return set(match.group(1).split())

    def test_header_is_sticky_pinned_to_the_top(self):
        classes = self._header_classes()
        self.assertIn("sticky", classes, f"header must carry `sticky` -- got {sorted(classes)}")
        self.assertIn("top-0", classes, f"header must carry `top-0` -- got {sorted(classes)}")

    def test_header_is_never_fixed(self):
        # The load-bearing negative: `fixed` would satisfy AC1's "stays
        # at the top" naively while pulling the header out of flow,
        # silently reintroducing the AC2 overlap the ruling forbids.
        classes = self._header_classes()
        self.assertNotIn(
            "fixed", classes,
            f"header must never be `fixed` -- `sticky` is the ruled mechanism (PT-110.md @ d89288c); "
            f"`fixed` leaves normal flow and reintroduces the overlap AC2 forbids -- got {sorted(classes)}",
        )

    def test_header_layer_is_z_40_strictly_below_the_overlay_tier(self):
        # Addendum 2 (PT-110.md @ cfa5128): measured on the live board --
        # at z-50 (the equal overlay tier) the header clipped its own
        # settings popover. z-40 sits strictly below the portal'd
        # overlay tier (z-50: dropdown/select/popover/sheet/chart
        # tooltip) and strictly above ordinary content (z-auto).
        classes = self._header_classes()
        self.assertIn(
            "z-40", classes,
            f"header must carry `z-40` -- strictly below the z-50 portal'd overlay tier "
            f"(dropdown/select/popover/sheet/chart tooltip) so those overlays paint over it, "
            f"and strictly above ordinary z-auto content so the header still wins over "
            f"scrolled content -- got {sorted(classes)}",
        )
        self.assertNotIn(
            "z-50", classes,
            f"header must NOT carry `z-50` -- measured to clip the header's own settings "
            f"popover at that equal tier (addendum 2, PT-110.md @ cfa5128); the escape hatch "
            f"to raise it further is withdrawn as backwards -- got {sorted(classes)}",
        )

    def test_header_surface_is_opaque_muted_with_a_bottom_border(self):
        classes = self._header_classes()
        self.assertIn("bg-muted", classes, f"header must carry `bg-muted` (matches body's own surface) -- got {sorted(classes)}")
        self.assertIn("border-b", classes, f"header must carry `border-b` -- got {sorted(classes)}")


PAGE_ROOT_OPEN_RE = re.compile(r'<div class="flex min-h-screen flex-col gap-6 bg-muted px-7 py-7">\s*')


class HeaderIsAnImmediateChildOfThePageRootTests(unittest.TestCase):
    """PT-110 NO-GO, gate-4 verdict (architect, PT-110.md @ 4faae8f):
    "pinning classes are necessary and not sufficient; the containing
    block is the mechanism" -- a sticky element cannot outlive its
    PARENT's box, and the first fix (5d94640) left the header inside an
    89px-tall wrapper div (`div.mx-auto.flex.w-full.flex-col.gap-6`,
    PT-74) whose own box is exactly the header's height, defeating
    `sticky top-0` at the real page-root scroll extent. Re-issued
    ruling item (1): delete that wrapper, move `mx-auto w-full` onto
    the `<header>` itself, so it is a DIRECT child of the tall page
    root (`flex min-h-screen ... px-7 py-7`, ~3073px measured).

    Structural, not stylistic -- this is the guard that would have
    caught the first (class-only) fix. Mutation: reintroduce ANY
    wrapper element between the page root and `<header` -> red."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_header_opening_tag_immediately_follows_the_page_root_div(self):
        match = PAGE_ROOT_OPEN_RE.search(self.source)
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: page-root div (`flex min-h-screen flex-col gap-6 bg-muted "
            f"px-7 py-7`) not found -- this test's structural assumption may be stale, not "
            f"something to silence.",
        )
        after = self.source[match.end():].lstrip()
        self.assertTrue(
            after.startswith("<header"),
            f"{DASHBOARD_APP_SVELTE}: expected `<header` to be the IMMEDIATE child of the page-root "
            f"div -- found {after[:80]!r} instead. A wrapper between them (even one that carries no "
            f"visible styling) becomes the sticky header's containing block and silently caps it "
            f"at the wrapper's own height (PT-110 NO-GO @ 4faae8f) -- exactly the bug this guard "
            f"exists to catch.",
        )


class NoSpacerElementBelowTheHeaderTests(unittest.TestCase):
    """Ruling item (3): `sticky` keeps the header in normal flow, so a
    spacer/padding-top element equal to the header height would
    double-count and push the first card down by a header's worth of
    dead space -- explicitly rejected. Restated for the post-NO-GO
    shape (team-lead, red-2 kickoff): with the PT-74 wrapper deleted,
    the header's own close is immediately followed -- once comments are
    stripped -- by the route switch (`{#if !onIssueTracking}`), never a
    spacer. Mutation: insert a spacer div (e.g. `<div class="h-16">
    </div>`) directly after `</header>` -> this goes red."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_nothing_is_inserted_immediately_after_the_header_closes(self):
        self.assertIn("</header>", self.source, f"{DASHBOARD_APP_SVELTE}: no </header> close tag found")
        after = self.source.split("</header>", 1)[1]
        stripped = after.lstrip()
        self.assertTrue(
            stripped.startswith("{#if !onIssueTracking}"),
            f"{DASHBOARD_APP_SVELTE}: expected the route switch (`{{#if !onIssueTracking}}`) to "
            f"follow </header> directly (comments aside) -- found {stripped[:80]!r} instead, which "
            f"looks like a spacer element the ruling explicitly forbids (sticky needs none)",
        )


class FloatingWrapperZIndexFloorTests(unittest.TestCase):
    """Verdict delta 2 (architect, PT-110.md @ 0b26e90): bits-ui's
    `[data-bits-floating-content-wrapper]` computes `z-index: auto` for
    every floating overlay (popover/dropdown/select/tooltip), so with
    the header at a positive `z-40` every overlay sat at layer 0 --
    invisible until the header was the first thing tall enough to
    stand on their toes. `app.css` needs a floor rule.

    THE SCAN IS THE FLOOR, NOT THE PROOF (the ruling's own words): no
    test in either suite renders bits-ui, so this only proves the rule
    text exists, never that the cascade actually resolves it live. The
    acceptance is the browser leg -- elementFromPoint in the popover's
    top strip returning the popover, not the header, on both themes.

    Parse-level throughout (PT-57 rule): brace-depth block extraction
    after comment-stripping, matching test_base_theme_contrast_gate.py's
    own `_extract_unqualified_block` shape -- a comment mentioning the
    selector or `z-index: 50` can never satisfy either assertion."""

    def setUp(self):
        self.assertTrue(APP_CSS.is_file(), f"{APP_CSS} does not exist")
        self.source = APP_CSS.read_text(encoding="utf-8")
        self.body = _extract_css_rule_block(self.source, "[data-bits-floating-content-wrapper]")

    def test_the_floating_wrapper_selector_sets_z_index_50(self):
        self.assertTrue(
            self.body,
            f"{APP_CSS}: no `[data-bits-floating-content-wrapper] {{ ... }}` rule found -- without "
            f"it every bits-ui floating overlay (popover/dropdown/select/tooltip) computes "
            f"z-index: auto and sits at layer 0, below the header's z-40 (verdict delta 2)",
        )
        self.assertRegex(
            self.body, r"z-index\s*:\s*50\s*;",
            f"{APP_CSS}: [data-bits-floating-content-wrapper] must set z-index: 50 -- the floor "
            f"above the header's z-40 so every portal'd overlay clears it -- rule body: {self.body!r}",
        )

    def test_the_z_index_declaration_carries_no_important(self):
        self.assertNotIn(
            "!important", self.body,
            f"{APP_CSS}: no !important on the z-index floor -- if bits-ui's own RAF-copied inline "
            f"z-index DOES land, it must win with the same value (this rule is a floor, not an "
            f"override, per verdict delta 2) -- rule body: {self.body!r}",
        )


class HeaderCancelsTheGapAndSiblingsAreIsolatedTests(unittest.TestCase):
    """PT-117 gate-1 ruling (architect, PT-117.md @ce0c15b): the header's
    24px gap was only half the defect -- at scrollY 1500 the token
    chart's own tooltip (`z-index: 50`, set by LayerChart in the content
    subtree) painted OVER the pinned header (623 of 1026 hit-test points
    in the header's own box). Ruled mechanism, two parts, both measured
    live:
    1. `isolate` (`isolation: isolate`) on every non-header direct child
       of the page root -- each becomes its own stacking context, so a
       library's z-50 can no longer escape it and compete with the
       header. Measured: 623 -> 0 over-header hits at scrollY 1500.
    2. `-mb-6` on the `<header>` -- cancels the page root's flex row-gap
       after the header only, so the first content block's border-box
       top IS the header's bottom edge. Measured: next.top - header.bottom,
       24 -> 0, both routes.

    PT-110's own guards (sticky/top-0/z-40/bg-muted/border-b/never-fixed/
    structural-child-of-root/no-spacer) are KEPT, not restated away --
    see the classes above. A negative margin is a margin, not a spacer
    (ruling's own words)."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def _header_classes(self) -> set[str]:
        match = re.search(r'<header\b[^>]*\bclass="([^"]*)"', self.source)
        self.assertIsNotNone(match, f"{DASHBOARD_APP_SVELTE}: no <header class=\"...\"> element found")
        return set(match.group(1).split())

    def test_header_cancels_the_gap_with_a_negative_bottom_margin(self):
        classes = self._header_classes()
        self.assertIn(
            "-mb-6", classes,
            f"header must carry `-mb-6` to cancel the page root's row-gap after itself "
            f"(measured next.top - header.bottom: 24 -> 0 both routes) -- got {sorted(classes)}",
        )

    def _tag_containing(self, anchor: str) -> str:
        idx = self.source.find(anchor)
        self.assertGreaterEqual(
            idx, 0, f"{DASHBOARD_APP_SVELTE}: anchor {anchor!r} not found -- this test's "
            f"structural assumption may be stale, not something to silence",
        )
        tag_start = self.source.rfind("<", 0, idx)
        tag_end = self.source.index(">", idx)
        return self.source[tag_start : tag_end + 1]

    def _classes_in_tag(self, tag_text: str) -> set[str]:
        m = re.search(r'class="([^"]*)"', tag_text)
        return set(m.group(1).split()) if m else set()

    def test_dashboard_content_wrapper_is_isolated(self):
        # The `!onIssueTracking` branch's content wrapper -- a direct
        # child of the page-root div on /dashboard.
        tag = self._tag_containing('mx-auto flex w-full flex-col gap-6"')
        classes = self._classes_in_tag(tag)
        self.assertIn(
            "isolate", classes,
            f"the dashboard route's content wrapper (a direct child of the page root) must "
            f"carry `isolate` -- got tag={tag!r}",
        )

    def test_board_section_is_isolated(self):
        # PT-62: the Board section is deliberately OUTSIDE the content
        # wrapper above -- a SECOND direct child of the page root on
        # /dashboard, so it needs its own `isolate`.
        tag = self._tag_containing('aria-label="Board"')
        classes = self._classes_in_tag(tag)
        self.assertIn(
            "isolate", classes,
            f"the Board section (a direct child of the page root on /dashboard) must carry "
            f"`isolate` -- got tag={tag!r}",
        )

    def test_issue_tracking_section_is_isolated(self):
        # The `onIssueTracking` branch's only top-level element -- the
        # page root's sole non-header child on /dashboard/issues.
        tag = self._tag_containing('aria-label="Issue Tracking"')
        classes = self._classes_in_tag(tag)
        self.assertIn(
            "isolate", classes,
            f"the Issue Tracking section (the page root's only direct child on "
            f"/dashboard/issues) must carry `isolate` -- got tag={tag!r}",
        )


class BuiltCssHasTheGapAndIsolationRulesTests(unittest.TestCase):
    """PT-117 gate-1 ruling, guard 2 -- the architect's own measured trap:
    a first pass applied `pb-6 -mb-6` via `classList` and measured "no
    change", because those utilities were never compiled into
    `dist/assets/index.css` at all (`.isolate` present, `.pb-6`/`.-mb-6`
    absent) -- the acceptance was silently a no-op against stale CSS.
    This scans the BUILT css actually served, not App.svelte's class
    string, so that trap can never repeat silently."""

    def setUp(self):
        self.assertTrue(DIST_ASSETS_DIR.is_dir(), f"{DIST_ASSETS_DIR} does not exist")
        css_files = sorted(DIST_ASSETS_DIR.glob("*.css"))
        self.assertTrue(css_files, f"no .css files found under {DIST_ASSETS_DIR}")
        self.css_text = "".join(p.read_text(encoding="utf-8") for p in css_files)

    def test_built_css_compiles_the_isolation_rule(self):
        # assertTrue on a bool, not assertRegex on the whole blob --
        # assertRegex's own failure message always echoes the full
        # searched text, which here is the entire (minified,
        # hundred-KB-plus) dist CSS.
        found = bool(re.search(r"\.isolate\{[^}]*isolation:isolate[^}]*\}", self.css_text))
        self.assertTrue(
            found,
            "dist/assets/*.css must compile the .isolate utility (isolation: isolate) -- "
            "without it a library's z-50 (LayerChart's tooltip) can escape its stacking "
            "context and paint over the header (measured: 623/1026 hits at scrollY 1500)",
        )

    def test_built_css_compiles_the_negative_margin_rule(self):
        # Addendum (implementation-lead's measurement): Tailwind v4 emits
        # this utility as `margin-bottom:calc(var(--spacing) * -6)` --
        # never a literal `-1.5rem` anywhere in the built CSS. Whitespace-
        # tolerant around the calc() internals; the selector and the
        # calc() shape are still what the ruling's own trap is about
        # (compiled or not), a literal-rem match is simply unreachable.
        found = bool(re.search(
            r"\.-mb-6\{[^}]*margin-bottom:\s*calc\(\s*var\(--spacing\)\s*\*\s*-6\s*\)[^}]*\}",
            self.css_text,
        ))
        self.assertTrue(
            found,
            "dist/assets/*.css must compile -mb-6 as margin-bottom: calc(var(--spacing) * -6) "
            "(Tailwind v4's own compiled form -- never a literal -1.5rem) -- the architect's "
            "own measured trap: applying this utility via classList alone read as a no-op "
            "because it was never in the compiled CSS at all",
        )


class RenderedProofsOwnedByTheLeadsBrowserLegNote(unittest.TestCase):
    """PT-117 gate-1 ruling, guard 4: properties A and B are RENDERED
    proofs -- no test in this suite renders App.svelte, bits-ui, or
    LayerChart, so neither can be measured from source. The scan classes
    above prove the mechanism's classes and built-CSS rules exist; they
    do not and cannot prove the cascade resolves them live. The lead's
    browser leg re-runs these exact predicates, verbatim, at scrolls
    0 / 200 / 700 / 1500 / 2400, on both /dashboard and
    /dashboard/issues, light and dark:

    A (nothing over the header): for every y in [header.top, header.bottom)
    at 9 x positions spanning the header's width,
    document.elementFromPoint(x, y) is the header or a descendant.
    Baseline (pre-fix): 0, 0, 0, 623, 0. Required after both fixes: 0
    everywhere, both themes.

    B (content top is the header's bottom edge): at rest,
    header.nextElementSibling.getBoundingClientRect().top -
    header.getBoundingClientRect().bottom === 0. Baseline 24px, required
    after the fix: 0px, on both routes.
    """

    def test_this_class_intentionally_asserts_nothing_the_note_above_is_the_guard(self):
        # No Python-side assertion belongs here: re-deriving arithmetic on
        # numbers this suite invented would not be a measurement of the
        # real page. See the class docstring for the two verbatim
        # predicates the browser leg owns.
        pass


if __name__ == "__main__":
    unittest.main()
