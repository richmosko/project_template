"""PT-60 failing acceptance tests: dashboard polish items #3 (Skeleton at
fetch boundaries) and #4 (aria-live on the loading badge).

Source-text guards against App.svelte, in the established shape for this
codebase's Svelte-source checks (test_board_fonts.py's @font-face/CSS
guards, test_dashboard_board_embed.py's iframe guards): deliberately
STRUCTURAL, not visual -- confirms the Skeleton primitive is actually
wired at the three named fetch boundaries (status cards, roster, tracker
table) and that the loading badge is announced to assistive tech, never
whether it LOOKS right mid-load. That's the browser pass's job (team-lead's
own framing on this anchor).

Nothing under test exists yet: App.svelte has no Skeleton import, no
`<Skeleton` usage anywhere, and the loading Badge has no `aria-live`.
Every test below is expected to fail on a genuinely-absent substring --
never an import error.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"


def _read_app_svelte() -> str:
    return DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")


class SkeletonAtFetchBoundariesTests(unittest.TestCase):
    def test_skeleton_component_is_imported(self):
        source = _read_app_svelte()
        match = re.search(r"from\s+['\"]\$lib/components/ui/skeleton", source)
        self.assertIsNotNone(
            match,
            "App.svelte does not import the shadcn-svelte Skeleton component "
            "(design-system-spec.md: 'every list/board fetch should render a skeleton "
            "shaped like the real card/row/table it's replacing')",
        )

    def test_skeleton_is_actually_used_at_multiple_fetch_boundaries(self):
        # Not pinning exact placement/composition (implementer judgment,
        # per the spec's own "shaped like the real card/row/table" --
        # different shapes at each boundary) -- but the anchor names
        # THREE boundaries explicitly (status cards, roster, tracker
        # table) while /api/dashboard//api/roster are in flight, so a
        # single decorative <Skeleton/> somewhere isn't the claim.
        source = _read_app_svelte()
        usages = re.findall(r"<Skeleton\b", source)
        self.assertGreaterEqual(
            len(usages), 3,
            f"expected <Skeleton> used at least 3 times (status cards + roster + tracker "
            f"table fetch boundaries), found {len(usages)}",
        )

    def test_the_old_bare_loading_text_paragraphs_are_replaced(self):
        # Regression-guard-shaped: the roster section's plain "Loading…"
        # <p> (a spinner-adjacent, non-skeleton loading state) is exactly
        # what this item retires -- "honest loading, not spinners" per
        # the anchor. Its disappearance is a weak but real signal the
        # Skeleton swap actually reached this specific boundary, not just
        # some other part of the page.
        source = _read_app_svelte()
        match = re.search(r'<p[^>]*>\s*Loading…\s*</p>', source)
        self.assertIsNone(
            match,
            f"a bare 'Loading…' <p> paragraph is still present ({match.group(0) if match else None!r}) "
            f"-- Skeleton components should replace this loading state, not sit alongside it",
        )


class LoadingBadgeAriaLiveTests(unittest.TestCase):
    def test_loading_badge_has_aria_live(self):
        # Architect's PT-54 forward note: the header's Badge cycles
        # through Loading… / branch-state / unreachable text as the
        # payload resolves -- without aria-live, a screen reader never
        # announces that change at all (a Badge isn't a live region by
        # default).
        source = _read_app_svelte()
        # Scoped to the header's own Badge cluster (Loading…/branch-state/
        # unreachable), not a whole-file substring check -- the claim is
        # "the loading badge has aria-live on it", not "aria-live exists
        # somewhere in the file" (which could pass by accident via an
        # unrelated component).
        self.assertIn("</header>", source, "expected a <header> section in App.svelte")
        header_section = source[: source.find("</header>")]
        match = re.search(r"aria-live", header_section)
        self.assertIsNotNone(
            match,
            "the header's status Badge cluster (Loading…/branch-state/unreachable) has no "
            "aria-live attribute anywhere in it -- a screen reader never announces the "
            "loading-to-loaded transition",
        )


if __name__ == "__main__":
    unittest.main()
