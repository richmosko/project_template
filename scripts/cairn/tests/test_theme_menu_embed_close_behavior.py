"""PT-69 fix-iteration guard (Mosko's live-test finding #2, issue thread
2026-08-29, "fix iteration before merge"): "Board panel can't be closed --
permanently open once triggered."

**Original diagnosis (superseded in shape, kept as explanation):** the
board is embedded via a same-origin `<iframe>` inside the dashboard
(`App.svelte:509`, PT-55's embedding ruling -- `window.self !== window.top`
is literally how `board.js` already detects this, see `isEmbedMode`).
`wireThemeSettings()`'s outside-click and Escape handlers are attached to
the board's OWN `document` only -- events never cross a frame boundary, so
a click or Escape keypress in the PARENT (dashboard) page (most of the
visible page when the board is embedded as one section among several)
never reaches the iframe's own `document` listeners. That diagnosis is
still the correct EXPLANATION of Mosko's symptom in the embed context, and
lines up with finding #1 (Mosko's live test used the trigger "inside the
embedded kanban section" specifically).

**Reshaped per team-lead's reconciliation with ux-designer's embed-dedup
ruling (issue thread, same day):** the ruling doesn't ask the embedded
panel to become closeable cross-frame -- it removes the embedded trigger
FROM THE DOM ENTIRELY ("not `display:none` -- a hidden-but-present control
still sits in the tab order, a real keyboard-nav defect... the host page's
trigger governs"). Under that architecture the embedded panel can never
be OPENED in the first place, which makes it moot whether it can be
closed cross-frame -- a `window.parent.document` listener requirement
would have pinned complexity the ruled design eliminates rather than
needing. So:

1. The embedded board renders NO theme-settings trigger at all -- this is
   the dedup mechanism, and it is ALSO the actual fix for finding #2 in
   the embed context: no trigger, no way to open the panel from inside
   the iframe, no "permanently open" possible there. Detection mechanism
   is implementation-lead's call (ux's ruling: "whatever existing
   embedded-mode signal the board already carries") -- this file keys off
   `isEmbedMode`, the signal that already exists.
2. The 5 same-document toggle/outside-click/Escape pins from the original
   version of this file are KEPT, because the STANDALONE (non-embedded)
   board is where the panel actually opens and where those mechanisms
   matter for real.
3. The cross-frame (`window.parent`/`window.top`) listener requirement is
   DROPPED -- it would be dead code under the ruled architecture (nothing
   ever opens a panel with no trigger), and asserting on dead code is
   worse than asserting on nothing.

Nothing under test exists yet when this file is written for the dedup
half: `wireThemeSettings`/board.js has no `isEmbedMode`-gated trigger
removal anywhere. The 5 standalone-close pins should already be green
(pre-existing behavior, unaffected by this reshape).
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"


class ExtractionError(AssertionError):
    """Same fail-loudly contract as this suite's other source-text
    extractors -- a genuinely missing function is a real problem, not
    something to silently skip past."""


def _extract_top_level_function_body(source: str, function_name: str) -> str:
    """The body of a top-level (2-space-indented, this file's established
    style throughout board.js's IIFE) `function <name>(...) {` declaration
    -- from its own line up to (not including) the NEXT top-level function
    declaration. Line-based rather than full brace-parsing: board.js's own
    style is consistently one top-level function per top-level `function`
    keyword at exactly 2-space indent, so this is a safe, much simpler
    stand-in for a real JS parser here."""
    lines = source.splitlines()
    start_idx = None
    header_re = re.compile(r"^  function " + re.escape(function_name) + r"\s*\(")
    for i, line in enumerate(lines):
        if header_re.match(line):
            start_idx = i
            break
    if start_idx is None:
        raise ExtractionError(
            f"could not find a top-level `function {function_name}(` in board.js -- if this "
            f"function was renamed or restructured, this guard needs updating, not silencing."
        )
    next_fn_re = re.compile(r"^  function \w+\s*\(")
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if next_fn_re.match(lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


class PlainPageCloseBehaviorRegressionTests(unittest.TestCase):
    """The STANDALONE board's close mechanism -- this is where the panel
    actually opens and where toggle/outside-click/Escape matter. Predates
    this fix iteration; regression-pinned so it can't quietly regress
    while the embed-dedup work above lands."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        source = BOARD_JS.read_text(encoding="utf-8")
        self.body = _extract_top_level_function_body(source, "wireThemeSettings")

    def test_trigger_click_toggles_the_menu(self):
        self.assertTrue("menu.hidden = !" in self.body, "no toggle-on-trigger-click assignment found")

    def test_own_document_outside_click_closes_the_menu(self):
        match = re.search(r"document\.addEventListener\(\s*['\"]click['\"]", self.body)
        self.assertIsNotNone(
            match,
            "no document-level click listener found in wireThemeSettings -- outside-click-to-"
            "close needs this.",
        )

    def test_own_document_escape_closes_the_menu(self):
        match = re.search(r"document\.addEventListener\(\s*['\"]keydown['\"]", self.body)
        self.assertIsNotNone(
            match,
            "no document-level keydown listener found in wireThemeSettings -- Escape-to-close "
            "needs this.",
        )
        self.assertTrue(
            "Escape" in self.body,
            "wireThemeSettings has a keydown listener but never checks for the Escape key.",
        )


class EmbedDedupRemovesTheTriggerEntirelyTests(unittest.TestCase):
    """ux-designer's ruling (issue thread): when the board renders
    embedded in the dashboard, its own theme-settings trigger is NOT
    RENDERED AT ALL -- explicitly not `display:none`/`hidden`, which
    would leave a focusable-but-invisible control in the tab order (a
    real keyboard-nav defect ux calls out by name). This is simultaneously
    the dedup mechanism (one trigger per page, the host's) AND the actual
    fix for Mosko's "permanently open" finding in the embed context: no
    trigger reachable from inside the iframe means no way to open the
    embedded panel in the first place."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        self.source = BOARD_JS.read_text(encoding="utf-8")
        self.body = _extract_top_level_function_body(self.source, "wireThemeSettings")

    def test_board_js_has_an_embed_detection_mechanism_to_hook(self):
        # Sanity precondition -- if this ever stops being true, the fix
        # below has nothing to key off and needs a different shape.
        self.assertTrue(
            "isEmbedMode" in self.source,
            "board.js no longer exposes an isEmbedMode signal -- ux's ruling explicitly defers "
            "to 'whatever existing embedded-mode signal the board already carries'; this file "
            "keys off isEmbedMode specifically.",
        )

    def test_wire_theme_settings_checks_embed_mode_at_all(self):
        self.assertTrue(
            "isEmbedMode" in self.body,
            "wireThemeSettings never references isEmbedMode -- the embed-dedup ruling has "
            "nothing to key off inside this function.",
        )

    def test_embedded_trigger_is_removed_from_the_dom_not_merely_hidden(self):
        # Proximity search (not full control-flow parsing) for a real DOM-
        # removal call near the isEmbedMode check -- `.remove()` or the
        # equivalent `parentNode.removeChild(...)` form.
        match = re.search(r"isEmbedMode[\s\S]{0,300}?(\.remove\(\)|removeChild\()", self.body)
        self.assertIsNotNone(
            match,
            "no DOM-removal call (.remove() / removeChild(...)) found near an isEmbedMode check "
            "in wireThemeSettings -- ux's ruling requires the embedded trigger to be REMOVED "
            "from the DOM entirely, not hidden, when the board is embedded.",
        )

    def test_embedded_trigger_removal_does_not_use_the_rejected_hidden_approach(self):
        # Negative check: ux explicitly rejected `display:none`/`hidden`
        # as the mechanism ("a hidden-but-present control still sits in
        # the tab order, a real keyboard-nav defect"). Scoped to the
        # neighborhood of the isEmbedMode check specifically, not the
        # whole function (the EXISTING menu-open/close toggle legitimately
        # uses `.hidden` elsewhere in this same function, for a completely
        # different purpose -- this must not flag that).
        window_match = re.search(r"isEmbedMode[\s\S]{0,300}", self.body)
        if window_match is None:
            self.skipTest("no isEmbedMode reference found in wireThemeSettings yet")
        neighborhood = window_match.group(0)
        self.assertNotRegex(
            neighborhood, r"trigger\.hidden\s*=\s*true|trigger\.style\.display\s*=\s*['\"]none['\"]",
            "the embed-dedup fix appears to hide the trigger (trigger.hidden = true / "
            "style.display = 'none') rather than removing it from the DOM -- ux's ruling "
            "explicitly rejects this: a hidden-but-present control still sits in the tab order.",
        )


if __name__ == "__main__":
    unittest.main()
