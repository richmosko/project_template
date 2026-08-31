"""PT-74 guard (Mosko's finding, 2026-08-31, post-PT-73): "the title bar
still carries the old left/right padding; the cards below went full-bleed
in PT-73." No design decision here -- the spec is literally "match the
cards below," same rule PT-73 already applied to the other sections.

Confirmed by reading App.svelte directly before writing anything: the
header's own wrapper div is still `class="mx-auto flex w-full max-w-6xl
flex-col gap-6"` (unconditional, part of the persistent shell chrome per
PT-72 -- outside the `{#if !onIssueTracking}` branch), while the "other
sections" wrapper PT-73 already fixed reads `class="mx-auto flex w-full
flex-col gap-6"` -- identical except the header's still has the `max-w-6xl`
the sections wrapper already dropped.

Same symmetry-assertion shape as PT-73's `HomeSectionWidthUnificationTests`
-- this file just adds the header wrapper as a THIRD area that must agree,
rather than re-deriving the whole mechanism from scratch.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


class HeaderWidthMatchesSectionsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def _header_wrapper_class(self):
        # The div immediately wrapping <header ...> -- unconditional,
        # part of the persistent shell chrome (PT-72), not inside the
        # `{#if !onIssueTracking}` branch.
        match = re.search(
            r'<div class="([^"]*)">\s*<header class="flex flex-wrap items-center justify-between gap-4">',
            self.source,
        )
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: could not find the wrapper div immediately preceding "
            f"<header ...> -- this test's structural assumption may be stale, not something "
            f"to silence.",
        )
        return match.group(1)

    def _sections_wrapper_class(self):
        match = re.search(r"\{#if !onIssueTracking\}\s*<div class=\"([^\"]*)\"", self.source)
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: could not find the 'other sections' wrapper div "
            f"immediately inside `{{#if !onIssueTracking}}` -- this test's structural "
            f"assumption may be stale, not something to silence.",
        )
        return match.group(1)

    def test_header_wrapper_no_longer_caps_at_max_w_6xl(self):
        header_class = self._header_wrapper_class()
        self.assertNotIn(
            "max-w-6xl", header_class,
            f"{DASHBOARD_APP_SVELTE}: the header's own wrapper div still caps at max-w-6xl "
            f"({header_class!r}) -- PT-73 already dropped this cap from the sections below; "
            f"the header needs the same treatment, per Mosko's 'match the cards below' spec.",
        )

    def test_header_wrapper_class_matches_the_unified_sections_wrapper_exactly(self):
        # Stronger than the negative check above: the two wrapper divs
        # should be the SAME class string, not just both lacking
        # max-w-6xl by coincidence (e.g. one could drop max-w-6xl but add
        # some other divergent width rule and still pass the test above).
        header_class = self._header_wrapper_class()
        sections_class = self._sections_wrapper_class()
        self.assertEqual(
            header_class, sections_class,
            f"{DASHBOARD_APP_SVELTE}: the header wrapper ({header_class!r}) and the unified "
            f"sections wrapper ({sections_class!r}) have different classes -- 'match the "
            f"cards below' means these two should carry the identical width-governing rule, "
            f"not merely agree on the absence of max-w-6xl.",
        )


if __name__ == "__main__":
    unittest.main()
