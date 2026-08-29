"""PT-69 final fix-iteration guard (Mosko's live-test finding #4, issue
thread 2026-08-29): "Row behavior: sections (Mode/Base/Theme/Chart) should
open as POPOVERS (flyout to the left, per shadcn-svelte's own Popover
docs) -- the board panel's flat always-visible groups don't match."
ux-designer's ruling: BOTH the top-level panel and each ROW use the
Popover interaction model on both surfaces, nested `side="left"`, and
"toggle-close, outside-click close, and Escape are now stated requirements
on EVERY Popover, both surfaces -- not assumed to come free."

This file is written AFTER the implementation landed (team-lead's final
fix-iteration verification round) -- unlike this feature's earlier red
guards, these are REGRESSION pins confirming a shipped, working mechanism,
same discipline as test_board_css_js_class_contract.py's own "green today
by design; it exists to fail loudly the moment that stops being true."
Verified against source before writing (not assumed): board.js's per-row
flyout close mechanism (toggle/outside-click/innermost-first-Escape) and
dashboard's nested `side="left"` Popover.Content on all four rows both
exist and were read directly, not inferred.

**Scope:** source-level pins only. Whether a real browser actually
dismisses a row flyout on outside click / Escape, and whether the nested
flyout actually renders to the row's LEFT rather than overflowing off-
screen, is team-lead's rendered browser leg -- not verifiable from text.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"
DASHBOARD_THEME_SETTINGS = helpers.CAIRN_DIR / "dashboard" / "src" / "lib" / "components" / "ThemeSettings.svelte"

FOUR_DIMENSIONS = ("mode", "base", "theme", "chart")


class ExtractionError(AssertionError):
    """Same fail-loudly contract as this suite's other source-text
    extractors."""


def _extract_top_level_function_body(source: str, function_name: str) -> str:
    """Same line-based extractor as test_theme_menu_embed_close_behavior.py
    -- duplicated locally rather than imported, per this suite's own
    precedent of keeping test files import-light."""
    lines = source.splitlines()
    start_idx = None
    header_re = re.compile(r"^  function " + re.escape(function_name) + r"\s*\(")
    for i, line in enumerate(lines):
        if header_re.match(line):
            start_idx = i
            break
    if start_idx is None:
        raise ExtractionError(f"could not find a top-level `function {function_name}(` in board.js")
    next_fn_re = re.compile(r"^  function \w+\s*\(")
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if next_fn_re.match(lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


def _escape_dismissal_order(body: str):
    """'row-first' if the keydown('Escape') handler checks `openRowDim !==
    null` BEFORE it sets `menu.hidden = true` (innermost-first dismissal);
    'top-first' if the order is reversed; None if the expected shape
    (an early-return guard on the key, followed by BOTH the row-check and
    the top-level close, somewhere after it) isn't found at all. Actual
    TEXTUAL ORDER of the two markers is what's compared -- not just
    whether both are present somewhere after the guard, which a single
    combined regex cannot reliably distinguish (see EscapePrecedenceSelfTests)."""
    guard_match = re.search(r"key\s*!==\s*['\"]Escape['\"][^\n]*\breturn\b", body)
    if guard_match is None:
        return None
    rest = body[guard_match.end():]
    row_check = re.search(r"openRowDim\s*!==\s*null", rest)
    top_close = re.search(r"menu\.hidden\s*=\s*true", rest)
    if row_check is None or top_close is None:
        return None
    return "row-first" if row_check.start() < top_close.start() else "top-first"


class BoardRowFlyoutCloseBehaviorTests(unittest.TestCase):
    """The board's hand-rolled nested-Popover equivalent -- ux's ruling
    explicitly named this as the LIKELY ROOT CAUSE of finding #2 ("Popover's
    contract is small enough to hand-roll consistently in vanilla JS for
    the board; reproducing full DropdownMenu menu semantics there would
    not be -- likely why the board's version wasn't dismissable in the
    first place"), so this surface gets its own dedicated pins rather than
    trusting a library to have handled it."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        source = BOARD_JS.read_text(encoding="utf-8")
        # Row-flyout wiring spans both renderThemeMenu (creates the row
        # trigger + flyout, wires the toggle) and wireThemeSettings (the
        # shared outside-click/Escape listeners) -- concatenate both
        # bodies rather than picking one.
        self.body = (
            _extract_top_level_function_body(source, "renderThemeMenu")
            + "\n"
            + _extract_top_level_function_body(source, "wireThemeSettings")
        )

    def test_a_row_trigger_click_toggles_its_own_flyout(self):
        self.assertTrue(
            "flyout.hidden = false" in self.body and "closeOpenRowFlyout" in self.body,
            "expected a row trigger click handler that opens its flyout (flyout.hidden = "
            "false) and a shared closeOpenRowFlyout() used to close whichever row is open.",
        )

    def test_outside_panel_click_resets_the_open_row_tracking_state(self):
        match = re.search(r"openRowDim\s*=\s*null", self.body)
        self.assertIsNotNone(
            match,
            "expected the outside-click handler to reset openRowDim to null when the whole "
            "panel closes, so a later reopen doesn't believe a stale row flyout is open.",
        )

    def test_escape_closes_the_open_row_flyout_before_the_top_level_panel(self):
        # ux: "Innermost-first... matches the reference Popover's own
        # nested-dismissal behavior." Pin the actual precedence: the
        # keydown handler must check `openRowDim !== null` (and call
        # closeOpenRowFlyout) BEFORE it closes the top-level menu.
        order = _escape_dismissal_order(self.body)
        self.assertEqual(
            order, "row-first",
            f"expected the keydown('Escape') handler to check openRowDim and call "
            f"closeOpenRowFlyout() BEFORE closing the top-level menu (innermost-first "
            f"dismissal, per ux's Popover ruling) -- got {order!r} (None means the expected "
            f"shape wasn't found at all; 'top-first' means the order is backwards).",
        )

    def test_clicking_inside_the_panel_but_outside_the_open_row_flyout_closes_just_that_row(self):
        match = re.search(r"openFlyout\.contains\(e\.target\)", self.body)
        self.assertIsNotNone(
            match,
            "expected a check for whether the click landed inside the currently-open row's "
            "own flyout -- a click elsewhere in the (still-open) top-level panel should close "
            "just that row, not the whole panel.",
        )


class DashboardNestedPopoverDirectionTests(unittest.TestCase):
    """ux's ruling: every row's Popover.Content is `side="left"` -- the
    reference site's own cascading-left flyout direction."""

    def setUp(self):
        self.assertTrue(DASHBOARD_THEME_SETTINGS.is_file(), f"{DASHBOARD_THEME_SETTINGS} does not exist")
        self.source = DASHBOARD_THEME_SETTINGS.read_text(encoding="utf-8")

    def test_every_row_popover_content_uses_side_left(self):
        row_popover_contents = re.findall(r'<Popover\.Content\b([^>]*)>', self.source)
        # The TOP-LEVEL panel's own Popover.Content (no side="left" --
        # it's the anchor, not a nested flyout) is excluded by requiring
        # at least one nested row nonetheless.
        nested_side_left = [attrs for attrs in row_popover_contents if 'side="left"' in attrs]
        self.assertGreaterEqual(
            len(nested_side_left), len(FOUR_DIMENSIONS),
            f"expected at least {len(FOUR_DIMENSIONS)} nested `<Popover.Content side=\"left\" "
            f"...>` blocks (one per row: {', '.join(FOUR_DIMENSIONS)}), found "
            f"{len(nested_side_left)} -- ux's ruling: every row's flyout cascades to the left.",
        )

    def test_no_row_disables_default_outside_click_or_escape_dismissal(self):
        # shadcn/bits-ui Popover dismisses on outside-click/Escape by
        # default -- this is a NEGATIVE check that nobody overrode that
        # default (e.g. `interactOutside={(e) => e.preventDefault()}` or
        # an `onEscapeKeydown` that calls `preventDefault()`), which would
        # silently break "toggle-close, outside-click close, and Escape...
        # not assumed to come free" for this surface.
        for forbidden in ("interactOutside", "onEscapeKeydown", "escapeKeydown"):
            self.assertNotIn(
                forbidden, self.source,
                f"found `{forbidden}` in ThemeSettings.svelte -- this is exactly the prop shape "
                f"used to override bits-ui Popover's default dismiss behavior; verify it isn't "
                f"disabling outside-click/Escape close before assuming this is harmless.",
            )


class EscapePrecedenceSelfTests(unittest.TestCase):
    """Proves `_escape_dismissal_order` CAN distinguish the correct
    (innermost-first) order from a plausible WRONG-order implementation,
    not just that the real file currently reads as correct. An earlier
    draft of this check used a single combined regex that could not
    actually tell the two orders apart (found by this very self-test
    failing against the wrong-order snippet during development) -- kept
    as a lesson: a "does the pattern appear somewhere after" regex is not
    the same claim as "does it appear in the right ORDER"."""

    def test_correct_innermost_first_order_is_detected(self):
        snippet = (
            "if (e.key !== \"Escape\") return;\n"
            "if (openRowDim !== null) {\n"
            "  closeOpenRowFlyout();\n"
            "  return;\n"
            "}\n"
            "menu.hidden = true;\n"
        )
        self.assertEqual(_escape_dismissal_order(snippet), "row-first")

    def test_top_level_first_wrong_order_is_detected_as_wrong(self):
        # The WRONG order: top-level panel closes first, row flyout
        # never gets a chance to absorb the first Escape press.
        snippet = (
            "if (e.key !== \"Escape\") return;\n"
            "menu.hidden = true;\n"
            "trigger.setAttribute(\"aria-expanded\", \"false\");\n"
            "if (openRowDim !== null) {\n"
            "  closeOpenRowFlyout();\n"
            "}\n"
        )
        self.assertEqual(_escape_dismissal_order(snippet), "top-first")

    def test_missing_shape_returns_none(self):
        self.assertIsNone(_escape_dismissal_order("function noop() {}"))


if __name__ == "__main__":
    unittest.main()
