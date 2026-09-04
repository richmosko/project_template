"""PT-78 failing acceptance tests: `scripts/cairn/otel_receiver.py`, the
ongoing OTLP metrics receiver that appends `source: "otel"` lines to the
same `process/cairn/metrics/token-usage.jsonl` PT-77 backfills once.

Pinned to the architect's ruling (4a23dc8, §§0-11), the addendum
(f92a06a, concrete implementation surface), and the amendment (25d7a42,
attribute-placement correction + the session.id role resolver now that
`agent.name` is confirmed absent on teammate-shaped processes). Each
later comment supersedes only what it explicitly names, not the rest of
the ruling.

**Nothing under test exists yet** -- no `otel_receiver.py` file at all.
Every test imports/invokes it fresh so a genuinely-missing script fails
clearly (subprocess tests: `python3: can't open file ...`, exit 2, not a
silent skip).

## Test-seam discipline (addendum's own instruction)

"`parse_export`/`fold` are where every counting and privacy assertion
belongs. Only the `--once` test touches a port." This file honors that:
every counting/privacy/attribution/merge/malformed/lock test goes through
`--ingest PATH --out-file PATH` (a subprocess call that folds one payload,
flushes, and exits -- no socket, no threading, no daemon lifecycle).
Exactly ONE test (`OnceIntegrationTests`) binds a real port via `--once`,
to prove the HTTP wiring reaches the same code path.

## Attribute placement (amendment A, settled)

Every fixture built here follows the amendment's measured wire shape,
NOT my earlier resource-level guess: identity keys (`user.email`,
`user.id`, `user.account_id`, `user.account_uuid`, `organization.id`,
`terminal.type`, `session.id`) plus `type`/`model`/`query_source` live
**only** at datapoint level; `cairn.issue` appears at **both** levels
with an identical value (Claude Code copies it down); the resource level
carries only `service.*`/`host.*`/`os.*`. The receiver's own rule is
"flatten resource attrs, overlay datapoint attrs, datapoint wins" and the
12-key allow-list applies to the flattened per-datapoint dict.

## Role resolution (amendment B, settled)

`agent.name` is confirmed absent on teammate-shaped processes, so §5's
original table is replaced: role resolves from `session.id` through a
**transcript-header lookup** (first `agentName` within the first 50
records of `~/.claude/projects/<slug>/<session.id>.jsonl`, PT-77's
roster-anchored normalisation, `team-lead` when the transcript exists
with none, `subagent-unattributed` when no transcript exists at all).
The amendment states this resolver is an "injectable seam -- `--ingest`
and every unit test pass a stub, so no test needs a real transcript."
**Proposed flag** (not literally named in the amendment, inferred from
its own "injectable seam" framing plus `backfill_tokens.py`'s existing
`--transcripts-dir` precedent): `--ingest ... --transcripts-dir PATH`
points the resolver at a synthetic transcripts directory instead of the
real `~/.claude/projects/...`. Fixture skeleton:
`fixtures/otlp/transcripts/session-with-agentname.jsonl` (sessionId
`otel-role-test-session-with-agent`, one record with `agentName:
"qa-engineer"`) and `session-without-agentname.jsonl` (sessionId
`otel-role-test-session-no-agent`, no `agentName` key -- the `team-lead`
case). A THIRD session id used in fixtures deliberately has no matching
transcript file at all, for the `subagent-unattributed` "no transcript"
case (amendment B's own explicit "test to add").

## Branch stubbing (inferred from the in-progress draft, flagged)

The addendum's own CLI table names no `--repo-root`/`--branch` override
flag, but the WIP `otel_receiver.py` already sitting in the shared tree
(uncommitted, pre-addendum shape) exposes `--repo-root REPO_ROOT` at the
top level -- strong signal this is the real mechanism, even though it
predates `--ingest`/`--once` and the rest of the addendum's CLI. Tests
below pass `--repo-root <throwaway-git-repo>` rather than relying on
`cwd`; if this guess is wrong, only the branch-attribution tests'
invocation helper needs to change, not their assertions.
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

SCRIPT_PATH = helpers.CAIRN_DIR / "otel_receiver.py"
FIXTURES = helpers.FIXTURES_DIR / "otlp"

# The 12-key allow-list, addendum's own verbatim order.
ALLOWED_LINE_KEYS_ORDERED = (
    "source", "generated", "window_start", "window_end",
    "issue", "role", "model", "input", "cache_write", "cache_read", "output", "records",
)

FORBIDDEN_VALUES = [
    "not-a-real-user@example.com",
    "fake-session-abc123",
    "fake-user-id-001",
    "fake-account-id-002",
    "fake-account-uuid-003",
    "fake-org-id-004",
    "iTerm.app",
]
FORBIDDEN_KEY_SUBSTRINGS = [
    "user.email", "user.id", "user.account_id", "user.account_uuid",
    "organization.id", "terminal.type", "session.id", "effort",
]


def run_receiver(args: list[str], cwd: Optional[Path] = None, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None, env=env,
    )


def ingest(
    payload_fixture: str, out_path: Path,
    cwd: Optional[Path] = None, repo_root: Optional[Path] = None,
    transcripts_dir: Optional[Path] = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    payload_path = FIXTURES / payload_fixture
    args = ["--ingest", str(payload_path), "--out-file", str(out_path)]
    if repo_root is not None:
        args += ["--repo-root", str(repo_root)]
    if transcripts_dir is not None:
        args += ["--transcripts-dir", str(transcripts_dir)]
    args += extra_args or []
    return run_receiver(args, cwd=cwd)


def read_jsonl(path: Path) -> list[dict]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


def read_jsonl_raw_order(path: Path) -> list[list[str]]:
    """Same as read_jsonl but preserves each line's raw KEY ORDER (for the
    addendum's "in this order" requirement) -- json.loads with the
    default object_pairs_hook preserves source-text insertion order in
    CPython, but being explicit here documents that's what's asserted."""
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                out.append(list(json.loads(raw).keys()))
    return out


# --------------------------------------------------------------------------
# Throwaway git repo helper (branch-attribution test seam -- see the
# module docstring's flagged judgment call)
# --------------------------------------------------------------------------

def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def make_repo_on_branch(testcase, branch: str) -> Path:
    """A throwaway git repo checked out on `branch`. Explicit `-b main` on
    init (not relying on the host's `init.defaultBranch`) so the "main"
    cases aren't silently environment-dependent."""
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


class OtelReceiverPresenceGuard(unittest.TestCase):
    """One cheap, always-first-to-fail check: the script must exist at
    all. Every other test would fail anyway (python3: can't open file),
    but this gives one unambiguous, clearly-worded red result rather than
    N confusing subprocess-error assertions."""

    def test_script_exists(self):
        self.assertTrue(
            SCRIPT_PATH.is_file(),
            f"{SCRIPT_PATH} does not exist yet -- implementation-lead's PT-78 slice creates it; "
            f"see this file's module docstring for the proposed (addendum-named) contract.",
        )


class PrivacyAllowListTests(unittest.TestCase):
    """Ruling §6 + addendum's verbatim 12-key list, in order."""

    def test_identity_values_never_reach_the_output_file_bytes(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("basic.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        raw = out_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_VALUES:
            self.assertNotIn(forbidden, raw, f"{forbidden!r} leaked into the committed output")
        for forbidden_key in FORBIDDEN_KEY_SUBSTRINGS:
            self.assertNotIn(forbidden_key, raw, f"{forbidden_key!r} leaked into the committed output")

    def test_output_lines_carry_exactly_the_twelve_keys_in_the_ruled_order(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("basic.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        key_orders = read_jsonl_raw_order(out_path)
        self.assertTrue(key_orders)
        for keys in key_orders:
            self.assertEqual(tuple(keys), ALLOWED_LINE_KEYS_ORDERED, f"got key order {keys}")

    def test_source_is_always_the_literal_string_otel(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("basic.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        for line in lines:
            self.assertEqual(line["source"], "otel")


class CountingTests(unittest.TestCase):
    """Ruling §3, addendum's implementable pseudocode. Both fixtures put
    the repeated series on PT-33 (a `cairn.issue` resource attr, cwd left
    at the real repo so branch resolves to `main` and the fallback
    engages) so the assertions can target one predictable bucket."""

    def test_an_exact_duplicate_entry_within_one_payload_counts_once(self):
        # duplicate_within_payload.json: the identical (attrs,
        # startTimeUnixNano, value=100) datapoint appears twice in one
        # payload's dataPoints array -- the concrete shape an export
        # retry/duplicate delivery produces. Must fold to 100, not 200.
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("duplicate_within_payload.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        pt33 = [l for l in lines if l["issue"] == "PT-33"]
        self.assertEqual(len(pt33), 1, lines)
        self.assertEqual(pt33[0]["input"], 100, "an exact duplicate entry must not double-count")

    def test_a_rising_value_at_one_repeated_start_time_counts_the_maximum_not_the_sum(self):
        # rising_within_group.json: same series, same startTimeUnixNano,
        # values 100 then 150 -- must count 150 (the max), never 250 (the
        # sum). This is the ruling's explicit warning: "do not simplify
        # to a plain sum without first proving delta behaviourally."
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("rising_within_group.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        pt33 = [l for l in lines if l["issue"] == "PT-33"]
        self.assertEqual(len(pt33), 1, lines)
        self.assertEqual(pt33[0]["input"], 150, "must take the MAXIMUM within one (series, startTimeUnixNano) group")


class BranchAttributionTests(unittest.TestCase):
    """Ruling §4 -- branch-first, `cairn.issue` fallback only when branch
    resolves to `main`. See the module docstring's flagged judgment call
    on the cwd-as-stub mechanism."""

    def test_feature_branch_wins_even_without_a_cairn_issue_attribute(self):
        repo = make_repo_on_branch(self, "feature/pt-95-otel-thing")
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("no_cairn_issue.json", out_path, repo_root=repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        issues = {l["issue"] for l in read_jsonl(out_path)}
        self.assertEqual(issues, {"PT-95"}, issues)

    def test_cairn_issue_wins_only_when_branch_resolves_to_main(self):
        repo = make_repo_on_branch(self, "main")
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        # basic.json carries cairn.issue: PT-95
        result = ingest("basic.json", out_path, repo_root=repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        issues = {l["issue"] for l in read_jsonl(out_path)}
        self.assertEqual(issues, {"PT-95"}, issues)

    def test_feature_branch_overrides_a_stale_cairn_issue_attribute(self):
        # §4's load-bearing ordering: a real branch signal must win over
        # a stale cairn.issue, never the reverse.
        repo = make_repo_on_branch(self, "feature/pt-95-otel-thing")
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        # basic.json's cairn.issue is PT-95 too by coincidence -- use a
        # fixture with a DIFFERENT cairn.issue to make this test a real
        # discriminator: old_timestamp.json carries cairn.issue: PT-1.
        result = ingest("old_timestamp.json", out_path, repo_root=repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        issues = {l["issue"] for l in read_jsonl(out_path)}
        self.assertEqual(issues, {"PT-95"}, f"branch (PT-95) must win over the stale cairn.issue (PT-1) attribute -- got {issues}")

    def test_neither_branch_nor_cairn_issue_lands_in_main(self):
        repo = make_repo_on_branch(self, "main")
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("no_cairn_issue.json", out_path, repo_root=repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        issues = {l["issue"] for l in read_jsonl(out_path)}
        self.assertEqual(issues, {"main"}, issues)

    def test_a_milestone_branch_still_falls_to_main_engaging_the_cairn_issue_fallback(self):
        # Reuses PT-77's exact branch regex (ruling: "call the same
        # function, do not reimplement it") -- a chore/pt-0.11-*
        # milestone branch must land in main, not a fabricated PT-0.
        repo = make_repo_on_branch(self, "chore/pt-0.11-token-accounting")
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("old_timestamp.json", out_path, repo_root=repo)  # cairn.issue: PT-1
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        issues = {l["issue"] for l in read_jsonl(out_path)}
        self.assertEqual(issues, {"PT-1"}, "a milestone branch resolves to main, so the cairn.issue fallback must engage")


class MergeWithBackfillTests(unittest.TestCase):
    """Ruling §7/§8 -- append-only, own-source-only, non-overlap
    invariant."""

    def _seed_backfill_line(self, out_path: Path, generated: str, issue: str = "PT-1") -> dict:
        line = {
            "source": "transcript-backfill", "generated": generated,
            "window_start": "2026-08-18", "window_end": "2026-08-24",
            "issue": issue, "role": "implementation-lead", "model": "claude-sonnet-5",
            "input": 10, "cache_write": 20, "cache_read": 30, "output": 5, "records": 1,
        }
        out_path.write_text(json.dumps(line, separators=(",", ":")) + "\n", encoding="utf-8")
        return line

    def test_transcript_backfill_line_survives_a_receiver_flush_byte_for_byte(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        backfill_line = self._seed_backfill_line(out_path, generated="2026-08-01T00:00:00Z")

        result = ingest("basic.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        lines = read_jsonl(out_path)
        backfill_lines = [l for l in lines if l["source"] == "transcript-backfill"]
        otel_lines = [l for l in lines if l["source"] == "otel"]
        self.assertEqual(backfill_lines, [backfill_line], "the pre-existing transcript-backfill line must survive untouched")
        self.assertTrue(otel_lines, "the new otel contribution must also be present")

    def test_a_flush_predating_the_latest_backfill_generated_is_refused(self):
        # §8: non-overlap invariant. old_timestamp.json's datapoint is
        # 2024-01-01; seed a backfill line generated far AFTER that.
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        self._seed_backfill_line(out_path, generated="2026-12-31T00:00:00Z")

        result = ingest("old_timestamp.json", out_path)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("2026-12-31", combined, f"error must name the backfill's generated timestamp -- got: {combined!r}")


class MalformedPayloadTests(unittest.TestCase):
    """Both assertions here go beyond a bare nonzero-exit check
    deliberately: a receiver that doesn't even recognise `--ingest` yet
    (the WIP draft currently in the tree, pre-addendum) ALSO exits
    non-zero and touches no file, for a completely unrelated reason
    (argparse rejecting the whole invocation) -- confirmed by hand before
    writing this comment. A loose nonzero-exit-only assertion would pass
    against that accidentally, the same false-positive trap PT-77's own
    malformed-input tests were built to avoid."""

    def test_structurally_invalid_payload_is_rejected_without_writing(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        sentinel = '{"source":"otel","sentinel":true}\n'
        out_path.write_text(sentinel, encoding="utf-8")
        result = ingest("malformed_no_resource_metrics.json", out_path)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("resourceMetrics", combined, f"error must name the missing/malformed field -- got: {combined!r}")
        self.assertEqual(out_path.read_text(encoding="utf-8"), sentinel, "a rejected payload must leave a pre-existing --out-file untouched")

    def test_invalid_json_body_is_rejected_without_writing(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        payload_path = FIXTURES / "malformed_invalid_json.txt"
        result = run_receiver(["--ingest", str(payload_path), "--out-file", str(out_path)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        # "invalid choice" is argparse's OWN generic rejection message (the
        # WIP draft currently in the tree doesn't recognise --ingest at
        # all yet, and that message happens to echo the file path back
        # too) -- explicitly excluding it is what keeps this test from
        # passing against a --ingest that doesn't exist, only against one
        # that exists and does its own JSON-parsing rejection.
        self.assertNotIn("invalid choice", combined, f"this must be --ingest's OWN json-parse rejection, not argparse failing to recognise --ingest at all -- got: {combined!r}")
        self.assertIn(str(payload_path), combined, f"error must name the offending payload file -- got: {combined!r}")
        self.assertFalse(out_path.exists(), "invalid JSON must never produce a written file")


class LockContentionTests(unittest.TestCase):
    """PT-77's own `.lock` semantics (O_CREAT|O_EXCL, stale after 60s),
    reused by both writers per the ruling's §7."""

    def _seed_otel_line(self, out_path: Path) -> str:
        line = json.dumps({
            "source": "otel", "generated": "2026-08-01T00:00:00Z",
            "window_start": "2026-08-01", "window_end": "2026-08-01",
            "issue": "PT-1", "role": "team-lead", "model": "claude-sonnet-5",
            "input": 1, "cache_write": 1, "cache_read": 1, "output": 1, "records": 1,
        }, separators=(",", ":")) + "\n"
        out_path.write_text(line, encoding="utf-8")
        return line

    def test_a_fresh_lock_held_by_another_writer_defers_without_corrupting_existing_content(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        existing = self._seed_otel_line(out_path)
        lock_path = out_dir / ".lock"
        lock_path.write_text("held\n", encoding="utf-8")  # fresh -- just created

        result = ingest("basic.json", out_path)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("lock", combined.lower(), f"error must mention the lock contention specifically -- got: {combined!r}")
        self.assertEqual(out_path.read_text(encoding="utf-8"), existing, "a fresh lock held by another writer must leave existing content untouched")

    def test_a_stale_lock_older_than_sixty_seconds_is_reclaimed(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        lock_path = out_dir / ".lock"
        lock_path.write_text("stale\n", encoding="utf-8")
        stale_time = time.time() - 120  # 2 minutes -- past the 60s staleness window
        os.utime(lock_path, (stale_time, stale_time))

        result = ingest("basic.json", out_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr, "a stale lock must be reclaimed, allowing the flush to succeed")
        self.assertTrue(out_path.is_file())


class OutFileResolvesFromRepoRootTests(unittest.TestCase):
    """PT-77's blocking defect (0e8832c) and PT-80 exist because of
    exactly this failure mode -- the addendum explicitly calls it out for
    --out-file. Deliberately does NOT test the truly-default (unspecified
    --out-file) path: that would resolve to this real checkout's actual
    process/cairn/metrics/token-usage.jsonl, which already holds real
    committed PT-77 data and must never be touched by a test. Instead:
    an EXPLICIT --out-file (safe, isolated) plus a cwd outside the repo,
    asserting the OTHER repo-root-anchored resolution (branch regex
    prefix, via the real config.yml) still works correctly -- if cwd leaked
    into that resolution the way it did for PT-77/PT-80, this would
    misattribute or error instead of landing on PT-95."""

    def test_prefix_and_branch_resolution_do_not_depend_on_cwd(self):
        outside_cwd = helpers.make_empty_tmp_dir(self)
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = run_receiver(
            ["--ingest", str(FIXTURES / "no_cairn_issue.json"), "--out-file", str(out_path)],
            cwd=outside_cwd,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(out_path.is_file(), "a run from outside the repo must still write real output")
        issues = {l["issue"] for l in read_jsonl(out_path)}
        # This repo's real branch is whatever the shared checkout is
        # currently on (feature/pt-78-otel-receiver at time of writing) --
        # assert only that SOME real PT-NN issue was resolved, not "main",
        # since main would be the silent-collapse failure mode.
        self.assertTrue(issues, issues)
        self.assertNotEqual(issues, {"main"}, f"cwd outside the repo must not collapse attribution to main -- got {issues}")


class OnceIntegrationTests(unittest.TestCase):
    """The ONE test in this file that binds a real port -- every other
    assertion goes through --ingest per the addendum's own instruction.

    Judgment call, flagged: `--once`'s CLI signature (`[--port N]`) gives
    no way for an external test process to discover which port got bound
    if `--port 0` (ephemeral) were used, since `--once` is a one-shot
    subprocess, not an in-process object a test can introspect via
    `server.server_address[1]` the way `test_server.py` does for
    `cairn.make_server`. Rather than invent an unspecified "print the
    bound port" stdout protocol, this picks a FIXED high port
    (`48765 + PID % 1000`, spreading collisions across parallel runs) --
    matches how every other subprocess-CLI test in this suite that can't
    introspect a child's bound port has to work. A real, if small,
    flake risk (another process on the same port) that a `--port 0` +
    stdout-announcement contract would remove -- worth proposing to
    implementation-lead as a cheap addition (one `print(f"listening on
    127.0.0.1:{port}")`) if this test proves flaky in practice."""

    def test_once_accepts_one_request_flushes_and_exits(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        port = 48765 + (os.getpid() % 1000)
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH), "--once", "--port", str(port), "--out-file", str(out_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self._wait_until_listening(port)
            body = (FIXTURES / "basic.json").read_bytes()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/v1/metrics", body=body, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            response.read()
            self.assertLess(response.status, 300, "a well-formed payload must be accepted")

            stdout, stderr = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 0, f"stdout={stdout!r} stderr={stderr!r}")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        self.assertTrue(out_path.is_file(), "--once must flush to --out-file after handling its one request")
        issues = {l["issue"] for l in read_jsonl(out_path)}
        self.assertIn("PT-95", issues, f"expected basic.json's PT-95 line, got {issues}")

    def _wait_until_listening(self, port: int, timeout: float = 5.0):
        import socket

        deadline = time.time() + timeout
        last_exc = None
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError as e:
                last_exc = e
                time.sleep(0.05)
        self.fail(f"--once never started listening on 127.0.0.1:{port} within {timeout}s ({last_exc!r})")


class RoleResolutionTests(unittest.TestCase):
    """Amendment B (25d7a42): role resolves from `session.id` through a
    transcript-header lookup, not `agent.name`/`query_source`. Uses the
    proposed `--transcripts-dir` seam (see module docstring) pointed at
    `fixtures/otlp/transcripts/` -- never a real transcript, per the
    amendment's own "no test needs a real transcript" instruction."""

    TRANSCRIPTS_DIR = FIXTURES / "transcripts"

    def test_a_session_whose_transcript_has_an_agent_name_resolves_and_normalises_it(self):
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("role_resolver_two_sessions.json", out_path, transcripts_dir=self.TRANSCRIPTS_DIR)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        roles = {l["role"] for l in lines}
        self.assertIn("qa-engineer", roles, f"session-with-agentname.jsonl's agentName must resolve and normalise -- got roles {roles}")

    def test_amendment_b_explicit_test_one_stub_hit_one_guard_from_a_single_payload(self):
        # Amendment B's own "test to add": a resolver returning a role for
        # one session.id and nothing for another must produce ONE
        # resolved-role line and ONE subagent-unattributed line from a
        # SINGLE payload -- proving the guard survives and the fallback
        # does not quietly become team-lead. role_resolver_two_sessions.json
        # carries otel-role-test-session-with-agent (resolvable) and
        # otel-role-test-session-no-transcript-at-all (no matching file in
        # TRANSCRIPTS_DIR at all).
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("role_resolver_two_sessions.json", out_path, transcripts_dir=self.TRANSCRIPTS_DIR)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        roles = {l["role"] for l in lines}
        self.assertEqual(roles, {"qa-engineer", "subagent-unattributed"}, f"got {roles}")
        self.assertNotIn("team-lead", roles, "a session with no matching transcript file at all must never quietly fall to team-lead")

    def test_a_transcript_that_exists_with_no_agent_name_resolves_to_team_lead(self):
        # session-without-agentname.jsonl exists but carries no agentName
        # key at all -- amendment B step 4: file exists, no agentName in
        # the first 50 records -> team-lead (distinct from "no transcript
        # file at all" -> subagent-unattributed).
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest("role_resolver_lead_session.json", out_path, transcripts_dir=self.TRANSCRIPTS_DIR)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        roles = {l["role"] for l in read_jsonl(out_path)}
        self.assertEqual(roles, {"team-lead"}, roles)


if __name__ == "__main__":
    unittest.main()
