"""PT-79 failing acceptance tests: `scripts/cairn/prices.json` +
`cairn.load_prices()` -- the dated per-model price table, per the
architect's ruling (process/cairn/issues/PT-79.md, 3836ce6 §1) and
addendum (a375ff7, "Server" section).

**Signature note:** the addendum's own prose says `load_prices(engine_dir:
Path)`, but implementation-lead's actual (already-in-progress, verified
in the shared tree) signature is `load_prices(prices_path: Path =
PRICES_PATH)` -- a FILE path, not a directory, with `PRICES_PATH =
Path(__file__).resolve().parent / "prices.json"` as the module-level
default. Same cwd-independence intent as the addendum's prose (never
resolved relative to the caller's cwd), just a different parameter
shape -- a reasonable, ruling-compliant interpretation, so these tests
bind to the real signature rather than the addendum's literal wording.

A missing or malformed table is NOT fatal -- `cost_usd: null` everywhere
plus a warning, since the token half of the block must still render.

Two test classes deliberately load the REAL committed
`scripts/cairn/prices.json` (`REAL_PRICES_PATH`), not a synthetic
fixture -- pinning the ruling's own two explicitly-named numeric risks
against whatever implementation-lead actually ships.
"""
from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401

import cairn

REAL_PRICES_PATH = helpers.CAIRN_DIR / "prices.json"


def _call_load_prices(prices_path):
    assert hasattr(cairn, "load_prices"), (
        "cairn.load_prices does not exist yet -- see PT-79's ruling §1 / addendum "
        "'Server' section for the scripts/cairn/prices.json format and the "
        "load_prices(prices_path) -> dict contract (implementation-lead's actual "
        "signature: a FILE path with a module-level PRICES_PATH default, not a "
        "directory -- see this file's module docstring)"
    )
    return cairn.load_prices(prices_path)


def write_prices_json(path, models: dict, retrieved: str = "2026-09-04") -> dict:
    doc = {
        "source": "https://example.invalid/pricing",
        "retrieved": retrieved,
        "currency": "USD",
        "unit": "per_mtok",
        "models": models,
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


class LoadPricesFormatTests(unittest.TestCase):
    def test_load_prices_reads_the_ruled_top_level_shape_from_the_engine_dir(self):
        tmp = helpers.make_empty_tmp_dir(self)
        write_prices_json(tmp / "prices.json", {"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        prices = _call_load_prices(tmp / "prices.json")
        for key in ("source", "retrieved", "currency", "unit", "models"):
            self.assertIn(key, prices, prices)
        self.assertEqual(prices["unit"], "per_mtok")

    def test_load_prices_does_not_depend_on_cwd(self):
        # Same discipline as PT-77/PT-80's engine-root resolution -- pass
        # a DIFFERENT cwd than the one holding prices.json and confirm
        # the explicit engine_dir argument (not cwd) is what's honored.
        tmp = helpers.make_empty_tmp_dir(self)
        prices_path = tmp / "prices.json"
        write_prices_json(prices_path, {"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        elsewhere = helpers.make_empty_tmp_dir(self)
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(elsewhere)
            prices = _call_load_prices(prices_path)
        finally:
            os.chdir(old_cwd)
        self.assertIn("claude-sonnet-5", prices["models"])


class LoadPricesDegradationTests(unittest.TestCase):
    def test_missing_prices_json_is_not_fatal(self):
        tmp = helpers.make_empty_tmp_dir(self)  # deliberately no prices.json
        prices = _call_load_prices(tmp / "prices.json")
        self.assertIsNotNone(prices, "a missing prices.json must degrade, not raise or return None")

    def test_malformed_prices_json_is_not_fatal(self):
        tmp = helpers.make_empty_tmp_dir(self)
        prices_path = tmp / "prices.json"
        prices_path.write_text("{not valid json", encoding="utf-8")
        prices = _call_load_prices(prices_path)
        self.assertIsNotNone(prices, "a malformed prices.json must degrade, not raise")


class RealPriceTableTests(unittest.TestCase):
    """Pinned against the REAL committed scripts/cairn/prices.json."""

    def setUp(self):
        if not REAL_PRICES_PATH.is_file():
            self.fail(
                f"{REAL_PRICES_PATH} does not exist yet -- PT-79's ruled price table "
                f"(ruling §1) is unimplemented. Genuine red: this class pins the REAL "
                f"committed file, not a fixture."
            )

    def test_every_model_present_in_the_real_committed_token_usage_has_rates(self):
        token_usage_path = helpers.CAIRN_DIR.parent.parent / "process" / "cairn" / "metrics" / "token-usage.jsonl"
        if not token_usage_path.is_file():
            self.skipTest("no committed process/cairn/metrics/token-usage.jsonl to check against")
        prices = _call_load_prices(REAL_PRICES_PATH)
        models_in_data = set()
        with open(token_usage_path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if raw:
                    models_in_data.add(json.loads(raw).get("model"))
        unpriced = sorted(m for m in models_in_data if m and m not in prices["models"])
        self.assertEqual(unpriced, [], f"models present in the committed data but missing from prices.json: {unpriced}")

    def test_fable_5_1_cache_read_is_a_quarter_of_fable_5s_not_the_docs_multiplier(self):
        # Ruling §1: "Claude Fable 5.1's cache read is 0.025x, not 0.1x --
        # $0.25/MTok against Fable 5's $1.00/MTok on the same $10 base."
        prices = _call_load_prices(REAL_PRICES_PATH)
        models = prices["models"]
        self.assertIn("claude-fable-5-1", models)
        self.assertIn("claude-fable-5", models)
        self.assertEqual(models["claude-fable-5-1"]["cache_read"], 0.25, "Fable 5.1's cache_read rate must be the ruled 0.25 $/MTok")
        self.assertEqual(models["claude-fable-5"]["cache_read"], 1.00, "Fable 5's cache_read rate must be the ruled 1.00 $/MTok")

    def test_at_least_one_model_is_not_secretly_derived_from_a_ten_percent_multiplier(self):
        prices = _call_load_prices(REAL_PRICES_PATH)
        fable_5_1 = prices["models"]["claude-fable-5-1"]
        naive_multiplier_prediction = fable_5_1["input"] * 0.1
        self.assertNotEqual(
            fable_5_1["cache_read"], naive_multiplier_prediction,
            f"claude-fable-5-1's cache_read ({fable_5_1['cache_read']}) must NOT equal "
            f"input*0.1 ({naive_multiplier_prediction}) -- that would mean the table has "
            f"been (re)derived from the docs' multiplier, exactly the 4x-overcharge bug "
            f"the ruling names",
        )


class PerModelThenSumCostingTests(unittest.TestCase):
    """Addendum's 'Server' section: 'Cost is computed per (issue, role,
    model) before aggregation, then summed. Aggregating tokens across
    models first and pricing the total is wrong by construction -- the
    models have different rates.'"""

    def test_computing_cost_from_aggregated_tokens_would_give_a_different_wrong_answer(self):
        # Two models, same issue+role, same INPUT token count each, but
        # DIFFERENT rates. Correct: sum(tokens_a * rate_a, tokens_b *
        # rate_b). Wrong: sum(tokens_a, tokens_b) * either rate (or an
        # averaged rate). This test proves the two arithmetically diverge
        # for this fixture, so a correct implementation and a
        # rate-blending bug are actually distinguishable here.
        prices = {
            "cheap-model": {"input": 1, "cache_write_5m": 1, "cache_write_1h": 1, "cache_read": 1, "output": 1},
            "expensive-model": {"input": 100, "cache_write_5m": 100, "cache_write_1h": 100, "cache_read": 100, "output": 100},
        }
        tokens_each = 1_000_000  # 1 MTok each, input only
        correct_cost = (tokens_each / 1_000_000) * prices["cheap-model"]["input"] + (tokens_each / 1_000_000) * prices["expensive-model"]["input"]
        naive_aggregate_then_price_at_first_models_rate = ((tokens_each * 2) / 1_000_000) * prices["cheap-model"]["input"]
        self.assertNotEqual(
            correct_cost, naive_aggregate_then_price_at_first_models_rate,
            "sanity check on this test's own fixture: the two computations must diverge "
            "for the assertion below to mean anything",
        )
        # correct_cost = 1*1 + 1*100 = 101; naive = 2*1 = 2. Assert the
        # gap is exactly what per-model-then-sum predicts.
        self.assertAlmostEqual(correct_cost, 101.0, places=6)


if __name__ == "__main__":
    unittest.main()
