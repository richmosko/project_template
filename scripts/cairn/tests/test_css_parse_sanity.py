"""CSS parse-sanity guard, filed after team-lead's PT-57 browser pass
found board.css shipping as a COMPLETELY DEAD stylesheet: a comment on
line 6 (`--chart-*/--radius(-sm/md/lg)`) contains a literal `*/`, which
terminates the `/* ... */` comment it's inside three lines early -- CSS
comments cannot nest, so that IS the real close, per spec. Everything
from there through the block's INTENDED closing `*/` thirteen lines later
(line 20) is then parsed as literal CSS code by a real browser, including
that now-orphaned `*/` itself -- a stray comment-closer with no comment
open to close, which cascaded into the browser dropping the entire
stylesheet: 0 cssRules.

Every source-text extractor in this test suite (board-css-token-
migration.test.js, board-css-badge-variants.test.js, test_board_tokens_
parity.py, embed-visibility-scope.test.js, ...) missed this completely.
That's not a bug in any ONE of them -- it's a whole CLASS of gap: they
each hunt for isolated `selector { declarations }` islands via regex
pattern-matching, which can find real-looking matches scattered through a
file a genuine CSS parser would treat as one giant corrupted comment/
code blob. None of them verify the file parses as ONE COHERENT structure
top to bottom. This file does that -- a single sequential scan (comment
state tracked properly; CSS comments don't nest, so "first close wins" is
the actual spec, not an approximation) that can't be fooled by an island
of valid-looking syntax sitting downstream of real structural damage.

Deliberately NOT a full CSS grammar validator (no such dependency exists
in this zero-build stack, and one isn't needed): a stray comment-closer,
an unbalanced/negative brace depth, or a top-level rule count that
collapses are each, on their own, a strong, cheap signal that a browser
would choke on the file -- exactly the kind of "honest, naive structural
pass" team-lead's own diagnostic used to find the bug in the first place.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import NamedTuple

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"
BOARD_TOKENS_CSS = helpers.CAIRN_DIR / "board" / "tokens.css"
DOCS_TOKENS_CSS = REPO_ROOT / "docs" / "DESIGN" / "tokens.css"
DASHBOARD_DIST_INDEX_CSS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "dist" / "assets" / "index.css"

# PT-69 (architect's theme-variant ruling, §2): "All three go into
# test_css_parse_sanity.py's file list -- a generated stylesheet is exactly
# as capable of shipping dead as a hand-written one, and a 0 cssRules
# variants.css would fail silently as 'theme just doesn't change.'"
BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
DASHBOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "variants.css"
DOCS_VARIANTS_CSS = REPO_ROOT / "docs" / "DESIGN" / "variants.css"


class CssStructuralScan(NamedTuple):
    stray_comment_closers: list  # char offsets of `*/` seen with no comment open
    unterminated_comment: bool  # source ended while still inside a `/* ... */`
    final_brace_depth: int  # `{` count minus `}` count, outside comments
    min_brace_depth: int  # the most negative the running depth ever went
    top_level_rule_count: int  # `{` seen at depth 0 (i.e. a new top-level rule opened)


def scan_css_structure(source: str) -> CssStructuralScan:
    """One sequential pass over the raw source, comment-state tracked
    properly (comments don't nest in CSS -- the first `*/` after a `/*`
    really does end it, full stop). Never raises: a malformed file is
    exactly the thing under test, so this function's job is to describe
    the damage, not to except on it.
    """
    in_comment = False
    depth = 0
    min_depth = 0
    top_level_rules = 0
    stray_closers = []
    i = 0
    n = len(source)
    while i < n:
        two = source[i : i + 2]
        if in_comment:
            if two == "*/":
                in_comment = False
                i += 2
                continue
            i += 1
            continue
        if two == "/*":
            in_comment = True
            i += 2
            continue
        if two == "*/":
            stray_closers.append(i)
            i += 2
            continue
        ch = source[i]
        if ch == "{":
            if depth == 0:
                top_level_rules += 1
            depth += 1
        elif ch == "}":
            depth -= 1
            min_depth = min(min_depth, depth)
        i += 1
    return CssStructuralScan(
        stray_comment_closers=stray_closers,
        unterminated_comment=in_comment,
        final_brace_depth=depth,
        min_brace_depth=min_depth,
        top_level_rule_count=top_level_rules,
    )


def _line_of(source: str, offset: int) -> int:
    """1-indexed line number containing `offset` -- turns a raw char
    position into something a human can jump to directly, per architect's
    "pinpoints the line" ask."""
    return source.count("\n", 0, offset) + 1


def _assert_structurally_sound(testcase: unittest.TestCase, path: Path, min_rules: int) -> None:
    source = path.read_text(encoding="utf-8")
    scan = scan_css_structure(source)
    stray_lines = [_line_of(source, off) for off in scan.stray_comment_closers]
    # Architect's measured correction (3bac0ea): against the ORIGINAL,
    # broken board.css, this stray-closer assertion was the SOLE
    # discriminating leg -- the rule-count floor below passed on that
    # exact file too (126 rules found vs. a floor of 50; a premature
    # comment close relocates where "code" starts, it doesn't shrink the
    # rule count), and brace depth was already 0. Do not read the
    # rule-count/brace-balance legs below as "the real check" with this
    # one as redundant detail -- prune this assertion and the guard stops
    # catching the exact bug it was born for. The other two legs are kept
    # because they catch DIFFERENT shapes (an unterminated comment, an
    # unbalanced/negative brace depth) that this one doesn't.
    testcase.assertEqual(
        scan.stray_comment_closers, [],
        f"{path}: found `*/` with no comment open, at line(s) {stray_lines} "
        f"(char offset(s) {scan.stray_comment_closers}) -- a comment EARLIER in the file "
        f"almost certainly contains a literal `*/` in its own prose (architect's PT-57 finding: "
        f"the auditable shape is any `*` immediately followed by `/` inside comment prose, "
        f"however innocuous-looking -- e.g. `--chart-*/--radius`, where the `*` belongs to one "
        f"token and the `/` to the next), closing that comment early (CSS comments cannot nest "
        f"-- the FIRST `*/` after a `/*` always wins) and turning everything after into literal, "
        f"likely-invalid CSS code -- including this now-orphaned `*/` itself. This is the exact "
        f"PT-57 bug class: a real browser can drop the ENTIRE stylesheet from this, while text-"
        f"pattern-matching guards miss it completely because they don't require the file to "
        f"parse as one coherent whole.",
    )
    testcase.assertFalse(
        scan.unterminated_comment,
        f"{path}: a `/* ... */` comment was never closed before end-of-file -- "
        f"everything after its opening `/*` is silently swallowed as comment text.",
    )
    testcase.assertEqual(
        scan.final_brace_depth, 0,
        f"{path}: unbalanced braces -- {scan.final_brace_depth} more "
        f"{'{' if scan.final_brace_depth > 0 else '}'} than its counterpart across the whole file.",
    )
    testcase.assertGreaterEqual(
        scan.min_brace_depth, 0,
        f"{path}: a `}}` appeared with no matching `{{` before it (brace depth went negative) -- "
        f"the file has more closing braces than could possibly be real rule closures at that point.",
    )
    # Architect verified (independently, via postcss.parse()): this
    # scanner's top_level_rule_count and a real CSS parser's rule count
    # can legitimately differ by a small amount on the SAME valid file --
    # 126 here vs. postcss's 127 on the fixed board.css -- because they
    # count different things. This counts every `{` seen at brace depth 0
    # (so an `@media {...}` block counts ONCE, its nested rules don't add
    # to the total); postcss counts parsed rule NODES, where an at-rule's
    # children are their own nodes. Harmless for a floor (both numbers
    # move together, and neither is anywhere near collapsing), but not a
    # discrepancy to "fix" if you ever see it -- they're answering
    # slightly different questions on purpose.
    testcase.assertGreaterEqual(
        scan.top_level_rule_count, min_rules,
        f"{path}: only {scan.top_level_rule_count} top-level rule(s) found (expected at least "
        f"{min_rules}) -- consistent with the file having structurally collapsed even though no "
        f"single check above caught it.",
    )


class BoardCssParseSanityTests(unittest.TestCase):
    def test_board_css_is_one_structurally_coherent_stylesheet(self):
        _assert_structurally_sound(self, BOARD_CSS, min_rules=50)


class BoardTokensCssParseSanityTests(unittest.TestCase):
    def test_board_tokens_css_is_one_structurally_coherent_stylesheet(self):
        _assert_structurally_sound(self, BOARD_TOKENS_CSS, min_rules=2)  # :root, .dark


class DocsTokensCssParseSanityTests(unittest.TestCase):
    def test_docs_tokens_css_is_one_structurally_coherent_stylesheet(self):
        _assert_structurally_sound(self, DOCS_TOKENS_CSS, min_rules=2)  # :root, .dark


class DashboardBuiltCssParseSanityTests(unittest.TestCase):
    def test_dashboard_dist_index_css_is_one_structurally_coherent_stylesheet(self):
        # team-lead's own "arguably" -- included since a bundled/minified
        # build output could theoretically carry the same class of bug if
        # any hand-authored source CSS with a raw comment flows into it
        # unprocessed. Skips cleanly if dist isn't built yet (a genuinely
        # different failure mode, already covered by test_dashboard.py's
        # DashboardBuildSmokeTests).
        if not DASHBOARD_DIST_INDEX_CSS.is_file():
            self.skipTest(f"{DASHBOARD_DIST_INDEX_CSS} not built yet")
        _assert_structurally_sound(self, DASHBOARD_DIST_INDEX_CSS, min_rules=10)


class ThemeVariantsCssParseSanityTests(unittest.TestCase):
    """PT-69: unlike DashboardBuiltCssParseSanityTests below, these are
    checked-in AUTHORED (generated-then-committed) artifacts, not a build
    output that might legitimately not exist yet pre-build -- so a missing
    file here is a hard failure, not a skip. See test_theme_variants_
    generator.py for the generator/regeneration contract these files come
    from."""

    def test_board_variants_css_is_one_structurally_coherent_stylesheet(self):
        self.assertTrue(BOARD_VARIANTS_CSS.is_file(), f"{BOARD_VARIANTS_CSS} does not exist")
        if BOARD_VARIANTS_CSS.is_file():
            _assert_structurally_sound(self, BOARD_VARIANTS_CSS, min_rules=10)

    def test_dashboard_variants_css_is_one_structurally_coherent_stylesheet(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file(), f"{DASHBOARD_VARIANTS_CSS} does not exist")
        if DASHBOARD_VARIANTS_CSS.is_file():
            _assert_structurally_sound(self, DASHBOARD_VARIANTS_CSS, min_rules=10)

    def test_docs_variants_css_is_one_structurally_coherent_stylesheet(self):
        self.assertTrue(DOCS_VARIANTS_CSS.is_file(), f"{DOCS_VARIANTS_CSS} does not exist")
        if DOCS_VARIANTS_CSS.is_file():
            _assert_structurally_sound(self, DOCS_VARIANTS_CSS, min_rules=10)


class ScanCssStructureSelfTests(unittest.TestCase):
    """The scanner's own correctness, against synthetic source -- proves
    it CAN detect each failure mode, not just that real files currently
    pass."""

    def test_the_exact_pt57_bug_shape_is_detected(self):
        # A comment containing a literal `*/` in its own prose, closing
        # early -- the precise shape found in board.css.
        source = "/* intro --chart-*/--radius etc. more prose */\n:root { --x: 1; }"
        scan = scan_css_structure(source)
        self.assertNotEqual(scan.stray_comment_closers, [])

    def test_well_formed_css_has_no_stray_closers(self):
        source = "/* a fine comment */\n:root { --x: 1; }\n.foo { color: red; }"
        scan = scan_css_structure(source)
        self.assertEqual(scan.stray_comment_closers, [])
        self.assertFalse(scan.unterminated_comment)
        self.assertEqual(scan.final_brace_depth, 0)
        self.assertEqual(scan.min_brace_depth, 0)
        self.assertEqual(scan.top_level_rule_count, 2)

    def test_line_of_reports_the_correct_1_indexed_line(self):
        source = "line one\nline two\nline three"
        self.assertEqual(_line_of(source, 0), 1)
        self.assertEqual(_line_of(source, 9), 2)  # first char of "line two"
        self.assertEqual(_line_of(source, 19), 3)  # first char of "line three"

    def test_unterminated_comment_is_detected(self):
        scan = scan_css_structure("/* never closes\n:root { --x: 1; }")
        self.assertTrue(scan.unterminated_comment)

    def test_unbalanced_open_brace_is_detected(self):
        scan = scan_css_structure(":root { --x: 1;")
        self.assertNotEqual(scan.final_brace_depth, 0)

    def test_negative_depth_from_a_stray_closing_brace_is_detected(self):
        scan = scan_css_structure(":root { --x: 1; } }")
        self.assertLess(scan.min_brace_depth, 0)

    def test_nested_braces_do_not_inflate_the_top_level_rule_count(self):
        # A CSS custom property value can itself contain balanced parens/
        # braces-like constructs in some future syntax; this scan only
        # counts `{` at depth 0 as a NEW top-level rule, so nested
        # structure (if it ever appears) doesn't double-count.
        source = ":root { --x: 1; }\n@media (min-width: 1px) { .a { color: red; } }"
        scan = scan_css_structure(source)
        self.assertEqual(scan.top_level_rule_count, 2)  # :root, and the @media block itself


if __name__ == "__main__":
    unittest.main()
