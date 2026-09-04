"""PT-77 failing acceptance tests: the one-time transcript token backfill.

Pinned to the architect's gating ruling, committed at 6eb4782 as a comment on
process/cairn/issues/PT-77.md -- that comment is authoritative for every
constant/shape below; this docstring is just the map from ruling section to
test.

Contract under test (`scripts/cairn/backfill_tokens.py`, run directly, not a
`cairn` subcommand):

- CLI flags: `--transcripts-dir PATH` (override; real default is
  `~/.claude/projects/<slug>`), `--out-file PATH`, `--dry-run`.
- Scans `**/*.jsonl` under the transcript dir recursively (subagent
  transcripts live in `<session>/subagents/agent-*.jsonl`).
- Keeps `type == "assistant"` records carrying `message.usage`; skips
  everything else silently, INCLUDING `message.model == "<synthetic>"`
  records (no real API call behind them).
- Dedupes globally (across every file in the scan, not per file) by
  `requestId`, falling back to `uuid` when `requestId` is absent.
- Buckets by issue -- `^(?:feature|chore)/<prefix>-(\\d+)(?![\\d.])`,
  case-insensitive, anchored, prefix from `process/cairn/config.yml`
  (`PT` in this repo); multi-issue branches attribute wholly to the FIRST
  id; anything else (including a `chore/pt-0.11-*` MILESTONE branch, guarded
  by the `(?![\\d.])` lookahead) -> `main`.
- Buckets by role -- `agentName`, default `team-lead`; normalises a
  trailing `-<digits>` suffix ONLY when the stem is a roster name
  (`.claude/agents/<stem>.md` exists) -- `qa-engineer-76` -> `qa-engineer`,
  but `impl2` (stem `impl`, not a roster file) stays verbatim.
- Fails loudly (non-zero exit, error names the file + line number, writes
  NOTHING) on: absent `gitBranch`, absent `message.model`, or any of the
  four usage counters missing FROM A PRESENT `message.usage` object
  (including a present-but-empty `usage: {}`). The ONE tolerated exception:
  a malformed/truncated FINAL line of a file (warn, skip, continue) -- a
  malformed line anywhere else in the file is a hard fail, same as a
  missing field. **Distinct from the above:** an `assistant` record whose
  `message.usage` KEY IS ABSENT ENTIRELY is not a fail case at all -- the
  architect's addendum (03f758e) step 2 bundles "carrying message.usage"
  into the KEEP filter itself, same tier as filtering out non-`assistant`
  types, so a usage-less assistant record is silently skipped, never
  validated, never reaches the fail-loudly step. Validation only applies
  to records that DID pass the keep filter (i.e. a `usage` key exists, even
  if empty or incomplete).
- Output: JSON Lines at `process/cairn/metrics/token-usage.jsonl` (or
  wherever `--out` points, for tests), one object per (source, issue, role,
  model) bucket-total line: `source`, `generated` (RFC3339 UTC, `Z`
  suffix), `window_start`/`window_end` (`YYYY-MM-DD`, inclusive --
  both DATA-derived: `window_start` is the earliest contributing record's
  date, `window_end` is the LATEST contributing record's date -- NOT the
  date portion of `generated` (struck by the architect's amendment,
  9e94514, which resolved a self-contradiction between the ruling's own
  §1 and §2: "generated already records the scrape moment; the only
  reading under which window_end earns its place in the schema is the
  data-derived one"). Both computed ONCE per run, contribution-wide, and
  repeated identically on every line of that run -- not per-bucket. The
  PT-78 non-overlap invariant keys on `generated`, not `window_end`, for
  this exact reason.), `issue`, `role`, `model`,
  `input`, `cache_write`, `cache_read`, `output` (the four AUTHORITATIVE
  counters), optionally `cache_write_5m`/`cache_write_1h`/`records`. No
  other keys -- in particular no `sessionId`/`requestId`/`uuid`/message
  content anywhere in the file. Lines ordered: issue numeric ascending,
  `main` last, then role, then model, then source.
- Merge semantics: totals are a plain sum over every line in the file. A
  regenerating source (backfill re-run) rewrites ONLY its own
  `source == "transcript-backfill"` lines (read all -> drop own-source
  lines -> append fresh ones -> temp + `os.replace`) -- lines from any
  OTHER source (e.g. a future `otel` line) survive untouched.

Nothing under test exists yet -- there is no `scripts/cairn/backfill_tokens.py`
file at all. Every CLI invocation below is expected to fail (nonexistent
script -> `python3: can't open file ...` -> exit 2) until implementation-lead
creates the script; this is a genuinely strong RED because the assertions go
well past a bare non-zero-exit check (matching content in the golden-path
runs; SPECIFIC substrings from the fixture, not the generic
missing-file message, on the fail-loudly runs) -- a run that fails only
because the script doesn't exist cannot accidentally satisfy them.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn

SCRIPT_PATH = helpers.CAIRN_DIR / "backfill_tokens.py"
TRANSCRIPTS_FIXTURES = helpers.FIXTURES_DIR / "transcripts"

# The exact schema keys the ruling allows -- "No other keys." Any output
# line's key set must be a subset of this.
ALLOWED_LINE_KEYS = {
    "source", "generated", "window_start", "window_end",
    "issue", "role", "model",
    "input", "cache_write", "cache_read", "output",
    "cache_write_5m", "cache_write_1h", "records",
}
REQUIRED_LINE_KEYS = {
    "source", "generated", "window_start", "window_end",
    "issue", "role", "model", "input", "cache_write", "cache_read", "output",
}

# Substrings that must NEVER appear anywhere in the output file -- the
# privacy scope ruling ("no transcript content, no prompts, no tool output,
# no message text, no session ids"). Every one of these is a literal id or
# content string planted in the golden fixture; a leak has somewhere
# concrete to leak FROM.
FORBIDDEN_SUBSTRINGS = [
    "sessionId", "requestId", "uuid",
    "fake-session-a", "fake-session-b", "fake-session-c", "fake-session-e",
    "req-lead-1", "uuid-lead-1", "req-role2-1", "req-main-1",
    "req-qa76-1", "req-impl-1", "uuid-fallback-1", "req-subagent-1",
    "req-multi-issue-1", "req-impllead2-1",
    "synthetic placeholder user turn",
]


def run_backfill(
    args: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True, text=True,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )


def read_jsonl(path: Path) -> list[dict]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            lines.append(json.loads(raw))
    return lines


def bucket_map(lines: list[dict]) -> dict[tuple[str, str, str], dict]:
    """(issue, role, model) -> line, asserting no accidental duplicate
    bucket keys within a single output (merge semantics operate on whole
    lines, one line per bucket per source)."""
    out: dict[tuple[str, str, str], dict] = {}
    for line in lines:
        key = (line["issue"], line["role"], line["model"])
        assert key not in out, f"duplicate bucket line for {key!r} -- bucketing must fold into ONE line per (issue, role, model, source)"
        out[key] = line
    return out


class BackfillGoldenPathTests(unittest.TestCase):
    """Runs against fixtures/transcripts/golden/ -- the kitchen-sink
    synthetic tree covering every case named in both the original AC5 list
    and the architect's own QA fixture-case list (duplicate requestId
    across two files, a lead record with no agentName, a nested
    subagents/agent-*.jsonl record, a main record, agentName:
    qa-engineer-76, model: "<synthetic>", an uppercase feature/PT-47
    branch, a chore/pt-0.11-* milestone branch).

    RESTRUCTURED (PT-87, architect's per-test ruling at 4bd40f9, on top
    of the addendum at 0aa49be): role resolution moved from per-record
    to per-FILE (both agentName and the new agentSetting are measured
    session-constant on every real transcript -- 0/53 and 0/69 vary
    within a file). The four original files here each mixed several
    DIFFERENT agentName values across their records -- a shape real
    transcripts never produce -- so each now lives as several
    single-role files instead. Every field VALUE (branch, requestId,
    uuid, model, usage counters, timestamp) is preserved byte-for-byte
    from the original session-a/b/c/e.jsonl; only which FILE each
    record lives in changed. The 9 hand-counted bucket totals below are
    therefore unchanged from before the split -- re-derived by hand from
    these fixture files' own record contents, NOT recomputed from the
    implementation's own output (the architect's explicit warning: a
    total computed from the code under test proves only
    self-consistency)."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.out_path = self.tmp / "token-usage.jsonl"

    def _run_golden(self, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
        return run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "golden"),
            "--out-file", str(self.out_path),
            *(extra_args or []),
        ])

    def test_exits_zero_and_writes_the_output_file(self):
        result = self._run_golden()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.out_path.is_file(), "backfill must write --out on a clean run")

    def test_bucketing_by_issue_role_and_model_matches_the_hand_counted_totals(self):
        # Hand-derived from the golden fixture -- see this file's module
        # docstring / the fixture files themselves for how each of these
        # 9 buckets was built. Every count below is the value of the
        # single (deduped) contributing record for that bucket.
        result = self._run_golden()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(self.out_path)
        buckets = bucket_map(lines)

        expected = {
            ("PT-7", "impl2", "claude-sonnet-5"): (3, 4, 5, 1),
            ("PT-28", "team-lead", "claude-sonnet-5"): (100, 200, 300, 50),
            ("PT-28", "backend-lead", "claude-fable-5-1"): (10, 20, 30, 5),
            ("PT-28", "qa-engineer", "claude-sonnet-5"): (50, 60, 70, 20),
            ("PT-28", "implementation-lead", "claude-sonnet-5"): (6, 7, 8, 2),
            ("PT-47", "qa-engineer", "claude-sonnet-5"): (11, 22, 33, 4),
            ("PT-90", "team-lead", "claude-sonnet-5"): (15, 16, 17, 3),
            ("main", "team-lead", "claude-sonnet-5"): (7, 8, 9, 2),
            ("main", "impl", "claude-sonnet-5"): (5, 6, 7, 1),
        }
        self.assertEqual(set(buckets.keys()), set(expected.keys()), buckets)
        for key, (inp, cw, cr, out) in expected.items():
            line = buckets[key]
            self.assertEqual(line["input"], inp, key)
            self.assertEqual(line["cache_write"], cw, key)
            self.assertEqual(line["cache_read"], cr, key)
            self.assertEqual(line["output"], out, key)

    def test_dedupe_by_request_id_across_files_counts_the_pair_once(self):
        # req-lead-1 appears in BOTH team_lead_pt28.jsonl and
        # team_lead_pt28_dup.jsonl (different uuid each time, same
        # requestId, same values -- the architect measured zero
        # disagreeing duplicates in the real corpus). Both files resolve
        # to the SAME role (team-lead, no name field in either) --
        # deliberate, per the architect's per-test ruling (4bd40f9): a
        # cross-file dedupe pair spanning two DIFFERENT roles would be
        # order-dependent under per-file resolution (whichever file the
        # scan reaches first keeps the contribution). Global cross-file
        # dedupe must fold this pair to ONE record, not two -- caught by
        # both the totals (100, not 200) and `records` if the script
        # fills that optional field.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        buckets = bucket_map(lines)
        line = buckets[("PT-28", "team-lead", "claude-sonnet-5")]
        self.assertEqual(line["input"], 100, "duplicate requestId across two files must be deduped, not double-counted")
        if "records" in line:
            self.assertEqual(line["records"], 1, "exactly one unique requestId contributed to this bucket")

    def test_dedupe_fallback_to_uuid_when_request_id_is_absent(self):
        # team_lead_pt90.jsonl and team_lead_pt90_dup.jsonl both omit
        # `requestId` entirely and share the same `uuid` -- dedupe must
        # fall back to uuid and still fold this pair to one contribution.
        # Both files are nameless (team-lead) -- same same-role
        # constraint as the requestId dedupe pair above, and deliberately
        # NOT bundled into golden/subagents/agent-1.jsonl (which carries
        # a real qa-engineer record) for the same reason.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        buckets = bucket_map(lines)
        line = buckets[("PT-90", "team-lead", "claude-sonnet-5")]
        self.assertEqual(line["input"], 15, "uuid-fallback dedupe must fold the pair sharing uuid-fallback-1 to one contribution")
        if "records" in line:
            self.assertEqual(line["records"], 1)

    def test_role_defaults_to_team_lead_when_agent_name_is_absent(self):
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        buckets = bucket_map(lines)
        self.assertIn(("PT-28", "team-lead", "claude-sonnet-5"), buckets)
        self.assertIn(("main", "team-lead", "claude-sonnet-5"), buckets)

    def test_roster_suffixed_role_name_is_normalised(self):
        # agentName "qa-engineer-76" -- stem "qa-engineer" IS a roster
        # file (.claude/agents/qa-engineer.md) -- must normalise to
        # "qa-engineer", not stay "qa-engineer-76". Architect's own
        # warning (per-test ruling, 4bd40f9): a bare "'qa-engineer' is
        # SOMEWHERE in the output" check would pass even if the
        # stripping rule were never exercised, since golden/subagents/
        # agent-1.jsonl ALSO produces role "qa-engineer" via a plain,
        # unrelated, no-stripping-needed pass-through. Scoped to the
        # PT-47 bucket specifically -- the ONE bucket only
        # qa_engineer_suffix_stripped_pt47.jsonl's stripped record can
        # produce -- so this test can only pass for the right reason.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        buckets = bucket_map(lines)
        self.assertIn(
            ("PT-47", "qa-engineer", "claude-sonnet-5"), buckets,
            "qa-engineer-76's stem (qa-engineer) IS a roster name -- must normalise, and PT-47 is the only "
            "bucket this specific record can produce",
        )
        roles = {line["role"] for line in lines}
        self.assertNotIn("qa-engineer-76", roles)

    def test_adhoc_role_name_stays_verbatim_even_with_a_trailing_digit(self):
        # agentName "impl2" -- stripping a trailing -<digits> gives stem
        # "impl", which is NOT a roster file -- must stay "impl2"
        # verbatim, not get folded to "impl" or stripped at all. Separately,
        # "impl" (impl_adhoc_milestone_branch_main.jsonl, no trailing
        # digit) is unambiguously ad-hoc and must also stay verbatim.
        # Both roles are unique to their own fixture file -- no other
        # record produces "impl2" or "impl", so no scoping ambiguity.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        roles = {line["role"] for line in lines}
        self.assertIn("impl2", roles, "impl2's stem (impl) is not a roster name -- must not be normalised")
        self.assertIn("impl", roles)

    def test_roster_suffixed_role_with_multi_word_stem_is_normalised(self):
        # agentName "implementation-lead-2" -- stem "implementation-lead"
        # IS a roster file -- must normalise to "implementation-lead".
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        roles = {line["role"] for line in lines}
        self.assertIn("implementation-lead", roles)
        self.assertNotIn("implementation-lead-2", roles)

    def test_main_bucket_is_kept_separate_not_spread_across_issues(self):
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        issues = {line["issue"] for line in lines}
        self.assertIn("main", issues)
        # A phase/* branch (team_lead_main.jsonl) and a chore/pt-0.11-*
        # MILESTONE branch (impl_adhoc_milestone_branch_main.jsonl) both
        # land in main, not PT-0 or PT-0.11 -- only a genuine numeric
        # issue id or "main" may appear.
        for issue in issues:
            self.assertTrue(
                issue == "main" or (issue.startswith("PT-") and issue[3:].isdigit()),
                f"unexpected issue bucket {issue!r} -- a milestone branch (chore/pt-0.11-*) must land in main, not a fabricated PT-0/PT-0.11",
            )

    def test_case_insensitive_uppercase_branch_still_buckets(self):
        # qa_engineer_suffix_stripped_pt47.jsonl's record is on
        # "feature/PT-47" (uppercase, no trailing slug) -- must still
        # bucket to PT-47.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        issues = {line["issue"] for line in lines}
        self.assertIn("PT-47", issues)

    def test_multi_issue_branch_attributes_wholly_to_the_first_id(self):
        # feature/pt-7-8-9-13-cli-hardening -- must land entirely on PT-7,
        # never split or attributed to PT-8/PT-9/PT-13.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        issues = {line["issue"] for line in lines}
        self.assertIn("PT-7", issues)
        self.assertNotIn("PT-8", issues)
        self.assertNotIn("PT-9", issues)
        self.assertNotIn("PT-13", issues)

    def test_subagent_record_in_nested_subdirectory_is_picked_up(self):
        # golden/subagents/agent-1.jsonl -- must be found by the
        # recursive scan, not just top-level *.jsonl files. Deliberately
        # the ONLY record in that file (see its own comment in the
        # fixture-generation script/commit message) -- a nameless
        # (team-lead) record used to share this file and was moved out
        # specifically so this file resolves to exactly one role.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        buckets = bucket_map(lines)
        self.assertIn(("PT-28", "qa-engineer", "claude-sonnet-5"), buckets)

    def test_two_roles_two_models_on_one_issue_are_kept_distinct(self):
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        pt28_lines = [line for line in lines if line["issue"] == "PT-28"]
        role_model_pairs = {(line["role"], line["model"]) for line in pt28_lines}
        self.assertIn(("team-lead", "claude-sonnet-5"), role_model_pairs)
        self.assertIn(("backend-lead", "claude-fable-5-1"), role_model_pairs)
        self.assertGreaterEqual(len(role_model_pairs), 2, "PT-28 must carry at least two distinct role/model pairs, not one merged bucket")

    def test_non_assistant_record_with_no_usage_is_skipped_without_error(self):
        # non_assistant_no_usage.jsonl's type:"user" record carries no
        # message.usage at all -- must be silently skipped, must NOT
        # trigger the fail-loudly path (that's reserved for a malformed
        # ASSISTANT record).
        result = self._run_golden()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_assistant_record_with_no_usage_key_at_all_is_skipped_not_a_hard_fail(self):
        # Separate, dedicated fixture (not the kitchen-sink golden one):
        # an otherwise-complete `assistant` record whose `message` has NO
        # `usage` key at all. Per the architect's addendum (03f758e) step
        # 2, "carrying message.usage" is part of the KEEP filter itself --
        # same tier as filtering out a non-assistant type -- so this is a
        # SILENT SKIP, not the fail-loudly path (that's reserved for a
        # record whose `usage` key IS present but incomplete/empty).
        result = run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "skipped_no_usage_key"),
            "--out-file", str(self.out_path),
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if self.out_path.exists():
            lines = read_jsonl(self.out_path)
            backfill_lines = [line for line in lines if line.get("source") == "transcript-backfill"]
            self.assertEqual(backfill_lines, [], "a usage-key-less assistant record must not produce any output bucket")

    def test_synthetic_model_record_is_skipped_and_not_counted(self):
        # synthetic_model_filtered.jsonl's model:"<synthetic>" record has
        # no requestId, all-zero usage -- must be filtered before
        # dedupe/bucketing, not counted anywhere (including not silently
        # folded into PT-28 via uuid fallback).
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        total_records = sum(line.get("records", 1) for line in lines)
        # 9 real contributing records total (see the bucketing test); the
        # <synthetic> record and the type:"user" record must not appear
        # in this count under any bucket.
        self.assertEqual(total_records, 9, "the <synthetic>-model record and the non-assistant record must not be counted anywhere")

    def test_output_contains_no_session_ids_uuids_or_message_text(self):
        result = self._run_golden()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        raw = self.out_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(forbidden, raw, f"{forbidden!r} leaked into the committed output -- privacy scope ruling forbids any transcript-internal id or message content")

    def test_output_lines_carry_only_the_allowed_schema_keys(self):
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        self.assertTrue(lines, "golden fixture must produce at least one output line")
        for line in lines:
            extra = set(line.keys()) - ALLOWED_LINE_KEYS
            self.assertFalse(extra, f"unexpected keys in output line: {extra} -- ruling says 'No other keys.'")
            missing = REQUIRED_LINE_KEYS - set(line.keys())
            self.assertFalse(missing, f"missing required keys in output line: {missing}")
            self.assertEqual(line["source"], "transcript-backfill")

    def test_window_start_is_the_earliest_record_date_not_today(self):
        # Earliest surviving record in the golden fixture is
        # impl_adhoc_milestone_branch_main.jsonl's chore/pt-0.11-* line,
        # timestamped 2026-08-18T07:00:00Z.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        window_starts = {line["window_start"] for line in lines}
        self.assertEqual(window_starts, {"2026-08-18"}, "window_start must be the earliest contributing record's date, uniform across every line of one run")

    def test_window_end_is_the_latest_record_date_not_generated(self):
        # Architect's amendment (9e94514) struck the ruling's original §2
        # sentence ("the backfill sets window_end to its generated date")
        # as self-contradictory with §1 -- window_end is DATA-derived: the
        # latest contributing record's date. Golden fixture's latest
        # surviving record is 2026-08-24 (golden/subagents/agent-1.jsonl,
        # the nested subagent record), well before whatever "today"
        # (generated's date) happens to be --
        # the exact shape the amendment calls out as the real
        # discriminator (a struck "use generated" implementation would
        # produce today's date here, not 2026-08-24).
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        window_ends = {line["window_end"] for line in lines}
        self.assertEqual(window_ends, {"2026-08-24"}, "window_end must be the latest contributing record's date, not generated's date")
        self.assertNotEqual(window_ends, {today}, "window_end must not silently equal today -- that would be the struck reading")

    def test_window_end_tracks_the_record_not_the_clock_on_a_dedicated_fixture(self):
        # The architect explicitly asked for this: "a run whose newest
        # record is well before generated, asserting window_end tracks
        # the record and not the clock. That is exactly the case the
        # struck sentence would have got wrong." Isolated 2-record fixture
        # so the discriminator is impossible to miss (both dates are
        # 2026-07, guaranteed months before any real test run's "today").
        tmp = helpers.make_empty_tmp_dir(self)
        out_path = tmp / "token-usage.jsonl"
        result = run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "window_end"),
            "--out-file", str(out_path),
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        self.assertTrue(lines)
        window_starts = {line["window_start"] for line in lines}
        window_ends = {line["window_end"] for line in lines}
        self.assertEqual(window_starts, {"2026-07-01"})
        self.assertEqual(window_ends, {"2026-07-15"})

    def test_every_line_in_one_run_carries_the_identical_window_pair(self):
        # Contribution-wide, not per-bucket (architect's amendment): one
        # (window_start, window_end) pair computed once across the whole
        # run and repeated on every line, regardless of which bucket that
        # line belongs to.
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        self.assertTrue(lines)
        pairs = {(line["window_start"], line["window_end"]) for line in lines}
        self.assertEqual(len(pairs), 1, f"every line of one run must share the exact same (window_start, window_end) pair, got {pairs}")

    def test_generated_timestamp_is_rfc3339_utc_with_z_suffix(self):
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        generated_values = {line["generated"] for line in lines}
        self.assertEqual(len(generated_values), 1, "every line from one run must share the same generated timestamp")
        generated = next(iter(generated_values))
        self.assertRegex(generated, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", "generated must be RFC3339 UTC with a Z suffix")

    def test_line_order_is_deterministic_issue_ascending_main_last(self):
        result = self._run_golden()
        lines = read_jsonl(self.out_path)
        issue_sequence = [line["issue"] for line in lines]
        numeric_part = [i for i in issue_sequence if i != "main"]
        self.assertEqual(
            numeric_part,
            sorted(numeric_part, key=lambda i: int(i.split("-")[1])),
            "issue buckets must sort numerically ascending",
        )
        if "main" in issue_sequence:
            self.assertEqual(issue_sequence[-1], "main", "main must sort last, not interleaved with numeric issues")

    def test_dry_run_prints_a_summary_and_writes_nothing(self):
        result = self._run_golden(["--dry-run"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.out_path.exists(), "--dry-run must never create --out")
        self.assertTrue((result.stdout + result.stderr).strip(), "--dry-run must print a summary somewhere")

    def test_cairn_check_still_passes_after_the_output_file_is_written(self):
        # AC7: `cairn check` passes. process/cairn/metrics/ is a new
        # top-level subdir cairn's engine has never seen before -- confirm
        # check_repo tolerates it rather than choking on an unrecognised
        # entry.
        data_dir = helpers.make_tmp_data_dir(self)
        metrics_dir = data_dir / "metrics"
        metrics_dir.mkdir()
        out_path = metrics_dir / "token-usage.jsonl"
        result = run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "golden"),
            "--out-file", str(out_path),
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        errors = cairn.check_repo(data_dir)
        self.assertEqual(errors, [], "cairn check must stay clean with process/cairn/metrics/token-usage.jsonl present")


class BackfillOrderingTests(unittest.TestCase):
    """Isolated fixture (4 records, 3 buckets) purely for the line-order
    tiebreak -- kept separate from the kitchen-sink golden fixture so this
    assertion doesn't ride on the golden fixture's larger, harder-to-eyeball
    bucket set.

    RESTRUCTURED (PT-87, architect's per-test ruling, row 8: "Two files,
    same issue"): per-file role resolution means the original single
    4-record file (agentName zzz-role/aaa-role/aaa-role/aaa-role across
    its records) can no longer produce two roles from one file. Split
    into 4 single-role files -- the PT-5 pair (zzz_role_pt5.jsonl,
    aaa_role_pt5.jsonl) is the one that must stay two SEPARATE files to
    prove "role lexicographic within one issue" at all; PT-2 and main
    each only ever needed one role and one record. Every value/timestamp
    preserved from the original ordering/session.jsonl."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.out_path = self.tmp / "token-usage.jsonl"

    def test_role_ordering_within_one_issue_is_lexicographic(self):
        result = run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "ordering"),
            "--out-file", str(self.out_path),
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(self.out_path)
        sequence = [(line["issue"], line["role"]) for line in lines]
        self.assertEqual(
            sequence,
            [("PT-2", "aaa-role"), ("PT-5", "aaa-role"), ("PT-5", "zzz-role"), ("main", "aaa-role")],
            "expected order: issue numeric ascending, main last, role lexicographic within an issue",
        )


class BackfillFailLoudlyTests(unittest.TestCase):
    """Every case here must (a) exit non-zero, (b) name something SPECIFIC
    to the fixture/failure (not just the generic python
    can't-open-the-script message, which would let these tests pass
    trivially before the script even exists), and (c) leave a pre-existing
    --out file byte-for-byte untouched -- 'the script fails loudly on a
    missing field; it never silently under-counts' (AC4) means nothing
    partial gets written either."""

    def _run_against(self, fixture_name: str, out_path: Path) -> subprocess.CompletedProcess:
        return run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / fixture_name),
            "--out-file", str(out_path),
        ])

    def _assert_hard_fail_leaves_sentinel_untouched(self, fixture_name: str, must_mention: list[str]):
        tmp = helpers.make_empty_tmp_dir(self)
        out_path = tmp / "token-usage.jsonl"
        sentinel = '{"source":"otel","sentinel":true}\n'
        out_path.write_text(sentinel, encoding="utf-8")

        result = self._run_against(fixture_name, out_path)
        self.assertNotEqual(result.returncode, 0, f"{fixture_name} must exit non-zero: {result.stdout + result.stderr}")
        combined = result.stdout + result.stderr
        for token in must_mention:
            self.assertIn(token, combined, f"error output must name {token!r} specifically (not just a generic failure) -- got: {combined!r}")
        self.assertEqual(out_path.read_text(encoding="utf-8"), sentinel, "a hard-fail run must leave a pre-existing --out file completely untouched")

    def test_empty_usage_object_fails_loudly(self):
        # `message.usage` key IS present but empty (`{}`) -- distinct from
        # the skipped_no_usage_key fixture (no `usage` key at all, a
        # silent skip per the architect's addendum). A present-but-empty
        # usage object passes the keep filter and must hard-fail
        # validation (all four counters missing).
        self._assert_hard_fail_leaves_sentinel_untouched(
            "malformed_empty_usage_object", must_mention=["session.jsonl"],
        )

    def test_missing_one_of_the_four_counters_fails_loudly(self):
        self._assert_hard_fail_leaves_sentinel_untouched(
            "malformed_missing_counter", must_mention=["session.jsonl"],
        )

    def test_missing_git_branch_fails_loudly(self):
        self._assert_hard_fail_leaves_sentinel_untouched(
            "malformed_missing_branch", must_mention=["session.jsonl"],
        )

    def test_missing_model_fails_loudly(self):
        self._assert_hard_fail_leaves_sentinel_untouched(
            "malformed_missing_model", must_mention=["session.jsonl"],
        )

    def test_malformed_json_line_in_the_middle_of_a_file_is_a_hard_fail(self):
        # Distinct from the tolerated-truncated-LAST-line case below --
        # this garbage line sits at line 2 of 3, with a valid line
        # following it. The tolerance is specifically for a file caught
        # mid-flush at EOF, not for garbage anywhere in the file.
        self._assert_hard_fail_leaves_sentinel_untouched(
            "malformed_middle_of_file", must_mention=["session.jsonl"],
        )

    def test_missing_transcript_dir_is_a_loud_error_never_an_empty_result(self):
        tmp = helpers.make_empty_tmp_dir(self)
        out_path = tmp / "token-usage.jsonl"
        nonexistent = tmp / "does-not-exist-at-all"
        result = run_backfill(["--transcripts-dir", str(nonexistent), "--out-file", str(out_path)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(out_path.exists(), "a missing transcript dir must never produce an (empty) output file -- 'no data here' and 'no tracker here' must not render identically")


class BackfillWorkingDirectoryAndConfigResolutionTests(unittest.TestCase):
    """Architect's blocking finding on the 99725d0 review (0e8832c): the
    tracker prefix was resolved via `cairn.find_data_dir()`, which walks up
    from `Path.cwd()` rather than the repo root the script already
    computes. Combined with `load_config`'s SILENT default of
    `prefix: "ISS"` when `config.yml` is missing, a run from outside the
    repo collapses every issue bucket into `main` at exit 0 -- a total
    mis-attribution that looks like a successful run, exactly what AC4
    exists to prevent. Every OTHER test in this file runs with an implicit
    cwd of the repo root (subprocess.run inherits the parent's cwd), so
    none of them could ever have caught this -- these three are the ones
    that actually vary cwd/CAIRN_DATA_DIR."""

    def test_cwd_outside_the_repo_still_resolves_issue_buckets_correctly(self):
        # The architect's own repro: same script, same fixtures, cwd =
        # somewhere outside the repo -- must still see real PT-N buckets,
        # not collapse to ['main'] only. --transcripts-dir/--out-file are
        # absolute paths, so only the PREFIX resolution (which depends on
        # finding process/cairn/config.yml) is under test here.
        outside_cwd = helpers.make_empty_tmp_dir(self)
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"

        result = run_backfill(
            ["--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "golden"), "--out-file", str(out_path)],
            cwd=outside_cwd,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(out_path.is_file(), "a run from outside the repo must still write real output, not silently produce nothing")
        lines = read_jsonl(out_path)
        issues = {line["issue"] for line in lines}
        self.assertTrue(
            any(issue != "main" for issue in issues),
            f"cwd outside the repo must not collapse every issue bucket into 'main' -- got {issues!r}. "
            f"This is the architect's blocking finding on 99725d0: the prefix must resolve from the "
            f"script's own repo root, not from cwd via cairn.find_data_dir().",
        )
        self.assertIn("PT-28", issues, "the golden fixture's PT-28 records must still bucket correctly regardless of cwd")

    def test_cairn_data_dir_pointing_at_a_dir_with_no_config_yml_is_a_loud_error(self):
        # CAIRN_DATA_DIR is a real seam (cairn.py itself honors it) -- but
        # per the architect's required fix, pointing it at a directory
        # with NO config.yml must be a loud, named error (exit 1, message
        # names the path), never the silent prefix:"ISS" fallback
        # cairn.load_config provides for every OTHER cairn.py caller.
        bogus_data_dir = helpers.make_empty_tmp_dir(self)  # deliberately no config.yml inside
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        # A WELL-FORMED pre-existing line -- deliberately not the minimal
        # sentinel used elsewhere in this file. A minimal/incomplete
        # sentinel here would confound this test with the unrelated
        # architect's-minor-2 bug (a malformed existing line crashing
        # _sort_key with a raw KeyError) instead of cleanly isolating the
        # CAIRN_DATA_DIR/prefix-resolution bug this test targets -- verified
        # by hand against 99725d0: a minimal sentinel crashes on missing
        # "issue" before ever reaching the prefix-resolution code path.
        sentinel = json.dumps({
            "source": "otel", "generated": "2026-09-01T00:00:00Z",
            "window_start": "2026-09-01", "window_end": "2026-09-01",
            "issue": "PT-1", "role": "frontend-lead", "model": "claude-sonnet-5",
            "input": 1, "cache_write": 1, "cache_read": 1, "output": 1,
        }) + "\n"
        out_path.write_text(sentinel, encoding="utf-8")

        env = dict(os.environ)
        env["CAIRN_DATA_DIR"] = str(bogus_data_dir)
        result = run_backfill(
            ["--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "golden"), "--out-file", str(out_path)],
            env=env,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn(str(bogus_data_dir), combined, f"error must name the offending path -- got: {combined!r}")
        self.assertEqual(out_path.read_text(encoding="utf-8"), sentinel, "a loud config-resolution error must leave a pre-existing --out-file completely untouched")

    def test_existing_output_line_missing_role_fails_cleanly_not_a_traceback(self):
        # Architect's minor 2: an existing (foreign-source) line missing a
        # required key (role) currently raises a bare KeyError out of the
        # sort key, dumping a Python traceback. Required: a clean,
        # named BackfillError-style message instead -- still exit
        # non-zero, still nothing corrupted (the atomic write means the
        # bad pre-existing content itself must also survive untouched,
        # same contract as every other hard-fail path in this file).
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        broken_foreign_line = '{"source":"otel","generated":"2026-09-01T00:00:00Z","window_start":"2026-09-01","window_end":"2026-09-01","issue":"PT-1","model":"claude-sonnet-5","input":1,"cache_write":1,"cache_read":1,"output":1}\n'
        out_path.write_text(broken_foreign_line, encoding="utf-8")  # no "role" key

        result = run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "golden"),
            "--out-file", str(out_path),
        ])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertNotIn("Traceback (most recent call last)", combined, f"a malformed existing line must produce a clean, named error, not a raw Python traceback -- got: {combined!r}")
        self.assertIn("role", combined, f"the error should name the specific missing field -- got: {combined!r}")
        self.assertEqual(out_path.read_text(encoding="utf-8"), broken_foreign_line, "a hard-fail on a malformed existing line must leave the file completely untouched")


class BackfillTruncatedFinalLineTests(unittest.TestCase):
    """The ONE tolerated skip: a malformed final line, warned about and
    skipped, run still succeeds and still writes real output for every
    OTHER valid record in the file."""

    def test_truncated_final_line_is_tolerated_and_the_valid_line_still_counts(self):
        tmp = helpers.make_empty_tmp_dir(self)
        out_path = tmp / "token-usage.jsonl"
        result = run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "tolerated_truncated_last_line"),
            "--out-file", str(out_path),
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(out_path.is_file())
        lines = read_jsonl(out_path)
        buckets = bucket_map(lines)
        self.assertIn(("PT-15", "team-lead", "claude-sonnet-5"), buckets)
        line = buckets[("PT-15", "team-lead", "claude-sonnet-5")]
        self.assertEqual(line["input"], 9)
        self.assertEqual(line["cache_write"], 8)
        self.assertEqual(line["cache_read"], 7)
        self.assertEqual(line["output"], 6)
        # A warning about the skip should surface somewhere, even on a
        # successful run -- not required to match exact wording, just
        # that the run isn't silent about dropping a line.
        self.assertTrue((result.stdout + result.stderr).strip(), "a tolerated skip should still be visible to the operator, even on a zero exit")


class BackfillMergeSemanticsTests(unittest.TestCase):
    """Re-running the backfill against an --out that already has content
    must rewrite ONLY its own source's lines. A line from a different
    source (simulating a future PT-78 'otel' contribution) must survive
    byte-for-byte; a STALE prior transcript-backfill line for a bucket the
    current scan no longer produces must be dropped, not accumulated
    alongside the fresh one."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.out_path = self.tmp / "token-usage.jsonl"

    def _golden_run(self) -> subprocess.CompletedProcess:
        return run_backfill([
            "--transcripts-dir", str(TRANSCRIPTS_FIXTURES / "golden"),
            "--out-file", str(self.out_path),
        ])

    def test_otel_source_line_survives_a_backfill_rerun_untouched(self):
        otel_line = {
            "source": "otel", "generated": "2026-09-01T00:00:00Z",
            "window_start": "2026-09-01", "window_end": "2026-09-01",
            "issue": "PT-12", "role": "frontend-lead", "model": "claude-sonnet-5",
            "input": 999, "cache_write": 888, "cache_read": 777, "output": 666,
        }
        self.out_path.write_text(json.dumps(otel_line, separators=(",", ":")) + "\n", encoding="utf-8")

        result = self._golden_run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        lines = read_jsonl(self.out_path)
        otel_lines = [line for line in lines if line["source"] == "otel"]
        self.assertEqual(len(otel_lines), 1, "the pre-existing otel line must survive the backfill's own-source-only rewrite")
        self.assertEqual(otel_lines[0], otel_line, "an appending source's line must be byte-for-byte untouched by a regenerating source's rewrite")

        backfill_lines = [line for line in lines if line["source"] == "transcript-backfill"]
        self.assertTrue(backfill_lines, "the golden fixture's own contributions must still be present alongside the preserved otel line")

    def test_stale_backfill_line_for_a_bucket_no_longer_scanned_is_dropped_not_accumulated(self):
        stale_backfill_line = {
            "source": "transcript-backfill", "generated": "2026-08-01T00:00:00Z",
            "window_start": "2026-07-01", "window_end": "2026-08-01",
            "issue": "PT-99", "role": "somebody-who-left", "model": "some-old-model",
            "input": 1, "cache_write": 1, "cache_read": 1, "output": 1,
        }
        self.out_path.write_text(json.dumps(stale_backfill_line, separators=(",", ":")) + "\n", encoding="utf-8")

        result = self._golden_run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        lines = read_jsonl(self.out_path)
        pt99_lines = [line for line in lines if line["issue"] == "PT-99"]
        self.assertEqual(pt99_lines, [], "a stale transcript-backfill line for a bucket the CURRENT scan doesn't produce must be dropped on rewrite, not accumulated forever")

    def test_rerunning_against_the_same_transcripts_is_idempotent(self):
        first = self._golden_run()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_lines = read_jsonl(self.out_path)
        first_backfill = sorted(
            [line for line in first_lines if line["source"] == "transcript-backfill"],
            key=lambda line: (line["issue"], line["role"], line["model"]),
        )

        second = self._golden_run()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        second_lines = read_jsonl(self.out_path)
        second_backfill = sorted(
            [line for line in second_lines if line["source"] == "transcript-backfill"],
            key=lambda line: (line["issue"], line["role"], line["model"]),
        )

        self.assertEqual(len(second_backfill), len(first_backfill), "a rerun over unchanged transcripts must not duplicate bucket lines")
        for a, b in zip(first_backfill, second_backfill):
            for counter in ("input", "cache_write", "cache_read", "output"):
                self.assertEqual(a[counter], b[counter], f"{a['issue']}/{a['role']}/{a['model']} {counter} changed across an idempotent rerun")


if __name__ == "__main__":
    unittest.main()
