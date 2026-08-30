"""PT-70 guard (Mosko's post-merge live-test findings #1 and #2, 2026-08-29,
issue thread): two real gaps found in the embedded board, diagnosed from
source before writing anything below (per team-lead's explicit ask --
"investigate the actual mechanism first... read the code, pin the real
gap").

## Finding #1 -- live theme propagation into the embed

**Root cause, confirmed by reading `board.js` directly, not assumed:**
`wireThemeSettings()` -- the ONLY place that registers the `storage` event
listener (and the `matchMedia('(prefers-color-scheme: dark)')` `change`
listener for live system-mode follow) -- opens with:

```js
if (isEmbedMode) {
  var wrapper = trigger.closest(".theme-settings");
  (wrapper || trigger).remove();
  return;                      // <-- unconditional return
}
trigger.addEventListener("click", ...);
...
window.addEventListener("storage", function (e) { ... });   // unreachable when embedded
```

PT-69's embed-dedup ruling (ux-designer) was specifically about the
TRIGGER: "the embedded board renders no theme-settings trigger at all."
That ruling never asked for the CROSS-CONTEXT FOLLOW mechanism to be
skipped too -- but the early `return` inside the `isEmbedMode` branch
takes both down together, as an unintended side effect of removing the
trigger. Same-tab, same-origin iframes DO receive `storage` events fired
by writes from their parent context (they're distinct `window`s sharing
one `localStorage`, and the spec fires `storage` in every OTHER same-
origin browsing context, iframes included) -- so the mechanism WOULD work
if it were ever registered. It just never gets the chance to register
when embedded, which is exactly Mosko's symptom: "changing theme on the
dashboard does NOT restyle the embedded kanban until a page reload"
(reload re-runs the inline bootstrap script, which reads the CURRENT
`cairn.theme` value fresh -- masking the bug on every fresh load and
surfacing it only on a live, no-reload change).

**What this file pins:** the `storage` listener (and the system-mode
`matchMedia` `change` listener) must be reachable/registered regardless of
`isEmbedMode` -- the embed-mode branch may still legitimately skip
trigger-specific UI wiring (click/outside-click/keydown/render), but must
not `return` before the cross-context listeners get attached.

## Finding #2 -- pull-to-refresh must not wire in the embed

`wirePullToRefresh()` is called unconditionally from `init()` -- no
`isEmbedMode` check anywhere near the call site. Team-lead's ruling: PT-33's
trackpad-overscroll pull-to-refresh adapter must not wire in the embed
(the dashboard card context makes it awkward UI), staying on for the
standalone board.

**Green-stays-green fence:** `tests/js/pull-refresh.test.js` and
`tests/js/wheel-adapter.test.js` test the PURE logic functions
(`pullPhase`, `pullIndicatorOffset`, `shouldCancelPull`, the wheel-gesture
reducer, etc.) -- never `wirePullToRefresh()`'s DOM-wiring call site or
`isEmbedMode` at all (checked directly, not assumed). Gating the wiring
call site on `isEmbedMode` cannot regress either file; both should stay
green exactly as they are.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"
PULL_REFRESH_JS_TEST = helpers.CAIRN_DIR / "tests" / "js" / "pull-refresh.test.js"
WHEEL_ADAPTER_JS_TEST = helpers.CAIRN_DIR / "tests" / "js" / "wheel-adapter.test.js"


class ExtractionError(AssertionError):
    """Same fail-loudly contract as this suite's other source-text
    extractors -- a genuinely missing function is a real problem, not
    something to silently skip past."""


def _extract_top_level_function_body(source: str, function_name: str) -> str:
    """Same line-based extractor as test_theme_menu_embed_close_behavior.py
    / test_theme_menu_popover_row_behavior.py -- duplicated locally per
    this suite's own precedent of keeping test files import-light."""
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


class LiveThemeFollowReachesTheEmbedTests(unittest.TestCase):
    """Finding #1: the cross-context storage/matchMedia listeners must be
    reachable when isEmbedMode is true -- pinning the DIAGNOSED root cause
    (an unconditional `return` in the embed branch), not a guess."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        source = BOARD_JS.read_text(encoding="utf-8")
        self.body = _extract_top_level_function_body(source, "wireThemeSettings")

    def test_storage_listener_exists_at_all(self):
        match = re.search(r"window\.addEventListener\(\s*['\"]storage['\"]", self.body)
        self.assertIsNotNone(match, "no window.addEventListener('storage', ...) found in wireThemeSettings")

    def test_storage_listener_is_reachable_when_embedded(self):
        # The exact diagnosed bug: an unconditional `return;` inside
        # `if (isEmbedMode) { ... }`, with the storage listener registered
        # LATER in the same top-level function body and not itself gated
        # on `!isEmbedMode` -- meaning it's unreachable whenever
        # isEmbedMode is true. A fix that moves the listener registration
        # before the embed check, or restructures the embed branch to not
        # `return` unconditionally (e.g. `if (isEmbedMode) { ...; } else {
        # ...UI wiring...}` with the listeners unconditional after), both
        # make this pass -- this test doesn't pin ONE specific refactor
        # shape, only the reachability outcome.
        embed_match = re.search(r"if\s*\(\s*isEmbedMode\s*\)\s*\{([^}]*)\}", self.body)
        self.assertIsNotNone(embed_match, "no `if (isEmbedMode) { ... }` block found in wireThemeSettings")
        embed_block = embed_match.group(1)
        storage_match = re.search(r"window\.addEventListener\(\s*['\"]storage['\"]", self.body)
        self.assertIsNotNone(storage_match, "no storage listener found in wireThemeSettings")

        embed_block_returns_unconditionally = re.search(r"(?<![\w.])return\s*;", embed_block) is not None
        storage_listener_is_after_embed_block = storage_match.start() > embed_match.end()
        self.assertFalse(
            embed_block_returns_unconditionally and storage_listener_is_after_embed_block,
            "wireThemeSettings's `if (isEmbedMode) { ... }` branch returns unconditionally "
            "BEFORE the storage listener is registered later in the same function -- the "
            "listener is therefore never attached when embedded, so a live cairn.theme change "
            "in the parent (dashboard) context never re-applies into the embedded board "
            "without a full reload. Mosko's exact finding #1.",
        )

    def test_matchmedia_system_follow_listener_is_also_reachable_when_embedded(self):
        # Same reachability question, for the OTHER cross-context listener
        # this function registers (architect's addendum item 3 / ux's
        # Mode addendum -- system-mode live-follow).
        embed_match = re.search(r"if\s*\(\s*isEmbedMode\s*\)\s*\{([^}]*)\}", self.body)
        self.assertIsNotNone(embed_match, "no `if (isEmbedMode) { ... }` block found in wireThemeSettings")
        embed_block = embed_match.group(1)
        matchmedia_match = re.search(r"matchMedia\([^)]*prefers-color-scheme[^)]*\)[\s\S]{0,200}?addEventListener\(\s*['\"]change['\"]", self.body)
        self.assertIsNotNone(matchmedia_match, "no matchMedia(...).addEventListener('change', ...) found in wireThemeSettings")

        embed_block_returns_unconditionally = re.search(r"(?<![\w.])return\s*;", embed_block) is not None
        matchmedia_listener_is_after_embed_block = matchmedia_match.start() > embed_match.end()
        self.assertFalse(
            embed_block_returns_unconditionally and matchmedia_listener_is_after_embed_block,
            "the system-mode matchMedia 'change' listener is also registered after an "
            "unconditional return in the isEmbedMode branch -- OS-level light/dark changes "
            "while mode=system would silently stop live-following once embedded, same root "
            "cause as the storage-listener gap.",
        )


class PullToRefreshDisabledWhenEmbeddedTests(unittest.TestCase):
    """Finding #2: PT-33's trackpad-overscroll pull-to-refresh adapter
    must not wire in the embed."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        source = BOARD_JS.read_text(encoding="utf-8")
        self.source = source
        self.init_body = _extract_top_level_function_body(source, "init")

    def test_wire_pull_to_refresh_is_called_from_init(self):
        match = re.search(r"wirePullToRefresh\(\)", self.init_body)
        self.assertIsNotNone(match, "wirePullToRefresh() is not called from init() at all")

    def test_wire_pull_to_refresh_call_is_gated_on_embed_mode(self):
        match = re.search(r"wirePullToRefresh\(\)", self.init_body)
        self.assertIsNotNone(match, "wirePullToRefresh() is not called from init() at all")
        # Proximity search (not full control-flow parsing, same discipline
        # as this feature's other isEmbedMode-adjacent guards): the call
        # site must have `isEmbedMode` referenced somewhere in the
        # preceding ~150 characters (an `if (!isEmbedMode)` guard on the
        # same or an immediately preceding line).
        window_start = max(0, match.start() - 150)
        neighborhood = self.init_body[window_start:match.start()]
        self.assertTrue(
            "isEmbedMode" in neighborhood,
            "wirePullToRefresh() in init() is called unconditionally -- no isEmbedMode check "
            "found in the ~150 characters immediately before the call. PT-33's trackpad-"
            "overscroll pull-to-refresh must not wire when the board is embedded in the "
            "dashboard (team-lead's ruling, finding #2) -- it should stay on standalone only.",
        )


class GreenStaysGreenFenceTests(unittest.TestCase):
    """Verifies the fence team-lead named explicitly: the pre-existing
    PT-33 JS tests exercise pure logic functions only, never
    wirePullToRefresh()'s DOM-wiring call site or isEmbedMode -- so
    gating that call site cannot regress them. Checked directly here
    (not just asserted in a comment) so this claim is itself guarded."""

    def test_pull_refresh_test_file_does_not_reference_embed_mode_or_the_wiring_function(self):
        self.assertTrue(PULL_REFRESH_JS_TEST.is_file(), f"{PULL_REFRESH_JS_TEST} does not exist")
        source = PULL_REFRESH_JS_TEST.read_text(encoding="utf-8")
        self.assertNotIn(
            "isEmbedMode", source,
            f"{PULL_REFRESH_JS_TEST} references isEmbedMode -- this test file's own docstring "
            f"claims it tests pure logic only; if that's changed, the green-stays-green "
            f"reasoning in this guard's docstring needs re-checking, not silently trusted.",
        )
        self.assertNotIn(
            "wirePullToRefresh", source,
            f"{PULL_REFRESH_JS_TEST} references wirePullToRefresh -- same concern as above.",
        )

    def test_wheel_adapter_test_file_does_not_reference_embed_mode_or_the_wiring_function(self):
        self.assertTrue(WHEEL_ADAPTER_JS_TEST.is_file(), f"{WHEEL_ADAPTER_JS_TEST} does not exist")
        source = WHEEL_ADAPTER_JS_TEST.read_text(encoding="utf-8")
        self.assertNotIn("isEmbedMode", source, f"{WHEEL_ADAPTER_JS_TEST} references isEmbedMode")
        self.assertNotIn("wirePullToRefresh", source, f"{WHEEL_ADAPTER_JS_TEST} references wirePullToRefresh")


class ExtractorSelfTests(unittest.TestCase):
    """Proves the reachability-detection logic used above CAN distinguish
    the buggy shape from a fixed one, against synthetic input -- not just
    that the real file currently reads one way."""

    def _reachable(self, body: str) -> bool:
        embed_match = re.search(r"if\s*\(\s*isEmbedMode\s*\)\s*\{([^}]*)\}", body)
        storage_match = re.search(r"window\.addEventListener\(\s*['\"]storage['\"]", body)
        if embed_match is None or storage_match is None:
            return False
        embed_block = embed_match.group(1)
        returns_unconditionally = re.search(r"(?<![\w.])return\s*;", embed_block) is not None
        listener_after = storage_match.start() > embed_match.end()
        return not (returns_unconditionally and listener_after)

    def test_current_buggy_shape_is_detected_as_unreachable(self):
        buggy = (
            "if (isEmbedMode) {\n"
            "  trigger.remove();\n"
            "  return;\n"
            "}\n"
            "trigger.addEventListener('click', function () {});\n"
            "window.addEventListener('storage', function (e) {});\n"
        )
        self.assertFalse(self._reachable(buggy))

    def test_listener_moved_before_the_embed_check_is_reachable(self):
        fixed = (
            "window.addEventListener('storage', function (e) {});\n"
            "if (isEmbedMode) {\n"
            "  trigger.remove();\n"
            "  return;\n"
            "}\n"
            "trigger.addEventListener('click', function () {});\n"
        )
        self.assertTrue(self._reachable(fixed))

    def test_embed_branch_without_a_return_is_reachable(self):
        fixed = (
            "if (isEmbedMode) {\n"
            "  trigger.remove();\n"
            "}\n"
            "window.addEventListener('storage', function (e) {});\n"
        )
        self.assertTrue(self._reachable(fixed))


if __name__ == "__main__":
    unittest.main()
