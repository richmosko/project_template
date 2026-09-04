"""palette_check.py — stdlib-only categorical-palette validator (PT-79).

Drop-in for `scripts/cairn/tests/palette_check.py`. Written by the architect
so the role-palette guard NEVER SKIPS: the external dataviz skill script is
unreachable on some harnesses, and a skipping guard is indistinguishable from
a passing one in a green run. The ordinal (`--chart-flow-*`) ramp test keeps
using the external script as today; this module covers only the categorical
role palette.

Two checks, exactly the ones the architect ran independently against
ux-designer's hand-computed table on 2026-09-04 (11/11 hex values and 22/22
contrast figures reproduced exactly):

1. WCAG contrast >= 2:1 for every role/guard token against **each mode's own
   real `--card` surface**, both parsed from the same `app.css` under test --
   never a hardcoded surface, because the point of the guard is to catch a
   later edit to either side.
2. Minimum pairwise OKLab dE >= 0.06 among the eight role hues. This is the
   CATEGORICAL criterion; do NOT substitute the ordinal validator's monotone
   -lightness check, which is meaningless for unordered categories and would
   make roles look ranked.

Deliberately NOT covered: CVD/deuteranopia simulation. That stays a
design-time check documented in `docs/DESIGN/design-system-spec.md` -- it
needs simulation matrices, and reimplementing them here would be a second
unverified implementation checking a second unverified implementation.

No third-party imports. No network.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Tuple

# Both thresholds are the ruling's, not this module's to soften.
CONTRAST_FLOOR = 2.0
MIN_PAIRWISE_DELTA_E = 0.06
ROLE_TOKEN_COUNT = 8

_OKLCH_RE = re.compile(
    r"--(?P<name>[a-z0-9-]+)\s*:\s*oklch\(\s*"
    r"(?P<l>[0-9.]+)\s+(?P<c>[0-9.]+)\s+(?P<h>[0-9.]+)\s*\)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Colour maths (OKLCH -> OKLab -> linear sRGB -> WCAG relative luminance)
# --------------------------------------------------------------------------
def oklch_to_oklab(l: float, c: float, h_deg: float) -> Tuple[float, float, float]:
    h = math.radians(h_deg)
    return (l, c * math.cos(h), c * math.sin(h))


def oklch_to_linear_srgb(l: float, c: float, h_deg: float) -> Tuple[float, float, float]:
    """Clamped to the sRGB gamut, which is what a browser renders and
    therefore what a contrast figure must be computed from."""
    _, a, b = oklch_to_oklab(l, c, h_deg)
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    lc, mc, sc = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc
    g = -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc
    bl = -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc
    return tuple(min(1.0, max(0.0, v)) for v in (r, g, bl))  # type: ignore[return-value]


def linear_to_hex(lin: Tuple[float, float, float]) -> str:
    def encode(v: float) -> float:
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055

    return "#" + "".join("%02x" % round(255 * min(1.0, max(0.0, encode(v)))) for v in lin)


def relative_luminance(lin: Tuple[float, float, float]) -> float:
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def oklab_delta_e(t1: Tuple[float, float, float], t2: Tuple[float, float, float]) -> float:
    """Euclidean distance in OKLab. ~0.02 is the rule-of-thumb JND."""
    return math.dist(oklch_to_oklab(*t1), oklch_to_oklab(*t2))


# --------------------------------------------------------------------------
# Parsing -- values come from the CSS under test, never a snapshot
# --------------------------------------------------------------------------
def parse_oklch_tokens(css_text: str) -> List[Tuple[str, Tuple[float, float, float], int]]:
    """[(token_name, (L, C, H), char_offset)] for every `--x: oklch(...)`.
    Offset is kept so `--card` can be attributed to the right mode block."""
    out = []
    for m in _OKLCH_RE.finditer(css_text):
        out.append((m.group("name"), (float(m.group("l")), float(m.group("c")), float(m.group("h"))), m.start()))
    return out


def card_surfaces(css_text: str) -> Dict[str, Tuple[float, float, float]]:
    """The real `--card` for each mode: the first `--card` is `:root`
    (light), the one inside/after the `.dark` block is dark mode. Raises if
    either is missing -- a guard that silently drops a surface is the failure
    this module exists to prevent."""
    cards = [(name, v, off) for name, v, off in parse_oklch_tokens(css_text) if name == "card"]
    if len(cards) < 2:
        raise ValueError(f"expected two --card definitions (light + .dark), found {len(cards)}")
    dark_at = css_text.find(".dark")
    if dark_at < 0:
        raise ValueError("no .dark block found in the CSS under test")
    light = [c for c in cards if c[2] < dark_at]
    dark = [c for c in cards if c[2] > dark_at]
    if not light or not dark:
        raise ValueError("could not attribute --card definitions to light and dark blocks")
    return {"light": light[0][1], "dark": dark[0][1]}


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------
def check_role_palette(css_text: str) -> List[str]:
    """Returns a list of failure strings; empty means pass. Never raises for
    a colour problem -- only for a structural one (missing tokens/surfaces),
    which is itself a failure worth surfacing loudly."""
    failures: List[str] = []
    tokens = {name: v for name, v, _ in parse_oklch_tokens(css_text)}
    surfaces = card_surfaces(css_text)

    role_names = [f"chart-role-{i}" for i in range(1, ROLE_TOKEN_COUNT + 1)]
    guard_names = ["chart-role-guard-aux", "chart-role-guard-unattributed", "chart-role-other"]

    missing = [n for n in role_names + guard_names if n not in tokens]
    if missing:
        failures.append(f"missing token(s): {missing}")
        return failures  # nothing further is meaningful

    # 1. contrast against each mode's own real --card
    for name in role_names + guard_names:
        lin = oklch_to_linear_srgb(*tokens[name])
        for mode, surface in surfaces.items():
            ratio = contrast_ratio(lin, oklch_to_linear_srgb(*surface))
            if ratio < CONTRAST_FLOOR:
                failures.append(
                    f"--{name} ({linear_to_hex(lin)}) is {ratio:.2f}:1 against the {mode} --card "
                    f"-- below the {CONTRAST_FLOOR}:1 floor"
                )

    # 2. categorical separation among the eight role hues
    for i in range(len(role_names)):
        for j in range(i + 1, len(role_names)):
            a, b = role_names[i], role_names[j]
            d = oklab_delta_e(tokens[a], tokens[b])
            if d < MIN_PAIRWISE_DELTA_E:
                failures.append(
                    f"--{a} and --{b} are only dE_OK {d:.3f} apart "
                    f"-- below the {MIN_PAIRWISE_DELTA_E} categorical floor"
                )
    return failures


def summarize(css_text: str) -> str:
    """Human-readable report; handy in a test failure message."""
    tokens = {name: v for name, v, _ in parse_oklch_tokens(css_text)}
    surfaces = card_surfaces(css_text)
    lines = []
    for i in range(1, ROLE_TOKEN_COUNT + 1):
        name = f"chart-role-{i}"
        if name not in tokens:
            continue
        lin = oklch_to_linear_srgb(*tokens[name])
        lines.append(
            "  --%s %s  light %.2f:1  dark %.2f:1"
            % (
                name,
                linear_to_hex(lin),
                contrast_ratio(lin, oklch_to_linear_srgb(*surfaces["light"])),
                contrast_ratio(lin, oklch_to_linear_srgb(*surfaces["dark"])),
            )
        )
    return "\n".join(lines)
