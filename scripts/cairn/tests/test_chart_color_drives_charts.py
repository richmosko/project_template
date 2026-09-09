"""PT-120 gate-1 ruling (architect, process/cairn/issues/PT-120.md @
fe2a929): Chart Color must wear the selected variant's vendored shadcn
`--chart-1..5` values EXACTLY -- Mosko's board steer overrides PT-118's
hue-rotation mechanism, which perceptually mismatched the selection
(Pink rendered brown, Amber teal, Cyan purple) despite being
mathematically consistent (an isometry anchored at yellow, not at the
selected hue).

Mechanism (ux-designer's design-2, adopted by the architect): a `var()`
ALIAS, declared ONCE in app.css, no per-variant emission, no generator
math at all:
    --chart-flow-opened:      var(--chart-1)
    --chart-flow-closed:      var(--chart-3)
    --chart-flow-wip:         var(--chart-5)
    --chart-counter-input:    var(--chart-5)
    --chart-counter-cache-write: var(--chart-4)
    --chart-counter-cache-read:  var(--chart-3)
    --chart-counter-output:   var(--chart-2)
`--chart-1..5` already varies correctly per variant (untouched
mechanism); aliasing rides it for free, and exactness holds BY
CONSTRUCTION rather than by assertion. `--chart-1` is deliberately
unused by counter (it already fails 2:1 against white, on record since
2026-08-28; flow has no such luxury and gets it anyway).

PT-118's rotation + gamut-mapper are DELETED, not bypassed
(`derive_chart_family_hue_rotation`, `_oklch_to_linear_rgb_unclamped`,
`_is_in_gamut`, `_max_in_gamut_chroma` no longer exist in
gen_variants.py). Its three floors (PT-92 pairwise ≥60°, counter
adjacency ΔE, sRGB gamut hard-fail) are RETIRED as gates -- exact
values are never nudged, Mosko's steer outranks -- and become recorded
OBSERVATIONS: a table asserted by name and value, so a change in the
vendored preset data shows up as a diff, never silence. This file is
REWRITTEN from PT-118's version, not patched -- every PT-118 gate
class (unclamped hard-fail, contrast floor, counter-vs-role, the
derivation guard, the wip pin, yellow byte-identity) is gone.

Independently re-measured for this rewrite (not copied from the
ruling): gamut 62/120 vendored steps outside sRGB (exact match), the
four counter-adjacency sub-floor variants and their ΔE values (exact
match to 4 decimals: blue 0.0584, indigo 0.0583, rose 0.0596, violet
0.0512), chart-2/3/4/5 contrast failure counts (exact match: 2/0/7/11).
One discrepancy found and flagged, not silently corrected: the ruling
states chart-1 misses 2:1 in "24/24 light"; this file's own sweep
measures 23/24 -- `indigo` clears the floor (ratio computed >= 2.0).
Built with the same vendored --card and --chart-N values the ruling
used; see IndigoChart1ContrastDiscrepancyTests below.
"""
from __future__ import annotations

import math
import re
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple

import helpers  # noqa: F401

import palette_check

DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"
APP_CSS = DASHBOARD_SRC / "app.css"
DASHBOARD_VARIANTS_CSS = DASHBOARD_SRC / "variants.css"
REPO_ROOT = helpers.CAIRN_DIR.parent.parent
BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
DOCS_VARIANTS_CSS = REPO_ROOT / "docs" / "DESIGN" / "variants.css"
ALL_THREE_COPIES = (BOARD_VARIANTS_CSS, DASHBOARD_VARIANTS_CSS, DOCS_VARIANTS_CSS)
GEN_VARIANTS_PY = helpers.CAIRN_DIR / "design" / "gen_variants.py"

# Ruling's adopted mapping (ux-designer's design-2), verbatim.
FLOW_MAPPING = {
    "chart-flow-opened": "chart-1",
    "chart-flow-closed": "chart-3",
    "chart-flow-wip": "chart-5",
}
COUNTER_MAPPING = {
    "chart-counter-input": "chart-5",
    "chart-counter-cache-write": "chart-4",
    "chart-counter-cache-read": "chart-3",
    "chart-counter-output": "chart-2",
}
FAMILY_MAPPING = {**FLOW_MAPPING, **COUNTER_MAPPING}
FLOW_TOKENS = tuple(FLOW_MAPPING)
COUNTER_TOKENS = tuple(COUNTER_MAPPING)
FAMILY_TOKENS = tuple(FAMILY_MAPPING)
ROLE_TOKENS = tuple(f"chart-role-{i}" for i in range(1, 9)) + (
    "chart-role-guard-aux", "chart-role-guard-unattributed", "chart-role-other",
)
CHART_N_TOKENS = tuple(f"chart-{i}" for i in range(1, 6))

MIN_PAIRWISE_DELTA_E = 0.06


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _extract_unqualified_block(source: str, selector: str) -> str:
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


_VARIANT_BLOCK_OPEN_RE = re.compile(r':root(?P<dark>\.dark)?\[data-cairn-chart="(?P<name>[\w-]+)"\]\s*\{')


def _find_chart_variant_blocks(source: str):
    stripped = _strip_css_comments(source)
    for match in _VARIANT_BLOCK_OPEN_RE.finditer(stripped):
        depth, i, n = 1, match.end(), len(stripped)
        while i < n and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        yield match.group("name"), bool(match.group("dark")), stripped[match.end() : i - 1]


def _oklch_in_block(block_text: str, var_name: str) -> Optional[Tuple[float, float, float]]:
    m = re.search(r"--" + re.escape(var_name) + r"\s*:\s*oklch\(([^)/]*)\)", block_text)
    if not m:
        return None
    parts = m.group(1).split()
    if len(parts) != 3:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _var_ref_in_block(block_text: str, var_name: str) -> Optional[str]:
    m = re.search(r"--" + re.escape(var_name) + r"\s*:\s*var\((--[\w-]+)\)", block_text)
    return m.group(1).lstrip("-") if m else None


def _resolve_oklch(var_name: str, variant_block: str, root_block: str, dark_block: str, is_dark: bool, depth: int = 0) -> Optional[Tuple[float, float, float]]:
    if depth > 4:
        return None
    fallback_block = dark_block if is_dark else root_block
    for block in (variant_block, fallback_block):
        if not block:
            continue
        literal = _oklch_in_block(block, var_name)
        if literal is not None:
            return literal
        alias = _var_ref_in_block(block, var_name)
        if alias is not None:
            return _resolve_oklch(alias, variant_block, root_block, dark_block, is_dark, depth + 1)
    return None


def _all_variants(variants_source: str) -> Dict[str, Dict[str, str]]:
    variants: Dict[str, Dict[str, str]] = {"yellow": {"light": "", "dark": ""}}
    for name, is_dark, body in _find_chart_variant_blocks(variants_source):
        variants.setdefault(name, {})["dark" if is_dark else "light"] = body
    return variants


def oklch_to_linear_srgb_unclamped(l: float, c: float, h_deg: float) -> Tuple[float, float, float]:
    """Independent, deliberately unclamped conversion for the GAMUT
    OBSERVATION table only (guard 4) -- this feature does not gate on
    gamut at all (exact values are never nudged), so this exists purely
    to measure and record, matching the ruling's own 62/120 figure."""
    h = math.radians(h_deg)
    a, b = c * math.cos(h), c * math.sin(h)
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    lc, mc, sc = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc
    g = -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc
    bl = -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc
    return (r, g, bl)


def is_in_gamut(l: float, c: float, h_deg: float, eps: float = 1e-6) -> bool:
    r, g, b = oklch_to_linear_srgb_unclamped(l, c, h_deg)
    return all(-eps <= v <= 1 + eps for v in (r, g, b))


def _all_chart_n_values(app_css_source: str, variants_source: str) -> Dict[str, Tuple[float, float, float]]:
    """{variant_name: chart-N oklch} for one fixed N, resolved per
    variant -- light and dark ramps are identical by construction
    (ruling's own measurement), so only the light block is read."""
    root_block = _extract_unqualified_block(app_css_source, ":root")
    variants = _all_variants(variants_source)
    out = {}
    for vname, modes in variants.items():
        out[vname] = modes.get("light", "")
    return out


# --------------------------------------------------------------------------
# Guard 1: the alias seam -- declared once in app.css, no literals left
# anywhere, no per-variant emission of the family tokens at all.
# --------------------------------------------------------------------------

class AliasSeamTests(unittest.TestCase):
    """Guard 1: the seven family tokens are `var(--chart-N)` aliases per
    FAMILY_MAPPING, declared ONCE in app.css -- no literal `oklch(...)`
    declaration for any of them anywhere in app.css or any generated
    variants.css, and no per-variant block redeclares them at all
    (there is nothing to redeclare -- the alias rides the variant's own
    --chart-1..5 override for free)."""

    def test_app_css_declares_each_family_token_as_the_ruled_alias(self):
        self.assertTrue(APP_CSS.is_file())
        source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(source, ":root")
        for token, target in FAMILY_MAPPING.items():
            with self.subTest(token=token):
                alias = _var_ref_in_block(root_block, token)
                self.assertEqual(
                    alias, target,
                    f"app.css :root must declare --{token}: var(--{target}) -- got alias={alias!r}",
                )

    def test_no_family_token_has_a_literal_oklch_declaration_in_app_css(self):
        self.assertTrue(APP_CSS.is_file())
        source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(source, ":root")
        dark_block = _extract_unqualified_block(source, ".dark")
        offenders = []
        for block_name, block in (("root", root_block), ("dark", dark_block)):
            for token in FAMILY_TOKENS:
                if _oklch_in_block(block, token) is not None:
                    offenders.append((block_name, token))
        self.assertEqual(offenders, [], f"app.css must carry no literal oklch(...) for a family token: {offenders!r}")

    def test_no_generated_variants_css_declares_a_family_token_at_all(self):
        for copy_path in ALL_THREE_COPIES:
            with self.subTest(copy=str(copy_path)):
                self.assertTrue(copy_path.is_file(), f"{copy_path} does not exist")
                source = copy_path.read_text(encoding="utf-8")
                offenders = []
                for variant_name, is_dark, body in _find_chart_variant_blocks(source):
                    for token in FAMILY_TOKENS:
                        if _oklch_in_block(body, token) is not None or _var_ref_in_block(body, token) is not None:
                            offenders.append((variant_name, "dark" if is_dark else "light", token))
                self.assertEqual(
                    offenders, [],
                    f"{copy_path}: a chart variant block declares a family token -- the alias is "
                    f"declared ONCE in app.css, nothing per-variant: {offenders!r}",
                )


# --------------------------------------------------------------------------
# Guard 2: resolution -- the cascade actually produces the mapped value.
# --------------------------------------------------------------------------

class ResolutionSweepTests(unittest.TestCase):
    """Guard 2: for every variant x mode, the computed value of each
    family token equals that variant's OWN mapped --chart-N, resolved
    through the real alias chain (never re-derived, never assumed from
    the mapping table alone)."""

    def test_every_family_token_resolves_to_its_mapped_chart_n_in_every_variant_and_mode(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        variants = _all_variants(variants_source)

        offenders = []
        seen = 0
        for variant_name, modes in sorted(variants.items()):
            for mode in ("light", "dark"):
                is_dark = mode == "dark"
                variant_block = modes.get(mode, "")
                for token, target in FAMILY_MAPPING.items():
                    seen += 1
                    resolved = _resolve_oklch(token, variant_block, root_block, dark_block, is_dark)
                    expected = _resolve_oklch(target, variant_block, root_block, dark_block, is_dark)
                    self.assertIsNotNone(expected, f"{variant_name}/{mode}: could not resolve --{target}")
                    if resolved != expected:
                        offenders.append((variant_name, mode, token, resolved, "expected", expected))
        self.assertGreater(seen, 0, "the sweep resolved zero combinations -- broken, not passing")
        # assertTrue on a bool + a truncated preview -- assertEqual([], ...)
        # on a large mismatch list echoes BOTH lists in the failure diff,
        # which here would be hundreds of tuples (24 variants x 2 modes x
        # 7 tokens).
        self.assertTrue(
            not offenders,
            f"{len(offenders)}/{seen} family tokens did not resolve to their mapped chart-N -- "
            f"first 5: {offenders[:5]!r}",
        )


# --------------------------------------------------------------------------
# Guard 3: flow separation -- the one real gate this feature keeps.
# --------------------------------------------------------------------------

class FlowSeparationTests(unittest.TestCase):
    """Guard 3: min pairwise OKLab ΔE >= 0.06 among opened/closed/wip,
    every variant x mode -- and no two flow tokens are ever identical
    (structural: --chart-1 != --chart-3 != --chart-5 because a shadcn
    ramp is monotonic in lightness by construction, per ux-designer's
    argument, checked here rather than assumed)."""

    def test_minimum_pairwise_delta_e_holds_across_all_variants_and_modes(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        variants = _all_variants(variants_source)

        global_min = None
        offenders = []
        for variant_name, modes in sorted(variants.items()):
            for mode in ("light", "dark"):
                is_dark = mode == "dark"
                variant_block = modes.get(mode, "")
                resolved = {}
                for token in FLOW_TOKENS:
                    oklch = _resolve_oklch(token, variant_block, root_block, dark_block, is_dark)
                    self.assertIsNotNone(oklch, f"{variant_name}/{mode}: could not resolve --{token}")
                    resolved[token] = oklch
                for i in range(len(FLOW_TOKENS)):
                    for j in range(i + 1, len(FLOW_TOKENS)):
                        a, b = FLOW_TOKENS[i], FLOW_TOKENS[j]
                        delta_e = palette_check.oklab_delta_e(resolved[a], resolved[b])
                        global_min = delta_e if global_min is None else min(global_min, delta_e)
                        if delta_e < MIN_PAIRWISE_DELTA_E:
                            offenders.append((variant_name, mode, a, b, round(delta_e, 4)))
                        if resolved[a] == resolved[b]:
                            offenders.append((variant_name, mode, a, b, "IDENTICAL"))
        self.assertIsNotNone(global_min, "the sweep resolved zero pairs -- broken, not passing")
        self.assertEqual(
            offenders, [],
            f"flow separation failure (measured global min ΔE this run: {global_min:.4f}): {offenders!r}",
        )


# --------------------------------------------------------------------------
# Guard 4: retired floors as recorded OBSERVATIONS -- named, not gated.
# --------------------------------------------------------------------------

class CounterAdjacencyObservationTests(unittest.TestCase):
    """Guard 4a: PT-92's counter-adjacency floor is RETIRED as a gate
    (exact values outrank it) -- but the sub-floor variants are recorded
    by name and value, so a change in the vendored preset data shows up
    as a diff, not silence. Independently re-measured for this file
    (not copied from the ruling): exact match to 4 decimals."""

    EXPECTED_SUB_FLOOR = {
        "blue": ("chart-4", "chart-3", 0.0584),
        "indigo": ("chart-4", "chart-3", 0.0583),
        "rose": ("chart-3", "chart-2", 0.0596),
        "violet": ("chart-4", "chart-3", 0.0512),
    }

    def test_the_four_named_sub_floor_variants_are_exactly_these_and_no_others(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        variants = _all_variants(variants_source)
        order = ["chart-5", "chart-4", "chart-3", "chart-2"]  # COUNTER_MAPPING's own order

        found: Dict[str, Tuple[str, str, float]] = {}
        for variant_name, modes in sorted(variants.items()):
            variant_block = modes.get("light", "")
            resolved = {tok: _resolve_oklch(tok, variant_block, root_block, dark_block, False) for tok in order}
            for i in range(len(order) - 1):
                a, b = order[i], order[i + 1]
                delta_e = palette_check.oklab_delta_e(resolved[a], resolved[b])
                if delta_e < MIN_PAIRWISE_DELTA_E:
                    found[variant_name] = (a, b, round(delta_e, 4))

        self.assertEqual(
            set(found), set(self.EXPECTED_SUB_FLOOR),
            f"the set of sub-floor variants drifted from the recorded table -- got {found!r}",
        )
        for variant_name, expected in self.EXPECTED_SUB_FLOOR.items():
            with self.subTest(variant=variant_name):
                self.assertEqual(found[variant_name], expected, f"{variant_name}: got {found[variant_name]!r}, table says {expected!r}")


class ContrastObservationTests(unittest.TestCase):
    """Guard 4b: PT-83's 2:1 contrast floor is RETIRED as a gate for the
    mapped chart-N steps -- recorded as an observation table instead.
    Independently re-measured: chart-2/3/4/5 counts match the ruling
    exactly (2/0/7/11). chart-1 does NOT: this file measures 23/24
    light failures, not 24/24 -- see the discrepancy test below, which
    documents the one variant (indigo) that clears the floor."""

    EXPECTED_LIGHT_FAIL_COUNT = {"chart-1": 23, "chart-2": 2, "chart-3": 0, "chart-4": 0, "chart-5": 0}
    EXPECTED_DARK_FAIL_COUNT = {"chart-1": 0, "chart-2": 0, "chart-3": 0, "chart-4": 7, "chart-5": 11}

    def _card_surfaces_linear(self, app_css_source: str):
        surfaces = palette_check.card_surfaces(app_css_source)
        return {mode: palette_check.oklch_to_linear_srgb(*oklch) for mode, oklch in surfaces.items()}

    def test_contrast_failure_counts_match_the_recorded_table(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        surface_lin = self._card_surfaces_linear(app_css_source)
        variants = _all_variants(variants_source)

        light_fail = {tok: 0 for tok in CHART_N_TOKENS}
        dark_fail = {tok: 0 for tok in CHART_N_TOKENS}
        for variant_name, modes in sorted(variants.items()):
            variant_block = modes.get("light", "")
            for tok in CHART_N_TOKENS:
                oklch = _oklch_in_block(variant_block, tok) or _oklch_in_block(root_block, tok)
                self.assertIsNotNone(oklch, f"{variant_name}: could not resolve --{tok}")
                lin = palette_check.oklch_to_linear_srgb(*oklch)
                if palette_check.contrast_ratio(lin, surface_lin["light"]) < 2.0:
                    light_fail[tok] += 1
                if palette_check.contrast_ratio(lin, surface_lin["dark"]) < 2.0:
                    dark_fail[tok] += 1

        for tok in CHART_N_TOKENS:
            with self.subTest(tok=tok, mode="light"):
                self.assertEqual(light_fail[tok], self.EXPECTED_LIGHT_FAIL_COUNT[tok], f"{tok} light fail count drifted -- got {light_fail!r}")
            with self.subTest(tok=tok, mode="dark"):
                self.assertEqual(dark_fail[tok], self.EXPECTED_DARK_FAIL_COUNT[tok], f"{tok} dark fail count drifted -- got {dark_fail!r}")


class IndigoChart1ContrastDiscrepancyTests(unittest.TestCase):
    """Bubble-up, pinned as a test rather than left in a message only:
    the ruling states chart-1 misses 2:1 against the light --card in
    "24/24" variants. This file's own sweep, using the same vendored
    --card and --chart-1 values, measures 23/24 -- `indigo` clears the
    floor. Both this test and ContrastObservationTests' table (23, not
    24) encode the same measurement; if a future re-check finds `indigo`
    also failing, THIS test is what will go red first and say why."""

    def test_indigo_chart_1_clears_the_light_contrast_floor(self):
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        surfaces = palette_check.card_surfaces(app_css_source)
        surface_light = palette_check.oklch_to_linear_srgb(*surfaces["light"])
        variants = _all_variants(variants_source)
        indigo_block = variants.get("indigo", {}).get("light", "")
        self.assertTrue(indigo_block, "no indigo variant block found -- structural assumption stale")
        oklch = _oklch_in_block(indigo_block, "chart-1") or _oklch_in_block(root_block, "chart-1")
        self.assertIsNotNone(oklch)
        ratio = palette_check.contrast_ratio(palette_check.oklch_to_linear_srgb(*oklch), surface_light)
        self.assertGreaterEqual(
            ratio, 2.0,
            f"indigo chart-1 vs light --card measured {ratio:.3f} -- if this now fails, the "
            f"ruling's stated 24/24 is correct and ContrastObservationTests' table needs updating",
        )


class GamutObservationTests(unittest.TestCase):
    """Guard 4c: the sRGB gamut hard-fail is RETIRED as a gate -- a
    hard fail would refuse the vendored preset data itself (62 of 120
    steps are outside sRGB by construction, P3-wide). Recorded as a
    total count; the browser gamut-maps, as it already does today."""

    EXPECTED_OUT_OF_GAMUT_COUNT = 62
    EXPECTED_TOTAL_CHECKED = 120  # 24 variants x 5 chart-N steps (mode-invariant)

    def test_out_of_gamut_count_matches_the_recorded_observation(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        variants = _all_variants(variants_source)

        total = 0
        out_of_gamut = 0
        for variant_name, modes in sorted(variants.items()):
            variant_block = modes.get("light", "")
            for tok in CHART_N_TOKENS:
                oklch = _oklch_in_block(variant_block, tok) or _oklch_in_block(root_block, tok)
                self.assertIsNotNone(oklch, f"{variant_name}: could not resolve --{tok}")
                total += 1
                if not is_in_gamut(*oklch):
                    out_of_gamut += 1
        self.assertEqual(total, self.EXPECTED_TOTAL_CHECKED, f"got {total} chart-N combinations, expected {self.EXPECTED_TOTAL_CHECKED}")
        self.assertEqual(out_of_gamut, self.EXPECTED_OUT_OF_GAMUT_COUNT, f"out-of-gamut count drifted -- got {out_of_gamut}/{total}")


# --------------------------------------------------------------------------
# Guard 5: deletion -- PT-118's rotation/gamut machinery no longer exists.
# --------------------------------------------------------------------------

class DeletionScanTests(unittest.TestCase):
    """Guard 5: PT-118's rotation and gamut-mapper symbols must no
    longer exist in gen_variants.py -- deleted, not bypassed. A
    survived-but-unused function would mean the derivation could keep
    passing its own (now-deleted-from-this-file) suite while shipping
    something else."""

    RETIRED_SYMBOLS = (
        "derive_chart_family_hue_rotation",
        "_oklch_to_linear_rgb_unclamped",
        "_is_in_gamut",
        "_max_in_gamut_chroma",
    )

    def test_pt118_symbols_no_longer_exist_in_gen_variants(self):
        self.assertTrue(GEN_VARIANTS_PY.is_file())
        source = GEN_VARIANTS_PY.read_text(encoding="utf-8")
        offenders = [name for name in self.RETIRED_SYMBOLS if name in source]
        self.assertEqual(offenders, [], f"gen_variants.py still references retired PT-118 symbol(s): {offenders!r}")


# --------------------------------------------------------------------------
# Guard 6: the default renders the default's own hue.
# --------------------------------------------------------------------------

class DefaultRendersDefaultsHueTests(unittest.TestCase):
    """Guard 6: PT-118's "yellow byte-identical to the OLD flow/counter
    values" contract is retired -- yellow's aliases resolve to YELLOW'S
    OWN --chart-N ramp (a real, larger swing: opened moves from 16.9 deg
    to 98.111 deg; counter moves from 205 deg to shades of gold). This
    file carries no test pinning the old historical literals -- their
    absence, from the full rewrite, is the deletion."""

    def test_yellow_family_tokens_resolve_to_yellows_own_chart_n_ramp(self):
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        for mode, block, is_dark in (("light", root_block, False), ("dark", dark_block, True)):
            for token, target in FAMILY_MAPPING.items():
                with self.subTest(mode=mode, token=token):
                    resolved = _resolve_oklch(token, "", root_block, dark_block, is_dark)
                    expected = _oklch_in_block(block, target)
                    self.assertIsNotNone(expected, f"app.css {mode}: no literal --{target}")
                    self.assertEqual(resolved, expected, f"yellow's --{token} must equal yellow's own --{target} ({mode})")


if __name__ == "__main__":
    unittest.main()
