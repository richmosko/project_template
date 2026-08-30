"""PT-72 guard (architect's consolidated unified-shell ruling, issue
thread, 2026-08-30) -- the board-side (vanilla JS) half: a `readonly=1`
query flag, orthogonal to the existing `embed=1`, suppressing every write
affordance at a SINGLE point, plus the new `open=<id>` deep-link capability
the shell needs for card-click navigation.

Nothing under test exists yet -- confirmed by reading board.js/board.html/
board.css directly before writing anything below: no `readonly` query
handling anywhere, drag (`dragstart` + `card.draggable = isDraggable(...)`)
is attached unconditionally, no `open=<id>` handling on load, and no
`body.readonly`-keyed CSS rules.

**Structural claim this file is built around** (architect, verbatim,
gating): "One flag read once in `init()` -> adds a `body.readonly` class
and skips handler attachment. No branching inside render functions, no
parallel state machine. If it starts growing conditionals inside rendering
functions, that is the failure PT-55 predicted and the design is wrong."
This is directly testable: whatever identifier ends up holding the
readonly flag should appear in only a SMALL, enumerable set of top-level
wiring functions (the `init()`-adjacent ones), never scattered through
render helpers -- `ReadOnlySinglePointOfSuppressionTests` operationalizes
that claim as a count ceiling rather than trusting a promise.

**Contract this file assumes** (spec-by-test, nothing implemented yet):
a module-level identifier containing the substring "readonly" (case-
insensitive -- e.g. `isReadOnly`, mirroring `isEmbedMode`'s own naming),
computed once from `window.location.search`, mirroring the existing
`isEmbedMode` pattern exactly. If implementation-lead names it something
else entirely, the presence/count tests still key on the substring match,
not one exact identifier -- but update this docstring's naming assumption
if it diverges further than that.

**Hidden-in-readonly list** (architect relaying ux-designer's "complete"
enumeration): wordmark/masthead + board's own Dashboard tab (already
handled via `embed=1`, not this flag -- NOT re-tested here); filter row;
Kanban/List view tabs; create-issue button; drag affordances; per-lane
`.swimlane-toggle`/`.repo-group-toggle`; `#expand-all-btn`/`#collapse-all-btn`.
"Per-column add buttons" is in the architect's list too but doesn't exist
as a feature on this board at all yet (checked -- only the single global
`#new-issue-btn`) -- not tested here since there is nothing to hide.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"
BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"
BOARD_HTML = helpers.CAIRN_DIR / "board" / "board.html"

# Anchors specifically on the QUERY-PARAM NAME "readonly" being read from
# the URL (`.get("readonly")`, URLSearchParams-style), NOT a bare
# identifier-name substring search. board.js already has an unrelated,
# PRE-EXISTING per-issue concept that also contains the substring
# "readonly" -- `var readOnly = !!issue.read_only;` inside renderDrawer
# (foreign/archived-issue read-only-ness, an entirely different feature),
# plus the `record-readonly-note` CSS class. A naive substring search
# collides with both and produces a false green (caught while writing
# this file -- verified the collision is real by running the broad regex
# against the actual file before trusting a narrower one). Anchoring on
# the query-string read is unambiguous: the pre-existing per-issue
# variable is never assigned from a URL read.
QUERY_PARAM_READONLY_RE = re.compile(
    r'(?:var|const|let)\s+(\w+)\s*=\s*[^;\n]*get\(\s*[\'"]readonly[\'"]\s*\)[^;\n]*;?'
)


def _find_readonly_flag_identifier(source: str):
    """The identifier assigned from a `.get("readonly")` read (e.g. `var
    isReadOnly = params.get("readonly") === "1";`), or None if no such
    assignment exists yet. Spec-by-test on the exact SHAPE of that
    assignment (a `.get("readonly")` call on the right-hand side) -- not
    on any particular chosen identifier name."""
    match = QUERY_PARAM_READONLY_RE.search(source)
    return match.group(1) if match else None


# init()-adjacent wiring functions where the readonly flag is legitimately
# allowed to appear (gating whether a handler gets attached / a class
# gets applied) -- a generous but bounded allowlist, not an exact
# specification of implementation-lead's function names. The ceiling
# below is the actual enforcement; this list exists only for readable
# failure messages.
EXPECTED_TOUCH_POINTS_CEILING = 6


def _strip_js_comments(source: str) -> str:
    # Same state-machine stripper as test_theme_bootstrap_and_dropdown.py
    # / test_icon_consistency.py, duplicated locally per this suite's own
    # import-light precedent.
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


def _all_top_level_function_bodies(source: str) -> dict:
    """{name: body} for every top-level (2-space-indented) `function
    name(...) {` in board.js's IIFE -- from its own header line to the
    next top-level function header (or end of file)."""
    lines = source.splitlines()
    headers = []  # (line_index, name)
    header_re = re.compile(r"^  function (\w+)\s*\(")
    for i, line in enumerate(lines):
        m = header_re.match(line)
        if m:
            headers.append((i, m.group(1)))
    bodies = {}
    for idx, (start_idx, name) in enumerate(headers):
        end_idx = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        bodies[name] = "\n".join(lines[start_idx:end_idx])
    return bodies


class ReadOnlyFlagExistsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        self.source = _strip_js_comments(BOARD_JS.read_text(encoding="utf-8"))

    def test_a_readonly_flag_identifier_is_assigned_from_the_query_string(self):
        identifier = _find_readonly_flag_identifier(self.source)
        self.assertIsNotNone(
            identifier,
            "no identifier assigned from a `.get(\"readonly\")` (URLSearchParams-style) read "
            "found in board.js -- architect's ruling: a readonly=1 query flag, read once, "
            "mirroring isEmbedMode's own pattern. (Note: board.js already has an unrelated "
            "pre-existing per-issue `readOnly` local variable in renderDrawer -- that one is "
            "NOT what this test is looking for, and this test's detection deliberately can't "
            "be satisfied by it.)",
        )

    def test_body_gets_a_readonly_class_applied(self):
        self.assertTrue(
            "classList.add" in self.source and re.search(r'classList\.add\(\s*["\']readonly["\']', self.source) is not None,
            "no `classList.add(\"readonly\")` found -- architect's ruling: 'adds a "
            "body.readonly class'.",
        )


class ReadOnlySinglePointOfSuppressionTests(unittest.TestCase):
    """Operationalizes architect's explicit failure-mode warning as a
    count ceiling: the SPECIFIC board-wide readonly flag identifier
    (extracted from its own query-param-read assignment, not a bare
    substring search) must appear in only a SMALL, bounded set of top-
    level functions (init()-adjacent wiring), never scattered through
    render helpers. This is the guard against 'grows conditionals in
    render functions' -- the specific shape architect named as the design
    being wrong."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        source = _strip_js_comments(BOARD_JS.read_text(encoding="utf-8"))
        self.identifier = _find_readonly_flag_identifier(source)
        self.bodies = _all_top_level_function_bodies(source)

    def test_readonly_identifier_touches_only_a_bounded_number_of_functions(self):
        if self.identifier is None:
            self.skipTest("no readonly flag identifier found yet -- see ReadOnlyFlagExistsTests")
        pattern = re.compile(r"\b" + re.escape(self.identifier) + r"\b")
        touching = sorted(name for name, body in self.bodies.items() if pattern.search(body))
        self.assertLessEqual(
            len(touching), EXPECTED_TOUCH_POINTS_CEILING,
            f"the readonly flag identifier ({self.identifier!r}) appears in {len(touching)} "
            f"top-level functions: {touching} -- more than the {EXPECTED_TOUCH_POINTS_CEILING} "
            f"expected init()-adjacent wiring touch points. This is architect's named failure "
            f"mode: readonly conditionals spreading into render functions instead of being "
            f"suppressed once at the top (a body.readonly CSS class + skipped handler "
            f"attachment), which means the single-point-of-suppression design has already "
            f"been abandoned.",
        )


class DragDisabledInReadOnlyTests(unittest.TestCase):
    """Drag affordances: 'do not attach dragstart/drop, and set
    draggable=false.' Currently unconditional -- confirmed by reading
    board.js directly (card.draggable = isDraggable(...) and
    card.addEventListener("dragstart", ...) both run with no readonly
    check at all)."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        self.source = _strip_js_comments(BOARD_JS.read_text(encoding="utf-8"))
        self.identifier = _find_readonly_flag_identifier(self.source)

    def test_dragstart_attachment_is_gated_on_readonly(self):
        if self.identifier is None:
            self.skipTest("no readonly flag identifier found yet -- see ReadOnlyFlagExistsTests")
        match = re.search(r'addEventListener\(\s*["\']dragstart["\']', self.source)
        self.assertIsNotNone(match, "no dragstart listener attachment found in board.js at all")
        neighborhood = self.source[max(0, match.start() - 200):match.start()]
        self.assertIn(
            self.identifier, neighborhood,
            f"the dragstart listener attachment doesn't appear to be gated on the readonly "
            f"flag ({self.identifier!r}) -- architect's strip list: 'do not attach dragstart/"
            f"drop' in read-only.",
        )

    def test_card_draggable_assignment_is_gated_on_readonly(self):
        if self.identifier is None:
            self.skipTest("no readonly flag identifier found yet -- see ReadOnlyFlagExistsTests")
        match = re.search(r"\.draggable\s*=\s*isDraggable\(", self.source)
        self.assertIsNotNone(match, "no `.draggable = isDraggable(...)` assignment found in board.js at all")
        neighborhood = self.source[max(0, match.start() - 200):match.start()]
        self.assertIn(
            self.identifier, neighborhood,
            f"the card draggable assignment doesn't appear to be gated on the readonly flag "
            f"({self.identifier!r}) -- architect's strip list: 'set draggable=false' in "
            f"read-only.",
        )


class AlwaysExpandedLanesInReadOnlyTests(unittest.TestCase):
    """'Read-only ignores cairn.board.expandedLanes entirely and always
    renders fully expanded... Because the toggles are hidden and their
    handlers unattached, no write path to that key exists in read-only.'
    The existing expandAllLanes() helper (already used by the 'Expand
    all' button) is the natural mechanism to reuse -- this guard doesn't
    require that specific reuse, only that SOME readonly-gated path
    forces full expansion rather than reading the persisted key."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        self.source = _strip_js_comments(BOARD_JS.read_text(encoding="utf-8"))
        self.identifier = _find_readonly_flag_identifier(self.source)

    def test_expanded_lanes_state_is_forced_when_readonly(self):
        if self.identifier is None:
            self.skipTest("no readonly flag identifier found yet -- see ReadOnlyFlagExistsTests")
        match = re.search(r"expandAllLanes\(", self.source)
        self.assertIsNotNone(
            match,
            "no expandAllLanes(...) call found outside the existing 'Expand all' button wiring "
            "-- read-only needs SOME path that forces full lane expansion rather than reading "
            "the persisted cairn.board.expandedLanes key.",
        )
        # At least one expandAllLanes(...) call site must be reachable
        # from a readonly-gated context -- proximity check against every
        # occurrence, not just the first (the pre-existing "Expand all"
        # button call site is a real, legitimate OTHER occurrence).
        found_readonly_gated = False
        for m in re.finditer(r"expandAllLanes\(", self.source):
            neighborhood = self.source[max(0, m.start() - 300):m.start()]
            if self.identifier in neighborhood:
                found_readonly_gated = True
                break
        self.assertTrue(
            found_readonly_gated,
            f"found expandAllLanes(...) call site(s), but none appear gated on the readonly "
            f"flag ({self.identifier!r}) -- the pre-existing 'Expand all' button call site "
            f"alone doesn't satisfy 'read-only ALWAYS renders fully expanded', which must "
            f"happen automatically, not only on manual click.",
        )


class CardClickNavigatesShellInReadOnlyTests(unittest.TestCase):
    """ux's spec: 'Card click: navigates the shell (window.top.location,
    same-origin) to /dashboard/issues?issue=<id>... Not an inline edit,
    not a read-only modal in place -- avoids a second detail-view
    implementation, the exact thing PT-55 rejected read-only over.'

    Confirmed currently: `cardEl`'s click handler is unconditional --
    `card.addEventListener("click", function () { openDrawer(issue.id); });`
    -- it always opens the LOCAL drawer, with no readonly branch at all.
    In read-only, this must instead navigate window.top.location to the
    shell's Issue Tracking route with the issue id, not open anything
    locally."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        self.source = _strip_js_comments(BOARD_JS.read_text(encoding="utf-8"))
        self.identifier = _find_readonly_flag_identifier(self.source)

    def test_window_top_location_navigation_exists_somewhere(self):
        match = re.search(r"window\.top\.location", self.source)
        self.assertIsNotNone(
            match,
            "no `window.top.location` reference found in board.js -- ux's spec: card click in "
            "read-only navigates the shell via window.top.location (same-origin, no "
            "postMessage needed).",
        )

    def test_the_navigation_target_includes_the_dashboard_issues_route_and_issue_param(self):
        match = re.search(r"window\.top\.location[\s\S]{0,200}", self.source)
        if match is None:
            self.skipTest("no window.top.location reference found -- see the test above")
        neighborhood = match.group(0)
        self.assertTrue(
            "/dashboard/issues" in neighborhood and "issue=" in neighborhood,
            "found a window.top.location reference, but the nearby code doesn't obviously "
            "build a '/dashboard/issues?issue=<id>' URL -- ux's spec names this exact route + "
            "param shape.",
        )

    def test_card_click_handler_is_gated_on_the_readonly_flag(self):
        if self.identifier is None:
            self.skipTest("no readonly flag identifier found yet -- see ReadOnlyFlagExistsTests")
        match = re.search(r'card\.addEventListener\(\s*["\']click["\']', self.source)
        self.assertIsNotNone(match, "no card.addEventListener('click', ...) found in board.js at all")
        # The handler body itself (not just nearby code) needs to branch
        # on the readonly flag -- widen forward from the match to a
        # generous handler-body window rather than backward, since the
        # branch lives INSIDE the click callback, not before it.
        handler_window = self.source[match.start():match.start() + 400]
        self.assertIn(
            self.identifier, handler_window,
            f"the card click handler doesn't appear to branch on the readonly flag "
            f"({self.identifier!r}) -- it must navigate the shell in read-only instead of "
            f"opening the local drawer (openDrawer), per ux's spec.",
        )


class OpenIdDeepLinkTests(unittest.TestCase):
    """'Reading open=<id> on load and opening that drawer is a new board
    capability... small and clean, but it must be costed, not assumed
    free.' Confirmed absent: board.js has no query-string handling for
    an `open` param anywhere."""

    def setUp(self):
        self.assertTrue(BOARD_JS.is_file(), f"{BOARD_JS} does not exist")
        self.source = _strip_js_comments(BOARD_JS.read_text(encoding="utf-8"))

    def test_open_query_param_is_read(self):
        match = re.search(r'get\(\s*["\']open["\']\s*\)', self.source)
        self.assertIsNotNone(
            match,
            "no `.get(\"open\")` (URLSearchParams-style read of an `open` query param) found "
            "in board.js -- architect's ruling: /?embed=1&open=PT-42 must open that issue's "
            "drawer on load.",
        )

    def test_open_drawer_is_called_with_the_query_param_value(self):
        open_param_match = re.search(r'get\(\s*["\']open["\']\s*\)', self.source)
        if open_param_match is None:
            self.skipTest("no `open` query param read found -- see test_open_query_param_is_read")
        neighborhood = self.source[open_param_match.start():open_param_match.start() + 400]
        self.assertIn(
            "openDrawer(", neighborhood,
            "read the `open` query param but doesn't appear to call openDrawer(...) with it "
            "nearby -- reading the param alone doesn't open anything.",
        )


class ReadOnlyStripListCssTests(unittest.TestCase):
    """CSS-side hiding for the enumerated strip list, keyed on
    body.readonly -- filter row, view tabs, create-issue button, lane
    toggles, expand/collapse-all buttons."""

    STRIP_SELECTORS = (
        ".filters",
        ".view-tabs",
        "#new-issue-btn",
        "#expand-all-btn",
        "#collapse-all-btn",
        ".swimlane-toggle",
        ".repo-group-toggle",
    )

    def setUp(self):
        self.assertTrue(BOARD_CSS.is_file(), f"{BOARD_CSS} does not exist")
        source = BOARD_CSS.read_text(encoding="utf-8")
        self.stripped = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)

    def test_every_strip_list_selector_has_a_body_readonly_hide_rule(self):
        missing = []
        for selector in self.STRIP_SELECTORS:
            # `body.readonly <selector> { display: none; }` or a compound
            # selector list containing it -- tolerant of exact grouping,
            # requires the selector to appear somewhere after
            # `body.readonly` within the same rule's selector list.
            pattern = re.compile(
                r"body\.readonly[^{]*" + re.escape(selector) + r"[^{]*\{([^}]*)\}"
                r"|" + re.escape(selector) + r"[^{]*body\.readonly[^{]*\{([^}]*)\}",
            )
            match = pattern.search(self.stripped)
            if match is None or not re.search(r"display\s*:\s*none", match.group(0)):
                missing.append(selector)
        self.assertEqual(
            missing, [],
            f"{BOARD_CSS}: no `body.readonly ... {{ display: none; }}` rule found for "
            f"selector(s) {missing} -- architect's read-only strip list (filter row, view "
            f"tabs, create-issue button, lane toggles, expand/collapse-all).",
        )


class ExtractorSelfTests(unittest.TestCase):
    """Proves the top-level-function-body extractor and the readonly-
    flag-identifier finder CAN produce every result the tests above rely
    on, against synthetic input -- including reproducing the EXACT false-
    positive this file's own first draft hit (a broad substring search
    matching board.js's real, unrelated, pre-existing per-issue `readOnly`
    variable) so that specific regression can't recur silently."""

    def test_all_top_level_function_bodies_splits_correctly(self):
        source = (
            "  function a() {\n    var x = 1;\n  }\n"
            "  function b() {\n    var y = 2;\n  }\n"
        )
        bodies = _all_top_level_function_bodies(source)
        self.assertEqual(set(bodies), {"a", "b"})
        self.assertIn("var x = 1;", bodies["a"])
        self.assertNotIn("var y = 2;", bodies["a"])

    def test_finds_a_real_query_param_derived_readonly_flag(self):
        for snippet in (
            'var isReadOnly = params.get("readonly") === "1";',
            "const readOnly = new URLSearchParams(window.location.search).get('readonly') === '1';",
        ):
            identifier = _find_readonly_flag_identifier(snippet)
            self.assertIsNotNone(identifier, snippet)

    def test_does_not_match_boards_real_pre_existing_unrelated_readonly_variable(self):
        # The EXACT line from board.js's renderDrawer that fooled this
        # file's first-draft broad substring regex -- a per-issue
        # concept (foreign/archived-issue read-only-ness), never derived
        # from a query-string read. Reproduced verbatim as the regression
        # case, not paraphrased.
        real_unrelated_line = "var readOnly = !!issue.read_only;"
        self.assertIsNone(_find_readonly_flag_identifier(real_unrelated_line))

    def test_returns_none_when_no_readonly_assignment_exists_at_all(self):
        self.assertIsNone(_find_readonly_flag_identifier("var isEmbedMode = true;"))


if __name__ == "__main__":
    unittest.main()
