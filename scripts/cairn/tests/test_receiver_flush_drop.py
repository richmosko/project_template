"""PT-89 failing acceptance tests: `otel_receiver.flush()` drops only the
datapoints/groups that predate the backfill's `generated` stamp, instead
of refusing the WHOLE batch (and then never flushing again for the life
of the process).

Pinned to the architect's gating ruling, process/cairn/issues/PT-89.md
("@architect -- 2026-09-05", commit 0fd8774) -- read it before anything
else. Two premises in the issue itself don't survive the code (measured
by the architect, not assumed):

- `start_ns` (`startTimeUnixNano`) is the metric STREAM's start, not the
  datapoint's own time -- under cumulative temporality that's effectively
  the exporting process's start, so a filter keyed on it would drop a
  long-running session's entire series, including everything that
  accrued AFTER the stamp.
- `group_max` retains no per-datapoint time at all (only a running max
  value) -- there is nothing per-datapoint left to filter once folded.

## The actual fix shape (§2)

`ReceiverState.group_time_bounds[(series_key, start_ns)] = (min_time_ns,
max_time_ns)`, recorded at fold time in the SAME loop that already
updates `group_max`. At flush time, each GROUP is classified against
`stamp_ns` (the backfill's `generated`, converted to ns at the START of
that second):

    min_time_ns >= stamp_ns   -> keep   (entirely after the regen)
    max_time_ns <  stamp_ns   -> drop   (entirely before -- already
                                          counted by the backfill)
    otherwise (straddling)    -> drop, counted SEPARATELY from the
                                  clean `dropped` count -- the group's
                                  value is an aggregate that cannot be
                                  split, so it is dropped WHOLE rather
                                  than partially counted. This is the
                                  case the issue's own two ACs miss: a
                                  batch-level straddle can be satisfied
                                  entirely by groups that each fall
                                  cleanly on one side.

`pending_min_ns`/`pending_max_ns` (window_start/window_end's inputs) are
recomputed from the SURVIVING groups' own bounds, never carried over
from the pre-filter batch -- and reset to `None` when nothing survives.
**That reset is the actual PT-89 fix (§4)**: it is the missing step that
makes the NEXT flush a clean slate instead of a permanent re-refusal. A
test asserting only "one log line, no crash" on a SINGLE flush passes
against today's broken code too (which also logs once, via the caller's
`except ReceiverError` branch, and doesn't crash there either) -- the
bug only shows up on the flush AFTER. This file therefore drives
`fold()`/`flush()` DIRECTLY against one persisted `ReceiverState` across
two fold/flush cycles wherever that is the property under test, rather
than going through the (necessarily one-shot-per-process) `--ingest` CLI
`test_otel_receiver.py` otherwise uses throughout -- a fresh subprocess
per call cannot observe in-process state surviving between two flushes
at all. Precedent for calling `otel_receiver`'s internals directly when
a property needs it: `test_otel_receiver_self_stop.py`'s
`PureSessionBookkeepingTests`, `test_otel_receiver_hardening.py`'s
`_effective_endpoint_port` check.

## Boundary (§3)

PT-84's half-open `[start, next)` convention is reused deliberately: a
datapoint inside the stamp's OWN second is KEPT (`time_ns >= stamp_ns`),
not dropped -- two different boundary conventions in one codebase is its
own defect class.

## Out of scope (§7, §8)

No backfill-side change (`merge_and_write` performs no cross-source
`generated` comparison to begin with). No live check -- the loss event
*is* a regeneration while the receiver runs, so the test would be the
incident; every test here uses a scratch `out_path`, never the real
committed data file, backstopped by the module-level guard below.

## AC 3's other half -- `--status` unaffected

The new drop/straddle counts are a `flush()`-time concern; `_status`
(session liveness reporting) is a structurally separate code path and
must not gain them.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import unittest
from pathlib import Path
from typing import Dict, Optional

import helpers  # noqa: F401

import otel_receiver

# --------------------------------------------------------------------------
# Module-wide guard: the real data file and session registry must never be
# touched by a test in this module -- same principle and same shape as
# test_milestone_overhead.py's guard (PT-84) and PT-91's conversion of
# test_otel_receiver_self_stop.py's. Module-level setUpModule/tearDownModule,
# not a TestCase's setUpClass/tearDownClass: unittest's loader walks
# dir(module) alphabetically, so a class-scoped guard only brackets its own
# class, not the whole file.
# --------------------------------------------------------------------------

REAL_METRICS_DIR = helpers.TESTS_DIR.parent.parent.parent / "process" / "cairn" / "metrics"
REAL_TOKEN_USAGE_PATH = REAL_METRICS_DIR / "token-usage.jsonl"
REAL_RECEIVER_PIDFILE = REAL_METRICS_DIR / ".receiver.pid"
REAL_SESSIONS_DIR = REAL_METRICS_DIR / ".sessions"

_REAL_TOKEN_USAGE_BEFORE: Optional[bytes] = None
_REAL_PIDFILE_BEFORE: Optional[bytes] = None
_REAL_SESSIONS_BEFORE: Optional[list] = None


def _snapshot_real_sessions_registry():
    if not REAL_SESSIONS_DIR.is_dir():
        return None
    return sorted((p.name, p.read_bytes()) for p in REAL_SESSIONS_DIR.iterdir() if p.is_file())


def setUpModule():
    global _REAL_TOKEN_USAGE_BEFORE, _REAL_PIDFILE_BEFORE, _REAL_SESSIONS_BEFORE
    _REAL_TOKEN_USAGE_BEFORE = REAL_TOKEN_USAGE_PATH.read_bytes() if REAL_TOKEN_USAGE_PATH.exists() else None
    _REAL_PIDFILE_BEFORE = REAL_RECEIVER_PIDFILE.read_bytes() if REAL_RECEIVER_PIDFILE.exists() else None
    _REAL_SESSIONS_BEFORE = _snapshot_real_sessions_registry()


def tearDownModule():
    after_data = REAL_TOKEN_USAGE_PATH.read_bytes() if REAL_TOKEN_USAGE_PATH.exists() else None
    assert after_data == _REAL_TOKEN_USAGE_BEFORE, (
        "the real, committed process/cairn/metrics/token-usage.jsonl must never be "
        "touched by this test module -- every test must use a scratch out_path"
    )
    after_pidfile = REAL_RECEIVER_PIDFILE.read_bytes() if REAL_RECEIVER_PIDFILE.exists() else None
    assert after_pidfile == _REAL_PIDFILE_BEFORE, (
        "the real process/cairn/metrics/.receiver.pid must never be touched by this "
        "test module -- these tests call fold()/flush()/_status() directly, never a "
        "CLI flag that touches the pidfile/sessions registry"
    )
    assert _snapshot_real_sessions_registry() == _REAL_SESSIONS_BEFORE, (
        "the real process/cairn/metrics/.sessions/ registry must never be touched by "
        "this test module"
    )


# --------------------------------------------------------------------------
# Fixtures.
# --------------------------------------------------------------------------

ONE_SEC_NS = 1_000_000_000
STAMP = "2026-08-20T10:00:00Z"


def _iso_to_stamp_ns(generated: str) -> int:
    """Independent of otel_receiver's own conversion -- this file computes
    the value a correct implementation must produce (start of the
    `generated` second, UTC) itself, so boundary fixtures are pinned to a
    value this test derives on its own, not copied from the
    implementation under test."""
    dt = datetime.datetime.strptime(generated, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp()) * ONE_SEC_NS


STAMP_NS = _iso_to_stamp_ns(STAMP)
BEFORE_NS = STAMP_NS - 10 * ONE_SEC_NS
AFTER_NS = STAMP_NS + 10 * ONE_SEC_NS


def _dp(model: str, start_ns: int, time_ns: int, value: float = 100.0, counter: str = "input") -> Dict[str, object]:
    """A synthetic, ALREADY-PARSED datapoint -- the exact dict shape
    `fold()` consumes (`otel_receiver._parse_datapoint`'s own output).
    Bypasses building full OTLP JSON since these tests need precise
    nanosecond control no payload fixture file can give without one file
    per case. `model` is the only attribute varied across a test's
    groups: `flush()`'s buckets key on `(issue, role, model)`, and
    `issue` is a single flush()-level argument (not per-datapoint), so
    `model` is what keeps a group's contribution attributable to one
    distinct output line."""
    series_key = frozenset([("type", "input"), ("model", model)])
    return {
        "series_key": series_key,
        "start_time_ns": start_ns,
        "time_ns": time_ns,
        "value": value,
        "counter": counter,
        "model": model,
        "role_raw": None,
        "session_id": None,
        "cairn_issue": None,
    }


def _seed_backfill_line(out_path: Path, generated: str) -> dict:
    line = {
        "source": "transcript-backfill", "generated": generated,
        "window_start": "2026-08-01", "window_end": "2026-08-19",
        "issue": "PT-1", "role": "implementation-lead", "model": "claude-sonnet-5",
        "input": 10, "cache_write": 0, "cache_read": 0, "output": 5, "records": 1,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(line, separators=(",", ":")) + "\n", encoding="utf-8")
    return line


def _flush(state, out_path: Path, issue: str = "PT-99", generated: str = "2026-09-05T12:00:00Z"):
    """flush() with the fixed, real-git-avoiding defaults every test in
    this file wants: no session/roster/transcript machinery (every
    synthetic datapoint has session_id=None, role_raw=None, which
    resolves to 'subagent-unattributed' without touching disk), and
    `milestone_windows_table=[]` so flush() never calls
    `cairn.milestone_windows(real_repo_root)` against this actual
    project's own git history."""
    return otel_receiver.flush(
        state, out_path, issue, generated,
        roster=set(), transcripts_dir=Path("/nonexistent"),
        milestone_windows_table=[],
    )


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


def _out_path(testcase) -> Path:
    return helpers.make_empty_tmp_dir(testcase) / "token-usage.jsonl"


# --------------------------------------------------------------------------
# §2's own named seam -- guard first, since every other test in this file
# depends on it existing.
# --------------------------------------------------------------------------

class GroupTimeBoundsSeamTests(unittest.TestCase):
    def test_fold_records_per_group_min_and_max_time_ns_regardless_of_arrival_order(self):
        state = otel_receiver.ReceiverState()
        self.assertTrue(
            hasattr(state, "group_time_bounds"),
            "ReceiverState.group_time_bounds does not exist yet -- PT-89 §2's seam is unimplemented",
        )
        dp_first = _dp("m-bounds", 1000, 5000)
        dp_earlier = _dp("m-bounds", 1000, 3000)  # arrives SECOND but is earlier -- min must track it
        dp_later = _dp("m-bounds", 1000, 9000)
        otel_receiver.fold([dp_first, dp_earlier, dp_later], state)
        group_key = (dp_first["series_key"], 1000)
        self.assertEqual(
            state.group_time_bounds.get(group_key), (3000, 9000),
            f"expected (min, max) = (3000, 9000) regardless of arrival order, got "
            f"{state.group_time_bounds.get(group_key)!r}",
        )


# --------------------------------------------------------------------------
# AC 2 + the reset regression (the property a single-flush test cannot see).
# --------------------------------------------------------------------------

class EntirelyDroppedBatchAndResetTests(unittest.TestCase):
    def test_a_batch_entirely_before_the_stamp_does_not_raise_and_writes_nothing(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([
            _dp("m-all-before", BEFORE_NS, BEFORE_NS - ONE_SEC_NS),
            _dp("m-all-before", BEFORE_NS, BEFORE_NS),
        ], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(
                f"a batch entirely before the backfill's generated stamp must be DROPPED, "
                f"not raised -- got {e}"
            )
        self.assertEqual(lines, [], "nothing should be returned when every group is dropped")
        otel_lines = [l for l in read_jsonl(out_path) if l["source"] == "otel"]
        self.assertEqual(otel_lines, [], "no otel line should be written for an entirely-dropped batch")

    def test_pending_state_resets_to_none_after_a_fully_dropped_flush(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([_dp("m-all-before2", BEFORE_NS, BEFORE_NS)], state)
        try:
            _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"setup flush must not raise -- got {e}")
        self.assertIsNone(
            state.pending_min_ns,
            "pending_min_ns must reset to None even when every group was dropped -- this IS the PT-89 fix",
        )
        self.assertIsNone(
            state.pending_max_ns,
            "pending_max_ns must reset to None even when every group was dropped",
        )

    def test_the_flush_after_a_fully_dropped_one_succeeds(self):
        # The regression a single-flush test cannot see: today's code
        # raises inside flush() BEFORE reaching the reset lines at the
        # bottom, so a caught-and-logged raise leaves pending_min_ns
        # poisoned and every SUBSEQUENT flush on this same long-lived
        # process is refused identically, forever. Proving the fix means
        # proving the SECOND flush on the SAME state, not just that the
        # first one didn't crash.
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([_dp("m-all-before3", BEFORE_NS, BEFORE_NS)], state)
        try:
            _flush(state, out_path)  # everything dropped
        except otel_receiver.ReceiverError as e:
            self.fail(f"setup flush must not raise -- got {e}")

        otel_receiver.fold([_dp("m-safe-after", AFTER_NS, AFTER_NS)], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(
                f"the flush AFTER a fully-dropped one must succeed -- a poisoned "
                f"pending_min_ns would refuse it identically, forever. Got: {e}"
            )
        self.assertEqual(
            [l["model"] for l in lines], ["m-safe-after"],
            "the second flush's safe, post-stamp datapoint must actually be written",
        )

    def test_exactly_one_log_line_names_the_stamp_and_the_dropped_count(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([
            _dp("m-all-before-a", BEFORE_NS, BEFORE_NS),
            _dp("m-all-before-b", BEFORE_NS, BEFORE_NS),
        ], state)
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                _flush(state, out_path)
            except otel_receiver.ReceiverError as e:
                self.fail(f"must not raise -- got {e}")
        combined = buf_out.getvalue() + buf_err.getvalue()
        log_lines = [l for l in combined.splitlines() if l.strip()]
        self.assertEqual(
            len(log_lines), 1,
            f"expected exactly one log line for the whole flush, not one per datapoint/group -- got {log_lines!r}",
        )
        self.assertIn(STAMP, log_lines[0], f"the log line must name the backfill's generated stamp -- got {log_lines[0]!r}")
        self.assertIn("dropped", log_lines[0].lower(), f"the log line must name the dropped count -- got {log_lines[0]!r}")


# --------------------------------------------------------------------------
# The hard case the issue's own ACs miss: a GROUP whose own datapoints span
# the stamp. Its value is an aggregate that cannot be split.
# --------------------------------------------------------------------------

class StraddlingGroupDroppedWholeTests(unittest.TestCase):
    def test_a_straddling_group_is_dropped_whole_and_counted_separately_from_a_clean_drop(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([
            # clean drop: both points before the stamp, own group.
            _dp("m-clean-drop", BEFORE_NS, BEFORE_NS - ONE_SEC_NS),
            _dp("m-clean-drop", BEFORE_NS, BEFORE_NS),
            # straddling: SAME group (shared start_ns), one point before
            # the stamp, one at/after it.
            _dp("m-straddle", BEFORE_NS, BEFORE_NS),
            _dp("m-straddle", BEFORE_NS, AFTER_NS),
            # clean keep: both points after the stamp.
            _dp("m-clean-keep", AFTER_NS, AFTER_NS),
        ], state)

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                lines = _flush(state, out_path)
            except otel_receiver.ReceiverError as e:
                self.fail(
                    f"a straddling group must be DROPPED, not raised -- the whole point of "
                    f"§2's group-level classification is that this no longer aborts the "
                    f"flush. Got: {e}"
                )
        log = (buf_out.getvalue() + buf_err.getvalue()).lower()

        models_written = {l["model"] for l in lines}
        self.assertEqual(
            models_written, {"m-clean-keep"},
            f"only the clean, entirely-after-stamp group must be flushed -- neither the "
            f"clean-drop nor the straddling group may appear, and the straddling group's "
            f"value must not be silently merged into a survivor -- got models {models_written!r}",
        )
        self.assertIn(
            "straddl", log,
            f"the log line must name a straddling count, distinct from the clean-dropped "
            f"count -- got {log!r}",
        )
        self.assertIn(
            "dropped", log,
            f"the log line must also name the clean-dropped count -- got {log!r}",
        )


# --------------------------------------------------------------------------
# AC 1 (restated correctly): a batch whose GROUPS fall cleanly on each side
# of the stamp -- window bounds on the surviving output line must derive
# from the survivor alone, never stretched back to the dropped group's time.
# --------------------------------------------------------------------------

class WindowBoundsRecomputedFromSurvivorsTests(unittest.TestCase):
    def test_pre_stamp_group_dropped_post_stamp_group_flushed_with_recomputed_window(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        far_before_ns = BEFORE_NS - 5 * 86400 * ONE_SEC_NS  # five days earlier
        otel_receiver.fold([
            _dp("m-old", far_before_ns, far_before_ns),
            _dp("m-new", AFTER_NS, AFTER_NS),
        ], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"must not raise -- got {e}")
        self.assertEqual(
            len(lines), 1,
            f"only the surviving group should produce an output line -- got {lines!r}",
        )
        line = lines[0]
        self.assertEqual(line["model"], "m-new")
        expected_date = otel_receiver._ns_to_date(AFTER_NS)
        self.assertEqual(
            line["window_start"], expected_date,
            f"window_start must derive from the SURVIVING group's own time range, not the "
            f"dropped group's -- got {line['window_start']!r}, expected {expected_date!r}",
        )
        self.assertEqual(line["window_end"], expected_date)

    def test_the_flush_after_a_partial_drop_also_succeeds(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([
            _dp("m-old2", BEFORE_NS, BEFORE_NS),
            _dp("m-new2", AFTER_NS, AFTER_NS),
        ], state)
        try:
            _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"setup flush must not raise -- got {e}")
        self.assertIsNone(state.pending_min_ns, "a PARTIAL drop must still reset pending_min_ns to None")
        self.assertIsNone(state.pending_max_ns, "a PARTIAL drop must still reset pending_max_ns to None")

        otel_receiver.fold([_dp("m-safe3", AFTER_NS + ONE_SEC_NS, AFTER_NS + ONE_SEC_NS)], state)
        try:
            lines2 = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"the flush after a PARTIAL drop must also succeed cleanly -- got {e}")
        self.assertEqual([l["model"] for l in lines2], ["m-safe3"])


# --------------------------------------------------------------------------
# §3's boundary: PT-84's half-open convention, reused deliberately.
# --------------------------------------------------------------------------

class StampBoundarySameSecondKeptTests(unittest.TestCase):
    def test_a_group_exactly_at_the_start_of_the_stamps_own_second_is_kept(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        # A companion group clearly before the stamp is folded alongside
        # the boundary one: today's naive batch-level check keys on the
        # WHOLE BATCH's earliest datapoint, so a boundary-only batch would
        # pass by coincidence (its own single timestamp equals the stamp,
        # which isn't "less than" under the old check either) without
        # exercising any group-level classification at all. The companion
        # forces the batch's own earliest to be BEFORE the stamp, so
        # today's code raises here -- the fix must classify per group and
        # still keep m-boundary while dropping the companion.
        otel_receiver.fold([
            _dp("m-clean-drop-companion", BEFORE_NS, BEFORE_NS),
            _dp("m-boundary", STAMP_NS, STAMP_NS),
        ], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"must not raise -- got {e}")
        models = {l["model"] for l in lines}
        self.assertIn(
            "m-boundary", models,
            "a datapoint exactly at the start of the stamp's own second must be KEPT "
            f"(half-open [start, next), PT-84's convention reused deliberately) -- got {models!r}",
        )
        self.assertNotIn(
            "m-clean-drop-companion", models,
            f"the companion group, entirely before the stamp, must still be dropped -- got {models!r}",
        )

    def test_a_group_one_nanosecond_before_the_stamps_second_is_dropped(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([_dp("m-just-before", STAMP_NS - 1, STAMP_NS - 1)], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"must not raise (dropped, not refused) -- got {e}")
        self.assertEqual(lines, [], "one nanosecond before the start of the stamp's own second must still be DROPPED")


# --------------------------------------------------------------------------
# AC 3's other half: --status must not gain the new drop/straddle counts.
# --------------------------------------------------------------------------

class StatusUnaffectedTests(unittest.TestCase):
    def test_status_output_never_mentions_the_new_drop_counts(self):
        root = helpers.make_empty_tmp_dir(self)
        pidfile = root / ".receiver.pid"  # never created -- "not running"
        out_path = root / "token-usage.jsonl"
        sessions_dir = root / ".sessions"
        transcripts_dir = root / "transcripts"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            otel_receiver._status(pidfile, 4318, out_path, sessions_dir, transcripts_dir)
        output = buf.getvalue().lower()
        self.assertNotIn("dropped", output, f"--status must not surface flush-level drop counts -- got {output!r}")
        self.assertNotIn("straddl", output, f"--status must not surface flush-level straddling counts -- got {output!r}")


# --------------------------------------------------------------------------
# §1: the filter keys on each group's own datapoint time bounds, never on
# startTimeUnixNano (the metric stream's start) -- a filter keyed on stream
# start would drop a long-running cumulative series' entire future after
# one regeneration.
# --------------------------------------------------------------------------

class FilterKeysOnDatapointTimeNotStreamStartTests(unittest.TestCase):
    def test_a_long_lived_series_with_an_old_start_but_a_fresh_datapoint_is_kept(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        ancient_start_ns = STAMP_NS - 365 * 86400 * ONE_SEC_NS  # a year before the stamp
        otel_receiver.fold([_dp("m-long-lived", ancient_start_ns, AFTER_NS)], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"must not raise -- got {e}")
        self.assertEqual(
            [l["model"] for l in lines], ["m-long-lived"],
            "a datapoint whose METRIC STREAM started long ago but whose OWN time is fresh must "
            "be KEPT -- filtering on startTimeUnixNano instead of the datapoint's own time_ns "
            "would wrongly drop this (§1's own named premise failure)",
        )


# --------------------------------------------------------------------------
# Architect's addendum (5208f32): group_time_bounds resets EVERY flush
# cycle (never lifetime-persistent), and flushed_baseline is re-keyed from
# SeriesKey to (SeriesKey, start_ns) -- the key group_max already uses.
# Two tests this change specifically requires.
# --------------------------------------------------------------------------

class NoDropSafetyParityTests(unittest.TestCase):
    """AC 4b -- the architect's own most-wanted test: every other test in
    this file exercises the DROP path; this is the one that guards the
    COMMON path. With nothing dropped, the re-keyed (per-group) baseline
    arithmetic must still sum to the correct per-series total -- a series
    with two groups (two different start_ns, e.g. a metric restart), both
    kept, must flush the exact sum of both groups' values."""

    def test_two_groups_of_the_same_series_both_kept_sum_to_the_correct_total(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()
        otel_receiver.fold([
            _dp("m-restart", AFTER_NS, AFTER_NS, value=30.0),
            _dp("m-restart", AFTER_NS + 5 * ONE_SEC_NS, AFTER_NS + 5 * ONE_SEC_NS, value=70.0),
        ], state)
        try:
            lines = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"must not raise -- got {e}")
        self.assertEqual(len(lines), 1, f"one series (one model) must produce one bucket line -- got {lines!r}")
        self.assertEqual(
            lines[0]["input"], 100,
            f"the flushed total must equal the sum of both groups' values (30+70=100) -- the "
            f"re-keyed per-group baseline must not change the common (no-drop) path's arithmetic "
            f"-- got {lines[0]['input']!r}",
        )


class DroppedGroupRecoveryTests(unittest.TestCase):
    """AC 4's resurrection-bug closure: a group dropped in cycle N still
    ADVANCES its baseline (architect's addendum) so that once it recovers
    in cycle N+1 (its own bounds, reset each cycle, no longer straddle or
    predate the stamp), the flushed delta excludes the already-dropped
    range rather than resurrecting it."""

    def test_a_group_dropped_in_one_cycle_recovers_without_double_counting_in_the_next(self):
        out_path = _out_path(self)
        _seed_backfill_line(out_path, generated=STAMP)
        state = otel_receiver.ReceiverState()

        # Cycle N: dropped -- entirely before the stamp.
        start_ns = BEFORE_NS
        otel_receiver.fold([_dp("m-recover", start_ns, BEFORE_NS, value=50.0)], state)
        try:
            lines_n = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"cycle N must not raise -- got {e}")
        self.assertEqual(lines_n, [], "cycle N's entirely-pre-stamp group must not be written")

        # Cycle N+1: SAME group (same model, same start_ns -- same
        # group_key), new growth, this time safely after the stamp --
        # group_time_bounds reset every cycle, so only THIS cycle's own
        # datapoint governs classification.
        otel_receiver.fold([_dp("m-recover", start_ns, AFTER_NS, value=90.0)], state)
        try:
            lines_n1 = _flush(state, out_path)
        except otel_receiver.ReceiverError as e:
            self.fail(f"cycle N+1 must not raise -- got {e}")
        self.assertEqual(
            [l["model"] for l in lines_n1], ["m-recover"],
            "the recovered group must be written once its recent window clears the stamp",
        )
        self.assertEqual(
            lines_n1[0]["input"], 40,
            f"the recovery flush must exclude the already-dropped 50 tokens (baseline advanced "
            f"to 50 in cycle N, so 90-50=40) -- a baseline that failed to advance on drop would "
            f"resurrect the full 90 -- got {lines_n1[0]['input']!r}",
        )
