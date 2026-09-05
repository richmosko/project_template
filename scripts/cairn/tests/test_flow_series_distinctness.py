"""PT-85 replacement for PT-61's ordinal-ramp guard (`test_dashboard_chart_ramp.py`,
`test_chart_variant_ramps.py`, both retired alongside the `--chart-flow-*`
ramp they guarded -- architect's addendum + team-lead's scope decision,
process/cairn/issues/PT-85.md).

## Why an ordinal check is the wrong replacement (and what this file checks instead)

The retired ramp's whole point was a MONOTONE progression (backlog -> ...
-> done, one hue, descending lightness) -- exactly the shape a reader
must NOT get for `opened`/`closed`/`wip`, which the architect's ruling
calls categorical: "opened and closed are two bars a reader must tell
apart at a glance... two neighbouring ramp steps are the hardest
possible encoding for it." So this file does not re-run an ordinal
validator against three cherry-picked steps -- it asserts the opposite
property: the three series colors are NOT drawn from any monotone-hue
family, and are separated enough in hue to read as distinct at a
glance.

## Two disproven assumptions this file's design had to react to

1. The architect's original §9 said "use the existing base categorical
   palette (--chart-1...--chart-5)". Verified (architect, self-
   corrected): `--chart-1..5` is ITSELF a monotone ordinal ramp (hues
   98.1 -> 61.9, 36 degrees, descending lightness) -- reusing three of
   its steps reproduces the exact defect being fixed. This file
   therefore asserts the series tokens are NOT `--chart-1..5` at all,
   not just that they're "different colors".
2. An earlier in-progress build reused three `--chart-flow-*` RAMP
   STEPS directly (`--chart-flow-todo`/`-done`/`-in-progress`) under a
   "confirmed against the architect" comment that predated the later,
   written retirement ruling. This file asserts the series tokens are
   not drawn from the retiring `--chart-flow-*` names either.

## What "categorically distinguishable" means here, numerically

Hue-angle separation, computed directly from each token's own declared
OKLCH values -- no dependency on the external dataviz validator (which
is ordinal-shape-specific and may not even be present on a given
harness; every pre-existing ramp test here already skips gracefully
without it). Thresholds are the architect's own PRE-REGISTERED numbers
(9336826, published before the build, derived from the actual
--chart-role-* palette so they are achievable rather than invented):
- **ΔH >= 60 degrees** between every pair of the three flow tokens
  (the retired ramp was 36 degrees across six steps, ~7 degrees
  adjacent; 60 is comfortably outside ramp territory and the widest
  achievable gap in the role palette is 65.6 degrees worst-case, so
  this is satisfiable with margin, not aspirational).
- **ΔH >= 25 degrees** from every `--chart-role-*` hue (the achievable
  maximum given the role palette's own gaps is ~30 degrees, so 25
  leaves headroom rather than pinning the answer to one placement).
Both checked in light AND dark separately -- the architect's own note:
a scan finding the same role hues across modes is an observation, not
a guarantee, so this file measures each block rather than assuming
they match.

Nothing under test exists yet in its final form: `IssueFlowChart.svelte`'s
`SERIES_COLOR` map is mid-flight (as of this file's writing, still
pointing at the retiring `--chart-flow-todo/-done/-in-progress` names) --
every test below is expected to fail loudly on that shape, not silently
skip.
"""
from __future__ import annotations

import math
import re
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple

import helpers  # noqa: F401

DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"
APP_CSS = DASHBOARD_SRC / "app.css"
BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
FLOW_CHART_SVELTE = DASHBOARD_SRC / "lib" / "components" / "IssueFlowChart.svelte"

# The retired ordinal ramp's six step names -- must never appear in the
# new SERIES_COLOR map, regardless of what replaces it.
RETIRED_RAMP_NAMES = {
    "--chart-flow-backlog", "--chart-flow-todo", "--chart-flow-in-progress",
    "--chart-flow-in-review", "--chart-flow-done", "--chart-flow-cancelled",
}
# The base "categorical" palette -- disproven (architect, self-corrected,
# this ticket): it is itself a monotone ordinal ramp and must not be used
# for these three series either.
BASE_RAMP_NAMES = {f"--chart-{i}" for i in range(1, 6)}

# Architect's pre-registered thresholds (9336826), derived from the
# actual --chart-role-* palette so they are achievable, not invented.
FLOW_PAIRWISE_HUE_FLOOR_DEGREES = 60.0
ROLE_COLLISION_HUE_FLOOR_DEGREES = 25.0

# team-lead's decision (69bee40): the three interim tokens must not
# coincide with a --chart-role-* hue used on the SAME dashboard
# (TokenCostChart.svelte) -- role-1..8 are fixed/global (not
# variant-scoped -- confirmed: 0 occurrences in board/variants.css).
# Checked in BOTH :root and .dark separately (architect's own note: a
# scan finding identical hues across modes is an observation, not a
# guarantee -- this file measures each block, never assumes they match).
CHART_ROLE_NAMES = tuple(f"--chart-role-{i}" for i in range(1, 9))

_VAR_REF_RE = re.compile(r"var\((--[\w-]+)\)")
_OKLCH_DECL_RE_TMPL = r"{name}\s*:\s*oklch\(([^)/]*)\)"
_VARIANT_BLOCK_OPEN_RE = re.compile(
    r':root(?P<dark>\.dark)?\[data-cairn-chart="(?P<name>[\w-]+)"\]\s*\{'
)


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
    m = re.search(_OKLCH_DECL_RE_TMPL.format(name=re.escape(var_name)), block_text)
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
    """If `var_name` is declared in this block as `var(--other)`, return
    `--other` (one level of alias indirection); None if not declared as
    an alias here at all."""
    m = re.search(re.escape(var_name) + r"\s*:\s*var\((--[\w-]+)\)", block_text)
    return m.group(1) if m else None


def _resolve_oklch(var_name: str, variant_block: str, root_block: str, dark_block: str, is_dark: bool, depth: int = 0) -> Optional[Tuple[float, float, float]]:
    """Resolves `var_name` to its final (L, C, H), preferring a literal
    declaration in the variant's own block, then falling back to
    app.css's own :root/.dark, following at most one level of `var(...)`
    aliasing within whichever scope declares it. `depth` guards against
    a pathological alias cycle."""
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


def _hue_distance(h1: float, h2: float) -> float:
    """Shortest angular distance between two hue degrees, 0-180."""
    diff = abs(h1 - h2) % 360
    return min(diff, 360 - diff)


def _series_color_tokens() -> Dict[str, str]:
    """Parses `IssueFlowChart.svelte`'s `SERIES_COLOR` object literal,
    returning {series_key: var_name} for opened/closed/wip. Fails
    loudly (not an opaque KeyError) if the map or a key is missing."""
    assert FLOW_CHART_SVELTE.is_file(), f"{FLOW_CHART_SVELTE} does not exist"
    source = FLOW_CHART_SVELTE.read_text(encoding="utf-8")
    m = re.search(r"SERIES_COLOR\s*=\s*\{([^}]*)\}", source)
    assert m is not None, "IssueFlowChart.svelte has no SERIES_COLOR object literal"
    body = m.group(1)
    tokens = {}
    for key in ("opened", "closed", "wip"):
        km = re.search(re.escape(key) + r"\s*:\s*'([^']*)'", body)
        assert km is not None, f"SERIES_COLOR has no '{key}' entry -- got body: {body!r}"
        var_m = _VAR_REF_RE.search(km.group(1))
        assert var_m is not None, f"SERIES_COLOR.{key} is not a var(--...) reference -- got {km.group(1)!r}"
        tokens[key] = var_m.group(1)
    return tokens


# --------------------------------------------------------------------------
# The two disproven-shape guards -- cheap, name-level, no OKLCH math needed.
# --------------------------------------------------------------------------

class SeriesTokensAreNotRetiredOrRampTokensTests(unittest.TestCase):
    def test_no_series_color_is_a_retired_chart_flow_ramp_step(self):
        tokens = _series_color_tokens()
        offending = {k: v for k, v in tokens.items() if v in RETIRED_RAMP_NAMES}
        self.assertEqual(
            offending, {},
            f"SERIES_COLOR must not reference a retired --chart-flow-* ramp step name -- "
            f"got {offending!r} (full map: {tokens!r})",
        )

    def test_no_series_color_is_the_base_chart_1_through_5_ramp(self):
        tokens = _series_color_tokens()
        offending = {k: v for k, v in tokens.items() if v in BASE_RAMP_NAMES}
        self.assertEqual(
            offending, {},
            f"SERIES_COLOR must not reference --chart-1..5 -- verified (this ticket) to be "
            f"ITSELF a monotone ordinal ramp (98.1 deg -> 61.9 deg, one hue family), so reusing "
            f"any of its steps reproduces the exact defect being fixed -- got {offending!r}",
        )


# --------------------------------------------------------------------------
# The numeric categorical-distinctness check -- every Chart Color variant,
# both modes.
# --------------------------------------------------------------------------

class CategoricalHueSeparationTests(unittest.TestCase):
    def test_opened_closed_and_wip_are_hue_separated_in_every_variant_and_mode(self):
        tokens = _series_color_tokens()
        app_css_source = APP_CSS.read_text(encoding="utf-8") if APP_CSS.is_file() else ""
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        self.assertTrue(root_block, f"{APP_CSS} has no :root block (or doesn't exist)")
        self.assertTrue(dark_block, f"{APP_CSS} has no .dark block (or doesn't exist)")

        variants = {"__default__": {"light": "", "dark": ""}}
        if BOARD_VARIANTS_CSS.is_file():
            variants_source = BOARD_VARIANTS_CSS.read_text(encoding="utf-8")
            for name, is_dark, body in _find_chart_variant_blocks(variants_source):
                variants.setdefault(name, {})["dark" if is_dark else "light"] = body

        for variant_name, modes in sorted(variants.items()):
            for mode in ("light", "dark"):
                with self.subTest(variant=variant_name, mode=mode):
                    variant_block = modes.get(mode, "")
                    is_dark = mode == "dark"
                    resolved = {}
                    for series, var_name in tokens.items():
                        oklch = _resolve_oklch(var_name, variant_block, root_block, dark_block, is_dark)
                        self.assertIsNotNone(
                            oklch,
                            f"{variant_name}/{mode}: could not resolve {series}'s token "
                            f"{var_name!r} to a declared oklch(...) value (checked the variant's "
                            f"own block, then app.css's :root/.dark, following at most one "
                            f"var(...) alias)",
                        )
                        resolved[series] = oklch

                    hues = {series: oklch[2] for series, oklch in resolved.items()}
                    pairs = [("opened", "closed"), ("opened", "wip"), ("closed", "wip")]
                    for a, b in pairs:
                        distance = _hue_distance(hues[a], hues[b])
                        self.assertGreaterEqual(
                            distance, FLOW_PAIRWISE_HUE_FLOOR_DEGREES,
                            f"{variant_name}/{mode}: '{a}' ({hues[a]:.1f} deg) and '{b}' "
                            f"({hues[b]:.1f} deg) are only {distance:.1f} deg apart -- below the "
                            f"{FLOW_PAIRWISE_HUE_FLOOR_DEGREES} deg floor (architect's pre-"
                            f"registered constraint 1, 9336826) for 'tell apart at a glance', "
                            f"the same defect the retired ramp had",
                        )


class NoCollisionWithChartRolePaletteTests(unittest.TestCase):
    """team-lead's decision (69bee40): the three interim tokens must not
    coincide with a --chart-role-* hue -- TokenCostChart.svelte, a
    sibling block on the same dashboard, already uses that palette to
    mean specific roster roles; an identical hue on the flow chart would
    read as "this bar is architect's work" to a reader who has seen the
    other chart. Threshold is the architect's pre-registered constraint
    2 (9336826): >=25 deg from every role hue, checked in :root and
    .dark SEPARATELY (their own note: matching hues across modes today
    is an observation, not a guarantee)."""

    def _role_hues(self, block: str, block_label: str) -> Dict[str, float]:
        role_hues = {}
        for name in CHART_ROLE_NAMES:
            oklch = _oklch_in_block(block, name)
            self.assertIsNotNone(oklch, f"{name} not found in app.css {block_label} -- expected the fixed role palette")
            role_hues[name] = oklch[2]
        return role_hues

    def test_no_flow_series_hue_matches_a_chart_role_hue_in_either_mode(self):
        tokens = _series_color_tokens()
        app_css_source = APP_CSS.read_text(encoding="utf-8") if APP_CSS.is_file() else ""
        root_block = _extract_unqualified_block(app_css_source, ":root")
        dark_block = _extract_unqualified_block(app_css_source, ".dark")
        self.assertTrue(root_block, f"{APP_CSS} has no :root block (or doesn't exist)")
        self.assertTrue(dark_block, f"{APP_CSS} has no .dark block (or doesn't exist)")

        for mode, block, is_dark in (("light", root_block, False), ("dark", dark_block, True)):
            with self.subTest(mode=mode):
                role_hues = self._role_hues(block, f"({mode})")
                for series, var_name in tokens.items():
                    oklch = _resolve_oklch(var_name, "", root_block, dark_block, is_dark=is_dark)
                    self.assertIsNotNone(oklch, f"{mode}: could not resolve '{series}' token {var_name!r} in app.css")
                    series_hue = oklch[2]
                    for role_name, role_hue in role_hues.items():
                        distance = _hue_distance(series_hue, role_hue)
                        self.assertGreaterEqual(
                            distance, ROLE_COLLISION_HUE_FLOOR_DEGREES,
                            f"{mode}: '{series}' ({var_name}, {series_hue:.1f} deg) is only "
                            f"{distance:.1f} deg from {role_name} ({role_hue:.1f} deg) -- below "
                            f"the {ROLE_COLLISION_HUE_FLOOR_DEGREES} deg floor (architect's "
                            f"pre-registered constraint 2, 9336826). TokenCostChart.svelte uses "
                            f"that hue to mean a specific roster role; the same hue on the flow "
                            f"chart would read as that role's work, not '{series}'",
                        )
