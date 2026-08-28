"""PT-57 (architect's token-delivery ruling, 2026-08-27): board/tokens.css
is a THIRD copy of the preset token values (alongside docs/DESIGN/
tokens.css and the dashboard's app.css) -- an accepted, unavoidable copy
per the ruling's own framing: "where a copy is unavoidable, make drift
loud." This is that loudness: parses the `:root`/`.dark` declarations out
of all three files and asserts every variable board/tokens.css shares with
the other two agrees on VALUE.

Not a set-equality check -- the three files deliberately carry different
key sets (docs/DESIGN/tokens.css and app.css carry font-family/typography
vars and app.css's extra --radius-2xl/3xl/4xl steps that board/tokens.css
explicitly omits, "colors and radius ONLY" per the ruling's own scope
cut). The guard is: for every key board/tokens.css DOES define, if either
other file also defines that key, the values must match. A key present in
board/tokens.css but absent from a sibling is not a failure (that's the
scope cut working as intended); a key present in more than one file with
DIFFERENT values is exactly the silent-drift this test exists to catch.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DOCS_TOKENS_CSS = REPO_ROOT / "docs" / "DESIGN" / "tokens.css"
APP_CSS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "app.css"
BOARD_TOKENS_CSS = helpers.CAIRN_DIR / "board" / "tokens.css"
BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"


class ExtractionError(AssertionError):
    """A required `:root`/`.dark` block could not be found -- raised
    loudly rather than silently comparing empty dicts (same discipline as
    every other source-text extractor in this suite)."""


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _extract_block(source: str, selector: str) -> dict:
    """The `{ --name: value; ... }` declarations inside the FIRST
    top-level block opened by `selector {`, keyed by variable name.
    Brace-matched (not a naive `[^}]*` capture), so a block containing a
    nested `calc(...)`-free ruleset boundary can't truncate early --
    board/tokens.css's `:root` block is followed immediately by `.dark`,
    and app.css's `:root` is followed by more content in the same file.
    """
    stripped = _strip_css_comments(source)
    match = re.search(re.escape(selector) + r"\s*\{", stripped)
    if not match:
        raise ExtractionError(
            f"could not find a `{selector} {{` block -- if this file's structure "
            f"changed, this guard needs to be updated, not silenced."
        )
    start = match.end()
    depth = 1
    i = start
    while i < len(stripped) and depth > 0:
        if stripped[i] == "{":
            depth += 1
        elif stripped[i] == "}":
            depth -= 1
        i += 1
    if depth != 0:
        raise ExtractionError(f"unbalanced braces while extracting `{selector}`'s block")
    body = stripped[start : i - 1]

    declarations = {}
    for decl_match in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body):
        name, value = decl_match.group(1), decl_match.group(2).strip()
        declarations[name] = value
    return declarations


def _assert_shared_keys_agree(testcase, base_name, base_decls, other_name, other_decls):
    mismatches = []
    for key, value in base_decls.items():
        if key in other_decls and other_decls[key] != value:
            mismatches.append((key, value, other_decls[key]))
    testcase.assertEqual(
        mismatches, [],
        f"{base_name} and {other_name} disagree on shared token(s): "
        + ", ".join(f"{k}: {base_name}={v1!r} vs {other_name}={v2!r}" for k, v1, v2 in mismatches),
    )


class BoardTokensRootParityTests(unittest.TestCase):
    def setUp(self):
        self.board_root = _extract_block(BOARD_TOKENS_CSS.read_text(encoding="utf-8"), ":root")
        self.docs_root = _extract_block(DOCS_TOKENS_CSS.read_text(encoding="utf-8"), ":root")
        self.app_root = _extract_block(APP_CSS.read_text(encoding="utf-8"), ":root")

    def test_board_tokens_root_agrees_with_docs_tokens_root(self):
        _assert_shared_keys_agree(self, "board/tokens.css :root", self.board_root, "docs/DESIGN/tokens.css :root", self.docs_root)

    def test_board_tokens_root_agrees_with_app_css_root(self):
        _assert_shared_keys_agree(self, "board/tokens.css :root", self.board_root, "dashboard app.css :root", self.app_root)

    def test_board_tokens_root_shares_a_real_non_trivial_key_set_with_each_sibling(self):
        # Guards against the comparison being vacuously true because the
        # extractor found nothing / found empty blocks.
        self.assertGreater(len(self.board_root.keys() & self.docs_root.keys()), 5)
        self.assertGreater(len(self.board_root.keys() & self.app_root.keys()), 5)

    def test_board_tokens_root_carries_font_vars_as_of_pt63(self):
        # PT-57 scoped board/tokens.css to "colors and radius ONLY" and
        # this test originally pinned that as a negative assertion (font
        # vars must be ABSENT). PT-63 is the pre-decided follow-up that
        # deliberately supersedes that scope cut -- the three preset faces
        # are now self-hosted (see vendor/NOTICE.md), so the negative
        # assertion flipped to a positive one: the font vars must be
        # PRESENT, and (via the shared-keys-agree check in setUp/the two
        # tests above) must match the sibling files' values exactly.
        for font_key in ("--font-sans", "--font-heading", "--font-mono"):
            self.assertIn(font_key, self.board_root, "board/tokens.css should carry font vars as of PT-63")


class BoardTokensDarkParityTests(unittest.TestCase):
    def setUp(self):
        self.board_dark = _extract_block(BOARD_TOKENS_CSS.read_text(encoding="utf-8"), ".dark")
        self.docs_dark = _extract_block(DOCS_TOKENS_CSS.read_text(encoding="utf-8"), ".dark")
        self.app_dark = _extract_block(APP_CSS.read_text(encoding="utf-8"), ".dark")

    def test_board_tokens_dark_agrees_with_docs_tokens_dark(self):
        _assert_shared_keys_agree(self, "board/tokens.css .dark", self.board_dark, "docs/DESIGN/tokens.css .dark", self.docs_dark)

    def test_board_tokens_dark_agrees_with_app_css_dark(self):
        _assert_shared_keys_agree(self, "board/tokens.css .dark", self.board_dark, "dashboard app.css .dark", self.app_dark)


def _extract_var_references(cssSource: str) -> set:
    """Every distinct `--name` referenced inside a `var(--name...)` call,
    anywhere in the file -- catches usage regardless of which selector
    it's under, including nested `var(--a, var(--b))` fallbacks (the
    regex matches each `var(` occurrence independently)."""
    stripped = _strip_css_comments(cssSource)
    return set(re.findall(r"var\(\s*(--[\w-]+)", stripped))


class BoardCssNoUndefinedVariablesTests(unittest.TestCase):
    """Architect's explicit ask ("while you're in here"): every `var(--x)`
    board.css reaches for must be defined somewhere it can actually see --
    board/tokens.css's `:root` (loaded before board.css, per the ruling)
    or board.css's own retained `:root` (`--card-gap`, `--col-gap`,
    `--shadow`). This is the single test that would have caught the
    `--accent` meaning-collision class the ruling flags as the highest-
    risk item, plus any plain typo or a token the board reaches for that
    nobody ships.
    """

    def test_every_var_reference_in_board_css_is_defined(self):
        board_css_source = BOARD_CSS.read_text(encoding="utf-8")
        referenced = _extract_var_references(board_css_source)

        board_tokens_root = _extract_block(BOARD_TOKENS_CSS.read_text(encoding="utf-8"), ":root")
        board_own_root = _extract_block(board_css_source, ":root")
        defined = set(board_tokens_root) | set(board_own_root)

        undefined = referenced - defined
        self.assertEqual(
            undefined, set(),
            f"board.css references undefined variable(s) {sorted(undefined)} -- not in "
            f"board/tokens.css's :root or board.css's own retained :root. This is exactly "
            f"the class of bug (a token the board reaches for but nobody ships) this guard "
            f"exists to catch.",
        )

    def test_var_reference_extractor_catches_a_real_undefined_variable(self):
        # Sanity: the extractor mechanism itself must be able to fail.
        source = ":root { --defined: red; } .x { color: var(--defined); background: var(--totally-undefined); }"
        referenced = _extract_var_references(source)
        defined = set(_extract_block(source, ":root"))
        self.assertEqual(referenced - defined, {"--totally-undefined"})


class ExtractorSelfTests(unittest.TestCase):
    """The extractor's own correctness, against synthetic source -- proves
    the guard mechanism CAN fail, not just that it currently doesn't."""

    def test_negative_control_a_real_mismatch_is_caught(self):
        base = {"--primary": "oklch(0.5 0.134 242.749)"}
        other = {"--primary": "oklch(0.1 0.1 100)"}
        with self.assertRaises(AssertionError):
            _assert_shared_keys_agree(self, "a", base, "b", other)

    def test_a_key_present_in_only_one_file_is_not_a_failure(self):
        base = {"--radius-xl": "calc(var(--radius) * 1.4)"}
        other = {"--radius-2xl": "calc(var(--radius) * 1.8)"}
        _assert_shared_keys_agree(self, "a", base, "b", other)  # must not raise

    def test_missing_block_raises_loudly_naming_the_selector(self):
        with self.assertRaises(ExtractionError) as ctx:
            _extract_block("body { color: red; }", ":root")
        self.assertIn(":root", str(ctx.exception))

    def test_brace_matching_does_not_truncate_at_a_nested_calc(self):
        source = ":root { --radius-sm: calc(var(--radius) * 0.6); --radius-lg: var(--radius); }"
        decls = _extract_block(source, ":root")
        self.assertEqual(decls["--radius-sm"], "calc(var(--radius) * 0.6)")
        self.assertEqual(decls["--radius-lg"], "var(--radius)")

    def test_comments_do_not_leak_fake_declarations(self):
        source = ":root { /* --fake: oklch(0 0 0); */ --real: oklch(1 0 0); }"
        decls = _extract_block(source, ":root")
        self.assertEqual(decls, {"--real": "oklch(1 0 0)"})


if __name__ == "__main__":
    unittest.main()
