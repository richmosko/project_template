"""PT-78 failing acceptance tests: `scripts/cairn/otel_receiver.py`, the
ongoing OTLP metrics receiver that appends `source: "otel"` lines to the
same `process/cairn/metrics/token-usage.jsonl` PT-77 backfills once.

Pinned to the architect's gating ruling, committed at 4a23dc8 as a comment
on process/cairn/issues/PT-78.md (that comment, §§0-11, is authoritative
for every constant/shape below).

**Nothing under test exists yet** -- there is no `otel_receiver.py` file
at all, and no INTERFACE.md sibling for it the way PT-77 had one before
any test was written. The function names/signatures below are a QA
PROPOSAL, not a confirmed contract -- same posture test_dist_freshness.py
took for check_dist_freshness.py before implementation-lead's first
draft: "if you find a function here awkward to implement as named, change
it and update this file in the same commit as the test fix; keep
spec-compliance the north star, not this file's word choice." Every test
imports the module fresh in `setUp` so a genuinely-missing module fails
each test individually and clearly, not as one opaque collection error.

## Proposed shape (mirrors cairn.py's own pure-core/thin-HTTP-shell split)

Pure, directly-unit-testable core (no HTTP, no threading):
  - `parse_otlp_payload(body: dict) -> List[dict]` -- flattens
    `resourceMetrics[].scopeMetrics[].metrics[].sum.dataPoints[]` into a
    flat list of records, each `{"resource_attrs": dict, "point_attrs":
    dict, "start_time_ns": int, "time_ns": int, "value": int}`. Only
    `claude_code.token.usage` metrics are yielded. Raises
    `OtelPayloadError` on a structurally invalid body (missing
    `resourceMetrics`, non-JSON, etc.) -- the HTTP layer turns that into a
    400 and writes nothing.
  - `current_git_branch(repo_root: Path) -> Optional[str]` -- `git -C
    repo_root rev-parse --abbrev-ref HEAD`; `None` on any failure, never
    raises (same posture as cairn.py's own git readers). THE test seam
    for branch-attribution tests: point `repo_root` at a throwaway git
    repo with a specific branch checked out (same technique
    test_dist_freshness.py already uses for its own git fixtures).
  - `attribute_issue(resource_attrs: dict, repo_root: Path) -> str` --
    §4: branch first (via `backfill_tokens._issue_regex` /
    `_bucket_for_branch` + `current_git_branch` -- reused, not
    reimplemented, per the ruling), `cairn.issue` resource attribute only
    when branch resolves to `main`, else `main`.
  - `attribute_role(agent_name: Optional[str], query_source: Optional[str],
    roster: Set[str]) -> str` -- §5's explicit table. Reuses
    `backfill_tokens._normalize_role` for the present-agent-name case
    only (that function's own absent-default of `team-lead` does NOT
    apply here -- §5's table is richer and this function owns the
    absent-branching itself).
  - `accumulate_datapoint(acc: dict, record: dict) -> None` -- §3's
    max-within-group scheme. Mutates `acc` in place, keyed by
    `(series_key, start_time_ns)` where `series_key` is a sorted tuple of
    every resource+point attribute item INCLUDING `session.id` (held only
    in this in-memory dict, per §3/§6); value is `max(existing, new)`.
  - `rollup(acc: dict, repo_root: Path, roster: Set[str]) -> dict` --
    sums every accumulator entry into `(issue, role, model) -> {"input":
    int, "cache_write": int, "cache_read": int, "output": int, "records":
    int, "window_start": str, "window_end": str}` (§6's `type` mapping:
    input->input, cacheCreation->cache_write, cacheRead->cache_read,
    output->output).
  - `flush_to_file(grouped: dict, out_path: Path, lock_path: Path,
    generated: str) -> None` -- §7/§8: append-only `source: "otel"`
    lines, own-lines-only compaction on rewrite (never touches
    `transcript-backfill` lines), refuses (raises, names both
    timestamps) if any datapoint predates the latest `transcript-backfill`
    line's `generated` (§8's non-overlap invariant).

Thin HTTP shell (one integration-level test class only; every OTHER test
in this file exercises the pure core directly -- "lowest level that gives
confidence"):
  - `make_receiver_server(out_path: Path, repo_root: Path, port: int = 0,
    lock_path: Optional[Path] = None) -> http.server.HTTPServer` --
    binds `127.0.0.1:port` (`0` = ephemeral, mirrors `cairn.make_server`).
    `POST /v1/metrics` -> `parse_otlp_payload` -> `accumulate_datapoint`
    (in memory, across requests) -> `rollup` + `flush_to_file` on trigger
    (§7: attributed-issue change, clean shutdown, or a 30-minute timer).
    `server_close()` performs one final flush before closing -- the
    "clean shutdown" trigger -- so every test's teardown IS the flush
    trigger, no test-only admin endpoint needed.

## Fixture policy

Every OTLP-JSON payload below is HAND-BUILT via small Python dict
builders in this file -- never a captured real export (per the ruling's
own test #1: "do NOT check a real one in; it contains the user's
email"). Built as Python dicts rather than static fixture files (PT-77's
own convention) because the combinatorial shape here (resource attrs x
datapoint attrs x series-repetition) is more tractable to construct and
vary per-test in code than as N near-duplicate JSON files.
"""
from __future__ import annotations

import datetime
import http.client
import importlib
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

import cairn

MODULE_NAME = "otel_receiver"

# The 12-key allow-list, §6 -- exactly these, nothing else, ever.
ALLOWED_OTEL_LINE_KEYS = {
    "source", "generated", "window_start", "window_end",
    "issue", "role", "model", "input", "cache_write", "cache_read", "output", "records",
}

# Every identifying value the ruling's §6 forbids from ever reaching disk.
# Values, not just key names -- a leak could smuggle the VALUE under a
# differently-named or malformed key, which a keys-only check would miss.
FORBIDDEN_VALUES = [
    "not-a-real-user@example.com",
    "fake-session-abc123",
    "fake-user-id-001",
    "fake-account-id-002",
    "fake-account-uuid-003",
    "fake-org-id-004",
    "iTerm.app",
]
FORBIDDEN_KEYS_SUBSTRINGS = [
    "user.email", "user.id", "user.account_id", "user.account_uuid",
    "organization.id", "terminal.type", "session.id", "effort",
]


# --------------------------------------------------------------------------
# Hand-built OTLP HTTP/JSON payload constructors
# --------------------------------------------------------------------------

def _attr(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def _datapoint(point_attrs: dict, start_ns: int, time_ns: int, value: int) -> dict:
    return {
        "attributes": [_attr(k, v) for k, v in point_attrs.items()],
        "startTimeUnixNano": str(start_ns),
        "timeUnixNano": str(time_ns),
        "asInt": str(value),
    }


def _payload(resource_attrs: dict, datapoints: list) -> dict:
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": [_attr(k, v) for k, v in resource_attrs.items()]},
                "scopeMetrics": [
                    {
                        "scope": {"name": "com.anthropic.claude_code", "version": "1.0.0"},
                        "metrics": [
                            {
                                "name": "claude_code.token.usage",
                                "sum": {
                                    "dataPoints": datapoints,
                                    "aggregationTemporality": 1,
                                    "isMonotonic": True,
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }


IDENTITY_RESOURCE_ATTRS = {
    "service.name": "claude-code",
    "session.id": "fake-session-abc123",
    "user.email": "not-a-real-user@example.com",
    "user.id": "fake-user-id-001",
    "user.account_id": "fake-account-id-002",
    "user.account_uuid": "fake-account-uuid-003",
    "organization.id": "fake-org-id-004",
    "terminal.type": "iTerm.app",
}


def make_basic_payload(cairn_issue: Optional[str] = "PT-95", agent_name: Optional[str] = "implementation-lead",
                        query_source: str = "main", model: str = "claude-sonnet-5",
                        start_ns: int = 1756742400000000000, time_ns: int = 1756742460000000000,
                        values: dict | None = None) -> dict:
    """A full, realistic payload: every identity attribute present (for
    the allow-list tests), one series group across the four `type`
    values at one `startTimeUnixNano`."""
    values = values or {"input": 100, "cacheCreation": 200, "cacheRead": 300, "output": 50}
    resource = dict(IDENTITY_RESOURCE_ATTRS)
    if cairn_issue is not None:
        resource["cairn.issue"] = cairn_issue
    point_attrs = {"type": None, "model": model, "query_source": query_source, "effort": "high"}
    if agent_name is not None:
        point_attrs["agent.name"] = agent_name
    datapoints = []
    for otel_type, value in values.items():
        attrs = dict(point_attrs)
        attrs["type"] = otel_type
        datapoints.append(_datapoint(attrs, start_ns, time_ns, value))
    return _payload(resource, datapoints)


# --------------------------------------------------------------------------
# Throwaway git repo helper (branch-attribution test seam)
# --------------------------------------------------------------------------

def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def make_repo_on_branch(testcase, branch: str) -> Path:
    """A throwaway git repo checked out on `branch` -- the stub mechanism
    for `current_git_branch`/`attribute_issue`. Mirrors
    test_dist_freshness.py's own `make_dashboard_repo` git-fixture
    pattern.

    `-b main` on the initial commit's branch name is explicit rather than
    relying on `git init`'s default -- that default is machine-config
    dependent (`init.defaultBranch`, historically `master` on older
    installs), so an implicit default would make the "main" branch tests
    silently environment-dependent."""
    tmp = helpers.make_empty_tmp_dir(testcase)
    _run_git(tmp, "init", "-q", "-b", "main")
    _run_git(tmp, "config", "user.email", "test@example.com")
    _run_git(tmp, "config", "user.name", "Test")
    (tmp / "README.md").write_text("x\n", encoding="utf-8")
    _run_git(tmp, "add", "-A")
    _run_git(tmp, "commit", "-q", "-m", "initial")
    if branch != "main":
        _run_git(tmp, "checkout", "-q", "-b", branch)
    return tmp


class OtelReceiverModuleTestCase(unittest.TestCase):
    """Imports the module fresh in setUp -- a genuinely-missing module
    fails each test individually, matching test_dist_freshness.py's own
    precedent for a from-scratch script."""

    def setUp(self):
        if str(helpers.CAIRN_DIR) not in sys.path:
            sys.path.insert(0, str(helpers.CAIRN_DIR))
        try:
            self.module = importlib.import_module(MODULE_NAME)
            importlib.reload(self.module)
        except ModuleNotFoundError as e:
            self.fail(
                f"scripts/cairn/otel_receiver.py does not exist yet ({e!r}) -- "
                f"implementation-lead's PT-78 slice creates it; see this file's module "
                f"docstring for the proposed (negotiable) contract these tests pin."
            )
        self.roster = self.module._roster_names(helpers.CAIRN_DIR.parent.parent) if hasattr(self.module, "_roster_names") else set()


def read_jsonl(path: Path) -> list[dict]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


class PrivacyAllowListTests(OtelReceiverModuleTestCase):
    """§6 -- allow-list, not deny-list: exactly 12 keys, and every
    identity value (not just key) proven absent from the raw file bytes,
    per the ruling's own test #5 wording."""

    def test_identity_attributes_never_reach_the_output_file(self):
        acc = {}
        for record in self.module.parse_otlp_payload(make_basic_payload()):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)

        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        lock_path = out_dir / ".lock"
        self.module.flush_to_file(grouped, out_path, lock_path, generated="2026-09-04T12:00:00Z")

        raw = out_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_VALUES:
            self.assertNotIn(forbidden, raw, f"{forbidden!r} leaked into the committed output")
        for forbidden_key in FORBIDDEN_KEYS_SUBSTRINGS:
            self.assertNotIn(forbidden_key, raw, f"{forbidden_key!r} leaked into the committed output")

    def test_output_lines_carry_only_the_twelve_allowed_keys(self):
        acc = {}
        for record in self.module.parse_otlp_payload(make_basic_payload()):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)

        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        self.module.flush_to_file(grouped, out_path, out_dir / ".lock", generated="2026-09-04T12:00:00Z")

        lines = read_jsonl(out_path)
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(set(line.keys()), ALLOWED_OTEL_LINE_KEYS, f"got keys {set(line.keys())}")
            self.assertEqual(line["source"], "otel")


class RoleAttributionTests(OtelReceiverModuleTestCase):
    """§5's explicit table -- no silent folding into team-lead."""

    def test_agent_name_present_is_normalised_through_the_shared_roster_function(self):
        role = self.module.attribute_role("qa-engineer-76", "main", {"qa-engineer"})
        self.assertEqual(role, "qa-engineer")

    def test_agent_name_absent_query_source_main_is_team_lead(self):
        role = self.module.attribute_role(None, "main", set())
        self.assertEqual(role, "team-lead")

    def test_agent_name_absent_query_source_auxiliary_is_auxiliary(self):
        role = self.module.attribute_role(None, "auxiliary", set())
        self.assertEqual(role, "auxiliary")

    def test_agent_name_absent_query_source_sdk_is_auxiliary(self):
        role = self.module.attribute_role(None, "sdk", set())
        self.assertEqual(role, "auxiliary")

    def test_agent_name_absent_query_source_subagent_is_the_loud_guard_bucket(self):
        # Per §5: "subagent-unattributed is a loud guard, not a bucket we
        # expect to see" -- but it MUST be produced, not silently folded
        # into team-lead, when the table's other branches don't match.
        role = self.module.attribute_role(None, "subagent", set())
        self.assertEqual(role, "subagent-unattributed")

    def test_agent_name_absent_unknown_query_source_also_falls_to_the_guard_bucket(self):
        role = self.module.attribute_role(None, "some-future-value-not-in-the-table", set())
        self.assertEqual(role, "subagent-unattributed")


class CountingIdempotencyTests(OtelReceiverModuleTestCase):
    """§3 -- ruling tests #2 and #3."""

    def test_replaying_the_same_payload_twice_adds_no_additional_tokens(self):
        acc = {}
        payload = make_basic_payload(values={"input": 100, "cacheCreation": 0, "cacheRead": 0, "output": 0})
        records = self.module.parse_otlp_payload(payload)
        for record in records:
            self.module.accumulate_datapoint(acc, record)
        # Replay the IDENTICAL payload (same series, same startTimeUnixNano,
        # same value) a second time.
        for record in self.module.parse_otlp_payload(payload):
            self.module.accumulate_datapoint(acc, record)

        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)
        totals = next(iter(grouped.values()))
        self.assertEqual(totals["input"], 100, "a byte-identical replay must not double-count")

    def test_a_repeated_start_time_with_a_rising_value_counts_the_maximum_not_the_sum(self):
        # One series (identical attribute set), same startTimeUnixNano,
        # but two data points with different asInt values (100 then 150)
        # -- §3's max-within-group scheme must yield 150, not 250.
        attrs = {"type": "input", "model": "claude-sonnet-5", "query_source": "main", "agent.name": "backend-lead"}
        start_ns = 1756742400000000000
        payload = _payload(
            dict(IDENTITY_RESOURCE_ATTRS, **{"cairn.issue": "PT-33"}),
            [
                _datapoint(attrs, start_ns, start_ns + 1_000_000_000, 100),
                _datapoint(attrs, start_ns, start_ns + 2_000_000_000, 150),
            ],
        )
        acc = {}
        for record in self.module.parse_otlp_payload(payload):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)
        totals = next(iter(grouped.values()))
        self.assertEqual(totals["input"], 150, "must take the MAXIMUM within one (series, startTimeUnixNano) group, never sum")


class BranchAttributionTests(OtelReceiverModuleTestCase):
    """§4 -- branch-first, cairn.issue fallback only when branch is main."""

    def test_feature_branch_wins_even_when_no_cairn_issue_attribute_is_present(self):
        repo_root = make_repo_on_branch(self, "feature/pt-95-otel-thing")
        issue = self.module.attribute_issue({}, repo_root)
        self.assertEqual(issue, "PT-95")

    def test_cairn_issue_attribute_wins_only_when_the_branch_resolves_to_main(self):
        repo_root = make_repo_on_branch(self, "main")
        issue = self.module.attribute_issue({"cairn.issue": "PT-12"}, repo_root)
        self.assertEqual(issue, "PT-12")

    def test_feature_branch_overrides_a_stale_cairn_issue_attribute(self):
        # §4's load-bearing ordering: branch first, NOT cairn.issue first
        # -- a stale cairn.issue from a long-running session must never
        # override a correct, fresh branch signal.
        repo_root = make_repo_on_branch(self, "feature/pt-95-otel-thing")
        issue = self.module.attribute_issue({"cairn.issue": "PT-1"}, repo_root)
        self.assertEqual(issue, "PT-95", "a real branch signal must win over a stale cairn.issue attribute")

    def test_neither_branch_nor_cairn_issue_present_lands_in_main(self):
        repo_root = make_repo_on_branch(self, "main")
        issue = self.module.attribute_issue({}, repo_root)
        self.assertEqual(issue, "main")

    def test_a_milestone_branch_still_falls_to_main_not_a_fabricated_id(self):
        # Reuses PT-77's exact branch regex (the ruling: "call the same
        # function, do not reimplement it") -- chore/pt-0.11-* must still
        # land in main here too.
        repo_root = make_repo_on_branch(self, "chore/pt-0.11-token-accounting")
        issue = self.module.attribute_issue({"cairn.issue": "PT-70"}, repo_root)
        self.assertEqual(issue, "PT-70", "a milestone branch resolves to main, so the cairn.issue fallback engages")


class MergeWithBackfillTests(OtelReceiverModuleTestCase):
    """§7/§8 -- append-only, own-source-only, non-overlap invariant."""

    def _seed_backfill_line(self, out_path: Path, generated: str, issue: str = "PT-1") -> dict:
        line = {
            "source": "transcript-backfill", "generated": generated,
            "window_start": "2026-08-18", "window_end": "2026-08-24",
            "issue": issue, "role": "implementation-lead", "model": "claude-sonnet-5",
            "input": 10, "cache_write": 20, "cache_read": 30, "output": 5, "records": 1,
        }
        out_path.write_text(json.dumps(line, separators=(",", ":")) + "\n", encoding="utf-8")
        return line

    def test_transcript_backfill_line_survives_a_receiver_append_byte_for_byte(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        backfill_line = self._seed_backfill_line(out_path, generated="2026-08-01T00:00:00Z")

        acc = {}
        for record in self.module.parse_otlp_payload(make_basic_payload()):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)
        self.module.flush_to_file(grouped, out_path, out_dir / ".lock", generated="2026-09-04T12:00:00Z")

        lines = read_jsonl(out_path)
        backfill_lines = [l for l in lines if l["source"] == "transcript-backfill"]
        otel_lines = [l for l in lines if l["source"] == "otel"]
        self.assertEqual(backfill_lines, [backfill_line], "the pre-existing transcript-backfill line must survive untouched")
        self.assertTrue(otel_lines, "the new otel contribution must also be present")

    def test_a_flush_predating_the_latest_backfill_generated_is_refused(self):
        # §8: non-overlap invariant. Seed a backfill line whose `generated`
        # is LATER than the otel payload's own timestamps -- the receiver
        # must refuse to write, naming both timestamps.
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        self._seed_backfill_line(out_path, generated="2026-12-31T00:00:00Z")  # far in the future relative to the payload below

        acc = {}
        old_payload = make_basic_payload(start_ns=1704067200000000000, time_ns=1704067200000000000)  # 2024-01-01
        for record in self.module.parse_otlp_payload(old_payload):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)

        with self.assertRaises(Exception) as ctx:
            self.module.flush_to_file(grouped, out_path, out_dir / ".lock", generated="2024-01-01T00:00:00Z")
        message = str(ctx.exception)
        self.assertIn("2026-12-31", message, f"error must name the backfill's generated timestamp -- got: {message!r}")
        self.assertIn("2024-01-01", message, f"error must name the refused flush's own timestamp -- got: {message!r}")


class MalformedPayloadTests(OtelReceiverModuleTestCase):
    def test_a_payload_missing_resource_metrics_is_rejected(self):
        with self.assertRaises(Exception):
            self.module.parse_otlp_payload({"not_resource_metrics_at_all": []})

    def test_invalid_json_body_is_rejected_at_the_http_layer_without_writing(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        repo_root = helpers.CAIRN_DIR.parent.parent
        server = self.module.make_receiver_server(out_path, repo_root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=5)))
        port = server.server_address[1]

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/v1/metrics", body=b"{not valid json", headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        response.read()
        self.assertGreaterEqual(response.status, 400, "a malformed body must be rejected with an HTTP error status")
        self.assertFalse(out_path.exists(), "a rejected payload must never produce a written file")


class LockContentionTests(OtelReceiverModuleTestCase):
    def test_a_fresh_lock_held_by_another_writer_defers_without_corrupting_existing_content(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        existing = self._seed_line(out_path)
        lock_path = out_dir / ".lock"
        # Simulate PT-77's own O_CREAT|O_EXCL lock, held fresh by another
        # writer (mtime just now -- well under the 60s staleness window).
        lock_path.write_text("held\n", encoding="utf-8")

        acc = {}
        for record in self.module.parse_otlp_payload(make_basic_payload()):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)

        with self.assertRaises(Exception):
            self.module.flush_to_file(grouped, out_path, lock_path, generated="2026-09-04T12:00:00Z")
        self.assertEqual(out_path.read_text(encoding="utf-8"), existing, "a fresh lock held by another writer must leave existing content untouched")

    def test_a_stale_lock_older_than_sixty_seconds_is_reclaimed(self):
        import os
        import time as time_module

        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        lock_path = out_dir / ".lock"
        lock_path.write_text("stale\n", encoding="utf-8")
        stale_time = time_module.time() - 120  # 2 minutes old, past PT-77's 60s staleness window
        os.utime(lock_path, (stale_time, stale_time))

        acc = {}
        for record in self.module.parse_otlp_payload(make_basic_payload()):
            self.module.accumulate_datapoint(acc, record)
        repo_root = helpers.CAIRN_DIR.parent.parent
        roster = self.module._roster_names(repo_root)
        grouped = self.module.rollup(acc, repo_root, roster)
        # Must NOT raise -- a stale lock is reclaimed, not treated as
        # held.
        self.module.flush_to_file(grouped, out_path, lock_path, generated="2026-09-04T12:00:00Z")
        self.assertTrue(out_path.is_file(), "a stale lock must be reclaimed, allowing the flush to succeed")

    def _seed_line(self, out_path: Path) -> str:
        line = json.dumps({
            "source": "otel", "generated": "2026-08-01T00:00:00Z",
            "window_start": "2026-08-01", "window_end": "2026-08-01",
            "issue": "PT-1", "role": "team-lead", "model": "claude-sonnet-5",
            "input": 1, "cache_write": 1, "cache_read": 1, "output": 1, "records": 1,
        }, separators=(",", ":")) + "\n"
        out_path.write_text(line, encoding="utf-8")
        return line


class HttpWiringIntegrationTests(OtelReceiverModuleTestCase):
    """The ONE end-to-end test in this file -- confirms POST /v1/metrics
    actually reaches the same pure core every other test exercises
    directly. Every edge case is covered above at the pure-function
    level; this only proves the wiring."""

    def test_a_posted_payload_produces_a_file_delta_after_clean_shutdown(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        repo_root = make_repo_on_branch(self, "feature/pt-95-otel-thing")
        server = self.module.make_receiver_server(out_path, repo_root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps(make_basic_payload(cairn_issue=None)).encode("utf-8")
        conn.request("POST", "/v1/metrics", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        response.read()
        self.assertLess(response.status, 300, "a well-formed payload must be accepted")

        # server_close() is the "clean shutdown" flush trigger (proposed
        # contract, see module docstring) -- call it directly rather than
        # via addCleanup so the flush has definitely happened before the
        # assertions below.
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

        self.assertTrue(out_path.is_file(), "a clean shutdown must flush accumulated data to disk")
        lines = read_jsonl(out_path)
        self.assertTrue(any(l["issue"] == "PT-95" for l in lines), f"expected a PT-95 line, got {lines!r}")


if __name__ == "__main__":
    unittest.main()
