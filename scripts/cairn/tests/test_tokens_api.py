"""PT-79 failing acceptance tests: `GET /api/tokens` / `build_tokens_payload`
and `scripts/cairn/prices.json` -- the token/cost dashboard block's data
source, per the architect's committed ruling (process/cairn/issues/PT-79.md,
commit 3836ce6).

Mirrors test_dashboard_flow.py's own established shape for this suite
(same author, same conventions): real fixtures (a hand-built
`token-usage.jsonl` + a synthetic `prices.json`, never a mock of the
aggregation itself), a `_call_build_tokens_payload` indirection so a
genuinely-missing function fails with one clear message instead of an
opaque `AttributeError`, and a caching-tests class mirroring
`FlowCachingTests`'s memo-key-changes-on-write pattern (mtime/size here,
HEAD sha there).

Nothing under test exists yet: `cairn` has no `build_tokens_payload`
attribute, the server has no `/api/tokens` route, and
`scripts/cairn/prices.json` does not exist. Every test below fails on a
genuinely-missing function/file/route.

Two tests (`PriceTableAsymmetryTests`) deliberately load the REAL
committed `scripts/cairn/prices.json`, not a synthetic fixture -- they
pin the ruling's own two explicitly-named numeric risks (the Fable
5.1/5 cache-read asymmetry, and the 1h/5m cache-write split) against
whatever implementation-lead actually ships, per the ruling's own
instruction to assert direction/inequality for the drifting one, not a
value.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401

import cairn

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
REAL_PRICES_PATH = helpers.CAIRN_DIR / "prices.json"


def _call_build_tokens_payload(data_dir: Path):
    assert hasattr(cairn, "build_tokens_payload"), (
        "cairn.build_tokens_payload does not exist yet -- PT-79's ruled /api/tokens "
        "aggregation (process/cairn/issues/PT-79.md, 3836ce6) is unimplemented"
    )
    return cairn.build_tokens_payload(data_dir)


def _call_load_prices(prices_path: Path):
    assert hasattr(cairn, "load_prices"), (
        "cairn.load_prices does not exist yet -- see PT-79's ruling §1 for the "
        "scripts/cairn/prices.json format"
    )
    return cairn.load_prices(prices_path)


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------

def write_prices_json(path: Path, models: dict, retrieved: str = "2026-09-04") -> dict:
    doc = {
        "source": "https://example.invalid/pricing",
        "retrieved": retrieved,
        "currency": "USD",
        "unit": "per_mtok",
        "models": models,
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def token_line(
    issue: str, role: str, model: str,
    input=0, cache_write=0, cache_read=0, output=0,
    source: str = "transcript-backfill",
    generated: str = "2026-09-04T02:18:03Z",
    window_start: str = "2026-08-18", window_end: str = "2026-09-04",
    records: int = 1,
) -> dict:
    return {
        "source": source, "generated": generated,
        "window_start": window_start, "window_end": window_end,
        "issue": issue, "role": role, "model": model,
        "input": input, "cache_write": cache_write, "cache_read": cache_read, "output": output,
        "records": records,
    }


def write_token_usage_jsonl(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")


def make_tokens_data_dir(testcase, lines: list, prices_models: dict | None = None) -> Path:
    """A minimal data_dir with a metrics/token-usage.jsonl and its own
    prices.json alongside -- but note `load_prices`'s DEFAULT path is
    `scripts/cairn/prices.json` (the real engine file, per the ruling), so
    most tests pass `prices_path` explicitly to `build_tokens_payload`-
    adjacent calls rather than relying on that default resolving into a
    synthetic fixture."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "metrics").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\n", encoding="utf-8")
    write_token_usage_jsonl(data_dir / "metrics" / "token-usage.jsonl", lines)
    if prices_models is not None:
        write_prices_json(tmp / "prices.json", prices_models)
    return data_dir


class TokensPayloadShapeTests(unittest.TestCase):
    def test_payload_has_exactly_the_ruled_top_level_keys(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        expected_keys = {"issues", "window_start", "window_end", "generated", "sources", "prices", "warning"}
        self.assertEqual(set(payload.keys()), expected_keys, payload.keys())

    def test_each_issue_carries_total_and_roles_with_the_four_counters_plus_cost(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        self.assertEqual(len(payload["issues"]), 1)
        entry = payload["issues"][0]
        self.assertEqual(entry["issue"], "PT-1")
        for key in ("input", "cache_write", "cache_read", "output", "cost_usd"):
            self.assertIn(key, entry["total"], entry)
        self.assertEqual(len(entry["roles"]), 1)
        for key in ("role", "input", "cache_write", "cache_read", "output", "cost_usd"):
            self.assertIn(key, entry["roles"][0], entry["roles"][0])


class TokensAggregationTests(unittest.TestCase):
    def test_two_roles_on_one_issue_sum_correctly_at_the_issue_level_and_split_at_role_level(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-5", "backend-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
            token_line("PT-5", "qa-engineer", "claude-sonnet-5", input=50, cache_write=5, cache_read=10, output=2),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-5")
        self.assertEqual(entry["total"]["input"], 150)
        self.assertEqual(entry["total"]["cache_write"], 15)
        self.assertEqual(entry["total"]["cache_read"], 30)
        self.assertEqual(entry["total"]["output"], 7)
        roles = {r["role"]: r for r in entry["roles"]}
        self.assertEqual(set(roles.keys()), {"backend-lead", "qa-engineer"})
        self.assertEqual(roles["backend-lead"]["input"], 100)
        self.assertEqual(roles["qa-engineer"]["input"], 50)

    def test_two_models_on_one_issue_role_fold_into_one_role_line_with_model_never_crossing_the_wire(self):
        # Ruling §2: "model detail is folded into cost_usd server-side and
        # does not cross the wire." Same issue+role, two DIFFERENT models
        # -- must still be ONE roles[] entry (not two, one per model), and
        # no "model" key anywhere in the payload.
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-9", "team-lead", "claude-sonnet-5", input=100, cache_write=0, cache_read=0, output=0),
            token_line("PT-9", "team-lead", "claude-opus-5", input=50, cache_write=0, cache_read=0, output=0),
        ], prices_models={
            "claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10},
            "claude-opus-5": {"input": 5, "cache_write_5m": 6.25, "cache_write_1h": 10, "cache_read": 0.5, "output": 25},
        })
        payload = _call_build_tokens_payload(data_dir)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-9")
        self.assertEqual(len(entry["roles"]), 1, "two models under one issue+role must fold into one roles[] entry")
        self.assertEqual(entry["roles"][0]["input"], 150)
        raw = json.dumps(payload)
        self.assertNotIn('"model"', raw, "model detail must never cross the wire, per ruling §2")


class TokensCostTests(unittest.TestCase):
    def test_cost_usd_is_null_not_zero_for_an_unpriced_model(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-3", "team-lead", "claude-unreleased-model-x", input=1_000_000, cache_write=0, cache_read=0, output=0),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-3")
        self.assertIsNone(entry["total"]["cost_usd"], entry)
        self.assertIn("input", entry["total"], "tokens must still render for an unpriced model")
        self.assertEqual(entry["total"]["input"], 1_000_000)
        self.assertIn("claude-unreleased-model-x", payload["prices"]["unpriced_models"])

    def test_a_bucket_mixing_one_priced_and_one_unpriced_model_is_null_not_partial(self):
        # Ruling §2: "cost_usd is null... when ANY contributing model is
        # unpriced." A role bucket folding a priced model + an unpriced
        # model must be null overall, not silently the priced model's
        # partial contribution (which would look like a real, too-low
        # number instead of "unknown").
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-4", "team-lead", "claude-sonnet-5", input=1_000_000, cache_write=0, cache_read=0, output=0),
            token_line("PT-4", "team-lead", "claude-unreleased-model-y", input=1_000_000, cache_write=0, cache_read=0, output=0),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-4")
        self.assertIsNone(entry["roles"][0]["cost_usd"], "a mixed priced/unpriced bucket must be null, not the priced model's partial cost")
        self.assertIsNone(entry["total"]["cost_usd"])

    def test_a_fully_priced_bucket_computes_a_real_cost(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-2", "team-lead", "claude-sonnet-5", input=1_000_000, cache_write=0, cache_read=0, output=0),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-2")
        # 1,000,000 input tokens at $2/MTok = $2.00 exactly.
        self.assertAlmostEqual(entry["total"]["cost_usd"], 2.00, places=6)


class TokensWindowAndSourcesTests(unittest.TestCase):
    def test_window_and_sources_come_from_the_data_not_hardcoded(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=1, window_start="2025-01-01", window_end="2025-06-30", generated="2025-07-01T00:00:00Z"),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        self.assertEqual(payload["window_start"], "2025-01-01")
        self.assertEqual(payload["window_end"], "2025-06-30")
        self.assertEqual(payload["sources"], ["transcript-backfill"])

    def test_multiple_sources_are_all_named(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=1, source="transcript-backfill"),
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=1, source="otel"),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        payload = _call_build_tokens_payload(data_dir)
        self.assertEqual(set(payload["sources"]), {"transcript-backfill", "otel"})


class TokensDegradationTests(unittest.TestCase):
    def test_missing_data_file_returns_empty_issues_with_a_warning_not_a_raise(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        data_dir.mkdir()
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\n", encoding="utf-8")
        # Deliberately no metrics/token-usage.jsonl at all.
        payload = _call_build_tokens_payload(data_dir)
        self.assertEqual(payload["issues"], [])
        self.assertEqual(payload["warning"], "no token data", payload["warning"])

    def test_http_endpoint_degrades_to_200_never_500(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        (data_dir / "issues").mkdir(parents=True)
        (data_dir / "archive" / "issues").mkdir(parents=True)
        (data_dir / "milestones").mkdir(parents=True)
        (data_dir / "majors").mkdir(parents=True)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\n", encoding="utf-8")
        server = cairn.make_server(data_dir, port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/board", timeout=5).close()
                    break
                except Exception:
                    time.sleep(0.05)
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tokens", timeout=5)
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body["issues"], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TokensCachingTests(unittest.TestCase):
    """Mirrors FlowCachingTests's memo-key-changes-on-write pattern --
    (mtime, size) here instead of HEAD sha."""

    def test_a_file_change_invalidates_the_memo_and_is_reflected(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        first = _call_build_tokens_payload(data_dir)
        first_input = next(e for e in first["issues"] if e["issue"] == "PT-1")["total"]["input"]
        self.assertEqual(first_input, 100)

        write_token_usage_jsonl(data_dir / "metrics" / "token-usage.jsonl", [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=999),
        ])
        second = _call_build_tokens_payload(data_dir)
        second_input = next(e for e in second["issues"] if e["issue"] == "PT-1")["total"]["input"]
        self.assertEqual(second_input, 999, "a changed token-usage.jsonl (new mtime/size) must invalidate the memo, not serve stale data")


class TokensEndpointNotOnDashboardTests(unittest.TestCase):
    """Mirrors FlowEndpointHTTPHeadersTests's 'separate endpoint' guard."""

    def setUp(self):
        self.data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ], prices_models={"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        self.server = cairn.make_server(self.data_dir, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/board", timeout=5).close()
                return
            except Exception:
                time.sleep(0.05)
        raise AssertionError("server never came up")

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_tokens_endpoint_serves_200_json(self):
        resp = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/tokens", timeout=5)
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        body = json.loads(resp.read().decode("utf-8"))
        self.assertIn("issues", body)

    def test_tokens_endpoint_is_not_a_key_on_the_dashboard_payload(self):
        resp = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/dashboard", timeout=5)
        body = json.loads(resp.read().decode("utf-8"))
        self.assertNotIn("tokens", body, "/api/dashboard must not gain a 'tokens' key -- ruling §2 requires a SEPARATE endpoint")


class PriceTableFormatTests(unittest.TestCase):
    def test_load_prices_reads_the_ruled_top_level_shape(self):
        tmp = helpers.make_empty_tmp_dir(self)
        prices_path = tmp / "prices.json"
        write_prices_json(prices_path, {"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})
        prices = _call_load_prices(prices_path)
        for key in ("source", "retrieved", "currency", "unit", "models"):
            self.assertIn(key, prices, prices)
        self.assertEqual(prices["unit"], "per_mtok")


class PriceTableAsymmetryTests(unittest.TestCase):
    """Ruling §8 tests #2 and #3, against the REAL committed
    scripts/cairn/prices.json -- not a synthetic fixture. These pin the
    two numeric risks the architect explicitly named as the ones a
    careless refactor would silently reintroduce."""

    def setUp(self):
        if not REAL_PRICES_PATH.is_file():
            self.fail(
                f"{REAL_PRICES_PATH} does not exist yet -- PT-79's ruled price table "
                f"(ruling §1) is unimplemented. This is a genuine red, not a skip: the "
                f"whole point of this test class is pinning the REAL committed file."
            )

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
        # A refactor that "simplifies" explicit rates back into a
        # multiplier formula (cache_read = input * 0.1) would silently
        # reintroduce the exact 4x overcharge the ruling exists to
        # prevent -- assert against that specific regression shape.
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


class CacheWriteSplitRegressionTests(unittest.TestCase):
    """Ruling §8 test #3: pricing all cache_write at the 5m rate
    understates the true cost. Asserts the INEQUALITY and DIRECTION
    against the real committed data + real committed price table, per
    the ruling's own explicit instruction not to hardcode the drifting
    dollar figure."""

    def setUp(self):
        if not REAL_PRICES_PATH.is_file():
            self.fail(f"{REAL_PRICES_PATH} does not exist yet -- see PriceTableAsymmetryTests")
        self.real_token_usage_path = REPO_ROOT / "process" / "cairn" / "metrics" / "token-usage.jsonl"
        if not self.real_token_usage_path.is_file():
            self.skipTest("no committed process/cairn/metrics/token-usage.jsonl to regress against")

    def test_pricing_all_cache_write_at_the_5m_rate_understates_the_true_cost(self):
        prices = _call_load_prices(REAL_PRICES_PATH)
        models = prices["models"]
        lines = []
        with open(self.real_token_usage_path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if raw:
                    lines.append(json.loads(raw))

        correct_total = 0.0
        naive_5m_total = 0.0
        for line in lines:
            model = line.get("model")
            if model not in models:
                continue
            rates = models[model]
            cache_write_5m = line.get("cache_write_5m")
            cache_write_1h = line.get("cache_write_1h")
            cache_write_total = line.get("cache_write", 0)
            if cache_write_5m is not None and cache_write_1h is not None:
                correct_total += (cache_write_5m / 1_000_000) * rates["cache_write_5m"]
                correct_total += (cache_write_1h / 1_000_000) * rates["cache_write_1h"]
            else:
                # No split recorded (e.g. an otel line, which doesn't
                # carry the optional split) -- correct treatment is the
                # SAME as "all at 5m" absent finer data, so it can't
                # contribute to the discrepancy either way.
                correct_total += (cache_write_total / 1_000_000) * rates["cache_write_5m"]
            naive_5m_total += (cache_write_total / 1_000_000) * rates["cache_write_5m"]

        self.assertGreater(correct_total, 0, "the real committed data must contain at least some priced cache_write tokens for this regression to be meaningful")
        self.assertLess(
            naive_5m_total, correct_total,
            f"pricing all cache_write at the 5m rate ({naive_5m_total:.2f}) must UNDERSTATE "
            f"the correctly-split total ({correct_total:.2f}) -- if it doesn't, either the "
            f"1h rate stopped being more expensive than the 5m rate, or the split is being "
            f"computed incorrectly somewhere",
        )


if __name__ == "__main__":
    unittest.main()
