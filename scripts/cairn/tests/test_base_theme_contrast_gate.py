"""PT-69 architect ruling guard, REWRITTEN per architect's 2026-08-29
"contrast gate semantics" ruling (issue thread, commit 248f8eb) -- the
FIRST version of this file (built to the architect's own earlier spec) was
wrong in a specific, instructive way: it derived its pair list from
TOKEN-NAME SYMMETRY ("X-foreground renders on X") instead of from what the
surfaces actually render. That gated a pair nothing renders
(`--sidebar-primary-foreground`/`--sidebar-primary` -- zero references
anywhere outside the three token-declaration files, confirmed dead) while
simultaneously missing the single most common real pair in both surfaces
(`--muted-foreground` on `--card`, meta text inside cards).

**The structural fix, per the ruling:** the pair list is DERIVED FROM
SOURCE USAGE and RE-DERIVED ON EVERY RUN, never hand-maintained -- same
discipline as `test_board_small_label_face.py`, which re-derives its
selector set from source rather than pinning today's list. A pair enters
the gate when something in `board.css` or `dashboard/src` actually renders
that foreground on that background (as CSS `color:`/`background:`, a
Tailwind `text-*`/`bg-*`/`fill-*` utility class, or an SVG label fill --
architect's own "fill-muted-foreground" chart-axis-label case); it leaves
automatically when nothing does. This means a FUTURE dead pair (like
`--sidebar-primary`'s turned out to be) gets caught the same way this one
did, without anyone auditing the list by hand.

**Role-dependent floors, by the WCAG standard, not by convenience**
(architect's Q2): normal text 4.5:1 (1.4.3), large text 3:1 (>=24px or
>=18.66px bold), non-text/graphical objects 3:1 (1.4.11). A token can carry
BOTH roles (`--muted-foreground` is 12px `.column-header` TEXT in one rule
and a status-dot FILL in another) -- if it's ever rendered as text
anywhere, the stricter 4.5:1 governs for that token, full stop; the
looser 3:1 only applies to a token whose every rendered use is graphical.

**Explicitly carved out, per the ruling, not per this file's own
judgment:** `--foreground`/`--background` clears the usage-liveness bar
(both names ARE referenced somewhere in source), but the ruling holds it
out of the gate pending an actual browser-rendered confirmation --
"`--background` is never used as a surface on the board and the
dashboard's body is `bg-muted`... keep it only if the browser confirmation
finds it actually rendered." Static text-level inference cannot settle
"is X really the EFFECTIVE COMPOSITED background here" -- that is
precisely the class of question this project has been burned by trusting
a text-level guard on before (browser-visibility precedent), and the
ruling is explicit that the derived list is a REGRESSION GUARD after a
real browser pass, never a substitute for the first one. Remove
`PENDING_BROWSER_CONFIRMATION` below only once that confirmation lands,
in whichever direction it points.

**Scope note, flagged rather than silently decided:** the architect's own
message named exactly four pairs by discussion (drop sidebar-primary, keep
muted/muted, add muted/card, conditional foreground/background) while
ALSO instructing "derive from usage, don't hand-list" as the general
mechanism. Generic derivation over Base's full owned-var set surfaces five
MORE natural pairs the discussion didn't name individually (card-
foreground/card, popover-foreground/popover, secondary-foreground/
secondary, accent-foreground/accent, destructive-foreground/destructive,
sidebar-foreground/sidebar, sidebar-accent-foreground/sidebar-accent) --
all independently verified live in source (see this feature's QA handoff
notes). This file includes them, since the ruling's own stated mechanism
is "derive from usage" rather than "gate exactly these four" -- flagged in
the handoff for architect/team-lead to confirm or narrow, per the ruling's
own explicit invitation to push back.

Still true from the original version: nothing under test exists yet for
most variants when this file is written (board/variants.css currently
carries only Chart variants; Base/Theme variant blocks are still `{}` in
variants.json) -- every assertion either fails loudly or skips if the
dataviz-adjacent validator module can't be located.

**Second rewrite, per architect's 2026-08-29 follow-up ruling (05e963e):**
kept the generic within-dimension derivation above (architect: "narrowing
back to my four hand-named pairs would reinstate the exact defect... a
curated list is stale the moment anyone adds a rule") and it found a real
issue architect independently verified (`--destructive-foreground`/
`--destructive` on the board's Blocked/Cancelled chips, 4.35 light / 2.64
dark -- normal text at 11px, dark misses by 1.86).

But the within-dimension derivation has a structural blind spot architect
named precisely: it generates (X-foreground, X) pairs by SUFFIX SYMMETRY
WITHIN one dimension's owned-var set, so it can never produce a pair that
SPANS two dimensions -- and real CSS doesn't respect that boundary.
`.chip.status[data-status="paused"]` sets `background: var(--chart-2)`
(Chart) with `color: var(--foreground)` (Base) in the SAME rule --
1.83:1 in dark mode, worse than the destructive finding, and no per-
dimension derivation could ever have found it.

**The correction, added below as a SEPARATE, complementary mechanism (not
a replacement for the within-dimension one -- that one already correctly
covers same-rule-family pairs like `--muted-foreground`/`--muted`, which
is a parent/ancestor relationship, not same-rule co-occurrence, and stays
exactly as architect verified it):** `_derive_cross_dimension_pairs()`
scans board.css rule blocks and dashboard class-string literals for a
`background`/`bg-*` token and a `color`/`text-*`/`fill-*` token set
TOGETHER -- same rule, same class string, same rendered element -- and
keeps only the pairs whose two tokens belong to DIFFERENT dimensions
(same-dimension co-occurrences are redundant with the existing symmetric
derivation and are dropped to avoid double-asserting). A cross-dimension
pair is checked over the cross-product of BOTH dimensions' variants at the
SAME mode (mode is a single cross-cutting `.dark` class, not per-
dimension, so light-A-vs-dark-B is never a real combination) --
architect: "that's contrast arithmetic on a handful of pairs, not ramp
derivation; no budget concern, so don't approximate it."

**Framing note for whoever reads a cross-dimension failure, RESOLVED by
architect's follow-up ruling (1db6053):** neither the drop-don't-rederive
fence nor PT-61's re-derive fence applies to a cross-dimension failure --
a surviving one means a text-bearing surface is drawing its fill from a
dimension that has no product relationship to that surface's legibility
(the `--foreground`/`--chart-2` status chip: a chart-palette pick has
nothing to do with a status chip's readability). **The fix is to REPOINT
the consuming rule/component onto a token in its own dimension**, not to
adjust either dimension's palette -- exactly what happened to the paused/
cancelled-adjacent status chip (`board.css:676`, `badge.svelte`'s `chart`
variant, `App.svelte:65`), which ux-designer repointed onto `--accent`/
`--accent-foreground` (Base-owned, inverts correctly with mode). Once
that repointing landed, the pair stopped being generated by the
derivation entirely -- the correct way for a usage-derived pair to leave
a gate, per architect: "the derivation notices, and nobody maintains an
exclusion list." `KnownCrossDimensionPairIsDetectedTests` (below) tracks
this -- see task #24 for its retarget/retirement once confirmed.

**Also per architect's explicit instruction to keep, unchanged from the
first rewrite:** `PENDING_BROWSER_CONFIRMATION` for `--foreground`/
`--background` as a within-dimension pair (architect: "the right shape...
I'd like it to be the pattern for any future pair you can't settle
statically"), `_token_role()`'s text-wins-when-both-present rule, and the
dedicated dead-pair + `--ring` regression tests below.

**Final ruling (team-lead, posting Mosko's decision, 2026-08-29, "darken
the ink"):** the systemic within-dimension residue (`--muted-foreground`/
`--muted` light-mode miss across 6 of 7 Base variants, and the newly-
reachable `--destructive-foreground`/`--destructive` dark-mode failure)
gets resolved by a per-base MECHANICAL ink derivation in `gen_variants.py`
-- not accepted as debt, not punted as an open product question, and not
routed through the drop-don't-rederive fence (that fence is for a variant
failing something its siblings pass, not an every-variant systemic miss).
This gate is expected to hold at ZERO EXEMPTIONS once those derived inks
land; a failure here past that point is a real regression to investigate,
not a known-accepted residue to explain away.

**Third rewrite, per architect's ruling (4e0e678):** the "darkened" values
that landed for `--muted-foreground` and `--destructive-foreground` re-
opened this gate anyway, and the reason is structural, not a fresh derivation
mistake: this file computed contrast the SAME way `gen_variants.py` does --
round-trip every OKLCH value through 8-bit hex (`_oklch_to_hex` + the
validator's `contrast()`) before comparing. ux-designer's independently-
written, continuous-sRGB contrast check disagreed by ~0.8% on values this
gate had already certified (dark `--destructive-foreground`: 4.4955
continuous vs 4.5268 quantized, the 4.5 floor sitting INSIDE that gap). A
guard sharing its color bridge with the thing it guards can only certify
what that bridge likes -- it has no way to see its own bias. That is a
general lesson, not specific to this file: anywhere else in this suite a
test imports the same numeric-computation helper the production code
uses, the identical blind spot exists (architect's explicit flag, not
acted on elsewhere in this pass).

**The fix:** `_dual_model_contrast()` computes BOTH models --
`_oklch_to_hex`+`contrast()` (quantized, 8-bit round-trip) and
`_oklch_to_linear_rgb_clamped`+`_relative_luminance_linear` (continuous,
gamut-clamped but never rounded to integers) -- and every assertion in
this file now gates on `min(quantized, float)`, never either alone. The
generator additionally requires `floor + 0.05` headroom when DERIVING a
new value (so a future straddle doesn't reopen it); this gate asserts the
plain floor under both models, since it also checks values nobody
derived.
"""
from __future__ import annotations

import math
import re
import sys
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
BOARD_TOKENS_CSS = helpers.CAIRN_DIR / "board" / "tokens.css"
BOARD_VARIANTS_CSS = helpers.CAIRN_DIR / "board" / "variants.css"
BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"
BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"
DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"

sys.path.insert(0, str(helpers.TESTS_DIR))
from test_dashboard_chart_ramp import _oklch_to_hex, _find_validator_module  # noqa: E402

WCAG_NORMAL_TEXT = 4.5           # WCAG 1.4.3, normal text
WCAG_LARGE_TEXT_OR_GRAPHICAL = 3.0  # WCAG 1.4.3 large text (>=24px/>=18.66px bold) or 1.4.11 non-text/graphical


# -- Two-model contrast check, architect's ruling @ 4e0e678 -------------
#
# ux-designer's independently-written contrast implementation disagreed
# with the generator's (and this file's, until now) by ~0.8% on the
# already-"fixed" values -- not rounding noise, two different-but-both-
# correct models: hers computes on CONTINUOUS sRGB; the generator's (and
# this file's `_oklch_to_hex` + `module.contrast`) rounds through 8-bit
# hex first. Dark destructive ink sits at 4.4955 (float) / 4.5268
# (quantized), with the 4.5 floor INSIDE that gap -- so which model you
# ask determines whether it passes. This file shared the generator's
# color bridge, so it certified exactly the values that bridge liked and
# could not see its own bias -- "a guard that reuses the implementation
# it's guarding tests self-consistency, not correctness" (architect,
# verbatim, worth remembering generally).
#
# The fix: a pair passes only when BOTH models agree it clears the floor
# -- `min(quantized_contrast, float_contrast) >= floor`. (The generator
# additionally requires `floor + 0.05` when DERIVING a value, to leave
# headroom against exactly this straddling; this gate asserts the plain
# floor under both models since it also checks values nobody derived.)
def _oklch_to_linear_rgb_clamped(l: float, c: float, h_deg: float):
    """OKLCH -> linear sRGB, continuous floats, gamut-clamped to [0, 1]
    but NEVER rounded to 8-bit integers -- the "float model." Same
    published Bjorn Ottosson OKLab<->linear-sRGB matrices `_oklch_to_hex`
    uses (see test_dashboard_chart_ramp.py), stopped one step earlier:
    clamped like `lin2s` clamps before gamma-encoding, but skips both the
    gamma-encode AND the round-to-integer steps that introduce the
    quantization this check exists to catch."""
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
    return tuple(max(0.0, min(1.0, ch)) for ch in (r, g, bb))


def _relative_luminance_linear(rgb) -> float:
    """WCAG relative luminance, computed directly on already-LINEAR RGB
    (no gamma round-trip needed -- the formula wants linear values)."""
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_float(lum_a: float, lum_b: float) -> float:
    hi, lo = sorted((lum_a, lum_b), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _dual_model_contrast(fg_oklch, bg_oklch, module):
    """(min(quantized, float), quantized, float) for one fg/bg OKLCH
    pair. `quantized` is the pre-existing model (round-trip through
    `_oklch_to_hex` + the validator's own `contrast()`); `float` is the
    continuous model above. The gate asserts against the MIN -- a pair
    that either model alone would fail is a real failure; a pair only ONE
    model happens to clear is exactly the straddling case this exists to
    catch, so it must not pass on that model's say-so alone."""
    fg_hex = _oklch_to_hex(*fg_oklch, module.lin2s)
    bg_hex = _oklch_to_hex(*bg_oklch, module.lin2s)
    quantized = module.contrast(fg_hex, bg_hex)

    fg_rgb = _oklch_to_linear_rgb_clamped(*fg_oklch)
    bg_rgb = _oklch_to_linear_rgb_clamped(*bg_oklch)
    float_ratio = _contrast_float(_relative_luminance_linear(fg_rgb), _relative_luminance_linear(bg_rgb))

    return min(quantized, float_ratio), quantized, float_ratio


BASE_OWNED = frozenset({
    "--background", "--foreground", "--card", "--card-foreground",
    "--popover", "--popover-foreground", "--secondary", "--secondary-foreground",
    "--muted", "--muted-foreground", "--accent", "--accent-foreground",
    "--border", "--input", "--ring", "--destructive", "--destructive-foreground",
    "--sidebar", "--sidebar-foreground", "--sidebar-accent", "--sidebar-accent-foreground",
    "--sidebar-border", "--sidebar-ring",
})
THEME_OWNED = frozenset({
    "--primary", "--primary-foreground", "--sidebar-primary", "--sidebar-primary-foreground",
})
CHART_OWNED = frozenset({
    "--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5",
    "--chart-flow-backlog", "--chart-flow-todo", "--chart-flow-in-progress",
    "--chart-flow-in-review", "--chart-flow-done", "--chart-flow-cancelled",
})
DIMENSION_OWNED = {"base": BASE_OWNED, "theme": THEME_OWNED, "chart": CHART_OWNED}

# A real, usage-confirmed pair that isn't derivable from simple
# `X-foreground`/`X` suffix symmetry -- architect's own finding: "the
# single most common foreground/surface combination in both surfaces,
# which my cross-product never tested. It passes at 4.79:1... the
# identical text passes on cards and fails on the canvas."
EXTRA_PAIRS = {
    "base": [("--muted-foreground", "--card")],
}

# Explicitly held out pending a real browser confirmation pass -- see this
# file's module docstring. NOT derived, NOT decided here; a deliberate,
# documented manual override of what static usage-liveness alone would
# otherwise include.
PENDING_BROWSER_CONFIRMATION = {
    "base": {("--foreground", "--background")},
}

# Mosko's final ruling ("darken the ink", team-lead's post on the issue,
# 2026-08-29) resolved the systemic residue this gate surfaced: a rendered
# pair that fails across (most or all of) a dimension's variants is NOT a
# product-call punt and NOT a per-variant drop candidate -- it gets a
# mechanically-derived, per-base ink adjustment (minimum shift that clears
# the floor, owned by gen_variants.py so it's reproducible, before/after
# values recorded in design-system-spec.md's Accessibility section),
# applied to the shipped default too. This gate is therefore expected to
# hold at ZERO EXEMPTIONS once those derived inks land -- a lingering
# failure here is a real, unresolved gap, not a known/accepted residue.
# The drop-don't-rederive fence below is narrowed accordingly: it now
# governs only a GENUINE PER-VARIANT defect (one variant failing something
# its siblings pass) that survives the ruled gate -- not a systemic,
# every-variant miss, which gets the darken-the-ink treatment instead.
DROP_DONT_REDERIVE = (
    "Per architect's ruling + design-system-spec.md's Theme & color "
    "variants section: a Base or Theme variant that fails a GENUINELY "
    "RENDERED pair on its OWN (its siblings in the same dimension clear "
    "the same pair fine) gets DROPPED FROM THE OPTION SET in "
    "variants.json, never re-derived -- 'repairing' shadcn's published "
    "neutrals/accents into a variant that isn't the real published color "
    "is worse than offering fewer options. (Chart Color is the sole "
    "exception -- --chart-flow-* is this project's own token, re-stepped "
    "per PT-61, not dropped.) If EVERY (or nearly every) variant in a "
    "dimension fails the SAME pair, that is NOT this fence's job -- per "
    "Mosko's 'darken the ink' ruling, a systemic miss gets a mechanically-"
    "derived per-base ink adjustment in gen_variants.py, and this gate "
    "should be at zero exemptions once that lands. A failure at this "
    "point is a real, unresolved regression, not an accepted residue."
)

_VARIANT_BLOCK_OPEN_RE = re.compile(
    r':root(?P<dark>\.dark)?\[data-cairn-(?P<dim>base|theme|chart)="(?P<name>[\w-]+)"\]\s*\{'
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


def _var_values(body: str) -> dict:
    out = {}
    for name, triple in re.findall(r"(--[\w-]+)\s*:\s*oklch\(([^)/]*)\)", body):
        parts = triple.split()
        if len(parts) != 3:
            continue
        try:
            out[name] = tuple(float(p) for p in parts)
        except ValueError:
            continue
    return out


def _collect_variants(dim: str) -> dict:
    """{variant_name: {"light": {var: (l,c,h)}, "dark": {...}}} -- the
    DEFAULT (Stone/Sky) from board/tokens.css's own unqualified :root/
    .dark, plus every named variant from board/variants.css's attribute-
    qualified blocks."""
    variants = {}
    if BOARD_TOKENS_CSS.is_file():
        source = BOARD_TOKENS_CSS.read_text(encoding="utf-8")
        default_name = "stone (default)" if dim == "base" else "sky (default)"
        variants.setdefault(default_name, {})["light"] = _var_values(_extract_unqualified_block(source, ":root"))
        variants[default_name]["dark"] = _var_values(_extract_unqualified_block(source, ".dark"))
    if BOARD_VARIANTS_CSS.is_file():
        source = BOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        for block_dim, name, is_dark, body in _find_variant_blocks(source):
            if block_dim != dim:
                continue
            variants.setdefault(name, {})["dark" if is_dark else "light"] = _var_values(body)
    return variants


def _bare(var_name: str) -> str:
    return var_name.lstrip("-")


def _derive_natural_pairs(owned_vars) -> list:
    """Every (X-foreground, X) pair where both names are owned by the same
    dimension -- generic suffix-symmetry derivation, no hand-listing.
    `--foreground` is the one irregular case (its counterpart is
    `--background`, not `--` with the suffix stripped)."""
    owned = set(owned_vars)
    pairs = []
    if "--foreground" in owned and "--background" in owned:
        pairs.append(("--foreground", "--background"))
    for var in sorted(owned):
        if var.endswith("-foreground") and var != "--foreground":
            base = var[: -len("-foreground")]
            if base in owned:
                pairs.append((var, base))
    return pairs


def _token_role(var_name: str, board_css_source: str, dashboard_haystack: str):
    """(floor, role_label) if `var_name` is rendered ANYWHERE outside the
    token-declaration files, checking TEXT usage first (the stricter
    4.5:1 governs if the token is ever text, even if it's also used as a
    graphical fill elsewhere) then GRAPHICAL/fill usage (3:1). (None, None)
    if the token is never referenced at all -- a dead token, the exact
    shape `--sidebar-primary` turned out to be."""
    bare = _bare(var_name)
    text_patterns = (
        rf"color\s*:\s*var\(--{re.escape(bare)}\)",
        rf"(?<![\w-])text-{re.escape(bare)}(?![\w-])",
        rf"(?<![\w-])fill-{re.escape(bare)}(?![\w-])",  # SVG label glyphs, e.g. chart axis-tick text
    )
    fill_patterns = (
        rf"background(?:-color)?\s*:\s*var\(--{re.escape(bare)}\)",
        rf"(?<![\w-])bg-{re.escape(bare)}(?![\w-])",
    )
    haystacks = (board_css_source, dashboard_haystack)
    if any(re.search(p, h) for p in text_patterns for h in haystacks):
        return WCAG_NORMAL_TEXT, "text"
    if any(re.search(p, h) for p in fill_patterns for h in haystacks):
        return WCAG_LARGE_TEXT_OR_GRAPHICAL, "graphical fill"
    return None, None


def _token_referenced_at_all(var_name: str, board_css_source: str, dashboard_haystack: str) -> bool:
    bare = _bare(var_name)
    patterns = (
        rf"var\(--{re.escape(bare)}\)",
        rf"(?<![\w-])(?:text|bg|fill|border)-{re.escape(bare)}(?![\w-])",
    )
    haystacks = (board_css_source, dashboard_haystack)
    return any(re.search(p, h) for p in patterns for h in haystacks)


def _derive_gated_pairs(dim_key: str, board_css_source: str, dashboard_haystack: str):
    """The usage-derived, role-annotated pair list for one dimension:
    [(fg, bg, floor, role_label), ...] -- excludes dead pairs (either side
    unreferenced anywhere) and anything in PENDING_BROWSER_CONFIRMATION.
    Returns (gated_pairs, excluded_dead, excluded_pending) so callers/tests
    can assert on all three, not just the survivors."""
    owned = BASE_OWNED if dim_key == "base" else THEME_OWNED
    candidates = _derive_natural_pairs(owned) + EXTRA_PAIRS.get(dim_key, [])
    pending = PENDING_BROWSER_CONFIRMATION.get(dim_key, set())
    gated, dead, held = [], [], []
    for fg, bg in candidates:
        if (fg, bg) in pending:
            held.append((fg, bg))
            continue
        floor, role = _token_role(fg, board_css_source, dashboard_haystack)
        if floor is None or not _token_referenced_at_all(bg, board_css_source, dashboard_haystack):
            dead.append((fg, bg))
            continue
        gated.append((fg, bg, floor, role))
    return gated, dead, held


def _token_dimension(var_name: str):
    """Which of base/theme/chart owns `var_name`, or None if it's owned by
    none of the three (e.g. --border, --input, --ring aren't fg/bg-pair
    tokens in the sense this file cares about)."""
    for dim, owned in DIMENSION_OWNED.items():
        if var_name in owned:
            return dim
    return None


_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_BG_DECL_RE = re.compile(r"(?<![\w-])background(?:-color)?\s*:\s*var\(--([\w-]+)\)")
_FG_DECL_RE = re.compile(r"(?<![\w-])color\s*:\s*var\(--([\w-]+)\)")
# Tailwind utility classes, modifier-prefix-tolerant (dark:, hover:,
# md:, group-*:, etc.) -- `(?:[\w-]+:)*` eats zero or more `modifier:`
# prefixes before the bare utility name.
_BG_CLASS_RE = re.compile(r"(?<![\w/-])(?:[\w-]+:)*bg-([a-z][\w-]*)")
_TEXT_CLASS_RE = re.compile(r"(?<![\w/-])(?:[\w-]+:)*text-([a-z][\w-]*)")
_FILL_CLASS_RE = re.compile(r"(?<![\w/-])(?:[\w-]+:)*fill-([a-z][\w-]*)")
_STRING_LITERAL_RE = re.compile(r"[\"'`]([^\"'`]*)[\"'`]")


def _css_rule_co_occurring_pairs(css_source: str) -> set:
    """(fg_var, bg_var) for every rule block in `css_source` that sets
    BOTH a `color: var(--X)` and a `background(-color)?: var(--Y)` --
    literally the same rendered element, same rule, no ambiguity about
    "does this text sit on this background." Simple (non-nested) rule
    parsing is safe here: board.css has no @media/nested blocks (verified
    -- 0 `@media` occurrences)."""
    stripped = _strip_css_comments(css_source)
    pairs = set()
    for _selector, body in _RULE_RE.findall(stripped):
        bg_match = _BG_DECL_RE.search(body)
        fg_match = _FG_DECL_RE.search(body)
        if bg_match and fg_match:
            pairs.add((f"--{fg_match.group(1)}", f"--{bg_match.group(1)}"))
    return pairs


def _class_string_co_occurring_pairs(haystack: str) -> set:
    """(fg_var, bg_var) for every quoted string literal (a `class="..."`
    attribute or a `cn("...")` argument) that contains BOTH a `bg-X` and a
    `text-Y`/`fill-Y` Tailwind utility together -- same class list, same
    element. `fill-*` covers SVG label glyphs (chart axis-tick text),
    architect's own example of a text role expressed as a `fill` utility.
    """
    pairs = set()
    for literal in _STRING_LITERAL_RE.findall(haystack):
        bg_names = set(_BG_CLASS_RE.findall(literal))
        fg_names = set(_TEXT_CLASS_RE.findall(literal)) | set(_FILL_CLASS_RE.findall(literal))
        for bg in bg_names:
            for fg in fg_names:
                pairs.add((f"--{fg}", f"--{bg}"))
    return pairs


def _derive_cross_dimension_pairs(board_css_source: str, dashboard_haystack: str):
    """Every (fg, bg) pair that co-occurs on one rendered element (same
    CSS rule or same class-string) whose two tokens belong to DIFFERENT
    dimensions (base/theme/chart) -- architect's correction: 'derive pairs
    from co-occurrence in a rule, not dimension membership.' Same-
    dimension co-occurrences are dropped here (already covered by the
    within-dimension symmetric derivation above, so keeping them here
    would double-assert); pairs involving a token this file doesn't
    classify into any of the three dimensions are dropped too (nothing to
    cross-reference variants against)."""
    all_pairs = _css_rule_co_occurring_pairs(board_css_source) | _class_string_co_occurring_pairs(dashboard_haystack)
    cross = []
    for fg, bg in sorted(all_pairs):
        dim_fg, dim_bg = _token_dimension(fg), _token_dimension(bg)
        if dim_fg is None or dim_bg is None or dim_fg == dim_bg:
            continue
        cross.append((fg, bg, dim_fg, dim_bg))
    return cross


def _run_cross_dimension_gate(testcase, module):
    board_css_source = BOARD_CSS.read_text(encoding="utf-8") if BOARD_CSS.is_file() else ""
    dashboard_parts = []
    if DASHBOARD_SRC.is_dir():
        dashboard_parts = [
            p.read_text(encoding="utf-8")
            for p in DASHBOARD_SRC.rglob("*")
            if p.is_file() and p.suffix in (".svelte", ".ts")
        ]
    dashboard_haystack = "\n".join(dashboard_parts)

    cross_pairs = _derive_cross_dimension_pairs(board_css_source, dashboard_haystack)
    if not cross_pairs:
        testcase.skipTest("no cross-dimension co-occurring pairs found yet")

    failures = []
    for fg, bg, dim_fg, dim_bg in cross_pairs:
        floor, role = _token_role(fg, board_css_source, dashboard_haystack)
        if floor is None:
            continue  # shouldn't happen (fg came from an actual co-occurrence), but don't assert on a ghost
        variants_fg = _collect_variants(dim_fg)
        variants_bg = _collect_variants(dim_bg)
        if not variants_fg or not variants_bg:
            continue
        for name_fg, modes_fg in sorted(variants_fg.items()):
            for name_bg, modes_bg in sorted(variants_bg.items()):
                for mode in ("light", "dark"):
                    values_fg = modes_fg.get(mode, {})
                    values_bg = modes_bg.get(mode, {})
                    if fg not in values_fg or bg not in values_bg:
                        continue
                    ratio, quantized, float_ratio = _dual_model_contrast(values_fg[fg], values_bg[bg], module)
                    if ratio < floor:
                        failures.append(
                            f"{fg} ({dim_fg} '{name_fg}') on {bg} ({dim_bg} '{name_bg}'), {mode} "
                            f"mode: {ratio:.4f}:1 (min of quantized {quantized:.4f} / float "
                            f"{float_ratio:.4f}), below the {floor}:1 floor ({role} role)"
                        )
    testcase.assertEqual(
        failures, [],
        "Cross-dimension pair(s) below their WCAG floor. Architect's ruling (1db6053, the "
        "--foreground/--chart-2 status-chip finding) settled how these get resolved: NEITHER "
        "existing fence applies (the drop-don't-rederive fence assumes a droppable Base/Theme "
        "variant; PT-61's re-derive fence covers only --chart-flow-*, not the base --chart-1..5 "
        "ramp these pairs typically use) -- a surviving cross-dimension failure means a text-"
        "bearing surface is architecturally drawing its fill from the WRONG dimension (its "
        "legibility becomes a function of a setting -- Base/Theme/Chart -- that has no product "
        "relationship to it). The fix is to REPOINT the consuming rule/component onto a token "
        "in its own dimension (or one that inverts correctly with mode), not to adjust either "
        "dimension's palette. If this ever fires again, find the render site(s) and move them, "
        "the way board.css/badge.svelte/App.svelte's chart-2 status affordances were moved:"
        "\n\n" + "\n".join(failures),
    )


def _run_gate(testcase, dim_label: str, dim_key: str, module):
    board_css_source = BOARD_CSS.read_text(encoding="utf-8") if BOARD_CSS.is_file() else ""
    dashboard_parts = []
    if DASHBOARD_SRC.is_dir():
        dashboard_parts = [
            p.read_text(encoding="utf-8")
            for p in DASHBOARD_SRC.rglob("*")
            if p.is_file() and p.suffix in (".svelte", ".ts")
        ]
    dashboard_haystack = "\n".join(dashboard_parts)

    gated_pairs, _dead, _held = _derive_gated_pairs(dim_key, board_css_source, dashboard_haystack)
    testcase.assertTrue(
        gated_pairs,
        f"{dim_label}: usage-derivation found ZERO live pairs to gate for this dimension -- "
        f"that would mean nothing in {dim_label} renders at all, which is itself suspicious "
        f"(check the derivation mechanism, not just accept the vacuous pass).",
    )

    variants = _collect_variants(dim_key)
    if not variants:
        testcase.skipTest(f"no {dim_label} variants found yet (board/tokens.css or board/variants.css missing)")

    failures = []
    for name, modes in sorted(variants.items()):
        for mode, values in sorted(modes.items()):
            for fg, bg, floor, role in gated_pairs:
                if fg not in values or bg not in values:
                    failures.append(f"{dim_label} '{name}' ({mode}): missing {fg} or {bg} entirely")
                    continue
                ratio, quantized, float_ratio = _dual_model_contrast(values[fg], values[bg], module)
                if ratio < floor:
                    failures.append(
                        f"{dim_label} '{name}' ({mode}): {fg} on {bg} is {ratio:.4f}:1 (min of "
                        f"quantized {quantized:.4f} / float {float_ratio:.4f}), below the "
                        f"{floor}:1 floor ({role} role)"
                    )
    testcase.assertEqual(failures, [], DROP_DONT_REDERIVE + "\n\nFailing pairs:\n" + "\n".join(failures))


# Architect's follow-up correction on this test's own nature (read this
# BEFORE touching the threshold below): this is NOT a soft "getting
# close" early warning where a slightly-thin margin is an acceptable,
# known state -- it is a DERIVATION-BYPASS DETECTOR. The generator
# requires `min(quantized, float) >= floor + 0.05` whenever it DERIVES a
# value, so every generator-produced token has margin >= 0.05 BY
# CONSTRUCTION. That means a margin below 0.05 can only mean one of two
# real defects: (1) someone hand-edited a token value instead of
# regenerating it (exactly the drift class test_theme_variants_
# generator.py's byte-identity check exists to catch from the other
# direction), or (2) the generator's own derivation logic is broken and
# is no longer enforcing its own headroom rule. There is NO legitimate
# path to a margin under 0.05.
#
# THE RESPONSE WHEN THIS GOES RED IS TO RE-DERIVE THE VALUE OR FIX THE
# GENERATOR -- NEVER TO LOWER THIS THRESHOLD. The current worst case
# (olive's muted pair, +0.0532) sits only 0.0032 above this bar, which
# will make lowering it look like a reasonable, low-risk fix to someone
# in a hurry three months from now, when this thread is gone and this
# comment is the only thing that remembers why that's wrong. If the
# generator's own headroom rule ever legitimately changes, update it in
# gen_variants.py FIRST and let this constant follow that change with a
# comment citing the new ruling -- never adjust this number in isolation
# to make a red run go green.
#
# This means `_run_gate` and this test are NOT redundant despite both
# using `_dual_model_contrast`: `_run_gate` answers "is this value
# ACCESSIBLE (clears the WCAG floor)?"; this one answers "did this value
# come from the derivation we ruled (clears the floor WITH the generator's
# own headroom)?" -- different questions, different failure causes, both
# worth having.
MARGIN_EARLY_WARNING_THRESHOLD = 0.05


def _collect_margins(dim_key: str, module):
    """[(margin, label), ...] for every currently-gated (variant, mode,
    pair) combination in `dim_key` that PASSES its floor -- margin =
    min(quantized, float) ratio minus the floor. Failing combinations are
    skipped here (that's `_run_gate`'s job, not this diagnostic's)."""
    board_css_source = BOARD_CSS.read_text(encoding="utf-8") if BOARD_CSS.is_file() else ""
    dashboard_parts = []
    if DASHBOARD_SRC.is_dir():
        dashboard_parts = [
            p.read_text(encoding="utf-8")
            for p in DASHBOARD_SRC.rglob("*")
            if p.is_file() and p.suffix in (".svelte", ".ts")
        ]
    dashboard_haystack = "\n".join(dashboard_parts)
    gated_pairs, _dead, _held = _derive_gated_pairs(dim_key, board_css_source, dashboard_haystack)
    variants = _collect_variants(dim_key)

    margins = []
    for name, modes in sorted(variants.items()):
        for mode, values in sorted(modes.items()):
            for fg, bg, floor, _role in gated_pairs:
                if fg not in values or bg not in values:
                    continue
                ratio, _quantized, _float_ratio = _dual_model_contrast(values[fg], values[bg], module)
                if ratio >= floor:
                    margins.append((ratio - floor, f"{dim_key} '{name}' ({mode}): {fg} on {bg}"))
    return margins


class BaseVariantContrastGateTests(unittest.TestCase):
    def test_every_base_variant_clears_its_role_appropriate_floor_on_every_rendered_pair(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        _run_gate(self, "Base", "base", module)


class ThemeVariantContrastGateTests(unittest.TestCase):
    def test_every_theme_variant_clears_its_role_appropriate_floor_on_every_rendered_pair(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        _run_gate(self, "Theme", "theme", module)


class ThinMarginEarlyWarningTests(unittest.TestCase):
    """A DERIVATION-BYPASS DETECTOR, not a soft early warning -- see the
    long comment on `MARGIN_EARLY_WARNING_THRESHOLD` above before touching
    anything in this class. Every generator-derived token has margin
    >= 0.05 by construction (the generator's own headroom rule); a margin
    below that means either a hand-edited token (bypassed the generator)
    or a broken derivation (the generator stopped enforcing its own
    rule) -- never a legitimate, acceptable state. `_run_gate` asks "is
    this value accessible"; this asks "did this value come from the
    ruled derivation" -- red here means RE-DERIVE OR FIX THE GENERATOR,
    never lower this test's bar."""

    def test_minimum_margin_across_base_and_theme_is_not_dangerously_thin(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        margins = _collect_margins("base", module) + _collect_margins("theme", module)
        if not margins:
            self.skipTest("no gated Base/Theme pairs found yet")
        worst_margin, worst_label = min(margins, key=lambda m: m[0])
        self.assertGreaterEqual(
            worst_margin, MARGIN_EARLY_WARNING_THRESHOLD,
            f"thinnest passing margin is only +{worst_margin:.4f} ({worst_label}) -- below the "
            f"generator's own {MARGIN_EARLY_WARNING_THRESHOLD:g} derivation-headroom rule. This "
            f"is NOT a close call to shrug off and it is NOT a signal to lower this threshold: "
            f"every generator-derived value has >=0.05 margin by construction, so this means "
            f"either a hand-edited token (bypassed gen_variants.py) or the generator's own "
            f"derivation logic no longer enforcing its own headroom. Re-derive the value or fix "
            f"the generator -- do not touch MARGIN_EARLY_WARNING_THRESHOLD.",
        )


class CrossDimensionContrastGateTests(unittest.TestCase):
    """Architect's second-pass correction (05e963e): pairs that span two
    dimensions (e.g. Chart background under Base text on the paused-status
    chip) can never be produced by the within-dimension symmetric
    derivation above -- this walks the SAME-RULE/SAME-CLASS-STRING
    co-occurrence pairs across the cross-product of both dimensions'
    variants instead."""

    def test_no_cross_dimension_co_occurring_pair_is_below_its_floor(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        _run_cross_dimension_gate(self, module)


class NoCrossDimensionCoOccurrenceExistsTests(unittest.TestCase):
    """RETIRED-AND-REPLACED, task #24: this used to be
    `KnownCrossDimensionPairIsDetectedTests`, pinning that `.chip.status
    [data-status="paused"]`'s `background: var(--chart-2)` (Chart) +
    `color: var(--foreground)` (Base) pair -- 1.83:1 dark mode -- was
    findable by the co-occurrence extractor. ux-designer's repointing
    (per architect's ruling 1db6053) moved that rule onto `--accent`/
    `--accent-foreground` (both Base -- same-dimension, not a cross-
    dimension pair), and the same repointing landed in `badge.svelte` and
    `App.svelte`. Re-verified against the real tree: as of this rewrite,
    NO rule in `board.css` and no class-string literal anywhere under
    `dashboard/src` pairs a background token and a foreground token from
    two DIFFERENT dimensions. That is exactly the outcome architect
    predicted ("the co-occurrence disappears from source... the
    derivation notices") and exactly the case they asked to be told about
    ("if none does, tell me... that is itself worth knowing") --
    confirmed via SendMessage, this is that confirmation, made permanent
    as a positive invariant per their own suggestion rather than left as
    an absence nobody asserts on.

    This is a REGRESSION guard, not a red-then-green feature test: it
    should stay green as long as no rule/class-string mixes dimensions on
    one rendered element. If it ever goes red, that's architect's
    `_derive_cross_dimension_pairs` mechanism doing exactly its job --
    resurrect `CrossDimensionContrastGateTests` (already in place above
    and already exercising whatever it finds) as the thing that then
    needs a floor check, and consider naming the newly-reintroduced pair
    here the way this class's predecessor named the paused-chip one."""

    def test_no_rule_or_class_string_pairs_tokens_across_dimensions(self):
        board_css_source = BOARD_CSS.read_text(encoding="utf-8") if BOARD_CSS.is_file() else ""
        dashboard_parts = []
        if DASHBOARD_SRC.is_dir():
            dashboard_parts = [
                p.read_text(encoding="utf-8")
                for p in DASHBOARD_SRC.rglob("*")
                if p.is_file() and p.suffix in (".svelte", ".ts")
            ]
        dashboard_haystack = "\n".join(dashboard_parts)
        cross_pairs = _derive_cross_dimension_pairs(board_css_source, dashboard_haystack)
        self.assertEqual(
            cross_pairs, [],
            f"found cross-dimension co-occurring pair(s) {cross_pairs} -- a text-bearing "
            f"surface is drawing its fill from a dimension unrelated to that surface's "
            f"legibility (the exact defect class architect's ruling 1db6053 fixed for the "
            f"paused-status chip). Per that ruling, the fix is to REPOINT the consuming rule/"
            f"component onto a same-dimension (or mode-inverting) token, not to gate contrast "
            f"across the two dimensions.",
        )

    def test_chart_2_specifically_no_longer_pairs_with_a_base_foreground(self):
        # Narrower, named check for the EXACT historical regression --
        # independent of the general invariant above, same "dedicated
        # test for a specific past violation" shape as the dead-sidebar-
        # primary and --ring tests.
        self.assertTrue(BOARD_CSS.is_file(), f"{BOARD_CSS} does not exist")
        source = BOARD_CSS.read_text(encoding="utf-8")
        pairs = _css_rule_co_occurring_pairs(source)
        self.assertNotIn(
            ("--foreground", "--chart-2"), pairs,
            "board.css still pairs --foreground with --chart-2 in one rule -- the paused-chip "
            "repointing (ruling 1db6053) appears to have regressed.",
        )


class DeadSidebarPrimaryPairIsExcludedTests(unittest.TestCase):
    """Names the exact regression the ruling is about: `--sidebar-primary`/
    `--sidebar-primary-foreground` must be auto-excluded by the usage
    derivation (not gated, not silently passing a fabricated check) --
    independent of, and narrower than, the general dead-pair mechanism, so
    THIS SPECIFIC token pair has its own named test."""

    def test_sidebar_primary_pair_is_excluded_as_dead_not_gated(self):
        board_css_source = BOARD_CSS.read_text(encoding="utf-8") if BOARD_CSS.is_file() else ""
        dashboard_parts = []
        if DASHBOARD_SRC.is_dir():
            dashboard_parts = [
                p.read_text(encoding="utf-8")
                for p in DASHBOARD_SRC.rglob("*")
                if p.is_file() and p.suffix in (".svelte", ".ts")
            ]
        dashboard_haystack = "\n".join(dashboard_parts)
        gated, dead, _held = _derive_gated_pairs("theme", board_css_source, dashboard_haystack)
        gated_names = {(fg, bg) for fg, bg, _floor, _role in gated}
        self.assertNotIn(
            ("--sidebar-primary-foreground", "--sidebar-primary"), gated_names,
            "the usage derivation is gating --sidebar-primary-foreground/--sidebar-primary, but "
            "architect verified zero references to either token anywhere outside the three "
            "token-declaration files -- this pair must be excluded as dead, not asserted on.",
        )
        self.assertIn(
            ("--sidebar-primary-foreground", "--sidebar-primary"), dead,
            "expected --sidebar-primary-foreground/--sidebar-primary to be classified DEAD by "
            "the derivation (both sides unreferenced) -- if this now fails, either the tokens "
            "have been wired up for real (great -- move this pair back into the gate) or the "
            "derivation's liveness check has a false negative.",
        )


class RingPartitionRegressionTests(unittest.TestCase):
    """Unchanged from the original version of this file -- architect asked
    to keep this exactly as-is. The exact, named violation architect's
    first addendum caught by hand: `--ring`/`--sidebar-ring` must NOT
    appear in any Theme-dimension block (they're Base neutrals)."""

    def test_ring_and_sidebar_ring_are_not_declared_under_any_theme_block(self):
        if not BOARD_VARIANTS_CSS.is_file():
            self.skipTest(f"{BOARD_VARIANTS_CSS} does not exist yet")
        source = BOARD_VARIANTS_CSS.read_text(encoding="utf-8")
        offenders = []
        for dim, name, is_dark, body in _find_variant_blocks(source):
            if dim != "theme":
                continue
            found = set(re.findall(r"(--[\w-]+)\s*:", body))
            leaked = found & {"--ring", "--sidebar-ring"}
            if leaked:
                offenders.append((name, "dark" if is_dark else "light", sorted(leaked)))
        self.assertEqual(
            offenders, [],
            f"--ring/--sidebar-ring found under a Theme-dimension block: {offenders} -- "
            f"architect's addendum: these are Base neutrals (chroma ~0.01 at hue ~57, the "
            f"stone neutral hue), not the Theme accent. This is the exact partition violation "
            f"caught by hand before implementation started; it must not recur.",
        )


class CrossDimensionExtractionSelfTests(unittest.TestCase):
    """Proves the co-occurrence extractor CAN find a cross-dimension pair
    (and CAN'T manufacture one that isn't there / isn't cross-dimension)
    against synthetic input."""

    def test_css_rule_extractor_finds_a_same_rule_bg_fg_pair(self):
        css = '.chip.status[data-status="paused"] { background: var(--chart-2); color: var(--foreground); }'
        pairs = _css_rule_co_occurring_pairs(css)
        self.assertIn(("--foreground", "--chart-2"), pairs)

    def test_css_rule_extractor_ignores_a_rule_with_only_one_of_the_two(self):
        css = ".foo { background: var(--chart-2); }"  # no color: decl at all
        pairs = _css_rule_co_occurring_pairs(css)
        self.assertEqual(pairs, set())

    def test_css_rule_extractor_does_not_confuse_border_color_with_color(self):
        css = ".foo { border-color: var(--border); background: var(--card); color: var(--card-foreground); }"
        pairs = _css_rule_co_occurring_pairs(css)
        # Must pick up the real color:/background: pair, and must NOT
        # treat border-color's --border as the foreground.
        self.assertIn(("--card-foreground", "--card"), pairs)
        self.assertNotIn(("--border", "--card"), pairs)

    def test_class_string_extractor_finds_a_same_string_bg_text_pair(self):
        html = '<div class="bg-destructive text-destructive-foreground">x</div>'
        pairs = _class_string_co_occurring_pairs(html)
        self.assertIn(("--destructive-foreground", "--destructive"), pairs)

    def test_class_string_extractor_tolerates_modifier_prefixes(self):
        html = '<div class="dark:bg-muted hover:text-muted-foreground">x</div>'
        pairs = _class_string_co_occurring_pairs(html)
        self.assertIn(("--muted-foreground", "--muted"), pairs)

    def test_derive_cross_dimension_pairs_drops_same_dimension_co_occurrence(self):
        css = ".foo { background: var(--muted); color: var(--muted-foreground); }"  # both Base
        cross = _derive_cross_dimension_pairs(css, "")
        self.assertEqual(cross, [])  # same-dimension -- not this mechanism's job

    def test_derive_cross_dimension_pairs_keeps_a_real_cross_dimension_pair(self):
        css = '.chip.status[data-status="paused"] { background: var(--chart-2); color: var(--foreground); }'
        cross = _derive_cross_dimension_pairs(css, "")
        self.assertEqual(cross, [("--foreground", "--chart-2", "base", "chart")])

    def test_token_dimension_returns_none_for_an_unowned_var(self):
        # --radius is a sizing token, not owned by any of the three
        # base/theme/chart color dimensions this file classifies.
        self.assertIsNone(_token_dimension("--radius"))


class UsageDerivationSelfTests(unittest.TestCase):
    """Proves the derivation/role/liveness machinery CAN produce every
    outcome it claims to (dead-pair exclusion, text-role floor, graphical-
    role floor, pending-confirmation carve-out) against synthetic input --
    not just that real files currently behave a particular way."""

    def test_derive_natural_pairs_includes_foreground_background_and_x_pairs(self):
        owned = frozenset({"--foreground", "--background", "--card", "--card-foreground"})
        pairs = set(_derive_natural_pairs(owned))
        self.assertIn(("--foreground", "--background"), pairs)
        self.assertIn(("--card-foreground", "--card"), pairs)

    def test_derive_natural_pairs_skips_a_foreground_var_with_no_owned_counterpart(self):
        owned = frozenset({"--weird-foreground"})  # "--weird" not owned
        pairs = _derive_natural_pairs(owned)
        self.assertEqual(pairs, [])

    def test_token_role_returns_none_for_a_token_referenced_nowhere(self):
        floor, role = _token_role("--totally-unused-token", "body { color: red; }", "<div>hi</div>")
        self.assertIsNone(floor)
        self.assertIsNone(role)

    def test_token_role_prefers_text_over_graphical_when_both_present(self):
        board_css = "a { color: var(--muted-foreground); } b { background: var(--muted-foreground); }"
        floor, role = _token_role("--muted-foreground", board_css, "")
        self.assertEqual(floor, WCAG_NORMAL_TEXT)
        self.assertEqual(role, "text")

    def test_token_role_is_graphical_when_only_a_fill_usage_is_found(self):
        floor, role = _token_role("--muted-foreground", "b { background: var(--muted-foreground); }", "")
        self.assertEqual(floor, WCAG_LARGE_TEXT_OR_GRAPHICAL)
        self.assertEqual(role, "graphical fill")

    def test_token_role_detects_dashboard_tailwind_classes(self):
        floor, role = _token_role("--muted-foreground", "", '<p class="text-muted-foreground">x</p>')
        self.assertEqual(floor, WCAG_NORMAL_TEXT)
        floor2, role2 = _token_role("--muted-foreground", "", '<div class="bg-muted-foreground"></div>')
        self.assertEqual(floor2, WCAG_LARGE_TEXT_OR_GRAPHICAL)

    def test_a_pair_with_one_dead_side_is_excluded(self):
        # fg is referenced, but bg never is -- pair must still be dead.
        board_css = "a { color: var(--x-foreground); }"
        gated, dead, held = _derive_gated_pairs(
            "base", board_css, ""
        )
        # Using the real BASE_OWNED set for this one so --x isn't a
        # candidate at all; instead prove the mechanism directly:
        floor, _role = _token_role("--x-foreground", board_css, "")
        self.assertIsNotNone(floor)
        self.assertFalse(_token_referenced_at_all("--x", board_css, ""))

    def test_pending_browser_confirmation_pairs_are_never_gated(self):
        board_css = "a { color: var(--foreground); } b { background: var(--background); }"
        gated, dead, held = _derive_gated_pairs("base", board_css, "")
        gated_names = {(fg, bg) for fg, bg, _f, _r in gated}
        self.assertNotIn(("--foreground", "--background"), gated_names)
        self.assertIn(("--foreground", "--background"), held)


class ContrastGateHelperSelfTests(unittest.TestCase):
    def test_a_genuinely_low_contrast_pair_is_caught(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        light_gray = (0.6, 0.0, 0.0)
        slightly_darker_gray = (0.58, 0.0, 0.0)
        fg_hex = _oklch_to_hex(*light_gray, module.lin2s)
        bg_hex = _oklch_to_hex(*slightly_darker_gray, module.lin2s)
        ratio = module.contrast(fg_hex, bg_hex)
        self.assertLess(ratio, WCAG_NORMAL_TEXT)

    def test_black_on_white_clears_the_floor(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        ratio = module.contrast("#000000", "#ffffff")
        self.assertGreaterEqual(ratio, WCAG_NORMAL_TEXT)


class DualModelContrastSelfTests(unittest.TestCase):
    """Architect's ruling (4e0e678): a guard sharing its color bridge with
    the thing it guards can only certify what that bridge likes. Proves
    `_dual_model_contrast` actually uses TWO independent computations
    (not the same one twice under different names), and that its MIN-based
    gate genuinely catches a value straddling the floor -- exactly the
    real shape found in this feature (dark destructive ink: 4.4955 float /
    4.5268 quantized, the 4.5 floor sitting inside that 0.03 gap)."""

    def test_quantized_and_float_are_not_the_same_computation(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        # A value chosen to actually straddle in this codebase (verified
        # against the real board/tokens.css dark --destructive pairing
        # while this gate was being built) -- if these two ever come back
        # numerically identical, the "float" path has been accidentally
        # wired to reuse the quantized one, which is precisely the bug
        # this ruling exists to prevent recurring.
        fg = (0.2985, 0.01, 17.0)
        bg = (0.704, 0.191, 22.216)
        _min_ratio, quantized, float_ratio = _dual_model_contrast(fg, bg, module)
        self.assertNotEqual(
            round(quantized, 6), round(float_ratio, 6),
            "quantized and float contrast came back identical -- the two models must be "
            "independently computed (one round-tripping through 8-bit hex, one not), or this "
            "check can no longer catch a straddling value the way it's supposed to.",
        )

    def test_min_based_gate_fails_when_only_the_float_model_misses_the_floor(self):
        module = _find_validator_module()
        if module is None:
            self.skipTest("dataviz validate_palette.py not found on this harness")
        # Search a small neighborhood for a real straddling case in THIS
        # OKLCH bridge, rather than asserting on a hardcoded pair that
        # might not straddle under a future matrix/rounding tweak --
        # mirrors this suite's "don't hardcode which base is extremal"
        # discipline elsewhere (test_chart_variant_ramps.py).
        bg = (0.704, 0.191, 22.216)  # dark --destructive, fixed
        straddle_found = False
        for tenth_milli in range(2500, 3500):  # L from 0.2500 to 0.3499, 0.0001 steps
            fg = (tenth_milli / 10000.0, 0.01, 17.0)
            min_ratio, quantized, float_ratio = _dual_model_contrast(fg, bg, module)
            if float_ratio < WCAG_NORMAL_TEXT <= quantized:
                straddle_found = True
                self.assertLess(
                    min_ratio, WCAG_NORMAL_TEXT,
                    f"found a straddling L={fg[0]} (quantized {quantized:.4f} passes, float "
                    f"{float_ratio:.4f} fails) but the min-based ratio didn't fail -- the gate "
                    f"must reject on either model alone missing the floor.",
                )
                break
        self.assertTrue(
            straddle_found,
            "could not find ANY L in [0.2500, 0.3499] (0.0001 steps) where quantized clears "
            "4.5 and float doesn't -- either this OKLCH bridge no longer straddles here (fine, "
            "but update this test's search range so it still proves the mechanism) or "
            "something about the two models changed.",
        )

    def test_relative_luminance_linear_matches_the_quantized_paths_formula_shape(self):
        # Same WCAG weights (0.2126/0.7152/0.0722), just applied to
        # un-rounded linear values -- sanity-checks the constant isn't a
        # typo'd duplicate of some other weighting.
        self.assertAlmostEqual(_relative_luminance_linear((1.0, 1.0, 1.0)), 1.0, places=6)
        self.assertAlmostEqual(_relative_luminance_linear((0.0, 0.0, 0.0)), 0.0, places=6)

    def test_oklch_to_linear_rgb_clamped_stays_within_0_and_1(self):
        # An extreme/out-of-gamut OKLCH input shouldn't produce a
        # negative or >1 channel -- clamped like the quantized path's
        # `lin2s` clamps, just without the integer rounding.
        r, g, b = _oklch_to_linear_rgb_clamped(0.5, 0.5, 30.0)  # very high chroma
        for channel in (r, g, b):
            self.assertGreaterEqual(channel, 0.0)
            self.assertLessEqual(channel, 1.0)


if __name__ == "__main__":
    unittest.main()
