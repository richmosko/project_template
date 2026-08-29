"""PT-69 architect ruling §4 guard ("Chart-ramp validation -- per-variant,
extremal-surface, test-enforced"): every offered Chart Color variant ships
its own 6-step `--chart-flow-*` ordinal ramp (same PT-61 shape, re-stepped
per hue -- "the light-end floor failure ... will recur per hue, assume
every variant needs re-stepping, not just some"). The gate is structural:
"parameterize test_dashboard_chart_ramp.py's ChartRampOrdinalValidationTests
over every chart variant. A promise to run the validator is not a gate."

This file is a NEW, additive parameterized suite rather than an in-place
edit of test_dashboard_chart_ramp.py -- that file's own Stone/Yellow-
specific validation (against app.css's own --card) stays as-is and green;
this file re-validates EVERY chart variant (Yellow included) against the
architect's more general, stricter extremal-surface algorithm below, so it
subsumes rather than duplicates the existing coverage's *intent* without
touching a passing file mid-feature.

**Extremal-surface algorithm** (architect, verbatim reasoning): the naive
obligation is C x B x 2 validator runs (every chart variant, against every
base's --card, in both modes) because the ramp's contrast surface is
`--card`, which is Base-Color-dependent. It collapses to C x 2 because, for
a FIXED ramp, contrast against the card is monotone in card luminance on
each side: take the set of all `--card` values across every (base x mode)
combination and validate every ramp's light end against the MAXIMUM-
luminance card and its dark end against the MINIMUM-luminance card. If the
extremes pass, every base passes. The extrema are computed FROM THE DATA in
this file, never hardcoded (architect: "that is a fact about the option
set, and the option set will change").

Nothing under test exists yet (no board/variants.css, no dashboard/
variants.css) when this file is written -- every test either fails loudly
naming the missing construct or skips (never errors) if the dataviz
validator itself can't be located, mirroring test_dashboard_chart_ramp.py's
own discipline.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
BOARD_TOKENS_CSS = helpers.CAIRN_DIR / "board" / "tokens.css"
BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
APP_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "app.css"

# Reuse the established OKLCH<->hex bridge and validator-locator rather than
# re-deriving them -- same published Bjorn Ottosson matrices, already
# self-checked against the ruling's own reported numbers in that file's
# _SelfCheckTests.
sys.path.insert(0, str(helpers.TESTS_DIR))
from test_dashboard_chart_ramp import _oklch_to_hex, _find_validator_module  # noqa: E402

CHART_FLOW_NAMES = (
    "--chart-flow-backlog", "--chart-flow-todo", "--chart-flow-in-progress",
    "--chart-flow-in-review", "--chart-flow-done", "--chart-flow-cancelled",
)

CARD_RE = re.compile(r"--card\s*:\s*oklch\(([^)/]*)\)")
_VARIANT_BLOCK_OPEN_RE = re.compile(
    r':root(?P<dark>\.dark)?\[data-cairn-(?P<dim>base|theme|chart)="(?P<name>[\w-]+)"\]\s*\{'
)


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _extract_unqualified_block(source: str, selector: str) -> str:
    """Brace-matched body of the first top-level `selector { ... }` block
    (e.g. `:root`, `.dark`) -- same approach as test_board_tokens_parity's
    `_extract_block`, duplicated locally to keep this file import-light."""
    stripped = _strip_css_comments(source)
    match = re.search(re.escape(selector) + r"\s*\{", stripped)
    if not match:
        return ""
    depth, i, n = 1, match.end(), len(stripped)
    while i < n and depth > 0:
        if stripped[i] == "{":
            depth += 1
        elif stripped[i] == "}":
            depth -= 1
        i += 1
    return stripped[match.end() : i - 1]


def _find_variant_blocks(source: str):
    stripped = _strip_css_comments(source)
    for match in _VARIANT_BLOCK_OPEN_RE.finditer(stripped):
        depth, i, n = 1, match.end(), len(stripped)
        while i < n and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        yield match.group("dim"), match.group("name"), bool(match.group("dark")), stripped[match.end() : i - 1]


def _oklch_triple(text: str):
    parts = text.split()
    if len(parts) != 3:
        return None
    try:
        return tuple(float(p) for p in parts)
    except ValueError:
        return None


def _collect_all_card_hexes(module) -> list:
    """Every `--card` value across every (base x mode) combination, as hex:
    the DEFAULT (Stone) base from board/tokens.css's own :root/.dark, plus
    every named base variant's light/dark block in board/variants.css.
    Returns [] if the needed files don't exist yet -- callers skip in that
    case rather than treating an empty extrema set as meaningful."""
    hexes = []
    if BOARD_TOKENS_CSS.is_file():
        tokens_source = BOARD_TOKENS_CSS.read_text(encoding="utf-8")
        for selector in (":root", ".dark"):
            body = _extract_unqualified_block(tokens_source, selector)
            m = CARD_RE.search(body)
            if m:
                triple = _oklch_triple(m.group(1))
                if triple:
                    hexes.append(_oklch_to_hex(*triple, module.lin2s))
    if BOARD_VARIANTS_CSS.is_file():
        variants_source = BOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        for dim, name, is_dark, body in _find_variant_blocks(variants_source):
            if dim != "base":
                continue
            m = CARD_RE.search(body)
            if m:
                triple = _oklch_triple(m.group(1))
                if triple:
                    hexes.append(_oklch_to_hex(*triple, module.lin2s))
    return hexes


def _chart_flow_ramp(body: str, module) -> list:
    """The 6 `--chart-flow-*` values in `body`, in CHART_FLOW_NAMES order
    (the ramp's own defined step order), as hex. Returns None if any of
    the 6 names is absent, so callers can skip/fail with a clear reason
    rather than validating a partial ramp."""
    values = {}
    for name in CHART_FLOW_NAMES:
        m = re.search(re.escape(name) + r"\s*:\s*oklch\(([^)/]*)\)", body)
        if not m:
            return None
        triple = _oklch_triple(m.group(1))
        if not triple:
            return None
        values[name] = triple
    return [_oklch_to_hex(*values[name], module.lin2s) for name in CHART_FLOW_NAMES]


class ExtremalSurfaceComputationTests(unittest.TestCase):
    """The extrema-computation machinery itself, against synthetic input --
    proves it picks max/min by LUMINANCE (not by some incidental ordering),
    before any chart-variant test below trusts it."""

    def test_self_check_extrema_are_computed_not_hardcoded(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        # white, black, mid-gray -- luminance order is unambiguous.
        hexes = ["#ffffff", "#000000", "#808080"]
        brightest = max(hexes, key=module.relative_luminance)
        darkest = min(hexes, key=module.relative_luminance)
        self.assertEqual(brightest, "#ffffff")
        self.assertEqual(darkest, "#000000")


class ChartVariantRampOrdinalValidationTests(unittest.TestCase):
    """Parameterized (via subTest) over every chart variant found in
    board/variants.css, plus the DEFAULT (Yellow) ramp from app.css --
    validates each one's light-end ramp against the maximum-luminance
    --card across every (base x mode) combination, and its dark-end ramp
    against the minimum-luminance --card. Skips gracefully if the
    validator can't be located; fails (does not skip) if the variant files
    are simply missing, since that's the actual gap this guard exists to
    close before implementation-lead builds them."""

    def _extrema(self, module):
        hexes = _collect_all_card_hexes(module)
        if not hexes:
            self.skipTest(
                "no --card values found across board/tokens.css + board/variants.css -- "
                "see test_theme_variants_generator.py for the missing-file guards"
            )
        return max(hexes, key=module.relative_luminance), min(hexes, key=module.relative_luminance)

    def _validate_ramp(self, ramp_hexes, mode, surface_hex, module, label):
        report, ok = module.validate_ordinal(ramp_hexes, mode, surface_hex)
        self.assertTrue(
            ok,
            f"{label} ({mode}) chart-flow ramp fails the dataviz ordinal validator against "
            f"the {mode}-mode extremal --card {surface_hex}: {report}",
        )

    def test_every_chart_variant_ramp_passes_at_the_computed_extrema(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        light_surface, dark_surface = self._extrema(module)

        variants = {}  # name -> {"light": body, "dark": body}
        if BOARD_VARIANTS_CSS.is_file():
            for dim, name, is_dark, body in _find_variant_blocks(BOARD_VARIANTS_CSS.read_text(encoding="utf-8")):
                if dim != "chart":
                    continue
                variants.setdefault(name, {})["dark" if is_dark else "light"] = body

        # DEFAULT (Yellow) ramp lives, unqualified, in app.css -- included
        # so "every chart variant" genuinely means every OFFERED option,
        # not just the non-default ones represented via attribute blocks.
        if APP_CSS.is_file():
            app_source = APP_CSS.read_text(encoding="utf-8")
            variants.setdefault("yellow (default)", {})["light"] = _extract_unqualified_block(app_source, ":root")
            variants["yellow (default)"]["dark"] = _extract_unqualified_block(app_source, ".dark")

        if not variants:
            self.fail(
                "no chart variants found in board/variants.css or a default ramp in app.css -- "
                "the Chart Color dimension isn't wired up yet."
            )

        # Guard against a false-green: if board/variants.css doesn't exist
        # yet, `variants` still contains the pre-existing "yellow (default)"
        # entry from app.css, which would make this test vacuously pass
        # before any new variant is wired up. Require the ruled non-default
        # names to actually be present.
        #
        # Mosko's live-test finding #5 (issue thread, 2026-08-29, "fix
        # iteration before merge") LIFTED the ≤5-chart-variant cap and
        # ruled the full 23-alternate set (implementation-lead's
        # enumeration off the live generator's PRESET_CHART_COLORS, same
        # 24-name vocabulary as Theme) -- supersedes the earlier Yellow/
        # Blue/Violet curated set. Per implementation-lead's own note,
        # deriving+validating all 23 ramps is "the long pole" and lands
        # incrementally -- this floor is intentionally the FULL target,
        # not today's interim progress, so it stays red (correctly) until
        # every alternate is validated.
        required_non_default = {
            "neutral", "stone", "zinc", "amber", "blue", "cyan", "emerald", "fuchsia",
            "green", "indigo", "lime", "orange", "pink", "purple", "red", "rose",
            "sky", "teal", "violet", "mauve", "olive", "mist", "taupe",
        }
        missing = sorted(n for n in required_non_default if n not in variants)
        self.assertEqual(
            missing, [],
            f"expected chart variant(s) {sorted(required_non_default)} in "
            f"{BOARD_VARIANTS_CSS} (as data-cairn-chart=\"<name>\" blocks), missing: {missing} "
            f"-- only found {sorted(variants)}. Per Mosko's lifted-cap ruling, Chart Color "
            f"offers the full 24-name set (Yellow default + these 23 alternates).",
        )

        for name, modes in sorted(variants.items()):
            with self.subTest(chart_variant=name):
                self.assertIn("light", modes, f"{name}: no light-mode block found")
                self.assertIn("dark", modes, f"{name}: no dark-mode block found")
                light_ramp = _chart_flow_ramp(modes["light"], module)
                dark_ramp = _chart_flow_ramp(modes["dark"], module)
                self.assertIsNotNone(light_ramp, f"{name}: light-mode block is missing one or more of {CHART_FLOW_NAMES}")
                self.assertIsNotNone(dark_ramp, f"{name}: dark-mode block is missing one or more of {CHART_FLOW_NAMES}")
                self._validate_ramp(light_ramp, "light", light_surface, module, name)
                self._validate_ramp(dark_ramp, "dark", dark_surface, module, name)


class ChartFlowRampHelperSelfTests(unittest.TestCase):
    def test_chart_flow_ramp_returns_none_when_a_step_is_missing(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        body = "--chart-flow-backlog: oklch(0.77 0.17 95);"  # only 1 of 6
        self.assertIsNone(_chart_flow_ramp(body, module))

    def test_chart_flow_ramp_extracts_all_six_in_order(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        body = "\n".join(f"{name}: oklch(0.7 0.15 90);" for name in CHART_FLOW_NAMES)
        ramp = _chart_flow_ramp(body, module)
        self.assertEqual(len(ramp), 6)


if __name__ == "__main__":
    unittest.main()
