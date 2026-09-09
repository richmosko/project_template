"""PT-110 (architect's gate-1 ruling, process/cairn/issues/PT-110.md @
d89288c): the dashboard header (App.svelte ~L333) stays exactly where
it is in the DOM -- no restructure to the sidebar-07 shape -- because
nothing in the shell path establishes a scroll container (grep
overflow over body/sidebar-wrapper/sidebar-inset/page-root returns
nothing), so the document scrolls and `sticky` works in place.

Pins on the `<header>` element itself:
- `sticky` + `top-0`: keeps it pinned without leaving normal flow (no
  spacer needed -- item (2) of the ruling).
- `z-50`: the same tier as the portal'd overlays (chart tooltips,
  dropdown/select/popover/sheet) -- deliberately, so the header wins
  over ordinary scrolling content.
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
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


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

    def test_header_layer_is_z_50_matching_the_portaled_overlay_tier(self):
        classes = self._header_classes()
        self.assertIn(
            "z-50", classes,
            f"header must carry `z-50` -- the same tier as the chart tooltips/dropdown/select/"
            f"popover/sheet overlays, deliberately (ruling: 'a header that outranks its own "
            f"settings menu clips it') -- got {sorted(classes)}",
        )

    def test_header_surface_is_opaque_muted_with_a_bottom_border(self):
        classes = self._header_classes()
        self.assertIn("bg-muted", classes, f"header must carry `bg-muted` (matches body's own surface) -- got {sorted(classes)}")
        self.assertIn("border-b", classes, f"header must carry `border-b` -- got {sorted(classes)}")


class NoSpacerElementBelowTheHeaderTests(unittest.TestCase):
    """Ruling item (2): `sticky` keeps the header in normal flow, so a
    spacer/padding-top element equal to the header height would
    double-count and push the first card down by a header's worth of
    dead space -- explicitly rejected. Mutation: insert a spacer div
    (e.g. `<div class="h-16"></div>` or similar) directly after
    `</header>` -> this goes red."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_nothing_is_inserted_immediately_after_the_header_closes(self):
        self.assertIn("</header>", self.source, f"{DASHBOARD_APP_SVELTE}: no </header> close tag found")
        after = self.source.split("</header>", 1)[1]
        stripped = after.lstrip()
        self.assertTrue(
            stripped.startswith("</div>"),
            f"{DASHBOARD_APP_SVELTE}: expected the header's wrapper div to close immediately after "
            f"</header> with nothing in between -- found {stripped[:80]!r} instead, which looks like "
            f"a spacer element the ruling explicitly forbids (sticky needs none)",
        )


if __name__ == "__main__":
    unittest.main()
