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

RE-POINTED (PT-110 NO-GO, gate-4 verdict re-issued whole, architect,
PT-110.md @ 4faae8f, item (2)): the wrapper div this file originally
keyed on (`div.mx-auto.flex.w-full.flex-col.gap-6`, immediately
preceding `<header`) is DELETED by PT-110's re-issued fix -- it was
also the sticky header's containing block, capped at the header's own
height, which is the bug the NO-GO caught. `mx-auto w-full` moves onto
the `<header>` element itself. This file's invariant survives in
substance ("no max-w-6xl cap; same width rule as the sections wrapper")
but must now read the HEADER's own class string, as a SUBSET check --
never string equality, since the header legitimately carries many more
classes (sticky/z-50/surface/etc, PT-110's own scan in
test_dashboard_header_pinning.py) that the plain sections wrapper does
not.
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

    def _header_classes(self) -> set[str]:
        # PT-110 NO-GO re-point (PT-110.md @ 4faae8f, item (2)): the
        # header's OWN class string, not a preceding wrapper's -- the
        # wrapper this test used to key on is deleted by the same fix.
        match = re.search(r'<header\b[^>]*\bclass="([^"]*)"', self.source)
        self.assertIsNotNone(match, f"{DASHBOARD_APP_SVELTE}: no <header class=\"...\"> element found")
        return set(match.group(1).split())

    def _sections_wrapper_classes(self) -> set[str]:
        match = re.search(r"\{#if !onIssueTracking\}\s*<div class=\"([^\"]*)\"", self.source)
        self.assertIsNotNone(
            match,
            f"{DASHBOARD_APP_SVELTE}: could not find the 'other sections' wrapper div "
            f"immediately inside `{{#if !onIssueTracking}}` -- this test's structural "
            f"assumption may be stale, not something to silence.",
        )
        return set(match.group(1).split())

    def test_header_does_not_cap_at_max_w_6xl(self):
        header_classes = self._header_classes()
        self.assertNotIn(
            "max-w-6xl", header_classes,
            f"{DASHBOARD_APP_SVELTE}: the header still caps at max-w-6xl ({sorted(header_classes)}) "
            f"-- PT-73 already dropped this cap from the sections below; the header needs the same "
            f"treatment, per Mosko's 'match the cards below' spec.",
        )

    def test_header_carries_the_same_width_rule_as_the_unified_sections_wrapper(self):
        # SUBSET, never equality (PT-110 NO-GO item (2)): the header
        # legitimately carries many more classes (sticky/z-50/surface,
        # test_dashboard_header_pinning.py's own scan) than the plain
        # sections wrapper -- what must agree is the WIDTH-governing
        # rule (mx-auto, w-full), not the full class list.
        header_classes = self._header_classes()
        sections_classes = self._sections_wrapper_classes()
        width_tokens = {"mx-auto", "w-full"}
        self.assertTrue(
            width_tokens <= sections_classes,
            f"{DASHBOARD_APP_SVELTE}: the sections wrapper itself no longer carries {width_tokens} "
            f"({sorted(sections_classes)}) -- this test's structural assumption may be stale.",
        )
        missing = width_tokens - header_classes
        self.assertFalse(
            missing,
            f"{DASHBOARD_APP_SVELTE}: the header ({sorted(header_classes)}) is missing the width "
            f"rule the sections wrapper carries ({sorted(sections_classes)}) -- missing: {missing} "
            f"-- 'match the cards below' means these two must agree on width, not merely both lack "
            f"max-w-6xl.",
        )


if __name__ == "__main__":
    unittest.main()
