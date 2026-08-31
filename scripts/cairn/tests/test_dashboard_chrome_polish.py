"""PT-73 guard (Mosko's chrome-polish findings, 2026-08-30/31, issue
thread) -- two small dashboard-chrome fixes, both confirmed absent by
reading App.svelte directly before writing anything below. Both are now
FULLY RULED (ux-designer's picks posted 2026-08-30) -- narrowed from this
file's first draft, which was deliberately tolerant/symmetry-based pending
those picks.

## Finding #1 -- collapsed sidebar shows the full repo name

`Sidebar.Header` (PT-68) is a bare, non-collapse-aware `<div>`:
```
<div class="flex items-center gap-2 px-2 py-1.5">
	<span class="font-heading text-sm font-semibold text-sidebar-foreground">
		{data?.git.repo_name ?? '...'}
	</span>
</div>
```
No icon, and no `group-data-[collapsible=icon]:...` class on the label --
every collapse-aware element in this same `ui/sidebar/` component family
(`sidebar-group-label.svelte`, `sidebar-menu-badge.svelte`, `sidebar-menu-
sub-button.svelte`, ...) uses exactly that class family to hide/shrink
text when the sidebar collapses to its icon rail; the repo header simply
never adopted it, so the full name stays visible collapsed.

**Ruled: `FolderGit2`** -- ux's reasoning: it specifically evokes "which
git repo", where `Box`/`Package` are generic container metaphors, and its
folder-outline silhouette reads as a distinct shape class next to
`LayoutDashboard` (grid) and `Kanban` (column bars) below it. **Named
contingency, not tested here:** ux flagged a possible fallback to `Box` if
a real-rail-size legibility pass finds the branch glyph too fine/busy --
if that swap happens, update `REPO_ICON` below in the same commit, not a
silent test edit.

## Finding #2 -- section width inconsistency

PT-62's own hotfix comment names the exact asymmetry: "the Board section
is deliberately OUTSIDE the max-w-6xl wrapper above... it's the one
section this hotfix exists to give the full viewport to." Confirmed in
source: the "other sections" wrapper (status cards / tracker table / flow
chart / agent roster) is `<div class="mx-auto flex w-full max-w-6xl
flex-col gap-6">`, while `<section aria-label="Board">` carries no such
cap at all, inheriting the outer full-bleed container's width directly.

**Ruled: all sections adopt the Board card's width -- i.e. the "other
sections" wrapper loses its `max-w-6xl` cap** (the Board card isn't
gaining a NEW numeric max-width; it was already uncapped, "the widest
existing section" in ux's own words, so "adopt Board's width" concretely
means matching that already-full-bleed state, not introducing a new
shared value). **Container width only, not content** -- ux's explicit
clarification: the stat-card strip keeps its OWN internal responsive grid
(`grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`) and just spans the wider
unified container (more even spacing between the same 4 cards, not one
card stretched edge-to-edge) -- this file pins that the internal grid
classes survive unchanged, as a regression fence against an over-eager
implementation collapsing that structure while touching the outer wrapper.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

DASHBOARD_APP_SVELTE = helpers.CAIRN_DIR / "dashboard" / "src" / "App.svelte"

REPO_ICON = "FolderGit2"
REPO_ICON_IMPORT_PATH = "folder-git-2"


def _strip_html_comments(source: str) -> str:
    return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)


class RepoHeaderIconTests(unittest.TestCase):
    """Finding #1: the repo header follows the same collapse pattern as
    the nav items -- FolderGit2 on the left, name beside it expanded,
    icon-only collapsed."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))
        header_match = re.search(r"<Sidebar\.Header>(.*?)</Sidebar\.Header>", source, re.DOTALL)
        self.assertIsNotNone(header_match, f"{DASHBOARD_APP_SVELTE}: no <Sidebar.Header>...</Sidebar.Header> block found")
        self.header_block = header_match.group(1)
        self.source = source

    def test_foldergit2_icon_is_imported(self):
        match = re.search(
            r"import\s+" + re.escape(REPO_ICON) + r"\s+from\s+['\"]@lucide/svelte/icons/"
            + re.escape(REPO_ICON_IMPORT_PATH) + r"['\"]",
            self.source,
        )
        self.assertIsNotNone(
            match,
            f"no `import {REPO_ICON} from '@lucide/svelte/icons/{REPO_ICON_IMPORT_PATH}'` found "
            f"in {DASHBOARD_APP_SVELTE} -- ux's ruled pick for the repo header icon.",
        )

    def test_foldergit2_renders_inside_the_sidebar_header(self):
        self.assertIn(
            f"<{REPO_ICON}", self.header_block,
            f"<{REPO_ICON} ... /> doesn't render inside <Sidebar.Header> in "
            f"{DASHBOARD_APP_SVELTE} -- an import alone isn't wiring.",
        )

    def test_the_repo_name_label_participates_in_the_collapse_mechanism(self):
        # Same class family every OTHER collapse-aware element in this
        # sidebar component family uses (sidebar-group-label.svelte,
        # sidebar-menu-badge.svelte, sidebar-menu-sub-button.svelte, ...)
        # -- `group-data-[collapsible=icon]:...`. The repo header's label
        # currently has none of it at all.
        self.assertIn(
            "group-data-[collapsible=icon]", self.header_block,
            f"{DASHBOARD_APP_SVELTE}: the Sidebar.Header block has no "
            f"`group-data-[collapsible=icon]:...` class anywhere -- the repo name label needs "
            f"to hide/shrink on collapse the same way every other sidebar element in this "
            f"component family already does, not stay fully visible.",
        )


class HomeSectionWidthUnificationTests(unittest.TestCase):
    """Finding #2, now fully ruled: the 'other sections' wrapper loses
    its max-w-6xl cap, matching the Board card's already-uncapped,
    full-bleed width -- container only, stat-card grid internals
    untouched."""

    def setUp(self):
        self.assertTrue(DASHBOARD_APP_SVELTE.is_file(), f"{DASHBOARD_APP_SVELTE} does not exist")
        self.source = _strip_html_comments(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))

    def test_other_sections_wrapper_no_longer_caps_at_max_w_6xl(self):
        other_sections_match = re.search(
            r"\{#if !onIssueTracking\}\s*<div class=\"([^\"]*)\"",
            self.source,
        )
        self.assertIsNotNone(
            other_sections_match,
            f"{DASHBOARD_APP_SVELTE}: could not find the 'other sections' wrapper div "
            f"immediately inside the `{{#if !onIssueTracking}}` branch -- this test's "
            f"structural assumption may be stale, not something to silence.",
        )
        self.assertNotIn(
            "max-w-6xl", other_sections_match.group(1),
            f"{DASHBOARD_APP_SVELTE}: the 'other sections' wrapper still caps at max-w-6xl -- "
            f"ux's ruling: all sections adopt the Board preview card's (already-uncapped, "
            f"full-bleed) width, container only. Found class list: "
            f"{other_sections_match.group(1)!r}.",
        )

    def test_board_section_still_carries_no_competing_width_cap(self):
        # The Board card was ALREADY the widest/uncapped section -- "adopt
        # Board's width" means the OTHERS change, not Board itself. This
        # is a light regression pin against someone instead narrowing
        # Board down to introduce a NEW shared max-w value (which would
        # also make the two agree, but is the wrong direction per ux's
        # explicit "Board card isn't shrinking to match its narrower
        # siblings").
        board_section_match = re.search(r'<section aria-label="Board"[^>]*>', self.source)
        self.assertIsNotNone(board_section_match, f"{DASHBOARD_APP_SVELTE}: no <section aria-label=\"Board\"> found")
        self.assertNotIn(
            "max-w-", board_section_match.group(0),
            f"{DASHBOARD_APP_SVELTE}: the Board section now carries a max-w-* class "
            f"({board_section_match.group(0)!r}) -- ux's ruling is that the OTHER sections "
            f"widen to match Board, not that Board itself gets newly capped.",
        )

    def test_stat_card_internal_grid_is_unchanged_container_only_clarification(self):
        # ux's explicit clarification: container width unifies, but the
        # stat-card strip's OWN internal responsive grid stays as-is --
        # more even spacing between the same 4 cards at the wider
        # container, not a restructured or removed grid.
        self.assertTrue(
            re.search(r"grid-cols-1[^\"]*sm:grid-cols-2[^\"]*lg:grid-cols-4", self.source) is not None,
            f"{DASHBOARD_APP_SVELTE}: the stat-card strip's internal responsive grid classes "
            f"(grid-cols-1 ... sm:grid-cols-2 ... lg:grid-cols-4) are no longer found together "
            f"-- ux's ruling explicitly keeps this internal layout untouched; only the OUTER "
            f"container width unifies.",
        )


if __name__ == "__main__":
    unittest.main()
