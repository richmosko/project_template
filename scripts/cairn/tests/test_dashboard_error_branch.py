"""PT-67 failing acceptance test: status cards + tracker table skeletons have
no error branch.

Architect's post-merge PT-60 finding (preserved via PR #131, PT-60's
addendum comment): `data` is only assigned on a successful fetch, so the
status-cards grid and the tracker-breakdown table each render a bare
`{#if data} … {:else}` -- the `{:else}` is unconditionally the skeleton.
When the initial `/api/dashboard` fetch fails, `loadError` is set but
`data` stays `null` forever, so these two skeletons pulse indefinitely
*underneath* the top-level error card at line ~154, instead of themselves
switching to an error message.

The roster panel (`{#if rosterError && !roster}` -> message,
`{:else if roster === null}` -> skeleton, `{:else}` -> content) is the
in-repo reference for the correct three-state shape. This guard is scoped,
in the established shape for this suite (test_dashboard_polish.py's
`_read_app_svelte` + substring-scoped regex, test_dashboard_board_embed.py's
docstring convention), to each of the two named sections independently --
not a whole-file substring check, which could pass by accident via the
unrelated top-level error card or the roster panel's own `loadError`-free
`rosterError` branch.

Nothing under test exists yet: neither the status-cards grid section nor
the tracker-breakdown section references `loadError` (or any error state)
at all, and neither uses an `{:else if` branch. Every test below is
expected to fail on a genuinely-absent construct, never an import error.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"

STATUS_CARDS_START = '<section class="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">'
TRACKER_ARIA_LABEL = 'aria-label="Tracker breakdown"'
ROSTER_PANEL_MARKER = "<!-- PT-56: agent-roster panel"


def _read_app_svelte() -> str:
    return DASHBOARD_APP_SVELTE.read_text(encoding="utf-8")


def _status_cards_block(source: str) -> str:
    start = source.index(STATUS_CARDS_START)
    tracker_start = source.index(TRACKER_ARIA_LABEL)
    tracker_if_start = source.rfind("{#if", 0, tracker_start)
    return source[start:tracker_if_start]


def _tracker_table_block(source: str) -> str:
    tracker_start = source.index(TRACKER_ARIA_LABEL)
    if_start = source.rfind("{#if", 0, tracker_start)
    end = source.index(ROSTER_PANEL_MARKER, tracker_start)
    return source[if_start:end]


class StatusCardsErrorBranchTests(unittest.TestCase):
    def test_status_cards_section_references_load_error(self):
        # The section itself must gate on the error state -- not the
        # separate top-level error card above it (line ~154), which
        # doesn't stop the skeleton below it from also rendering.
        source = _read_app_svelte()
        block = _status_cards_block(source)
        self.assertIn(
            "loadError",
            block,
            "the status-cards grid section (`{STATUS_CARDS_START}` ... tracker section) "
            "never references loadError -- a failed initial load pulses the skeleton "
            "cards forever instead of switching to an error message",
        )

    def test_status_cards_section_has_three_state_branching(self):
        # Roster's shape is {#if error}/{:else if null}/{:else}. A bare
        # {#if data}/{:else} two-state branch (today's shape) can never
        # express "error" as distinct from "still loading".
        source = _read_app_svelte()
        block = _status_cards_block(source)
        match = re.search(r"\{:else if\b", block)
        self.assertIsNotNone(
            match,
            "the status-cards grid section has no `{:else if` branch -- it cannot "
            "distinguish an error state from the loading/skeleton state "
            "(roster's `{#if rosterError && !roster} … {:else if roster === null} … "
            "{:else}` is the in-repo reference shape)",
        )


class TrackerTableErrorBranchTests(unittest.TestCase):
    def test_tracker_table_section_references_load_error(self):
        source = _read_app_svelte()
        block = _tracker_table_block(source)
        self.assertIn(
            "loadError",
            block,
            "the tracker-breakdown section (both `{TRACKER_ARIA_LABEL}` branches) never "
            "references loadError -- a failed initial load pulses the skeleton rows "
            "forever instead of switching to an error message",
        )

    def test_tracker_table_section_has_three_state_branching(self):
        source = _read_app_svelte()
        block = _tracker_table_block(source)
        match = re.search(r"\{:else if\b", block)
        self.assertIsNotNone(
            match,
            "the tracker-breakdown section has no `{:else if` branch -- it cannot "
            "distinguish an error state from the loading/skeleton state "
            "(roster's `{#if rosterError && !roster} … {:else if roster === null} … "
            "{:else}` is the in-repo reference shape)",
        )


if __name__ == "__main__":
    unittest.main()
