"""PT-64 mechanical face-floor guard, broadened per Mosko's 2026-08-28
ruling ("extend option (a) to `.chip`... qa's guard broadens from
label-only to the full mechanical sub-13px enumeration").

History: this file started as a label-only guard (`.filters label`,
`.drawer-field label`) matching the FIRST narrowed ruling. A follow-up
computed-style read (team-lead, browser) found the chip exemption in that
ruling was a sampling artifact -- `.chip` has no font-family override at
all, and its actual face is PLACEMENT-DEPENDENT: chips inside
`.swimlane-header` inherit that ancestor's `--font-heading` (sans), chips
inside `.card-meta` (the bulk of board chips) inherit body's serif. Mosko
re-ruled: extend (a) to `.chip` itself, and broaden this guard to the
literal AC text -- "the sub-13px selector set ... enumerated mechanically
(every selector under 13px)" -- not just labels.

Because a source-level guard cannot see actual DOM placement (that's
exactly the gap the browser read closed), it can't ask "what does this
selector compute to in context X". What it CAN do, and what actually
matches the fix this ruling calls for, is ask a placement-INDEPENDENT
question: does this selector's OWN CSS rule (composed with whatever more
general rules target a subset of its own classes -- e.g. bare `.chip` for
`.chip.assignee`) explicitly declare a non-serif font-family? That is
precisely what "give `.chip` an explicit override so it no longer depends
on placement" means, and it's what makes this guard a real regression
fence rather than a snapshot of today's fix: a future variant added under
`.chip.*` without touching the base rule's font-family, or a brand new
sub-13px selector anywhere in the file, goes red the same way.

Two resolution strategies, chosen mechanically per selector shape (see
`_read_board_css` module docstring notes inline):

- CLASS-ONLY selectors (no combinator/whitespace, e.g. `.chip`,
  `.chip.repo`, `.chip.status[data-status="..."]`, `.connection-state`,
  `.swimlane-toggle`): resolved by composing every class-only rule in the
  file whose class set is a SUBSET of the target's own classes, least-
  specific first (mirrors how `.chip.assignee` picks up `.chip`'s
  font-family when it doesn't declare its own) -- this is what makes the
  guard already-passing the moment `.chip` gets the fix, without this
  file hardcoding each variant.
- Everything else (descendant/combinator selectors like `.filters label`,
  `table.issue-list th`, `.drawer .drawer-id`) is resolved from its own
  rule's declarations only (merged across any other rule sharing the
  exact same selector text, e.g. `table.issue-list th` is declared once
  in a comma group at 13px and again alone at 12px -- the second wins).
  No cross-selector inheritance is modeled here; a selector in this
  category with no font-family declared is treated as unresolved (fail),
  same posture as this file's original label-only version.

`var(--font-mono)` counts as PASSING alongside `var(--font-heading)` --
deliberately, not a silent regex accident: the face-floor rule is "not
serif/UA-default below 13px", not "must literally be Space Grotesk", and
`.chip.repo`'s existing mono override (the repo chip) is meant to keep
its monospace face rather than being forced sans. See ALLOWED_NON_SERIF_
FAMILIES below.

`font-family: inherit` (`.swimlane-toggle`, `.repo-group-toggle`) counts
as FAILING, deliberately, not an oversight: Mosko's final ruling (PT-64,
2026-08-28, "full face floor") confirmed via live browser read that both
currently DO compute Space Grotesk (they sit inside their section's
`--font-heading`-scoped header), but chose to require an EXPLICIT
`var(--font-heading)` on both rules anyway rather than have this guard
special-case "trust inherit when the parent scope is provable from
source" -- that's the same sampling-trap shape that produced the original
(wrong) chip exemption, and an explicit declaration keeps both rules
placement-independent the same way the `.chip` fix does. If a future
edit moves either element out of its sans-scoped header, an `inherit`-
based pass here would silently stop being true; an explicit declaration
can't.

Nothing under test exists yet for the newly-broadened set: `.chip` (and
every non-`.repo` variant that inherits its missing font-family), the two
`inherit`-based toggles above, and the twelve additional non-chip/non-
label selectors this enumeration reaches (`.connection-state` incl. its
`.live` variant, `.major-tab-open`, `.view-state-btn`, `table.issue-list
th`, `.comment-meta`, `.pr-link`/`.file-link`/`.parent-link`,
`.drawer-progress`, `.record-readonly-note`) all fail. The two label
selectors from the original guard are expected to stay green (fixed in
the same PR that reopened this scope). Every failure is expected to be a
genuinely-unresolved font-family, never an import error.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"

RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
FONT_SIZE_PX_RE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px")
FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;]+);")

# Deliberate, explicit allowlist -- not a "missing means pass" accident.
# --font-heading (Space Grotesk) is the ruled sans face; --font-mono
# (Geist Mono) is exempted because monospace isn't the serif-legibility
# risk the ruling is about (see .chip.repo).
ALLOWED_NON_SERIF_FAMILIES = {"var(--font-heading)", "var(--font-mono)"}

# A selector is "class-only" if it's nothing but one or more `.class`
# tokens (optionally with a trailing attribute selector) -- no element
# type, no whitespace/combinator. `.chip.status[data-status="x"]`
# qualifies; `.filters label` and `table.issue-list th` do not.
CLASS_ONLY_RE = re.compile(r"^(?:\.[\w-]+)+(?:\[[^\]]*\])?$")
CLASS_TOKEN_RE = re.compile(r"\.[\w-]+")


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _read_board_css() -> str:
    return BOARD_CSS.read_text(encoding="utf-8")


def _split_top_level_commas(selector_group: str):
    # No parens/brackets in this file's selector lists ever contain a
    # comma, so a plain split is safe and avoids pulling in a real CSS
    # selector parser for a one-file test guard.
    return [s.strip() for s in selector_group.split(",") if s.strip()]


def _extract_own_props(decls: str):
    props = {}
    size_match = FONT_SIZE_PX_RE.search(decls)
    if size_match:
        props["font-size"] = float(size_match.group(1))
    family_match = FONT_FAMILY_RE.search(decls)
    if family_match:
        props["font-family"] = family_match.group(1).strip()
    return props


def _extract_classes(selector: str) -> frozenset:
    without_attrs = re.sub(r"\[[^\]]*\]", "", selector)
    return frozenset(CLASS_TOKEN_RE.findall(without_attrs))


class _BoardCssModel:
    """Parses board.css once and exposes, for every individual selector
    in the file, the resolved (own-rule-or-composed) font-size/font-family
    pair used by the face-floor check. See module docstring for the two
    resolution strategies."""

    def __init__(self, css_source: str):
        stripped = _strip_css_comments(css_source)
        occurrences = []  # (selector, decls, order_idx)
        for order_idx, (selector_group, decls) in enumerate(RULE_RE.findall(stripped)):
            for selector in _split_top_level_commas(selector_group):
                occurrences.append((selector, decls, order_idx))

        # Exact-selector-text merge: later occurrence of the SAME selector
        # text wins per-property (handles e.g. `table.issue-list th`
        # being declared once in a comma group and again alone).
        self._exact_merged: dict[str, dict] = {}
        self._first_order_idx: dict[str, int] = {}
        for selector, decls, order_idx in sorted(occurrences, key=lambda t: t[2]):
            merged = self._exact_merged.setdefault(selector, {})
            merged.update(_extract_own_props(decls))
            self._first_order_idx.setdefault(selector, order_idx)

        self._class_only_selectors = [
            s for s in self._exact_merged if CLASS_ONLY_RE.match(s)
        ]

    def all_selectors(self):
        return list(self._exact_merged.keys())

    def resolve(self, selector: str) -> dict:
        if CLASS_ONLY_RE.match(selector):
            target_classes = _extract_classes(selector)
            applicable = [
                s for s in self._class_only_selectors
                if _extract_classes(s) <= target_classes
            ]
            applicable.sort(
                key=lambda s: (len(_extract_classes(s)), self._first_order_idx[s])
            )
            resolved: dict = {}
            for s in applicable:
                resolved.update(self._exact_merged[s])
            return resolved
        return dict(self._exact_merged.get(selector, {}))


def _sub_13px_selectors(model: "_BoardCssModel"):
    """Every selector in board.css whose RESOLVED font-size is under
    13px, paired with its resolved font-family (may be absent)."""
    found = []
    for selector in model.all_selectors():
        resolved = model.resolve(selector)
        size = resolved.get("font-size")
        if size is not None and size < 13:
            found.append((selector, resolved.get("font-family")))
    return found


class SubThirteenPixelFaceFloorTests(unittest.TestCase):
    def test_mechanical_enumeration_still_finds_the_label_selectors(self):
        # Regression guard on the enumeration itself (carried over from
        # this file's label-only predecessor).
        model = _BoardCssModel(_read_board_css())
        selectors = {sel for sel, _family in _sub_13px_selectors(model)}
        self.assertIn(".filters label", selectors, f"enumeration missed .filters label; found {selectors}")
        self.assertIn(".drawer-field label", selectors, f"enumeration missed .drawer-field label; found {selectors}")

    def test_mechanical_enumeration_finds_the_chip_family(self):
        # Same sanity check, extended to the newly-ruled-in-scope chip
        # selectors -- confirms the class-subset composition actually
        # reaches `.chip` and its variants, not just class-only selectors
        # with no siblings.
        model = _BoardCssModel(_read_board_css())
        selectors = {sel for sel, _family in _sub_13px_selectors(model)}
        self.assertIn(".chip", selectors, f"enumeration missed bare .chip; found {selectors}")
        self.assertIn(".chip.repo", selectors, f"enumeration missed .chip.repo; found {selectors}")

    def test_every_sub_13px_selector_resolves_to_a_non_serif_face(self):
        # The face-floor rule itself, over the FULL mechanical
        # enumeration (every selector under 13px in board.css, not just
        # labels) -- per the AC's literal wording and Mosko's 2026-08-28
        # ruling extending option (a) to `.chip`.
        model = _BoardCssModel(_read_board_css())
        rows = _sub_13px_selectors(model)
        self.assertTrue(rows, "mechanical enumeration found no sub-13px selectors to check")
        offenders = sorted(
            sel for sel, family in rows
            if family not in ALLOWED_NON_SERIF_FAMILIES
        )
        self.assertEqual(
            offenders, [],
            f"the following sub-13px selectors in board.css do not resolve to an "
            f"allowed non-serif face ({sorted(ALLOWED_NON_SERIF_FAMILIES)}), so they "
            f"render in the serif (body's inherited var(--font-sans) == Merriweather, "
            f"or an unresolved `inherit`): {offenders}",
        )

    def test_chip_repo_mono_override_is_deliberately_exempted(self):
        # Encodes the "mono passes too" carve-out as its own assertion,
        # not just a side effect of the allowlist above -- if a future
        # edit narrows ALLOWED_NON_SERIF_FAMILIES to heading-only, this
        # is the test that should go red and force a deliberate decision
        # about .chip.repo, rather than silently flipping it to fail.
        model = _BoardCssModel(_read_board_css())
        resolved = model.resolve(".chip.repo")
        self.assertEqual(resolved.get("font-family"), "var(--font-mono)")
        self.assertIn("var(--font-mono)", ALLOWED_NON_SERIF_FAMILIES)


if __name__ == "__main__":
    unittest.main()
