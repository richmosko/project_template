"""PT-79 failing acceptance tests: the role-stack categorical palette,
per the architect's amendments (process/cairn/issues/PT-79.md, ad940d3
§2 and 962f3e9). The categorical guard runs against the IN-REPO,
stdlib-only `scripts/cairn/tests/palette_check.py` -- NOT the external
dataviz skill (which stays optional, backing only the ORDINAL
`--chart-flow-*` ramp test in test_dashboard_chart_ramp.py). Architect's
own words: "a skipping guard is indistinguishable from a passing one in
a green run" -- this guard never skips.

`palette_check.py` is qa-engineer's drop-in per the amendment
("qa-engineer owns the drop-in"), copied byte-for-byte from
`temp/2026-09-04-architect-palette_check.py` to
`scripts/cairn/tests/palette_check.py`.

**Real token set, verified against `palette_check.py`'s own source**
(NOT team-lead's earlier shorthand of "--chart-role-guard and
--chart-role-other" -- the actual module checks for THREE neutral
tokens, matching the architect's own evidence text "all 11 values..."):
`--chart-role-1`..`--chart-role-8` (8 role hues) plus
`--chart-role-guard-aux`, `--chart-role-guard-unattributed`,
`--chart-role-other` (3 neutral fold/guard tokens) = 11 total.

Two checks, both parsed from `app.css` under test, never hardcoded:
1. WCAG contrast >= 2:1 for all 11 tokens against EACH mode's own real
   `--card`.
2. Minimum pairwise OKLab dE >= 0.06 among the 8 role hues (the
   categorical criterion -- never substitute the ordinal validator's
   monotone-lightness check, meaningless for unordered categories).

ux-designer has already proposed concrete values (commit fd6df5c,
`docs/DESIGN/design-system-spec.md`) but they are NOT YET pasted into
`app.css` -- amendment ad940d3 explicitly blocks implementation-lead from
touching `app.css` until the mechanism amendment (962f3e9) landed, which
it now has. This file's `RolePaletteTokenContractTests` class is
therefore expected to stay red until implementation-lead applies
ux-designer's proposed `:root`/`.dark` block -- correct, expected state,
not a bug in this test.
"""
from __future__ import annotations

import unittest

import helpers  # noqa: F401

import palette_check

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
APP_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "app.css"
TOKEN_CHART_LOGIC_TS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "lib" / "token-chart-logic.ts"

ROLE_TOKEN_NAMES = [f"chart-role-{i}" for i in range(1, 9)] + [
    "chart-role-guard-aux", "chart-role-guard-unattributed", "chart-role-other",
]


def _read_app_css() -> str:
    return APP_CSS.read_text(encoding="utf-8")


class RolePaletteTokenContractTests(unittest.TestCase):
    """Token NAMES and presence. Blocked-by-design until
    implementation-lead applies ux-designer's proposed values (see module
    docstring)."""

    def test_all_eleven_role_tokens_are_parseable_from_app_css(self):
        source = _read_app_css()
        tokens = {name: v for name, v, _ in palette_check.parse_oklch_tokens(source)}
        missing = sorted(n for n in ROLE_TOKEN_NAMES if n not in tokens)
        self.assertEqual(
            missing, [],
            f"missing role-palette tokens: {missing} -- ux-designer's proposal (fd6df5c, "
            f"design-system-spec.md) is not yet pasted into app.css",
        )

    def test_role_tokens_are_not_reused_from_the_ordinal_flow_ramp_or_the_base_ramp(self):
        # ad940d3 §2: "Do not reuse --chart-flow-*... Do not reuse
        # --chart-1...--chart-5."
        source = _read_app_css()
        tokens = {name for name, v, _ in palette_check.parse_oklch_tokens(source)}
        role_tokens = tokens & set(ROLE_TOKEN_NAMES)
        forbidden = {f"chart-{i}" for i in range(1, 6)} | {
            f"chart-flow-{s}" for s in ("backlog", "todo", "in-progress", "in-review", "done", "cancelled")
        }
        self.assertEqual(role_tokens & forbidden, set(), "role tokens must not reuse ordinal/base ramp names")


class RoleTokenOrderExportTests(unittest.TestCase):
    """token-chart-logic.ts's ROLE_TOKEN_ORDER + fold-to-'other' --
    covered primarily by tests/js/token-chart-logic.test.js; lightweight
    cross-check that the TS file at least declares the export."""

    def test_role_token_order_export_is_declared(self):
        if not TOKEN_CHART_LOGIC_TS.is_file():
            self.fail(f"{TOKEN_CHART_LOGIC_TS} does not exist yet -- see test_dashboard_token_block.py")
        source = TOKEN_CHART_LOGIC_TS.read_text(encoding="utf-8")
        self.assertRegex(
            source, r"export\s+const\s+ROLE_TOKEN_ORDER",
            "token-chart-logic.ts must export a ROLE_TOKEN_ORDER const -- amendment ad940d3 §2",
        )


class RolePaletteCategoricalValidationTests(unittest.TestCase):
    """Re-runs palette_check.check_role_palette against whatever role
    tokens actually sit in app.css. NEVER SKIPS (the whole point of the
    962f3e9 amendment) -- fails cleanly with the missing-token list if the
    contract above isn't satisfied yet, same information either way."""

    def test_role_palette_passes_contrast_and_categorical_separation(self):
        source = _read_app_css()
        failures = palette_check.check_role_palette(source)
        self.assertEqual(failures, [], "role palette check failed:\n" + "\n".join(failures))


class PaletteCheckModuleSelfTests(unittest.TestCase):
    """Sanity-checks palette_check.py's own math against the architect's
    independently-verified figures (962f3e9: 'ran independently against
    ux-designer's hand-computed table, 11/11 hex values and 22/22
    contrast figures reproduced exactly') -- if this ever goes red, the
    bug is in palette_check.py's color math, not in app.css."""

    def test_card_surfaces_is_not_fooled_by_an_earlier_dot_dark_substring(self):
        # Regression for a real bug found and fixed in palette_check.py
        # (2026-09-04, flagged to architect): the original
        # css_text.find(".dark") matched THIS repo's actual
        # "@custom-variant dark (&:is(.dark *));" line, which sits before
        # :root's own --card -- misattributing light-mode's --card as
        # "after the dark boundary" and leaving the light bucket empty.
        # Regex-anchored to a real ".dark {" rule opening now.
        css = (
            "@custom-variant dark (&:is(.dark *));\n"
            ":root { --card: oklch(1 0 0); }\n"
            ".dark { --card: oklch(0.2 0 0); }\n"
        )
        surfaces = palette_check.card_surfaces(css)
        self.assertEqual(surfaces["light"], (1.0, 0.0, 0.0), "light --card must come from :root, not be swallowed by the earlier '.dark' substring in @custom-variant")
        self.assertEqual(surfaces["dark"], (0.2, 0.0, 0.0))

    def test_module_reports_a_missing_token_by_name_not_silently(self):
        css = ":root { --card: oklch(1 0 0); }\n.dark { --card: oklch(0.2 0 0); }\n"
        failures = palette_check.check_role_palette(css)
        self.assertTrue(failures, "an empty CSS (no role tokens at all) must fail loudly, not pass silently")
        self.assertIn("missing token", failures[0])

    def test_module_fails_two_role_hues_collapsed_together(self):
        # Architect's own verification case: "Fails two role hues
        # collapsed together (dE 0.005)." Construct two near-identical
        # role hues and confirm the categorical check catches it.
        tokens = "\n".join(f"--chart-role-{i}: oklch(0.6 0.15 {i * 40});" for i in range(1, 9))
        # Overwrite role-1 and role-2 to be nearly identical (same L, C, tiny H delta).
        tokens = tokens.replace("--chart-role-1: oklch(0.6 0.15 40);", "--chart-role-1: oklch(0.6 0.15 100);")
        tokens = tokens.replace("--chart-role-2: oklch(0.6 0.15 80);", "--chart-role-2: oklch(0.6 0.15 100.1);")
        guards = (
            "--chart-role-guard-aux: oklch(0.7 0.02 250);"
            "--chart-role-guard-unattributed: oklch(0.7 0.02 250);"
            "--chart-role-other: oklch(0.7 0.02 250);"
        )
        css = f":root {{ --card: oklch(1 0 0); {tokens} {guards} }}\n.dark {{ --card: oklch(0.2 0 0); {tokens} {guards} }}\n"
        failures = palette_check.check_role_palette(css)
        self.assertTrue(any("dE_OK" in f or "categorical" in f for f in failures), f"expected a categorical-separation failure, got: {failures}")


if __name__ == "__main__":
    unittest.main()
