"""PT-79 failing acceptance tests: `GET /api/tokens` /
`build_tokens_payload` / `build_tokens_payload_cached` -- the token/cost
dashboard block's data source, per the architect's ruling
(process/cairn/issues/PT-79.md, 3836ce6 §2) and addendum (a375ff7,
"Server" section).

Mirrors test_dashboard_flow.py's own established shape: real fixtures
(hand-built `token-usage.jsonl`), a `_call_build_tokens_payload`
indirection so a genuinely-missing function fails with one clear message,
a caching-tests class mirroring `FlowCachingTests`.

## Real interface, verified against implementation-lead's in-progress
   code rather than assumed from the addendum's prose

- `build_tokens_payload(data_dir: Path, prices: Optional[dict] = None)`
  -- the RAW, uncached compute. `prices=None` defaults to
  `load_prices()` (the REAL committed `scripts/cairn/prices.json`). Every
  test below that needs a CONTROLLED price table passes `prices=`
  explicitly via `make_prices(...)` -- writing a synthetic prices.json
  file next to a temp `data_dir` does nothing; `build_tokens_payload`
  never looks there.
- `build_tokens_payload_cached(data_dir: Path)` -- the memoized wrapper
  (`_TOKENS_CACHE`, keyed on the metrics file's `(mtime_ns, size)`,
  mirrors `_FLOW_CACHE`). This is what `/api/tokens` calls internally.
  `TokensCachingTests` targets this function specifically, not the raw
  one (which has no cache to invalidate).
- `_read_token_usage_lines` skips a malformed line silently and keeps
  going (verified: the current code has NO warning tracking for this
  case at all) -- `MalformedLineWarningTests` below pins the NEW
  behavior team-lead asked for (partial data preserved, a `warning`
  naming the file + line number), which is genuinely unimplemented, not
  an artifact of a wrong test assumption on my part (my first draft
  wrongly assumed one bad line degrades to `issues: []`; the doc-string
  actually says "skip it, degrade THIS bucket by one contribution",
  which is more consistent with the code's own comment: "a READER here
  failing the whole dashboard over one bad line would be a second,
  needless failure mode").

## Data-file safety tripwire (team-lead's explicit instruction)

A synthetic-payload probe accidentally landed a line in the REAL
committed `process/cairn/metrics/token-usage.jsonl` during this feature
(traced to a manual architect probe against a live receiver with its
default --out-file, unrelated to any test in this suite -- confirmed and
cleaned up). Every test in this file already operates on an isolated
temp `data_dir`, never the real committed file -- `DataFileSha256GuardTests`
below is a suite-level tripwire regardless: records the real file's
sha256 in `setUpClass`, re-checks it in `tearDownClass`.

Nothing under test exists yet: `cairn` has no `build_tokens_payload`
attribute, the server has no `/api/tokens` route.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

import cairn

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
REAL_TOKEN_USAGE_PATH = REPO_ROOT / "process" / "cairn" / "metrics" / "token-usage.jsonl"


def _call_build_tokens_payload(data_dir: Path, prices: Optional[dict] = None):
    assert hasattr(cairn, "build_tokens_payload"), (
        "cairn.build_tokens_payload does not exist yet -- PT-79's ruled /api/tokens "
        "aggregation (process/cairn/issues/PT-79.md, 3836ce6) is unimplemented"
    )
    return cairn.build_tokens_payload(data_dir, prices=prices)


def _call_build_tokens_payload_cached(data_dir: Path):
    assert hasattr(cairn, "build_tokens_payload_cached"), (
        "cairn.build_tokens_payload_cached does not exist yet -- the memoized wrapper "
        "(addendum's Server section, _TOKENS_CACHE keyed on mtime_ns/size) is unimplemented"
    )
    return cairn.build_tokens_payload_cached(data_dir)


def make_prices(models: dict, retrieved: str = "2026-09-04") -> dict:
    """The FULL prices dict shape build_tokens_payload's `prices=`
    parameter expects -- not just the `models` sub-dict."""
    return {
        "source": "https://example.invalid/pricing",
        "retrieved": retrieved,
        "currency": "USD",
        "unit": "per_mtok",
        "models": models,
    }


EMPTY_PRICES = make_prices({}, retrieved=None)


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


def make_tokens_data_dir(testcase, lines: list) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    (data_dir / "metrics").mkdir(parents=True)
    (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\n", encoding="utf-8")
    write_token_usage_jsonl(data_dir / "metrics" / "token-usage.jsonl", lines)
    return data_dir


SONNET_PRICE = make_prices({"claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10}})


class TokensPayloadShapeTests(unittest.TestCase):
    def test_payload_has_exactly_the_ruled_top_level_keys(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        expected_keys = {"issues", "window_start", "window_end", "generated", "sources", "prices", "warning"}
        self.assertEqual(set(payload.keys()), expected_keys, payload.keys())

    def test_each_issue_carries_total_and_roles_with_the_four_counters_plus_cost(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
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
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
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
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-9", "team-lead", "claude-sonnet-5", input=100, cache_write=0, cache_read=0, output=0),
            token_line("PT-9", "team-lead", "claude-opus-5", input=50, cache_write=0, cache_read=0, output=0),
        ])
        prices = make_prices({
            "claude-sonnet-5": {"input": 2, "cache_write_5m": 2.5, "cache_write_1h": 4, "cache_read": 0.2, "output": 10},
            "claude-opus-5": {"input": 5, "cache_write_5m": 6.25, "cache_write_1h": 10, "cache_read": 0.5, "output": 25},
        })
        payload = _call_build_tokens_payload(data_dir, prices=prices)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-9")
        self.assertEqual(len(entry["roles"]), 1, "two models under one issue+role must fold into one roles[] entry")
        self.assertEqual(entry["roles"][0]["input"], 150)
        raw = json.dumps(payload)
        self.assertNotIn('"model"', raw, "model detail must never cross the wire, per ruling §2")

    def test_cost_is_computed_per_model_before_summing_not_on_aggregated_tokens(self):
        # Addendum's 'Server' section: "Cost is computed per (issue, role,
        # model) before aggregation, then summed."
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-20", "team-lead", "cheap-model", input=1_000_000),
            token_line("PT-20", "team-lead", "expensive-model", input=1_000_000),
        ])
        prices = make_prices({
            "cheap-model": {"input": 1, "cache_write_5m": 1, "cache_write_1h": 1, "cache_read": 1, "output": 1},
            "expensive-model": {"input": 100, "cache_write_5m": 100, "cache_write_1h": 100, "cache_read": 100, "output": 100},
        })
        payload = _call_build_tokens_payload(data_dir, prices=prices)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-20")
        # Correct (per-model-then-sum): 1*1 + 1*100 = 101.
        # Wrong (aggregate-then-price-at-one-rate): 2*1 = 2, or 2*100 = 200.
        self.assertAlmostEqual(entry["total"]["cost_usd"], 101.0, places=6)


class TokensCostTests(unittest.TestCase):
    def test_cost_usd_is_null_not_zero_for_an_unpriced_model(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-3", "team-lead", "claude-unreleased-model-x", input=1_000_000, cache_write=0, cache_read=0, output=0),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-3")
        self.assertIsNone(entry["total"]["cost_usd"], entry)
        self.assertEqual(entry["total"]["input"], 1_000_000, "tokens must still render for an unpriced model")
        self.assertIn("claude-unreleased-model-x", payload["prices"]["unpriced_models"])

    def test_a_bucket_mixing_one_priced_and_one_unpriced_model_is_null_not_partial(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-4", "team-lead", "claude-sonnet-5", input=1_000_000, cache_write=0, cache_read=0, output=0),
            token_line("PT-4", "team-lead", "claude-unreleased-model-y", input=1_000_000, cache_write=0, cache_read=0, output=0),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-4")
        self.assertIsNone(entry["roles"][0]["cost_usd"], "a mixed priced/unpriced bucket must be null, not the priced model's partial cost")
        self.assertIsNone(entry["total"]["cost_usd"])

    def test_no_price_table_at_all_still_renders_tokens_with_null_cost(self):
        # EMPTY_PRICES simulates load_prices()'s own documented "missing
        # or malformed table" fallback shape (models: {}) via the real
        # prices= injection seam, rather than trying to make the real
        # committed scripts/cairn/prices.json vanish (which would be a
        # shared-checkout hazard).
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=EMPTY_PRICES)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-1")
        self.assertEqual(entry["total"]["input"], 100, "tokens must still render with no price table at all")
        self.assertIsNone(entry["total"]["cost_usd"])

    def test_no_price_table_at_all_produces_a_top_level_warning(self):
        # Architect's review of 3aa09e8 (4f7fafc) found a missing
        # prices.json yields cost_usd: null everywhere plus every model
        # in unpriced_models, but warning: null -- and recommended
        # amending the RULING rather than the code, since
        # unpriced_models + the caption already name every affected
        # model. Team-lead's call: honour the original ruling literally
        # (a missing price table yields a top-level warning) rather than
        # adopt the architect's amendment recommendation. Pinned here.
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=EMPTY_PRICES)
        self.assertTrue(payload["warning"], f"a missing/empty price table must produce a non-empty top-level warning, got {payload['warning']!r}")


class TokensWindowAndSourcesTests(unittest.TestCase):
    def test_window_and_sources_come_from_the_data_not_hardcoded(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=1, window_start="2025-01-01", window_end="2025-06-30", generated="2025-07-01T00:00:00Z"),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        self.assertEqual(payload["window_start"], "2025-01-01")
        self.assertEqual(payload["window_end"], "2025-06-30")
        self.assertEqual(payload["sources"], ["transcript-backfill"])

    def test_multiple_sources_are_all_named(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=1, source="transcript-backfill"),
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=1, source="otel"),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        self.assertEqual(set(payload["sources"]), {"transcript-backfill", "otel"})


class TokensDegradationTests(unittest.TestCase):
    def test_missing_data_file_returns_empty_issues_with_a_warning_not_a_raise(self):
        tmp = helpers.make_empty_tmp_dir(self)
        data_dir = tmp / "cairn"
        data_dir.mkdir()
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\n", encoding="utf-8")
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
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


class MalformedLineWarningTests(unittest.TestCase):
    """Team-lead's explicit instruction: a malformed line must produce a
    200 with a top-level `warning` string naming the file path and the
    line number. Genuinely unimplemented today -- `_read_token_usage_lines`
    silently skips a bad line with NO warning tracking at all (verified
    against the current source). The GOOD lines around the bad one must
    still render (matches the function's own doc comment: "a READER here
    failing the whole dashboard over one bad line would be a second,
    needless failure mode")."""

    def test_a_malformed_line_is_skipped_but_the_valid_lines_around_it_still_render(self):
        data_dir = make_tokens_data_dir(self, [])
        token_usage_path = data_dir / "metrics" / "token-usage.jsonl"
        token_usage_path.write_text(
            json.dumps(token_line("PT-1", "team-lead", "claude-sonnet-5", input=1)) + "\n"
            + "{not valid json\n"
            + json.dumps(token_line("PT-2", "team-lead", "claude-sonnet-5", input=1)) + "\n",
            encoding="utf-8",
        )
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        issues = {e["issue"] for e in payload["issues"]}
        self.assertEqual(issues, {"PT-1", "PT-2"}, "the two VALID lines must still render around the one malformed line")

    def test_a_malformed_line_produces_a_warning_naming_the_file_and_line_number(self):
        data_dir = make_tokens_data_dir(self, [])
        token_usage_path = data_dir / "metrics" / "token-usage.jsonl"
        token_usage_path.write_text(
            json.dumps(token_line("PT-1", "team-lead", "claude-sonnet-5", input=1)) + "\n"
            + "{not valid json\n"
            + json.dumps(token_line("PT-2", "team-lead", "claude-sonnet-5", input=1)) + "\n",
            encoding="utf-8",
        )
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        self.assertTrue(payload["warning"], "expected a non-empty warning when a line was skipped")
        self.assertIn(str(token_usage_path), payload["warning"], f"warning must name the file path -- got: {payload['warning']!r}")
        self.assertIn("2", payload["warning"], f"warning must name the offending line number (2) -- got: {payload['warning']!r}")


class TokensCachingTests(unittest.TestCase):
    """Mirrors FlowCachingTests's memo-key-changes-on-write pattern --
    targets `build_tokens_payload_cached` specifically, the raw
    `build_tokens_payload` has no cache to invalidate."""

    def test_a_file_change_invalidates_the_memo_and_is_reflected(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ])
        first = _call_build_tokens_payload_cached(data_dir)
        first_input = next(e for e in first["issues"] if e["issue"] == "PT-1")["total"]["input"]
        self.assertEqual(first_input, 100)

        write_token_usage_jsonl(data_dir / "metrics" / "token-usage.jsonl", [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=999),
        ])
        second = _call_build_tokens_payload_cached(data_dir)
        second_input = next(e for e in second["issues"] if e["issue"] == "PT-1")["total"]["input"]
        self.assertEqual(second_input, 999, "a changed token-usage.jsonl (new mtime/size) must invalidate the memo, not serve stale data")

    def test_a_vanished_file_invalidates_rather_than_serving_a_stale_hit(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ])
        _call_build_tokens_payload_cached(data_dir)  # warm the memo
        (data_dir / "metrics" / "token-usage.jsonl").unlink()
        payload = _call_build_tokens_payload_cached(data_dir)
        self.assertEqual(payload["issues"], [], "a vanished file must invalidate the memo (addendum: 'a vanished file invalidates rather than serving a stale hit')")


class TokensEndpointNotOnDashboardTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = make_tokens_data_dir(self, [
            token_line("PT-1", "team-lead", "claude-sonnet-5", input=100),
        ])
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


class TokensPayloadMilestoneKindTests(unittest.TestCase):
    """PT-84 §7 (architect's gating ruling, process/cairn/issues/PT-84.md):
    'add an explicit `kind` per bar -- "issue" | "milestone" | "main".
    The chart must not infer type by string-sniffing the `issue` value;
    a prefix convention parsed on the client is exactly the coupling
    that breaks the next time the form changes.'

    Written after the ruling landed (same discipline as the rest of
    PT-84). Scoped narrowly to what §7 actually names -- the `kind`
    discriminator and the one-clause caption. Milestone-bucket ORDERING
    by creation timestamp (§6, 'ranked after issue bars, before main,
    by creation timestamp not string compare') needs its own
    coordination with implementation-lead first: it requires
    build_tokens_payload to consult cairn.milestone_windows (a
    repo_root-dependent lookup this function's current signature has no
    parameter for), and I'm not guessing a signature change here --
    flagged separately, not silently worked around.
    """

    def test_a_plain_issue_bucket_has_kind_issue(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-28", "team-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        entry = next(e for e in payload["issues"] if e["issue"] == "PT-28")
        self.assertEqual(entry.get("kind"), "issue", f"a plain issue bucket must carry kind: 'issue' -- got {entry!r}")

    def test_a_milestone_bucket_has_kind_milestone(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("milestone:PT-0.4", "team-lead", "claude-sonnet-5", input=50, cache_write=5, cache_read=10, output=2),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        entry = next(e for e in payload["issues"] if e["issue"] == "milestone:PT-0.4")
        self.assertEqual(entry.get("kind"), "milestone", f"a milestone bucket must carry kind: 'milestone', not 'issue' -- got {entry!r}")

    def test_the_main_bucket_has_kind_main(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("main", "team-lead", "claude-sonnet-5", input=30, cache_write=3, cache_read=6, output=1),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        entry = next(e for e in payload["issues"] if e["issue"] == "main")
        self.assertEqual(entry.get("kind"), "main", f"the main bucket must carry kind: 'main' -- got {entry!r}")

    def test_the_client_never_has_to_string_sniff_the_issue_value(self):
        # §7's own stated reason for the field: every bucket, of every
        # kind, in one payload -- proving kind is populated universally,
        # not just for the one shape each test above isolates.
        data_dir = make_tokens_data_dir(self, [
            token_line("PT-28", "team-lead", "claude-sonnet-5", input=100, cache_write=10, cache_read=20, output=5),
            token_line("milestone:PT-0.4", "team-lead", "claude-sonnet-5", input=50, cache_write=5, cache_read=10, output=2),
            token_line("main", "team-lead", "claude-sonnet-5", input=30, cache_write=3, cache_read=6, output=1),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        kinds_by_issue = {e["issue"]: e.get("kind") for e in payload["issues"]}
        self.assertEqual(
            kinds_by_issue, {"PT-28": "issue", "milestone:PT-0.4": "milestone", "main": "main"},
            f"every bucket in one payload must carry its own correct kind -- got {kinds_by_issue!r}",
        )

    def test_a_one_clause_caption_explains_what_milestone_buckets_are(self):
        data_dir = make_tokens_data_dir(self, [
            token_line("milestone:PT-0.4", "team-lead", "claude-sonnet-5", input=50, cache_write=5, cache_read=10, output=2),
        ])
        payload = _call_build_tokens_payload(data_dir, prices=SONNET_PRICE)
        caption = payload.get("milestone_caption") or payload.get("caption")
        self.assertIsNotNone(
            caption,
            f"§7: 'caption explains what they are in one clause' -- expected a caption string "
            f"somewhere in the payload (milestone_caption or caption), got payload keys {list(payload.keys())!r}",
        )
        self.assertNotIn(
            "\n", caption or "",
            "a ONE-clause caption must not itself be multi-line prose",
        )


class DataFileSha256GuardTests(unittest.TestCase):
    """Suite-level tripwire, team-lead's explicit instruction after the
    contamination incident (traced to an unrelated manual architect
    probe, not this suite -- but the guard stays regardless): the REAL
    committed process/cairn/metrics/token-usage.jsonl must be
    byte-identical before and after this entire test module runs."""

    @classmethod
    def setUpClass(cls):
        cls._real_file_existed = REAL_TOKEN_USAGE_PATH.is_file()
        cls._real_file_sha256_before = cls._hash() if cls._real_file_existed else None

    @staticmethod
    def _hash():
        return hashlib.sha256(REAL_TOKEN_USAGE_PATH.read_bytes()).hexdigest()

    def test_placeholder_so_setupclass_teardownclass_actually_run(self):
        # unittest only calls setUpClass/tearDownClass for a TestCase
        # that has at least one test method.
        self.assertTrue(True)

    @classmethod
    def tearDownClass(cls):
        still_exists = REAL_TOKEN_USAGE_PATH.is_file()
        if cls._real_file_existed:
            assert still_exists, (
                f"{REAL_TOKEN_USAGE_PATH} existed before this test module ran and is now "
                f"MISSING -- something in this suite deleted the real committed data file"
            )
            after = hashlib.sha256(REAL_TOKEN_USAGE_PATH.read_bytes()).hexdigest()
            assert after == cls._real_file_sha256_before, (
                f"{REAL_TOKEN_USAGE_PATH}'s sha256 changed during this test module's run "
                f"({cls._real_file_sha256_before} -> {after}) -- some test in this file "
                f"wrote to the REAL committed data file instead of an isolated tmpdir"
            )


if __name__ == "__main__":
    unittest.main()
