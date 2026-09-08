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
- `_SelfCheckTests` sanity-checks the OKLCH bridge every gated contrast
  pair still runs through -- reproducing PT-61's own reported
  1.33:1/1.91:1 light-end figures for the UNFIXED `--chart-1`/`--chart-2`
  values. PT-83 ported this off the external dataviz skill's
  `validate_palette.py` onto the vendored `palette_check.py`
  (`linear_to_hex(oklch_to_linear_srgb(...))` + `contrast_hex`) so it
  never skips; the assertions themselves are unchanged.

PT-85 (architect ruling 586af1f) retired PT-61's ordinal `--chart-flow-*`
ramp entirely, so the NUMERIC `ChartRampOrdinalValidationTests` class
that used to re-run the dataviz skill's ordinal-ramp validator against it
is gone (see the comment near the bottom of this file for the full
record) -- `_SelfCheckTests` is the only thing left that needs the OKLCH
bridge, and it survives because that bridge is still what every gated
contrast pair in test_base_theme_contrast_gate.py runs through.

Nothing under test exists yet: app.css has exactly the 5 base
`--chart-1..5` tokens per mode and nothing else `--chart-`-prefixed.
Every ChartLocalTokenContractTests failure is a genuinely-absent
construct, never an import error.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

import palette_check

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
APP_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "app.css"
DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"

BASE_CHART_NAMES = {f"--chart-{i}" for i in range(1, 6)}
CHART_VAR_RE = re.compile(r"(--chart-[\w-]+)\s*:\s*oklch\(([^)]*)\)")


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
    """PT-61's own derived ORDINAL ramp tokens ONLY -- scoped to the
    `--chart-flow-*` prefix specifically, not "any --chart-*-prefixed
    token beyond the base 5". PT-79 (ad940d3/962f3e9) introduced a
    SEPARATE, unrelated categorical role palette
    (`--chart-role-1..8`/`--chart-role-guard-aux`/
    `--chart-role-guard-unattributed`/`--chart-role-other`, guarded by
    its own scripts/cairn/tests/palette_check.py + test_dashboard_role_palette.py)
    that also lives under the `--chart-` prefix -- without this scoping,
    this file's token-count and ordinal-validation tests would silently
    swallow those unrelated tokens the moment they land in app.css, both
    inflating the "exactly 6" count here and running the ORDINAL
    validator against tokens that are explicitly categorical (unordered),
    which the PT-79 amendment calls out as meaningless."""
    return {name: v for name, v in _chart_vars_in_block(block_text).items() if name.startswith("--chart-flow-")}


class _SelfCheckTests(unittest.TestCase):
    """Sanity-checks the vendored OKLCH->hex bridge (`palette_check.
    linear_to_hex(palette_check.oklch_to_linear_srgb(...))`) against the
    ruling's own reported figures for the UNCHANGED preset ramp, before
    that bridge is trusted to validate anything PT-61 actually derived.
    If this test ever goes red, the bug is in the bridge's color math,
    not in app.css.

    PT-83 (architect's ruling, PT-83.md @ 0c79168 item (c)/(f)(3)): PORTED
    off the external dataviz skill's `validate_palette.py`
    (`_oklch_to_hex` + `module.contrast`, both retired) onto the vendored
    `palette_check.py` -- the two assertions are unchanged, and this test
    no longer skips. Red mutation (ruling): drop the `0.2158037573` term
    from `palette_check.oklch_to_linear_srgb`'s OKLab->LMS matrix."""

    def test_reproduces_the_rulings_reported_light_end_contrast_failures(self):
        # --card in :root (light mode surface) is oklch(1 0 0) = pure
        # white -- the ruling's "light card surface", not a generic
        # default surface.
        surface = "#ffffff"
        chart_1 = palette_check.linear_to_hex(palette_check.oklch_to_linear_srgb(0.905, 0.182, 98.111))
        chart_2 = palette_check.linear_to_hex(palette_check.oklch_to_linear_srgb(0.795, 0.184, 86.047))
        self.assertAlmostEqual(palette_check.contrast_hex(chart_1, surface), 1.33, places=2)
        self.assertAlmostEqual(palette_check.contrast_hex(chart_2, surface), 1.91, places=2)


class ChartLocalTokenContractTests(unittest.TestCase):
    # PT-85 (architect ruling 586af1f): the 6-token ORDINAL --chart-flow-*
    # ramp this file was written to guard is retired entirely -- PT-85's
    # 3 throughput series (opened/closed/wip) are categorical, not
    # ordinal, so 3 dedicated tokens replace it (implementation-lead,
    # same commit as the ruling's own "the guard edit is yours" -- a
    # forced mechanical consequence of retiring the thing being counted).
    def test_exactly_three_derived_chart_tokens_exist_in_light_mode(self):
        source = _read_app_css()
        derived = _derived_chart_vars(_block(source, ":root"))
        self.assertEqual(
            len(derived), 3,
            f"expected 3 --chart-flow-*-prefixed tokens in :root (opened/closed/wip), "
            f"found {len(derived)}: {sorted(derived)}",
        )

    def test_exactly_three_derived_chart_tokens_exist_in_dark_mode(self):
        source = _read_app_css()
        derived = _derived_chart_vars(_block(source, ".dark"))
        self.assertEqual(
            len(derived), 3,
            f"expected 3 --chart-flow-*-prefixed tokens in .dark (opened/closed/wip), "
            f"found {len(derived)}: {sorted(derived)}",
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


# PT-85 (architect ruling 586af1f): ChartRampOrdinalValidationTests
# REMOVED here, not just edited -- it re-ran the dataviz skill's
# ORDINAL-ramp check (monotone lightness, single hue, adjacent gaps)
# against the 6-token --chart-flow-* ramp, and that ramp no longer
# exists: PT-85's opened/closed/wip tokens are 3 categorical entries
# (red/green/violet), not a ramp, so an ordinal check has nothing left
# to validate -- "no ramp left to guard" (the architect's own words).
# implementation-lead removed rather than adjusted per that same
# ruling: "what replaces it (if anything) is a contrast/distinctness
# assertion over the three series, which is qa's call" -- not silently
# dropped, this comment is the record of what was here (a two-mode
# validate_ordinal() run against the external dataviz skill). PT-83
# later retired the `_oklch_to_hex`/`_find_validator_module` helpers that
# ran it -- `_SelfCheckTests` above still needs an OKLCH->hex bridge, but
# gets it from the vendored `palette_check.py` now, never the external
# script; a categorical replacement for THIS ramp, if ever built, should
# use `palette_check`'s own categorical checks (PT-69/PT-79), not rebuild
# either retired helper.


if __name__ == "__main__":
    unittest.main()
