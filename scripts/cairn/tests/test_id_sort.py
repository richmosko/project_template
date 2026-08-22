"""Direct unit tests for cairn._id_sort_key -- PT-2/PT-21's numeric-aware
id sort ("PT-2" < "PT-9" < "PT-10", not lexicographic).

PT-25 names this a drift pair with board-logic.js's idSortKey
(tests/js/id-sort.test.js): there is no shared-code seam across Python
and JS in this stack, so the same numeric-aware sort logic exists twice,
by design (architect's ruling) -- both sides are tested against the SAME
case list (PT-2 < PT-9 < PT-10) so they cannot silently diverge from
each other. _id_sort_key itself predates PT-25 (PT-2/PT-21) and is
already correct; these are regression locks, not red tests -- the drift
pair's genuinely new half is board-logic.js's idSortKey.
"""
from __future__ import annotations

import unittest

import helpers  # noqa: F401

import cairn


class IdSortKeyTests(unittest.TestCase):
    def test_numeric_not_lexicographic_ordering(self):
        ids = ["PT-10", "PT-2", "PT-9"]
        ordered = sorted(ids, key=cairn._id_sort_key)
        self.assertEqual(ordered, ["PT-2", "PT-9", "PT-10"])

    def test_plain_lexicographic_sort_gets_this_wrong(self):
        # Regression guard for the bug _id_sort_key exists to fix -- pins
        # down that the naive sorted(ids) really is wrong, so the fix
        # above isn't guarding against a strawman.
        ids = ["PT-10", "PT-2", "PT-9"]
        self.assertEqual(sorted(ids), ["PT-10", "PT-2", "PT-9"])

    def test_malformed_id_falls_back_to_string_key_not_raise(self):
        self.assertEqual(cairn._id_sort_key("mvp"), ("mvp", -1, "mvp"))
        self.assertEqual(cairn._id_sort_key(None), ("", -1, ""))

    def test_distinct_prefixes_sort_by_prefix_first_then_number(self):
        ids = ["SB-2", "PT-10", "SB-1", "PT-2"]
        ordered = sorted(ids, key=cairn._id_sort_key)
        self.assertEqual(ordered, ["PT-2", "PT-10", "SB-1", "SB-2"])


if __name__ == "__main__":
    unittest.main()
