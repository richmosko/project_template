"""PT-56 (Dashboard: agent-roster panel) -- guards written BEFORE the
architect's presence-source ruling lands.

The ruling gates implementation (candidates: shared task list, tmux pane
liveness, issue assignee fields, an explicit heartbeat file, or a
composition) -- same posture as PT-54's app-location ruling and PT-55's
embed-strategy ruling: don't guess at DOM/data shape ahead of a pending
architectural decision. What's testable regardless of which source wins is
the one architectural constraint the issue states explicitly, independent
of the ruling's outcome: "cairn's engine reads nothing outside
process/cairn/ + git (spin-off invariant, upheld twice); anything outside
that boundary needs a composed reader module, not an engine change."

The concrete, checkable form of that constraint today is the same one
PT-55's AC #1 produced: `/api/dashboard`'s payload (`build_dashboard_
payload`, PT-54) must not silently grow an agents/roster field as a
shortcut -- whatever presence source is ruled, it composes a SEPARATE
reader, not a widened engine payload. Green today by design (guard, not
red-then-green -- same posture as test_column_parity.py / PT-55's
DashboardPayloadDoesNotDuplicateBoardDataTests), so it fails loudly the
moment a future change takes the shortcut the constraint forbids.
"""
from __future__ import annotations

import unittest

import helpers  # noqa: F401

import cairn


class DashboardPayloadDoesNotCarryAgentDataTests(unittest.TestCase):
    """Mirrors test_dashboard_board_embed.py's PT-55 payload-boundary
    guard exactly -- same rationale, one feature over."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)

    def test_dashboard_payload_carries_no_agent_or_roster_data(self):
        payload = cairn.build_dashboard_payload(self.data_dir)
        for forbidden_key in ("agents", "roster", "presence"):
            self.assertNotIn(
                forbidden_key, payload,
                f"/api/dashboard must not carry {forbidden_key!r} -- the issue's own stated "
                f"constraint is that a presence source outside process/cairn/+git needs a "
                f"composed reader module, not an engine change; a key appearing directly on "
                f"build_dashboard_payload's return value would be exactly that engine change "
                f"(PT-56, pending architect ruling)",
            )

    def test_dashboard_payload_top_level_keys_are_still_exactly_the_pt54_contract(self):
        # Same "pin the whole set" strength as PT-55's version -- catches
        # ANY new top-level addition, not just the three obviously-agent-
        # shaped names checked above.
        payload = cairn.build_dashboard_payload(self.data_dir)
        self.assertEqual(
            set(payload.keys()),
            {"git", "tracker", "check", "release", "generated_at"},
            "build_dashboard_payload's top-level shape changed -- if this is PT-56 adding "
            "agent/roster data directly to it, that's the engine-change shortcut the issue's "
            "own constraint forbids; if it's a legitimate, ruled addition, update this pin "
            "deliberately",
        )


if __name__ == "__main__":
    unittest.main()
