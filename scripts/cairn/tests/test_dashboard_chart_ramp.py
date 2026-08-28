"""PT-61 guard: the chart-ramp re-step Mosko ruled (issue thread,
2026-08-28, "re-step the chart ramp"). implementation-lead's own
validator run found the preset's `--chart-1`/`--chart-2` fail the
ordinal light-end contrast floor against the card surface (1.33:1 /
1.91:1 vs. the 2:1 hard gate; chart-3..5 and all of dark mode pass).
Resolution: derive 6 new chart-LOCAL tokens (one per `STATUS_ORDER`
status) within the same golden hue, snapped to pass every ordinal check
in both modes -- the preset's `--chart-1..5` stay untouched for
everything else.

Two independent things this file checks, in two classes:

- `ChartLocalTokenContractTests` is STRUCTURAL (source-text, this suite's
  established shape): are there exactly 6 new `--chart-*`-prefixed custom
  properties in `app.css`, distinct from the base `--chart-1..5` names,
  declared in BOTH `:root` and `.dark` (mirroring how the base ramp
  itself is duplicated per mode) -- and does something under
  `dashboard/src` actually reference each of them via `var(--<name>)`,
  not just declare them. Naming assumption, stated plainly because
  nothing rules it: a `--chart-`-prefixed name, the natural continuation
  of the existing `--chart-1..5` convention ("chart-local" per the
  ruling's own wording) -- if implementation-lead names them something
  else entirely, this class's token-count test still passes (it doesn't
  anchor on specific names, only the `--chart-` prefix + count), but
  update this docstring's assumption note if that naming diverges.
- `ChartRampOrdinalValidationTests` is NUMERIC -- it re-runs the actual
  check that produced this ruling (the dataviz skill's ordinal-ramp
  validator: monotone lightness, visible adjacent gaps, single hue, and
  the light-end contrast floor against the surface) against whatever 6
  oklch values land in app.css, in BOTH modes, so a *future* edit to
  these specific tokens can't silently drop back below the floor the way
  the original `--chart-1..5` did. The OKLCH-to-hex bridge this class
  needs (the validator takes hex) is verified against the ruling's own
  reported numbers before being trusted -- see `_SelfCheckTests` below,
  which reproduces the ruling's exact 1.33:1/1.91:1 figures for the
  UNFIXED `--chart-1`/`--chart-2` values as a sanity check on the
  conversion math, not on anything PT-61 changes.

Per team-lead's explicit instruction, the validator's bundled-skill path
can move across harness versions -- `_find_validator_module` searches for
it rather than hardcoding one path, and every test in
`ChartRampOrdinalValidationTests` skips (not fails, not errors) if it
truly can't be found, so a harness upgrade that relocates the skill can't
silently red the whole suite over an unrelated path change.

Nothing under test exists yet: app.css has exactly the 5 base
`--chart-1..5` tokens per mode and nothing else `--chart-`-prefixed.
Every ChartLocalTokenContractTests failure is a genuinely-absent
construct, never an import error.
"""
from __future__ import annotations

import glob
import importlib.util
import math
import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
APP_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "app.css"
DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"

BASE_CHART_NAMES = {f"--chart-{i}" for i in range(1, 6)}
CHART_VAR_RE = re.compile(r"(--chart-[\w-]+)\s*:\s*oklch\(([^)]*)\)")

_VALIDATOR_GLOB_CANDIDATES = [
    "/private/tmp/claude-*/bundled-skills/*/*/dataviz/scripts/validate_palette.py",
    "/tmp/claude-*/bundled-skills/*/*/dataviz/scripts/validate_palette.py",
]


def _find_validator_module():
    """Locates and imports the dataviz skill's validate_palette.py by
    search, not a hardcoded path (team-lead: 'bundled path, may move
    across harness versions'). Returns the imported module, or None if
    it genuinely can't be found anywhere searched."""
    for pattern in _VALIDATOR_GLOB_CANDIDATES:
        matches = sorted(glob.glob(pattern))
        if matches:
            path = matches[-1]  # newest harness version, if more than one
            spec = importlib.util.spec_from_file_location("validate_palette", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            return module
    return None


def _read_app_css() -> str:
    return APP_CSS.read_text(encoding="utf-8")


def _block(source: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    return match.group(1) if match else ""


def _chart_vars_in_block(block_text: str) -> dict:
    """name -> (L, C, H) for every --chart-*-prefixed oklch(...) var in
    this block, base ramp included."""
    out = {}
    for name, triple in CHART_VAR_RE.findall(block_text):
        parts = triple.split()
        if len(parts) != 3:
            continue
        try:
            l, c, h = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            continue
        out[name] = (l, c, h)
    return out


def _derived_chart_vars(block_text: str) -> dict:
    return {name: v for name, v in _chart_vars_in_block(block_text).items() if name not in BASE_CHART_NAMES}


# -- OKLCH -> hex bridge, published Björn Ottosson OKLab<->linear-sRGB
# matrices (https://bottosson.github.io/posts/oklab/) -- the forward half
# is already in the skill's own validate_palette.py (lin2oklab); this is
# just its published inverse, needed because the skill's CLI/functions
# take hex, and app.css declares oklch(). Verified against the ruling's
# own reported numbers in _SelfCheckTests below, not trusted blind.
def _oklch_to_hex(l: float, c: float, h_deg: float, lin2s) -> str:
    h = math.radians(h_deg)
    a = c * math.cos(h)
    b = c * math.sin(h)
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    ll, mm, ss = l_**3, m_**3, s_**3
    r = 4.0767416621 * ll - 3.3077115913 * mm + 0.2309699292 * ss
    g = -1.2684380046 * ll + 2.6097574011 * mm - 0.3413193965 * ss
    bb = -0.0041960863 * ll - 0.7034186147 * mm + 1.7076147010 * ss
    rs, gs, bs = lin2s(r), lin2s(g), lin2s(bb)

    def to255(x: float) -> int:
        return max(0, min(255, round(x * 255)))

    return "#%02x%02x%02x" % (to255(rs), to255(gs), to255(bs))


class _SelfCheckTests(unittest.TestCase):
    """Sanity-checks the OKLCH->hex bridge above against the ruling's own
    reported figures for the UNCHANGED preset ramp, before that bridge is
    trusted to validate anything PT-61 actually derives. If this test
    ever goes red, the bug is in this file's color math, not in app.css."""

    def test_reproduces_the_rulings_reported_light_end_contrast_failures(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        # --card in :root (light mode surface) is oklch(1 0 0) = pure
        # white -- the ruling's "light card surface", not the script's
        # generic default surface.
        surface = "#ffffff"
        chart_1 = _oklch_to_hex(0.905, 0.182, 98.111, module.lin2s)
        chart_2 = _oklch_to_hex(0.795, 0.184, 86.047, module.lin2s)
        self.assertAlmostEqual(module.contrast(chart_1, surface), 1.33, places=2)
        self.assertAlmostEqual(module.contrast(chart_2, surface), 1.91, places=2)


class ChartLocalTokenContractTests(unittest.TestCase):
    def test_exactly_six_derived_chart_tokens_exist_in_light_mode(self):
        source = _read_app_css()
        derived = _derived_chart_vars(_block(source, ":root"))
        self.assertEqual(
            len(derived), 6,
            f"expected 6 new --chart-*-prefixed tokens in :root beyond the base "
            f"--chart-1..5 ramp (one per STATUS_ORDER status), found {len(derived)}: {sorted(derived)}",
        )

    def test_exactly_six_derived_chart_tokens_exist_in_dark_mode(self):
        source = _read_app_css()
        derived = _derived_chart_vars(_block(source, ".dark"))
        self.assertEqual(
            len(derived), 6,
            f"expected 6 new --chart-*-prefixed tokens in .dark beyond the base "
            f"--chart-1..5 ramp, found {len(derived)}: {sorted(derived)}",
        )

    def test_light_and_dark_derived_token_names_match(self):
        source = _read_app_css()
        light_names = set(_derived_chart_vars(_block(source, ":root")))
        dark_names = set(_derived_chart_vars(_block(source, ".dark")))
        self.assertEqual(
            light_names, dark_names,
            "the derived chart tokens declared in :root and .dark don't have the same "
            "names -- both modes should define the same 6 chart-local variables",
        )

    def test_every_derived_chart_token_is_actually_referenced_in_dashboard_source(self):
        source = _read_app_css()
        derived_names = set(_derived_chart_vars(_block(source, ":root")))
        self.assertTrue(derived_names, "no derived chart tokens found -- see the count tests above")
        haystack = "\n".join(
            p.read_text(encoding="utf-8")
            for p in DASHBOARD_SRC.rglob("*")
            if p.is_file() and p.suffix in (".svelte", ".ts") and p.resolve() != APP_CSS.resolve()
        )
        unreferenced = sorted(name for name in derived_names if f"var({name})" not in haystack)
        self.assertEqual(
            unreferenced, [],
            f"these derived chart tokens are declared in app.css but never referenced "
            f"(var(...)) anywhere under dashboard/src -- declaring isn't wiring: {unreferenced}",
        )


class ChartRampOrdinalValidationTests(unittest.TestCase):
    """Re-runs the dataviz skill's ordinal-ramp check against whatever 6
    derived tokens actually land in app.css, in both modes -- the
    permanent regression fence for the specific failure this ruling
    fixed (skips gracefully if the validator can't be located)."""

    def _validate_mode(self, mode: str, surface_hex: str):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        source = _read_app_css()
        selector = ":root" if mode == "light" else ".dark"
        derived = _derived_chart_vars(_block(source, selector))
        if len(derived) != 6:
            self.skipTest(f"{len(derived)} derived chart tokens found in {selector} (expected 6) -- see ChartLocalTokenContractTests")
        palette = [_oklch_to_hex(l, c, h, module.lin2s) for l, c, h in derived.values()]
        report, ok = module.validate_ordinal(palette, mode, surface_hex)
        self.assertTrue(
            ok,
            f"the {mode}-mode derived chart ramp fails the dataviz ordinal validator: {report}",
        )

    def test_light_mode_derived_ramp_passes_the_ordinal_validator(self):
        # --card in :root == oklch(1 0 0) == pure white -- the light
        # card surface the ruling's contrast figures were measured
        # against (see _SelfCheckTests).
        self._validate_mode("light", "#ffffff")

    def test_dark_mode_derived_ramp_passes_the_ordinal_validator(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        source = _read_app_css()
        card_match = re.search(r"--card:\s*oklch\(([^)]*)\)", _block(source, ".dark"))
        self.assertIsNotNone(card_match, "could not find .dark's --card token to use as the chart surface")
        l, c, h = (float(x) for x in card_match.group(1).split())
        surface_hex = _oklch_to_hex(l, c, h, module.lin2s)
        self._validate_mode("dark", surface_hex)


if __name__ == "__main__":
    unittest.main()
