#!/usr/bin/env python3
"""gen_variants.py -- PT-69 (architect's theme-variant ruling, §1/§2):
emits the three generated `variants.css` copies from the single vendored
source of truth, `variants.json`, sitting next to this script.

Authoring tool, not a runtime dependency: stdlib-only, zero deps, zero
network. Run by an agent to (re)generate the checked-in files, never on
the clone path (the board is zero-build; nothing in `cairn serve` invokes
this).

Usage:
    python3 gen_variants.py                  # writes the three real,
                                               # checked-in locations
    python3 gen_variants.py --out-dir DIR     # writes DIR/board/variants.css,
                                               # DIR/dashboard/src/variants.css,
                                               # DIR/docs/DESIGN/variants.css
                                               # -- for verification only,
                                               # never the authoring path.

Determinism (architect: "sorted keys, fixed block order"): dimensions are
emitted in a fixed order (base, theme, chart); variants within a
dimension are sorted alphabetically by their id; each variant's light
block precedes its dark block; CSS custom properties within a block are
sorted alphabetically by name. Two runs over the same variants.json
always produce byte-identical output -- see
test_theme_variants_generator.py's GeneratorDeterminismTests.

Mechanism (architect's ruling §2): one attribute-qualified block per
(dimension, variant, mode) --

    :root[data-cairn-<dim>="<name>"] { ... }
    :root.dark[data-cairn-<dim>="<name>"] { ... }

-- never a whole-theme block and never a default-variant block (the
default lives in the surface's own unqualified :root/.dark already;
duplicating it here would just be a second, driftable copy of tokens.css/
app.css's own values).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VARIANTS_JSON = SCRIPT_DIR / "variants.json"

# ---------------------------------------------------------------------------
# PT-69 (Mosko's ruling, 2026-08-29, "darken the ink"): --muted-foreground is
# DERIVED per Base Color variant, not vendored verbatim -- shadcn's published
# value fails the WCAG AA floor (4.5:1) against that base's own --muted in
# light mode for 6 of 7 bases, the shipped Stone default included (4.39:1,
# live since 2026-08-26). Resolution: darken the ink by the MINIMUM amount
# that clears 4.5:1 in both modes, holding chroma/hue fixed (same OKLCH
# L/C/H model the chart-flow ramps already use) -- "the same class" as the
# chart-flow re-step (Mosko's framing), except here there is exactly one
# token to adjust, not a 6-step ramp, and the adjustment is per-base rather
# than per-hue. This is why the math lives HERE (the generator), not as a
# one-off precomputed value in variants.json like the chart-flow ramps:
# re-running gen_variants.py after any future re-vendor of the raw base
# colors recomputes the correct ink automatically.
#
# variants.json keeps the VENDORED (undarkened) --muted-foreground under
# each Base variant -- true to NOTICE.md's "hand-vendored from the live
# generator" contract. This module derives the emitted value at render time.
#
# OKLCH<->linear-sRGB matrices: published Björn Ottosson constants
# (https://bottosson.github.io/posts/oklab/), same ones
# test_dashboard_chart_ramp.py's _oklch_to_hex uses -- reproduced here
# (not imported) because gen_variants.py must stay stdlib-only, zero deps,
# zero network, and the test suite's bridge lives in a test file, not a
# library this script can import without also importing `unittest`'s
# transitive weight into an authoring tool that ships in the clone path's
# neighbourhood.
_MUTED_FOREGROUND_FLOOR = 4.5  # WCAG AA, normal text (architect's ruling)


def _s2lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lin2s(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _oklch_to_linear_rgb(l: float, c: float, h_deg: float):
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
    return max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, bb))


def _oklch_to_hex(l: float, c: float, h_deg: float) -> str:
    r, g, bb = _oklch_to_linear_rgb(l, c, h_deg)

    def to255(x: float) -> int:
        return max(0, min(255, round(_lin2s(x) * 255)))

    return "#%02x%02x%02x" % (to255(r), to255(g), to255(bb))


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _s2lin(r) + 0.7152 * _s2lin(g) + 0.0722 * _s2lin(b)


def _relative_luminance_linear(r: float, g: float, b: float) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(hex_a: str, hex_b: str) -> float:
    """The QUANTIZED-model contrast -- both colors round-tripped through
    8-bit hex first, same bridge test_dashboard_chart_ramp.py's
    _oklch_to_hex/module.contrast uses elsewhere in this suite."""
    a, b = sorted((_relative_luminance(hex_a), _relative_luminance(hex_b)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _contrast_float(oklch_a, oklch_b) -> float:
    """The FLOAT-model contrast -- relative luminance computed directly
    from linear-sRGB floats, no 8-bit rounding at any point. `oklch_a`/
    `oklch_b` are (L, C, H) tuples."""
    la = _relative_luminance_linear(*_oklch_to_linear_rgb(*oklch_a))
    lb = _relative_luminance_linear(*_oklch_to_linear_rgb(*oklch_b))
    hi, lo = sorted((la, lb), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# PT-69 (architect's ruling, 2026-08-29, "the two-model rule"): a derived
# ink that clears the floor under ONE contrast model (quantized-hex,
# matching the dataviz-skill bridge everything else in this suite uses)
# can still sit under the floor by the FLOAT model (no 8-bit rounding) --
# the gap between the two models near a borderline value is real, not
# noise (ux-designer's independent re-check of the first destructive-
# foreground derivation: 4.4955:1 float vs 4.5268:1 quantized, floor
# sitting inside that ~0.03 gap). Every derivation in this module now
# requires BOTH models to clear floor + EPSILON, not just whichever one
# the search happened to be measuring.
_TWO_MODEL_EPSILON = 0.05


def _clears_both_models(ink: tuple, bg: tuple, floor: float, epsilon: float = _TWO_MODEL_EPSILON) -> bool:
    target = floor + epsilon
    quantized = _contrast(_oklch_to_hex(*ink), _oklch_to_hex(*bg))
    float_model = _contrast_float(ink, bg)
    return quantized >= target and float_model >= target


def _parse_oklch(value: str):
    match = re.match(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)", value)
    if not match:
        raise ValueError(f"not a plain oklch() value: {value!r}")
    return float(match.group(1)), float(match.group(2)), float(match.group(3))


def derive_muted_foreground(ink_value: str, muted_value: str, floor: float = _MUTED_FOREGROUND_FLOOR) -> str:
    """The minimum darkening of `ink_value` (a `--muted-foreground` oklch()
    string) that clears `floor`:1 contrast against `muted_value` (that
    variant/mode's own `--muted`) UNDER BOTH CONTRAST MODELS (architect's
    "two-model rule" -- see `_clears_both_models`) -- chroma and hue held
    fixed, only lightness moves, and only downward (this floor's failures
    are all "ink too light for this background," never the reverse).
    Already-passing input returns UNCHANGED (minimum darkening can be
    zero) -- this is what makes dark mode (which already clears 4.5:1 for
    every base) a no-op here, not a second derivation path.
    """
    ink = _parse_oklch(ink_value)
    bg = _parse_oklch(muted_value)
    if _clears_both_models(ink, bg, floor):
        return ink_value
    l, c, h = ink
    step = 0.0005
    new_l = l
    while new_l > 0:
        new_l -= step
        if _clears_both_models((new_l, c, h), bg, floor):
            return f"oklch({new_l:.4f} {c} {h})"
    raise ValueError(f"could not darken {ink_value!r} enough to clear {floor}:1 (both models) against {muted_value!r}")


_PRIMARY_FOREGROUND_FLOOR = 4.5  # WCAG AA, normal text -- same floor, different pair


def derive_primary_foreground(ink_value: str, primary_value: str, floor: float = _PRIMARY_FOREGROUND_FLOOR) -> str:
    """The minimum darkening of `ink_value` (a Theme `--primary-foreground`
    oklch() string) that clears `floor`:1 against `primary_value` (that
    variant/mode's own `--primary`) UNDER BOTH CONTRAST MODELS -- same
    shape and same direction as `derive_muted_foreground` (dark ink on a
    lighter fill, darkening only ever helps), reused rather than
    duplicated. Distinct name/floor constant because it's a different
    dimension's pair (qa's contrast gate treats Base and Theme
    separately) -- found by the 'yellow' Theme variant's dark-mode
    primary-foreground/primary margin sitting at only +0.038 (passes the
    bare 4.5:1 floor, misses the generator's own 0.05 derivation-headroom
    rule) once the curated Theme option-set cap was lifted and 'yellow'
    became a real (in fact default) option rather than staying excluded.
    """
    ink = _parse_oklch(ink_value)
    bg = _parse_oklch(primary_value)
    if _clears_both_models(ink, bg, floor):
        return ink_value
    l, c, h = ink
    step = 0.0005
    new_l = l
    while new_l > 0:
        new_l -= step
        if _clears_both_models((new_l, c, h), bg, floor):
            return f"oklch({new_l:.4f} {c} {h})"
    raise ValueError(f"could not darken {ink_value!r} enough to clear {floor}:1 (both models) against {primary_value!r}")


_DESTRUCTIVE_FOREGROUND_FLOOR = 4.5  # WCAG AA, normal text -- same floor, different pair


def derive_destructive_foreground(direction: str, ink_value: str, destructive_value: str,
                                   floor: float = _DESTRUCTIVE_FOREGROUND_FLOOR) -> str:
    """The minimum shift of `ink_value` (a `--destructive-foreground` oklch()
    string) that clears `floor`:1 against `destructive_value` (that mode's
    own `--destructive` fill) UNDER BOTH CONTRAST MODELS (see
    `_clears_both_models`) -- chroma/hue fixed, lightness moves in
    `direction` ONLY ("lighten" or "darken").

    UNLIKE `derive_muted_foreground` above, this is NOT a "the fix is
    always darker" function -- architect's ruling (2026-08-29, verified
    independently after implementation-lead's finding): light mode's
    --destructive is a DARK red (L~0.577) and wants lighter ink; dark
    mode's --destructive is, unusually, a LIGHTER red (L~0.704) than its
    own light-mode counterpart, and wants DARKER ink -- the two modes
    need opposite shift directions, which is exactly why a single shared
    ink value (the vendored default) could never clear both at once.
    Cloning derive_muted_foreground's always-darken search here would
    silently darken the light-mode ink away from its only viable
    direction and then raise on exhaustion -- the wrong kind of failure
    (looks like "no value exists" rather than "wrong direction was
    tried"). Callers MUST pass the correct `direction` for the mode they're
    deriving; there is no way to infer it from the values alone that
    wouldn't just be re-implementing this same ruling's reasoning.

    The two-model requirement (not just an arbitrary margin) is what this
    function needs specifically: a single-model bare-minimum search here
    once produced `oklch(0.3145 0.01 17.0)`, which cleared 4.5:1 under the
    quantized-hex model (4.5268:1) but NOT under the float model
    (4.4955:1) -- the floor sat inside the ~0.03 gap between the two
    bridges. `_clears_both_models`'s epsilon exists exactly to keep a
    future derived value from landing in that kind of gap again.
    """
    if direction not in ("lighten", "darken"):
        raise ValueError(f"direction must be 'lighten' or 'darken', got {direction!r}")
    ink = _parse_oklch(ink_value)
    bg = _parse_oklch(destructive_value)
    if _clears_both_models(ink, bg, floor):
        return ink_value
    l, c, h = ink
    step = 0.0005 if direction == "lighten" else -0.0005
    bound = 1.0 if direction == "lighten" else 0.0
    new_l = l
    while (direction == "lighten" and new_l < bound) or (direction == "darken" and new_l > bound):
        new_l += step
        if _clears_both_models((new_l, c, h), bg, floor):
            return f"oklch({new_l:.4f} {c} {h})"
    raise ValueError(
        f"could not {direction} {ink_value!r} enough to clear {floor}:1 (both models) against "
        f"{destructive_value!r} -- if this is the light-mode side, the ceiling may genuinely be below "
        f"the floor in the OTHER direction too; re-check both directions and the fill itself before "
        f"assuming a bug here."
    )


# Fixed emission order -- architect's ruling table order, not the JSON's
# (json.load doesn't guarantee dict order is meaningful here; we don't
# rely on it).
DIMENSION_ORDER = ("base", "theme", "chart")

# (relative path under the target root, indent style, header lines).
_BOARD_HEADER = """\
/*
 * variants.css -- GENERATED FILE, do not hand-edit.
 *
 * PT-69 (architect's theme-variant ruling, §1/§2): one attribute-qualified
 * CSS block per (dimension, variant, mode), sourced from
 * scripts/cairn/design/variants.json and emitted by
 * scripts/cairn/design/gen_variants.py -- regenerate with
 * `python3 scripts/cairn/design/gen_variants.py`, never edit this file by
 * hand (scripts/cairn/tests/test_theme_variants_generator.py asserts this
 * file is byte-identical to what the generator currently produces).
 *
 * Linked from board.html AFTER tokens.css, BEFORE board.css -- the
 * default (Stone/Sky/Yellow) values already live in tokens.css's own
 * unqualified :root/.dark; the blocks below only carry the DELTA a
 * non-default selection needs, and win on specificity alone (no
 * !important) because an attribute-qualified selector always outranks a
 * bare :root/.dark.
 *
 * See scripts/cairn/design/NOTICE.md for provenance (source, extraction
 * date, per-dimension notes).
 */

"""

_DASHBOARD_HEADER = """\
/* variants.css -- GENERATED FILE, do not hand-edit.
 *
 * PT-69 (architect's theme-variant ruling, §1/§2): one attribute-qualified
 * CSS block per (dimension, variant, mode), sourced from
 * scripts/cairn/design/variants.json and emitted by
 * scripts/cairn/design/gen_variants.py -- regenerate with
 * `python3 scripts/cairn/design/gen_variants.py`, never edit this file by
 * hand (scripts/cairn/tests/test_theme_variants_generator.py asserts this
 * file is byte-identical to what the generator currently produces).
 *
 * Imported from app.css immediately after its existing three @import
 * lines (tailwindcss, tw-animate-css, shadcn-svelte/tailwind.css) -- still
 * ahead of any rule, so Tailwind v4's "@import must lead the file" rule
 * holds. The default (Stone/Sky/Yellow) values already live in app.css's
 * own :root/.dark; the blocks below only carry the DELTA a non-default
 * selection needs.
 *
 * See scripts/cairn/design/NOTICE.md for provenance (source, extraction
 * date, per-dimension notes).
 */

"""

_DOCS_HEADER = """\
/*
 * variants.css -- GENERATED FILE, do not hand-edit.
 *
 * PT-69 (architect's theme-variant ruling): docs-side reference copy of
 * the theme-variant blocks, alongside docs/DESIGN/tokens.css's own
 * default-preset reference copy. Sourced from
 * scripts/cairn/design/variants.json, emitted by
 * scripts/cairn/design/gen_variants.py -- regenerate with
 * `python3 scripts/cairn/design/gen_variants.py`, never edit this file by
 * hand. See docs/DESIGN/design-system-spec.md's "Theme & color variants"
 * section for the full spec, and scripts/cairn/design/NOTICE.md for
 * provenance.
 */

"""

# (relative path used for the --out-dir verification layout -- always
# flattened under one root there, per the CLI contract
# test_theme_variants_generator.py pins), indent style, header.
_TARGETS = (
    ("board/variants.css", "  ", _BOARD_HEADER),
    ("dashboard/src/variants.css", "\t", _DASHBOARD_HEADER),
    ("docs/DESIGN/variants.css", "  ", _DOCS_HEADER),
)


def _load_variants() -> dict:
    with VARIANTS_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_values(dim: str, values: dict) -> dict:
    """The values a block actually emits -- identical to `values` for every
    dimension/pair except the two DERIVED ones: Base's `muted-foreground`
    (Mosko's "darken the ink" ruling) and Theme's `primary-foreground`
    (same treatment, applied once qa's contrast gate found 'yellow' sitting
    inside the derivation-headroom margin once Theme's option-set cap was
    lifted) -- both derived from the vendored ink + this same block's own
    background token, never emitted verbatim."""
    resolved = dict(values)
    if dim == "base" and "muted-foreground" in values and "muted" in values:
        resolved["muted-foreground"] = derive_muted_foreground(values["muted-foreground"], values["muted"])
    if dim == "theme" and "primary-foreground" in values and "primary" in values:
        resolved["primary-foreground"] = derive_primary_foreground(values["primary-foreground"], values["primary"])
    return resolved


def _render_block(dim: str, name: str, mode: str, values: dict, indent: str) -> str:
    attribute = f'data-cairn-{dim}'
    selector = (
        f':root[{attribute}="{name}"]'
        if mode == "light"
        else f':root.dark[{attribute}="{name}"]'
    )
    resolved = _resolve_values(dim, values)
    lines = [selector + " {"]
    for key in sorted(resolved):
        lines.append(f"{indent}--{key}: {resolved[key]};")
    lines.append("}")
    return "\n".join(lines)


def _render_css(data: dict, indent: str, header: str) -> str:
    blocks = []
    dimensions = data["dimensions"]
    for dim in DIMENSION_ORDER:
        variants = dimensions[dim]["variants"]
        for name in sorted(variants):
            variant = variants[name]
            blocks.append(_render_block(dim, name, "light", variant["light"], indent))
            blocks.append(_render_block(dim, name, "dark", variant["dark"], indent))
    body = "\n\n".join(blocks)
    if body:
        body += "\n"
    return header + body


_BOOTSTRAP_TEMPLATE = """\
(function () {
  try {
    var KEY = "%(storage_key)s";
    var DEFAULTS = { mode: "%(default_mode)s", base: "%(default_base)s", theme: "%(default_theme)s", chart: "%(default_chart)s" };
    var VALID_MODE = %(valid_mode)s;
    var VALID_BASE = %(valid_base)s;
    var VALID_THEME = %(valid_theme)s;
    var VALID_CHART = %(valid_chart)s;
    var raw = null;
    try {
      raw = localStorage.getItem(KEY);
    } catch (e) {}
    var parsed = null;
    if (raw) {
      try {
        parsed = JSON.parse(raw);
      } catch (e) {}
    }
    if (!parsed || parsed.v !== 1) parsed = {};
    // Per-dimension fallback (architect's ruling §3): an unrecognized or
    // absent value on ANY one field falls back to that field's own
    // default, independently -- never a whole-blob rejection.
    var mode = VALID_MODE.indexOf(parsed.mode) !== -1 ? parsed.mode : DEFAULTS.mode;
    var base = VALID_BASE.indexOf(parsed.base) !== -1 ? parsed.base : DEFAULTS.base;
    var theme = VALID_THEME.indexOf(parsed.theme) !== -1 ? parsed.theme : DEFAULTS.theme;
    var chart = VALID_CHART.indexOf(parsed.chart) !== -1 ? parsed.chart : DEFAULTS.chart;
    var root = document.documentElement;
    var systemDark = false;
    try {
      systemDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch (e) {}
    var dark = mode === "dark" || (mode === "system" && systemDark);
    root.classList.toggle("dark", dark);
    if (base !== DEFAULTS.base) root.setAttribute("data-cairn-base", base);
    if (theme !== DEFAULTS.theme) root.setAttribute("data-cairn-theme", theme);
    if (chart !== DEFAULTS.chart) root.setAttribute("data-cairn-chart", chart);
  } catch (e) {}
})();
"""


def _js_string_array(values) -> str:
    return "[" + ", ".join(json.dumps(v) for v in values) + "]"


def _render_bootstrap(data: dict) -> str:
    defaults = data["defaults"]
    dimensions = data["dimensions"]
    valid_base = [defaults["base"]] + sorted(dimensions["base"]["variants"])
    valid_theme = [defaults["theme"]] + sorted(dimensions["theme"]["variants"])
    valid_chart = [defaults["chart"]] + sorted(dimensions["chart"]["variants"])
    script = _BOOTSTRAP_TEMPLATE % {
        "storage_key": data["storageKey"],
        "default_mode": defaults["mode"],
        "default_base": defaults["base"],
        "default_theme": defaults["theme"],
        "default_chart": defaults["chart"],
        "valid_mode": _js_string_array(data["mode"]["options"]),
        "valid_base": _js_string_array(valid_base),
        "valid_theme": _js_string_array(valid_theme),
        "valid_chart": _js_string_array(valid_chart),
    }
    return (
        f'<script id="cairn-theme-bootstrap">\n{script}</script>\n'
    )


def _target_paths(out_dir: Path | None) -> list:
    """Absolute path for each of the three generated files.

    With `out_dir` given (the --out-dir verification path), all three sit
    flattened under one root -- `out_dir/board/variants.css`, etc. -- per
    the CLI contract test_theme_variants_generator.py pins. With no
    `out_dir` (the real authoring invocation), the three files' actual
    homes do NOT share a common relative-path prefix: board/ and
    dashboard/src/ live under scripts/cairn/, but docs/DESIGN/ lives at
    the repo root directly, not under scripts/cairn/docs/DESIGN -- so the
    real paths are resolved explicitly rather than by reusing the
    flattened --out-dir layout.
    """
    if out_dir is not None:
        return [out_dir / rel_path for rel_path, _, _ in _TARGETS]
    cairn_dir = SCRIPT_DIR.parent  # scripts/cairn/design -> scripts/cairn
    repo_root = cairn_dir.parents[1]  # scripts/cairn -> repo root
    return [
        cairn_dir / "board" / "variants.css",
        cairn_dir / "dashboard" / "src" / "variants.css",
        repo_root / "docs" / "DESIGN" / "variants.css",
    ]


def generate(out_dir: Path | None) -> None:
    data = _load_variants()
    targets = _target_paths(out_dir)
    for target, (_, indent, header) in zip(targets, _TARGETS):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_css(data, indent, header), encoding="utf-8")
    if out_dir is None:
        # Not part of the --out-dir CLI contract (that's the 3 CSS files
        # only) -- a convenience copy of the inline theme-bootstrap
        # snippet, so board.html and dashboard/index.html can be kept in
        # sync by pasting this file's contents into both <head>s verbatim
        # (test_theme_bootstrap_and_dropdown.py asserts they stay
        # byte-identical to each other; this file is the one generation
        # source both copies trace back to).
        bootstrap_path = SCRIPT_DIR / "bootstrap.snippet.html"
        bootstrap_path.write_text(_render_bootstrap(data), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="write board/, dashboard/src/, docs/DESIGN/ flattened under this directory instead "
        "of the real checked-in locations (verification only -- the authoring invocation takes "
        "no arguments and writes the real files).",
    )
    args = parser.parse_args(argv)
    generate(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
