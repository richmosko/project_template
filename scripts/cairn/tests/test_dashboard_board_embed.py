"""PT-55 (Dashboard: embed live kanban/list board) -- strategy-independent
guards, written BEFORE the architect's embed-strategy ruling lands.

PT-55's three embed candidates (iframe of the root board, board.js mounted
into a Svelte DOM node, or a Svelte component re-consuming `/api/board`)
produce fundamentally different DOM shapes -- a test asserting anything
about DOM structure or interaction wiring today would either be
meaningless or bake in a guess team-lead/architect explicitly asked me not
to make (see the PT-55 anchor task discussion). What IS testable regardless
of which strategy is chosen is the data-path half of AC #1: "no second
fetch layer, no duplicated column list -- PT-36's single-sourcing holds."

Mixed red/green is expected and correct here, same posture as
test_column_parity.py's own docstring: these are GUARDS against a future
regression, not red-then-green feature tests -- `/api/dashboard` (PT-54)
already exists and already doesn't duplicate board data, so
`test_dashboard_payload_carries_no_board_data` is GREEN today. It stays in
this suite so that if a future PT-55 implementation widens
`build_dashboard_payload` to also carry issues/majors/milestones (a second,
parallel data path -- exactly what AC #1 forbids), this test goes RED
immediately rather than the drift surviving to a manual review.

`test_column_parity.py`'s existing PT-36 guard (BOARD_COLUMNS/STATUS_ORDER
parity) is not duplicated here -- it already covers "PT-36's single-sourcing
holds" for board-logic.js itself, regardless of how/whether PT-55 embeds it.
"""
from __future__ import annotations

import unittest

import helpers  # noqa: F401

import cairn


class DashboardPayloadDoesNotDuplicateBoardDataTests(unittest.TestCase):
    """AC #1 ("no second fetch layer, no duplicated column list"): whatever
    PT-55's embed strategy turns out to be, `/api/dashboard`'s OWN payload
    (`build_dashboard_payload`, PT-54) must stay a status-summary API --
    counts, git state, release, lint -- never a second copy of the
    issues/majors/milestones data `/api/board` already serves. A component
    fetching board content for the embedded lane section must hit
    `/api/board` itself (or reuse whatever board.js already fetches), not
    a parallel field `/api/dashboard` grows for convenience.
    """

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)

    def test_dashboard_payload_carries_no_board_data(self):
        payload = cairn.build_dashboard_payload(self.data_dir)
        for forbidden_key in ("issues", "majors", "milestones", "board"):
            self.assertNotIn(
                forbidden_key, payload,
                f"/api/dashboard must not carry {forbidden_key!r} -- that would be a "
                f"second, duplicated data path for content /api/board already serves "
                f"(PT-55 AC #1 / PT-36 single-sourcing)",
            )

    def test_dashboard_payload_top_level_keys_are_exactly_the_pt54_contract(self):
        # Stronger than the negative check above: pins the WHOLE key set,
        # so a future addition of ANY new top-level group (not just the
        # four obviously-board-shaped names checked individually above)
        # is a deliberate, reviewed change to this test, not a silent
        # payload-shape drift.
        payload = cairn.build_dashboard_payload(self.data_dir)
        self.assertEqual(
            set(payload.keys()),
            {"git", "tracker", "check", "release", "generated_at"},
            "build_dashboard_payload's top-level shape changed -- if this is PT-55 "
            "adding board data to it, that violates AC #1's single-fetch-layer "
            "constraint; if it's a legitimate new field, update this pin deliberately",
        )


if __name__ == "__main__":
    unittest.main()
