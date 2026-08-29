"""PT-57 (Board: migrate board.css to preset tokens) -- regression pass,
structural/behavioral half (team-lead's framing: "functional in both
views + drawer", not visual -- the browser pass covers looks).

board.js drives interaction state entirely through `classList.add/remove/
toggle` -- drag-and-drop, the drawer/overlay open state, pull-to-refresh
spinner, filter validation, embed mode, collapsible lanes. A pure CSS
migration touches none of that JS, but it's exactly the kind of change
that COULD silently orphan a class (a selector renamed or a rule deleted
during the token rewrite, while the JS side keeps toggling the old name)
-- the AC's "remains functional" claim, made concrete: every class board.js
ever toggles must still have at least one real CSS rule SOMEWHERE the board
loads it from (board.css, board/tokens.css, or board/variants.css --
widened for PT-69, see the comment on BOARD_TOKENS_CSS_PATH below)
referencing it, cross-language, same JC1 rationale as test_column_parity.py
(Python is the unconditional hard gate; this lives here, not only in the
JS suite, so it's enforced regardless of whether `node` is available).

This is a REGRESSION guard, not a red-then-green feature test -- every
class here should already have a matching rule (the migration was colors/
radius only, no selectors touched, per the ruling). Green today by design;
it exists to fail loudly the moment that stops being true.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

BOARD_JS_PATH = helpers.CAIRN_DIR / "board" / "board.js"
BOARD_CSS_PATH = helpers.CAIRN_DIR / "board" / "board.css"

# PT-69 (implementation-lead's finding, 2026-08-29): board.js's first-ever
# `classList.toggle("dark", ...)` call (the new Mode mechanism) legitimately
# has ITS selector -- `.dark` -- live in board/tokens.css (the custom-
# property override block board.css's own rules consume via var()), not in
# board.css itself; board.css was never meant to carry its own duplicate
# `.dark` selector. Widened to also scan board/tokens.css and board/
# variants.css (a future variant could in principle add its own toggled
# class) so this guard doesn't flag a real, correctly-placed selector as
# orphaned just because it isn't physically inside board.css.
BOARD_TOKENS_CSS_PATH = helpers.CAIRN_DIR / "board" / "tokens.css"
BOARD_VARIANTS_CSS_PATH = helpers.CAIRN_DIR / "board" / "variants.css"


class ExtractionError(AssertionError):
    """Same fail-loudly contract as test_column_parity.py's own
    ExtractionError -- a pattern that stops matching must error, not
    silently compare empty to empty."""


def extract_toggled_classes(js_source: str) -> set:
    """Every class name literal passed to `.classList.add(...)`,
    `.classList.remove(...)`, or `.classList.toggle(...)` in board.js --
    the full set of classes JS can ever apply/remove at runtime. Only the
    literal FIRST argument is captured (classList.toggle's optional
    second boolean argument is irrelevant here); a computed/templated
    class name (never used in board.js today) would simply not match,
    which is the correct behavior for a source-text guard -- it can only
    see literals.
    """
    matches = re.findall(r'classList\.(?:add|remove|toggle)\(\s*"([\w-]+)"', js_source)
    if not matches:
        raise ExtractionError(
            "found zero classList.add/remove/toggle(\"...\") calls in board.js -- if this "
            "pattern changed (e.g. classList calls removed entirely, or a different API "
            "adopted), this guard needs to be updated, not silenced."
        )
    return set(matches)


def extract_css_defined_classes(css_source: str) -> set:
    """Every class name (without the leading dot) that appears anywhere
    in a CSS selector in board.css -- deliberately permissive (matches
    `.foo` as part of any compound/descendant selector, e.g.
    `body.embed`, `.column.drop-target`, `.card.is-archived`), since the
    claim under test is "this class is styled somewhere," not "this class
    has its own standalone rule."
    """
    stripped = re.sub(r"/\*.*?\*/", "", css_source, flags=re.DOTALL)
    return set(re.findall(r"\.([\w-]+)", stripped))


class BoardJsCssClassContractTests(unittest.TestCase):
    def setUp(self):
        self.js_source = BOARD_JS_PATH.read_text(encoding="utf-8")
        # Concatenated, not just board.css: a selector board.js toggles can
        # legitimately live in tokens.css/variants.css (custom-property
        # override blocks) rather than board.css's own rules -- see the
        # PT-69 comment on BOARD_TOKENS_CSS_PATH above. variants.css may
        # not exist yet on a given checkout (generated artifact), so it's
        # included only if present.
        css_sources = [BOARD_CSS_PATH.read_text(encoding="utf-8"), BOARD_TOKENS_CSS_PATH.read_text(encoding="utf-8")]
        if BOARD_VARIANTS_CSS_PATH.is_file():
            css_sources.append(BOARD_VARIANTS_CSS_PATH.read_text(encoding="utf-8"))
        self.css_source = "\n".join(css_sources)

    def test_every_class_board_js_toggles_has_a_real_css_rule(self):
        toggled = extract_toggled_classes(self.js_source)
        defined = extract_css_defined_classes(self.css_source)
        orphaned = toggled - defined
        self.assertEqual(
            orphaned, set(),
            f"board.js toggles class(es) {sorted(orphaned)} via classList that board.css no "
            f"longer styles at all -- a selector was likely renamed or deleted during the "
            f"PT-57 token migration, silently breaking the visual feedback for that state",
        )

    def test_toggled_class_set_is_non_trivial(self):
        # Guards against the extraction silently finding nothing and the
        # test above passing vacuously (empty set minus anything is
        # still empty).
        toggled = extract_toggled_classes(self.js_source)
        self.assertGreaterEqual(len(toggled), 5, toggled)


class ExtractorSelfTests(unittest.TestCase):
    def test_negative_control_extractor_finds_a_real_orphan(self):
        js = 'el.classList.add("totally-orphaned-class");'
        css = ".some-other-class { color: red; }"
        toggled = extract_toggled_classes(js)
        defined = extract_css_defined_classes(css)
        self.assertIn("totally-orphaned-class", toggled - defined)

    def test_extractor_handles_add_remove_and_toggle(self):
        js = (
            'a.classList.add("x");\n'
            'b.classList.remove("y");\n'
            'c.classList.toggle("z", someCondition);\n'
        )
        self.assertEqual(extract_toggled_classes(js), {"x", "y", "z"})

    def test_css_extractor_finds_classes_inside_compound_selectors(self):
        css = "body.embed .app-title { display: none; } .column.drop-target { outline: 1px; }"
        found = extract_css_defined_classes(css)
        self.assertIn("embed", found)
        self.assertIn("drop-target", found)

    def test_missing_classlist_calls_raises_loudly(self):
        with self.assertRaises(ExtractionError):
            extract_toggled_classes("function noop() {}")


if __name__ == "__main__":
    unittest.main()
