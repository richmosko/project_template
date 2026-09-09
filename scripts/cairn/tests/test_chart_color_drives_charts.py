"""PT-118 gate-1 ruling (architect, process/cairn/issues/PT-118.md @
c80dee8): Chart Color now drives BOTH charts via a global hue rotation
(Δh = variant.chart-1.h - yellow.chart-1.h, mode-invariant) applied to
the flow (`--chart-flow-opened/closed/wip`) and counter
(`--chart-counter-input/cache-write/cache-read/output`) families, L/C
held, THEN gamut-mapped (binary-search the largest in-gamut C at fixed
L/h) -- rotation alone is not enough (finding 3: 61 of 322 land outside
sRGB after a bare rotation). The role family (`--chart-role-1..8` + 3
neutral guards) stays FIXED across every variant -- an identity mapping
(PT-69/PT-79), not a stylistic preference; rotating it would put 146 of
368 checks outside sRGB.

Finding 1, the reason this file exists rather than reusing
`gen_variants._oklch_to_linear_rgb`: that helper clamps to [0,1] ON
RETURN, so any gamut check built on it passes by construction (the
architect's own control, L .6/C .40/h300, came back "in range").
`oklch_to_linear_srgb_unclamped` below is a deliberate SECOND, clamp-free
implementation -- the thing being detected is the clamp itself, so the
detector cannot share code with it (guard 5, `GamutCheckDoesNotUseTheClampingHelperTests`).

Finding 2: `--chart-flow-wip` (oklch 0.62/0.15/200.8 light, 0.60/0.13/
200.8 dark) is out of gamut TODAY, at Δh=0 (no rotation involved) --
red channel -0.091 light. A hard-fail gamut gate is therefore expected
to fail on the yellow/default variant until ux-designer re-authors
wip's chroma or explicitly grandfathers it; `YELLOW_GAMUT_EXCLUDE`
below names whichever token stays excluded once that decision lands.

All sweeps read the GENERATED CSS text directly (dashboard/src/
variants.css), never gen_variants.py's internal math -- matching
test_flow_series_distinctness.py's own resolve-from-source approach,
so this file is decoupled from exactly how the generator computes a
value and only cares what it emits.
"""
from __future__ import annotations

import inspect
import math
import re
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import helpers  # noqa: F401

import palette_check

DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"
APP_CSS = DASHBOARD_SRC / "app.css"
DASHBOARD_VARIANTS_CSS = DASHBOARD_SRC / "variants.css"
REPO_ROOT = helpers.CAIRN_DIR.parent.parent
BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
DOCS_VARIANTS_CSS = REPO_ROOT / "docs" / "DESIGN" / "variants.css"
ALL_THREE_COPIES = (BOARD_VARIANTS_CSS, DASHBOARD_VARIANTS_CSS, DOCS_VARIANTS_CSS)

FLOW_TOKENS = ("chart-flow-opened", "chart-flow-closed", "chart-flow-wip")
COUNTER_TOKENS = ("chart-counter-input", "chart-counter-cache-write", "chart-counter-cache-read", "chart-counter-output")
ROTATING_TOKENS = FLOW_TOKENS + COUNTER_TOKENS
ROLE_TOKENS = tuple(f"chart-role-{i}" for i in range(1, 9)) + (
    "chart-role-guard-aux", "chart-role-guard-unattributed", "chart-role-other",
)

CONTRAST_FLOOR = 2.0
# Architect's own measured floor (finding 4, PT-118.md @c80dee8): "0
# pairs below ΔE 0.06, min pairwise ΔE 0.0705 before and after" -- tighter
# than palette_check's generic categorical floor (0.06), used here as the
# regression pin for this specific token family.
MIN_PAIRWISE_DELTA_E = 0.0705

# Named per team-lead's instruction: ux-designer's wip decision (finding
# 2: re-author the ratified chroma, or grandfather the out-of-gamut
# value) had not landed on the issue at write time. Update this set the
# moment it does -- empty once wip is back in-gamut everywhere; unchanged
# (still excluding "chart-flow-wip") if grandfathered instead.
YELLOW_GAMUT_EXCLUDE: set = {"chart-flow-wip"}


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


def _hue_distance(h1: float, h2: float) -> float:
    diff = abs(h1 - h2) % 360
    return min(diff, 360 - diff)


# --------------------------------------------------------------------------
# Finding 1: a deliberately SEPARATE, unclamped OKLCH -> linear-sRGB
# conversion. Must not call, import, or otherwise reuse
# gen_variants._oklch_to_linear_rgb (guard 5) -- that is the exact
# vacuous-check defect this file exists to avoid repeating.
# --------------------------------------------------------------------------

def oklch_to_linear_srgb_unclamped(l: float, c: float, h_deg: float) -> Tuple[float, float, float]:
    h = math.radians(h_deg)
    a, b = c * math.cos(h), c * math.sin(h)
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    lc, mc, sc = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc
    g = -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc
    bl = -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc
    return (r, g, bl)  # deliberately NOT clamped


def is_in_gamut(l: float, c: float, h_deg: float, eps: float = 1e-6) -> bool:
    r, g, b = oklch_to_linear_srgb_unclamped(l, c, h_deg)
    return all(-eps <= v <= 1 + eps for v in (r, g, b))


def _iter_variant_mode_token_oklch(variants_source: str, app_css_source: str):
    """Yields (variant_name, mode, token, (l, c, h)) for every ROTATING
    token (flow + counter) resolved across every variant x mode --
    variant's own declaration first, falling back to app.css's :root/
    .dark (the "yellow"/unrotated case, and any token a variant does not
    override)."""
    root_block = _extract_unqualified_block(app_css_source, ":root")
    dark_block = _extract_unqualified_block(app_css_source, ".dark")
    variants = _all_variants(variants_source)
    for variant_name, modes in sorted(variants.items()):
        for mode in ("light", "dark"):
            is_dark = mode == "dark"
            variant_block = modes.get(mode, "")
            for token in ROTATING_TOKENS:
                oklch = _resolve_oklch(token, variant_block, root_block, dark_block, is_dark)
                if oklch is not None:
                    yield variant_name, mode, token, oklch


class ClampDetectionControlTests(unittest.TestCase):
    """Guard 1's own precondition: the architect's control probe (finding
    1) must FAIL the unclamped check, or the whole sweep is vacuous
    again -- this is the exact case that silently passed through
    gen_variants._oklch_to_linear_rgb."""

    def test_the_far_out_probe_fails_the_unclamped_gamut_check(self):
        self.assertFalse(
            is_in_gamut(0.6, 0.40, 300.0),
            "L .6/C .40/h300 must fail an unclamped gamut check -- if this passes, the check "
            "is clamping somewhere and the whole sweep is vacuous (finding 1)",
        )

    def test_a_known_in_gamut_value_passes(self):
        # Control in the other direction: a real, already-ratified token
        # (--chart-role-1) must read as in-gamut.
        self.assertTrue(is_in_gamut(0.570, 0.1587, 252.00))


class GamutCheckDoesNotUseTheClampingHelperTests(unittest.TestCase):
    """Guard 5: pins finding 1's defect so it cannot silently return --
    this file's gamut detector must never call, import, or reuse
    gen_variants's own clamping helper."""

    def test_this_modules_source_never_imports_gen_variants(self):
        # An import STATEMENT, not a bare substring scan -- this module's
        # own docstrings and comments discuss gen_variants.py's clamping
        # defect by name (that is the whole point of this file), so a
        # naive "gen_variants" in this_file scan would false-positive on
        # its own documentation.
        this_file = Path(__file__).read_text(encoding="utf-8")
        for line in this_file.splitlines():
            stripped = line.strip()
            with self.subTest(line=stripped[:80]):
                self.assertFalse(
                    stripped.startswith("import gen_variants") or stripped.startswith("from gen_variants"),
                    "test_chart_color_drives_charts.py must not import anything from gen_variants.py -- "
                    "the gamut check must be a genuinely separate implementation (finding 1)",
                )

    def test_oklch_to_linear_srgb_unclamped_never_clamps(self):
        # Comment-stripped first -- the function's own docstring/comment
        # explains it is "deliberately NOT clamped", which contains the
        # word being scanned for.
        source = inspect.getsource(oklch_to_linear_srgb_unclamped)
        code_only = re.sub(r"#.*", "", source)
        for forbidden in ("min(", "max("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code_only, f"the unclamped conversion must not call {forbidden!r}")


class UnclampedGamutSweepTests(unittest.TestCase):
    """Guard 1: every rotating (flow + counter) token, every variant,
    both modes, must be in-gamut under the UNCLAMPED check -- a silent
    clamp is exactly the defect finding 1 measured. Expected red today:
    chart-flow-wip is out of gamut at its current ratified value
    (finding 2), independent of rotation."""

    def test_every_rotating_token_is_in_gamut_in_every_variant_and_mode(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file(), f"{DASHBOARD_VARIANTS_CSS} does not exist")
        self.assertTrue(APP_CSS.is_file(), f"{APP_CSS} does not exist")
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        offenders = []
        seen = 0
        for variant, mode, token, (l, c, h) in _iter_variant_mode_token_oklch(variants_source, app_css_source):
            seen += 1
            if not is_in_gamut(l, c, h):
                offenders.append((variant, mode, token, (l, c, h)))
        self.assertGreater(seen, 0, "the sweep resolved zero (variant, mode, token) combinations -- broken, not passing")
        self.assertEqual(offenders, [], f"out-of-gamut rotating tokens (unclamped check): {offenders!r}")


class ContrastFloorSweepTests(unittest.TestCase):
    """Guard 2: every rotating token clears the 2:1 WCAG floor against
    BOTH modes' own real --card (the two-model form), every variant,
    both modes -- reuses palette_check's vendored (clamped-at-render,
    correct for what a browser actually paints) contrast math."""

    def test_every_rotating_token_clears_contrast_against_both_cards(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        surfaces = palette_check.card_surfaces(app_css_source)
        surface_lin = {mode: palette_check.oklch_to_linear_srgb(*oklch) for mode, oklch in surfaces.items()}
        offenders = []
        seen = 0
        for variant, mode, token, (l, c, h) in _iter_variant_mode_token_oklch(variants_source, app_css_source):
            seen += 1
            lin = palette_check.oklch_to_linear_srgb(l, c, h)
            for surface_mode, surface in surface_lin.items():
                ratio = palette_check.contrast_ratio(lin, surface)
                if ratio < CONTRAST_FLOOR:
                    offenders.append((variant, mode, token, f"vs --card({surface_mode})", round(ratio, 3)))
        self.assertGreater(seen, 0, "the sweep resolved zero combinations -- broken, not passing")
        self.assertEqual(offenders, [], f"contrast floor failures (< {CONTRAST_FLOOR}:1): {offenders!r}")


class CounterFamilyAdjacentSeparationSweepTests(unittest.TestCase):
    """Guard 3, counter half: the 4-step `--chart-counter-*` family is an
    ORDERED progression (palette_check.py's own established criterion,
    `check_counter_palette` / `MIN_ADJACENT_DELTA_L`), not an unordered
    categorical set -- adjacent steps must be individually
    distinguishable in COUNTER_TOKEN_ORDER, not just "some pair
    somewhere is far enough apart." Rotation holds L fixed (only C is
    ever gamut-mapped), so this is invariant under Δh by construction --
    swept per variant x mode anyway as an explicit regression floor,
    since a bug in the mapping step could still perturb L.

    NOT combined with the flow family: flow and counter render on
    DIFFERENT charts (IssueFlowChart vs TokenCostChart's tokens view)
    and are never shown together, so a flow-vs-counter distinctness
    check has no visual meaning -- measured live, e.g. dark-mode
    chart-flow-wip vs chart-counter-cache-write today sit only OKLab dE
    0.0665 apart, which would spuriously fail a combined check for two
    colours a reader never sees side by side."""

    def test_adjacent_counter_steps_stay_separated_in_every_variant_and_mode(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        variants = _all_variants(variants_source)

        offenders = []
        seen = 0
        for variant_name, modes in sorted(variants.items()):
            for mode in ("light", "dark"):
                is_dark = mode == "dark"
                variant_block = modes.get(mode, "")
                resolved = {}
                for token in palette_check.COUNTER_TOKEN_ORDER:
                    name = token[2:] if token.startswith("--") else token  # tolerate either spelling
                    oklch = _resolve_oklch(name, variant_block, root_block, dark_block, is_dark)
                    self.assertIsNotNone(oklch, f"{variant_name}/{mode}: could not resolve --{name}")
                    resolved[token] = oklch
                for i in range(len(palette_check.COUNTER_TOKEN_ORDER) - 1):
                    seen += 1
                    a, b = palette_check.COUNTER_TOKEN_ORDER[i], palette_check.COUNTER_TOKEN_ORDER[i + 1]
                    delta_l = abs(resolved[b][0] - resolved[a][0])
                    if delta_l < palette_check.MIN_ADJACENT_DELTA_L:
                        offenders.append((variant_name, mode, a, b, round(delta_l, 4)))
        self.assertGreater(seen, 0, "the sweep resolved zero adjacent pairs -- broken, not passing")
        self.assertEqual(
            offenders, [],
            f"adjacent counter steps below the {palette_check.MIN_ADJACENT_DELTA_L} ΔL floor: {offenders!r}",
        )


class CounterVsRoleCollisionSweepTests(unittest.TestCase):
    """Guard 3, the new cross-family risk PT-118 introduces: counter now
    rotates per variant while role stays fixed (ruling 3) -- the same
    identity-collision risk test_flow_series_distinctness.py's
    NoCollisionWithChartRolePaletteTests already guards for flow, but
    that test only checks app.css's own (unrotated) values, never swept
    per variant. Counter and role DO appear on the same chart
    (TokenCostChart's cost view is role-coloured, its tokens view is
    counter-coloured) -- a reader who has seen one view must not read a
    rotated counter hue as a specific roster role in the other. Same
    25-degree floor as the established flow-vs-role check."""

    ROLE_COLLISION_HUE_FLOOR_DEGREES = 25.0

    def test_no_counter_hue_matches_a_role_hue_in_any_variant_or_mode(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        variants = _all_variants(variants_source)

        offenders = []
        seen = 0
        for variant_name, modes in sorted(variants.items()):
            for mode in ("light", "dark"):
                is_dark = mode == "dark"
                variant_block = modes.get(mode, "")
                role_hues = {}
                for token in ROLE_TOKENS:
                    oklch = _resolve_oklch(token, "", root_block, dark_block, is_dark)
                    self.assertIsNotNone(oklch, f"{mode}: could not resolve --{token} in app.css")
                    role_hues[token] = oklch[2]
                for token in COUNTER_TOKENS:
                    oklch = _resolve_oklch(token, variant_block, root_block, dark_block, is_dark)
                    self.assertIsNotNone(oklch, f"{variant_name}/{mode}: could not resolve --{token}")
                    for role_name, role_hue in role_hues.items():
                        seen += 1
                        distance = _hue_distance(oklch[2], role_hue)
                        if distance < self.ROLE_COLLISION_HUE_FLOOR_DEGREES:
                            offenders.append((variant_name, mode, token, role_name, round(distance, 1)))
        self.assertGreater(seen, 0, "the sweep resolved zero counter-vs-role pairs -- broken, not passing")
        self.assertEqual(
            offenders, [],
            f"counter hue within {self.ROLE_COLLISION_HUE_FLOOR_DEGREES} deg of a fixed role hue: {offenders!r}",
        )


HUE_TOLERANCE_DEGREES = 0.5
L_TOLERANCE = 1e-6
C_TOLERANCE = 1e-6


class DerivationIsObservablePerVariantTests(unittest.TestCase):
    """team-lead's red-2 addition: the sweeps above are a FLOOR, not a
    red for the feature itself -- today every variant carries IDENTICAL
    flow/counter values (no rotation implemented yet), so contrast/
    distinctness/identity all pass vacuously before any implementation
    exists. This guard asserts the derivation actually happened: for
    every non-default (non-yellow) chart variant x mode, each rotating
    token's hue equals yellow's hue + Δh(variant) (mod 360, tolerance
    <=0.5 deg), L equals yellow's exactly (rotation holds L), and C may
    only SHRINK relative to yellow's (gamut-mapping only ever reduces
    chroma, never grows it). Δh(variant) is read from --chart-1, the
    ALREADY-declared per-variant token (ux-designer's own derivation
    rule) -- never hand-computed or duplicated from gen_variants.py."""

    def _delta_h(self, variant_block: str, root_block: str, dark_block: str, is_dark: bool, yellow_chart1_hue: float) -> float:
        oklch = _resolve_oklch("chart-1", variant_block, root_block, dark_block, is_dark)
        self.assertIsNotNone(oklch, "could not resolve --chart-1 for this variant/mode")
        return (oklch[2] - yellow_chart1_hue) % 360

    def test_every_rotating_token_matches_its_derived_position_in_every_non_default_variant(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        variants = _all_variants(variants_source)

        offenders = []
        seen = 0
        for mode, block, is_dark in (("light", root_block, False), ("dark", dark_block, True)):
            yellow_chart1 = _oklch_in_block(block, "chart-1")
            self.assertIsNotNone(yellow_chart1, f"app.css {mode}: no literal --chart-1")
            yellow_hue = yellow_chart1[2]
            yellow_tokens = {}
            for token in ROTATING_TOKENS:
                oklch = _oklch_in_block(block, token)
                self.assertIsNotNone(oklch, f"app.css {mode}: no literal --{token}")
                yellow_tokens[token] = oklch

            for variant_name, modes in sorted(variants.items()):
                if variant_name == "yellow":
                    continue
                variant_block = modes.get(mode, "")
                self.assertTrue(variant_block, f"{variant_name}/{mode}: no variant block found at all")
                delta_h = self._delta_h(variant_block, root_block, dark_block, is_dark, yellow_hue)

                for token in ROTATING_TOKENS:
                    seen += 1
                    yl, yc, yh = yellow_tokens[token]
                    resolved = _resolve_oklch(token, variant_block, root_block, dark_block, is_dark)
                    self.assertIsNotNone(resolved, f"{variant_name}/{mode}: could not resolve --{token}")
                    vl, vc, vh = resolved

                    expected_hue = (yh + delta_h) % 360
                    hue_gap = _hue_distance(vh, expected_hue)
                    if hue_gap > HUE_TOLERANCE_DEGREES:
                        offenders.append((variant_name, mode, token, "hue", f"got {vh:.2f}, expected {expected_hue:.2f} (Δh={delta_h:.2f}), off by {hue_gap:.2f} deg"))
                    if abs(vl - yl) > L_TOLERANCE:
                        offenders.append((variant_name, mode, token, "L", f"got {vl}, yellow's is {yl} -- rotation must hold L exactly"))
                    if vc > yc + C_TOLERANCE:
                        offenders.append((variant_name, mode, token, "C", f"got {vc}, yellow's is {yc} -- gamut-mapping may only SHRINK chroma, never grow it"))
        self.assertGreater(seen, 0, "the sweep resolved zero (variant, mode, token) combinations -- broken, not passing")
        self.assertEqual(offenders, [], f"derivation not observed in the generated CSS: {offenders!r}")


class RoleFamilyStaysFixedTests(unittest.TestCase):
    """Ruling 3: the role family (identity/PT-69/PT-79) is NOT rotated --
    no chart variant block may declare a --chart-role-* or guard token at
    all; every reader gets it from app.css's own :root/.dark,
    unconditionally."""

    def test_no_chart_variant_declares_a_role_or_guard_token(self):
        self.assertTrue(DASHBOARD_VARIANTS_CSS.is_file())
        variants_source = DASHBOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        offenders = []
        for variant_name, is_dark, body in _find_chart_variant_blocks(variants_source):
            for token in ROLE_TOKENS:
                if _oklch_in_block(body, token) is not None or _var_ref_in_block(body, token) is not None:
                    offenders.append((variant_name, "dark" if is_dark else "light", token))
        self.assertEqual(
            offenders, [],
            f"a chart variant block declares a role/guard token -- role identity must stay "
            f"fixed across every Chart Color choice: {offenders!r}",
        )


class WipReauthoredValueIsPinnedTests(unittest.TestCase):
    """ux-designer's landed decision (PT-118.md @d7f5724): re-author
    chart-flow-wip's chroma rather than grandfather an unrenderable
    value. New values, L and h held, ~5% headroom below the computed
    gamut edge (not the literal max -- rounding/engine differences
    shouldn't reopen this on a different renderer):
    - Light: oklch(0.62 0.100 200.8) (was 0.15)
    - Dark:  oklch(0.60 0.097 200.8) (was 0.13)
    Pinned directly to app.css (the ratified source), independently of
    the byte-identity guard below -- wip stays excluded from THAT guard
    (team-lead's instruction) so a generator rounding difference in the
    gamut-mapping step, even for an already-in-gamut value, cannot be
    confused with a real regression here."""

    NEW_WIP = {"light": (0.62, 0.100, 200.8), "dark": (0.60, 0.097, 200.8)}

    def test_app_css_carries_the_reauthored_wip_values(self):
        self.assertTrue(APP_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        for mode, block in (("light", root_block), ("dark", dark_block)):
            with self.subTest(mode=mode):
                oklch = _oklch_in_block(block, "chart-flow-wip")
                self.assertEqual(
                    oklch, self.NEW_WIP[mode],
                    f"app.css {mode} --chart-flow-wip must be {self.NEW_WIP[mode]!r} "
                    f"(ux-designer's re-authored value, PT-118.md @d7f5724) -- got {oklch!r}",
                )

    def test_the_reauthored_values_are_in_gamut_with_headroom(self):
        for mode, (l, c, h) in self.NEW_WIP.items():
            with self.subTest(mode=mode):
                self.assertTrue(is_in_gamut(l, c, h), f"{mode} wip {l, c, h} must be in-gamut")
                # Headroom, not the literal edge: a small chroma bump must
                # still read as in-gamut, or there is no margin left for
                # a different renderer's rounding.
                self.assertTrue(
                    is_in_gamut(l, c + 0.003, h),
                    f"{mode} wip has no headroom -- c={c} is too close to the gamut edge",
                )


class YellowByteIdenticalToAppCssTests(unittest.TestCase):
    """Guard 4: yellow (Δh=0) reproduces today's app.css values
    byte-for-byte in all three generated copies -- excluding
    YELLOW_GAMUT_EXCLUDE (finding 2: a token already out of gamut at
    Δh=0 is gamut-mapped even for the identity rotation, so it is not
    exempt from mapping just because it's yellow)."""

    def test_yellow_matches_app_css_in_every_generated_copy(self):
        self.assertTrue(APP_CSS.is_file())
        app_css_source = APP_CSS.read_text(encoding="utf-8")
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        expected: Dict[str, Tuple[float, float, float]] = {}
        for mode, block, is_dark in (("light", root_block, False), ("dark", dark_block, True)):
            for token in ROTATING_TOKENS:
                if token in YELLOW_GAMUT_EXCLUDE:
                    continue
                oklch = _oklch_in_block(block, token)
                self.assertIsNotNone(oklch, f"app.css {mode}: no literal declaration for --{token}")
                expected[f"{mode}:{token}"] = oklch

        for copy_path in ALL_THREE_COPIES:
            with self.subTest(copy=str(copy_path)):
                self.assertTrue(copy_path.is_file(), f"{copy_path} does not exist")
                variants_source = copy_path.read_text(encoding="utf-8")
                variants = _all_variants(variants_source)
                yellow = variants.get("yellow", {"light": "", "dark": ""})
                for mode, block, is_dark in (("light", yellow.get("light", ""), False), ("dark", yellow.get("dark", ""), True)):
                    for token in ROTATING_TOKENS:
                        if token in YELLOW_GAMUT_EXCLUDE:
                            continue
                        resolved = _resolve_oklch(token, block, root_block, dark_block, is_dark)
                        key = f"{mode}:{token}"
                        self.assertEqual(
                            resolved, expected[key],
                            f"{copy_path}: yellow's {token} ({mode}) is {resolved!r}, app.css's own "
                            f"ratified value is {expected[key]!r} -- yellow must reproduce it "
                            f"byte-for-byte (Δh=0)",
                        )


if __name__ == "__main__":
    unittest.main()
