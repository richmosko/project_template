#!/usr/bin/env python3
"""otel_receiver.py — PT-78: the ongoing local OTLP receiver for Claude
Code's own token/cost telemetry, appended to the same committed data file
PT-77's one-time backfill writes.

Design pinned by the architect's gating ruling (process/cairn/issues/PT-78.md,
"@architect — 2026-09-03") and the addendum that names the concrete
implementation surface (module seams, CLI flags, the settings.json block,
the hook line, the 12-key allow-list verbatim) — those comments are the
tie-breaker for "why does it do X"; this docstring is the map from ruling
section to code.

What it is: a separate, long-lived local HTTP server (NOT inside `cairn
serve` — the board dies on `/exit` and telemetry that only records while
someone has the board open would silently under-report). Started
idempotently by the `SessionStart` hook via `--ensure-running` (pidfile +
a listen probe; a second start is a no-op, never an error). Accepts
OTLP-over-`http/json` POST /v1/metrics, decodes `claude_code.token.usage`,
counts it correctly under either DELTA or CUMULATIVE aggregation
temporality (group by (series, startTimeUnixNano), max within a group,
sum across groups, kept in memory only — a receiver restart starts
fresh, on purpose), attributes each contribution to an issue (branch
first, `cairn.issue` only as a fallback when the branch is `main`) and a
role (`agent.name` normalised through PT-77's own roster-anchored
function, else a `query_source`-keyed table with a LOUD
`subagent-unattributed` guard rather than a silent `team-lead` fold —
NOTE: role attribution is flagged for an architect amendment replacing
this table with a session.id -> transcript lookup; this module keeps the
table-based rule until that amendment sha lands, since no test currently
pins a different behaviour), and appends token-count-only lines to
`process/cairn/metrics/token-usage.jsonl` under PT-77's own file lock —
`source: "otel"`, twelve keys, an allow-list not a deny-list, so a future
Claude Code export version that adds a new identifying attribute is
dropped by default rather than persisted until someone notices.

Never persists: `session.id` (held in memory only, as the series key),
`user.email`/`user.id`/`user.account_id`/`user.account_uuid`/
`organization.id`/`terminal.type`/`effort`, or `claude_code.cost.usage`
(dollars are recomputed from tokens later, by PT-79, from the same dated
price table for both sources). No prompts, no message bodies, no tool
output ever reach this process at all: `OTEL_LOGS_EXPORTER=none` and
`OTEL_LOG_RAW_API_BODIES` unset are enforced by the `.claude/settings.json`
env block this ticket ships (documented in process/TRACKER.md, absent
from the file until `/setup-tracker` opts a project in), not by this
script — the logs stream is where that content would ride; this receiver
only ever speaks metrics.

Module seams (addendum: "tests must not need a socket" — every counting/
privacy/attribution assertion goes through these three, pure, functions;
the HTTP server is a thin shell over them):

    parse_export(payload: dict) -> List[dict]
        OTLP-JSON -> flat datapoint records. Applies the 5-key attribute
        allow-list (agent.name, model, query_source, cairn.issue, type)
        immediately; `session.id` is carried separately, INSIDE each
        record's `series_key`, and never appears as its own field.
        Raises ReceiverError on a structurally invalid top level (no
        `resourceMetrics` list) -- malformed inner shapes are skipped,
        not fatal.
    fold(datapoints: List[dict], state: ReceiverState) -> ReceiverState
        The (series, startTimeUnixNano) grouping. Mutates and returns
        `state`.
    flush(state, out_path, issue, generated) -> List[dict]
        Computes each series' delta since its last-flushed baseline,
        buckets by (issue, role, model), and appends the resulting
        `source: "otel"` lines under `process/cairn/metrics/.lock`.
        Returns the lines written (empty list, no write at all, if
        nothing had accrued). Raises ReceiverError on the non-overlap
        invariant (an otel line predating the latest transcript-backfill
        `generated`) or a malformed existing data file -- nothing
        partial is ever written.

CLI:
    python3 scripts/cairn/otel_receiver.py [--port N] [--out-file PATH]
        [--flush-interval SECONDS] [--pidfile PATH]
        [--ingest PATH|-] [--once]
        [--ensure-running [--session-id ID --session-pid PID]]
        [--session-ended ID] [--grace-period-seconds N]
        [--status] [--flush-now] [--stop]

    No flag (bare invocation)  -- runs the long-lived HTTP server in the
        foreground: binds --port, writes --pidfile, flushes on SIGUSR1
        (--flush-now's target), flushes and exits cleanly on SIGTERM/
        SIGINT (--stop's target), and otherwise at most every
        --flush-interval seconds or when the attributed issue changes.
    --ingest PATH|-  -- read one OTLP-JSON payload from a file (or stdin
        with `-`), fold it, flush, exit. Binds no port -- the main test
        seam.
    --once  -- bind --port, accept exactly one POST /v1/metrics, flush,
        exit. The one integration test that touches a socket.
    --ensure-running  -- start a detached long-lived instance if the
        pidfile is stale/absent and nothing is listening; exit 0 either
        way, never an error (what the SessionStart hook calls). PT-81
        (H1-H3): declines quietly (returns False, spawns nothing) when
        `CLAUDE_CODE_ENABLE_TELEMETRY` isn't truthy in its own
        environment, or when `otel_port` disagrees with the port in its
        own inherited `OTEL_EXPORTER_OTLP_ENDPOINT` (naming both);
        distinguishes "another process already holds the port" from "we
        spawned a child but it never came up" (naming the port and
        `otel_port` either way) rather than reporting success either way.
        The hook still exits 0 regardless -- a SessionStart hook must
        never fail a session over telemetry -- but now lets stderr
        through instead of swallowing it, so these messages are visible.
        PT-86: paired with `--session-id ID --session-pid PID` (both, or
        neither -- a bare call, what every pre-PT-86 caller still does,
        registers nothing), registers ID as a live session (see "Session
        lifecycle" below) once the receiver is confirmed up, new spawn or
        already-running alike.
    --session-ended ID  -- PT-86, the SessionEnd hook's target: deregister
        ID, reap any OTHER recorded session whose pid has since died (the
        crash backstop), and ping the daemon to re-evaluate whether it
        should start its grace-shutdown countdown. No daemon running ->
        no-op, exit 0 -- same discipline as --ensure-running, since a
        SessionEnd hook must not fail session teardown either, and (per
        Claude Code's own hook contract) cannot block it regardless: this
        call never waits on the grace period itself, only the daemon does.
    --grace-period-seconds N  -- (bare/serve invocation; default 10)
        threaded through `--ensure-running`'s spawn args when it starts a
        FRESH daemon. See "Session lifecycle" below.
    --status  -- print whether a receiver is running, its port, and its
        --out-file, then exit 0 if running / 1 if not (a caller-facing
        health check, not what the hook itself calls). PT-86: also prints
        `sessions: N` and one `session <id>: alive|dead` line per
        RECORDED id (sorted, freshly probed, never mutating -- only
        --session-ended and a flush actually reap a dead entry).
    --flush-now / --stop  -- signal a running instance (SIGUSR1 / SIGTERM)
        via its pidfile.

Session lifecycle (PT-86, process/cairn/issues/PT-86.md, architect's
    addendum): the receiver stops itself when the LAST session on the
    repo ends, only after the exporter's final flush has had a grace
    window to land -- see `_sessions_dir`'s own docstring for the
    on-disk shape (one small file per session, no cross-process lock
    needed) and `serve`'s watchdog block for the state machine. In
    short: `--ensure-running`/`--session-ended` mutate the session-file
    directory directly (fast, synchronous, since a SessionEnd hook
    cannot block session teardown -- neither call ever waits on the
    grace period itself); `--session-ended` additionally sends SIGUSR2
    as a latency-only nudge (never load-bearing for correctness) so the
    daemon's watchdog thread re-evaluates and reaps dead siblings
    (addendum §3, "on every end event") sooner than its own
    WATCHDOG_TICK_SECONDS poll would. The watchdog arms a
    `--grace-period-seconds` deadline the first time it observes an
    empty registry that was previously non-empty, clears it on any tick
    that finds the registry non-empty again, and once the deadline has
    passed with the registry still empty (one more fresh probe first),
    runs the addendum §B two-flag `.closing` point-of-no-return protocol
    -- a session racing to register in that exact window still cancels
    the shutdown -- then closes the socket, does the final flush,
    compare-and-deletes the pidfile, and exits.

    --out-file and the config-derived prefix/port are resolved from the
    REPO ROOT (this script's own on-disk location), never from
    `Path.cwd()` -- PT-77's blocking defect and PT-80 exist because of
    exactly that mistake, and `cairn.load_config` now raises rather than
    silently defaulting, so this module leans on it. The repo's CURRENT
    BRANCH is a different query, deliberately NOT anchored the same way:
    OTel carries no branch attribute at all, so the receiver asks git
    *right now*, wherever the process happens to be running -- `git
    rev-parse --abbrev-ref HEAD` with no `-C`, inheriting the caller's
    own cwd (the SessionStart hook's cwd is the repo root at session
    start; a test can point cwd at a throwaway repo to control the
    branch signal without needing a --branch flag this design has no use
    for otherwise).
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import http.server
import json
import os
import select
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple
from urllib.parse import urlparse

import cairn
import backfill_tokens

SOURCE_NAME = "otel"
DEFAULT_OTEL_PORT = 4318
DEFAULT_FLUSH_INTERVAL_SECONDS = 30 * 60  # ruling §7: "at most every 30 minutes"
PIDFILE_REL = Path("process") / "cairn" / "metrics" / ".receiver.pid"
LOGFILE_REL = Path("process") / "cairn" / "metrics" / "otel_receiver.log"

# PT-86: the last-session-ends-the-daemon-stops-itself lifecycle. Design
# per process/cairn/issues/PT-86.md's architect addendum ("@architect --
# 2026-09-04", the second comment, which withdraws and replaces the
# first ruling's HTTP `/control/session` endpoint in favor of a file-per-
# session registry) -- see `_sessions_dir` and `serve`'s watchdog block.
SESSIONS_DIRNAME = ".sessions"
CLOSING_MARKER_NAME = ".closing"
# Architect review (ef000d5), Delta 6: written by `serve` at startup,
# inside `_sessions_dir` (zero new .gitignore surface -- the directory
# is already covered end-to-end, and the existing dotfile filter in
# `live_session_ids` already skips it the same way it skips
# CLOSING_MARKER_NAME). Its PRESENCE is the only thing that matters --
# `_nudge_daemon` only sends SIGUSR2 when it's there, so a receiver
# started before this change (no SIGUSR2 handler at all -- an unhandled
# SIGUSR2 terminates a Python process outright) is never signalled.
NUDGE_CAPABLE_MARKER_NAME = ".nudge-capable"
# `--status` (StatusFourStateTests) must label a `dead`/`dead-pending`
# entry using the SAME transcripts_dir the actual running daemon
# resolved at spawn time -- which can differ from whatever this SEPARATE
# CLI invocation would resolve on its own (its own `--transcripts-dir`
# default, or a test's deliberate override that was only ever passed on
# the ORIGINAL --ensure-running call, not on this one). Same pattern as
# NUDGE_CAPABLE_MARKER_NAME: written once at daemon startup, inside
# `_sessions_dir`, read back by whoever needs the daemon's own answer.
TRANSCRIPTS_DIR_MARKER_NAME = ".transcripts-dir"
DEFAULT_GRACE_PERIOD_SECONDS = 10.0  # addendum §D: default 10s
WATCHDOG_TICK_SECONDS = 0.2  # addendum §4: "ticks <= 0.25 s"
TRANSCRIPT_STALE_SECONDS = 30 * 60  # addendum C: the probe's second signal
# Team-lead's ruling (PT-86, 138c03c: "the slow periodic reap sweep in
# 12afe1d stays"), architect-reviewed at 0d9f0b5 (verified by
# construction: exits at one sweep interval, not indefinitely, once
# every registered session has crashed). The nudge-gated reap and the
# flush-triggered reap both go silent when EVERY registered session has
# crashed (no `end` event ever arrives to nudge, no export ever arrives
# to trigger a flush) -- this THIRD, time-based trigger, independent of
# both, is what makes that case genuinely bounded instead of pinned
# until an unrelated future session's own SessionEnd happens to reap it.
# Deliberately much slower than WATCHDOG_TICK_SECONDS (reaping every
# tick regardless of a nudge was tried and rejected -- see
# `_watchdog_loop`'s docstring -- it broke the "not yet reaped" window
# LivenessReapTests relies on) and much slower than
# TRANSCRIPT_STALE_SECONDS itself (no entry can become reap-eligible
# faster than that anyway). Configurable via `--periodic-reap-seconds`,
# same shape as `--grace-period-seconds`, so tests can shrink it to
# sub-second without a real multi-minute wait.
DEFAULT_PERIODIC_REAP_SECONDS = 5 * 60
# Addendum: the allow-list, verbatim -- every OTLP attribute NOT one of
# these five is dropped before it reaches memory beyond the series key.
_ATTR_ALLOW_LIST = ("agent.name", "model", "query_source", "cairn.issue", "type")

# Addendum: exact mapping, measured -- these four `type` values only.
_TYPE_TO_COUNTER = {
    "input": "input",
    "cacheCreation": "cache_write",
    "cacheRead": "cache_read",
    "output": "output",
}

_METRIC_NAME = "claude_code.token.usage"

# Addendum: the 12-key allow-list, verbatim order -- implemented as a
# literal tuple the writer iterates, NOT "the incoming dict minus a
# deny-list" (that phrasing is the addendum's own instruction).
_OUTPUT_KEY_ORDER = (
    "source", "generated", "window_start", "window_end",
    "issue", "role", "model", "input", "cache_write", "cache_read", "output", "records",
)


class ReceiverError(Exception):
    """Raised on the non-overlap violation, a malformed existing data
    file, or a structurally invalid OTLP payload -- same fail-loudly
    contract as backfill_tokens.BackfillError. Deliberately a distinct
    class: a receiver failure and a backfill failure are different
    callers' problems."""


# --------------------------------------------------------------------------
# OTLP/JSON decoding -- structure measured against a real local capture,
# 2026-09-03/04: resourceMetrics[].scopeMetrics[].metrics[].sum.dataPoints[].
# --------------------------------------------------------------------------

def decode_otlp_json(body: bytes, content_encoding: Optional[str]) -> Dict[str, Any]:
    """Handles `Content-Encoding: gzip` even though the measured exporter
    didn't use it -- protocol-legal, one branch. Raises ReceiverError on
    anything that isn't valid JSON after decompression."""
    if content_encoding and "gzip" in content_encoding.lower():
        try:
            body = gzip.decompress(body)
        except OSError as e:
            raise ReceiverError(f"malformed gzip OTLP body: {e}")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ReceiverError(f"malformed OTLP JSON body: {e}")


def _flatten_attrs(attr_list: Any) -> Dict[str, str]:
    """OTLP/JSON's `[{"key": k, "value": {"stringValue": v}}, ...]` shape
    -> a plain `{k: v}` dict restricted to `_ATTR_ALLOW_LIST` -- the
    earliest possible point to drop everything else, per the ruling's
    allow-list-not-deny-list instruction."""
    out: Dict[str, str] = {}
    if not isinstance(attr_list, list):
        return out
    for entry in attr_list:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if key not in _ATTR_ALLOW_LIST:
            continue
        value = entry.get("value")
        if not isinstance(value, dict):
            continue
        for vkey in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if vkey in value:
                out[key] = str(value[vkey])
                break
    return out


def _session_id(attr_list: Any) -> Optional[str]:
    """Read directly from the RAW attribute list -- deliberately never
    routed through `_flatten_attrs` (`session.id` is not in
    `_ATTR_ALLOW_LIST`), so it can never accidentally end up in a
    persisted field. Used only as part of an in-memory series key."""
    if not isinstance(attr_list, list):
        return None
    for entry in attr_list:
        if isinstance(entry, dict) and entry.get("key") == "session.id":
            v = entry.get("value") or {}
            return v.get("stringValue")
    return None


def _point_value(dp: Dict[str, Any]) -> Optional[float]:
    """OTLP/JSON int64 fields are transported as a JSON STRING (`asInt`)
    to avoid precision loss; `asDouble` is a plain JSON number. Both are
    observed in real captures, so both are handled. `None` (not a raise)
    when neither is present -- an inner malformed datapoint is skipped by
    the caller, not fatal to the whole payload."""
    if "asInt" in dp:
        try:
            return float(dp["asInt"])
        except (TypeError, ValueError):
            return None
    if "asDouble" in dp:
        try:
            return float(dp["asDouble"])
        except (TypeError, ValueError):
            return None
    return None


def _point_time_ns(dp: Dict[str, Any]) -> Optional[int]:
    raw = dp.get("timeUnixNano") or dp.get("startTimeUnixNano")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _ns_to_date(ns: int) -> str:
    return datetime.datetime.fromtimestamp(ns / 1e9, tz=datetime.timezone.utc).date().isoformat()


def _ns_to_iso(ns: int) -> str:
    return datetime.datetime.fromtimestamp(ns / 1e9, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# parse_export / fold -- the two pure, socket-free seams.
# --------------------------------------------------------------------------

SeriesKey = FrozenSet[Tuple[str, str]]


def parse_export(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """OTLP-JSON -> a flat list of datapoint records. Raises ReceiverError
    when the TOP-LEVEL shape isn't recognisable as an OTLP export at all
    (no `resourceMetrics` list) -- a payload that superficially looks
    like OTLP but has an inner malformed metric/dataPoint is tolerated by
    skipping just that item, not by failing the whole payload; the two
    are different failure classes (a caller sending the wrong THING
    entirely vs. one bad point in an otherwise-good export).
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("resourceMetrics"), list):
        raise ReceiverError("malformed OTLP payload: missing or non-list 'resourceMetrics'")

    datapoints: List[Dict[str, Any]] = []
    for rm in payload["resourceMetrics"]:
        if not isinstance(rm, dict):
            continue
        # Amendment A (25d7a42): one dict per datapoint = resource
        # attributes overlaid by that datapoint's own attributes,
        # DATAPOINT WINNING on conflict -- measured today Claude Code
        # copies every resource attribute down onto each datapoint
        # (cairn.issue included), so this is a no-op in practice, not a
        # real conflict resolution. It matters for a silent-degradation
        # path: if a future export ever stops duplicating `cairn.issue`
        # onto datapoints, reading resource-level attributes here is what
        # keeps the `main`-branch fallback from silently losing its hint.
        # `_flatten_attrs` already applies `_ATTR_ALLOW_LIST`, so merging
        # resource attrs in can never widen what gets persisted --
        # resource-only host.arch/os.*/service.* are dropped at the same
        # gate identity attributes already are.
        resource_attrs = _flatten_attrs((rm.get("resource") or {}).get("attributes"))
        for sm in rm.get("scopeMetrics") or []:
            if not isinstance(sm, dict):
                continue
            for metric in sm.get("metrics") or []:
                if not isinstance(metric, dict) or metric.get("name") != _METRIC_NAME:
                    continue
                for dp in ((metric.get("sum") or {}).get("dataPoints")) or []:
                    if not isinstance(dp, dict):
                        continue
                    record = _parse_datapoint(dp, resource_attrs)
                    if record is not None:
                        datapoints.append(record)
    return datapoints


def _parse_datapoint(dp: Dict[str, Any], resource_attrs: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    attrs = {**(resource_attrs or {}), **_flatten_attrs(dp.get("attributes"))}
    counter_type = attrs.get("type")
    if counter_type not in _TYPE_TO_COUNTER:
        return None  # not one of the four measured values -- not our metric shape

    try:
        start_ns = int(dp.get("startTimeUnixNano"))
    except (TypeError, ValueError):
        return None  # can't group without it -- drop the point rather than guess

    value = _point_value(dp)
    if value is None:
        return None

    session_id = _session_id(dp.get("attributes"))
    series_key: SeriesKey = frozenset(attrs.items()) | ({("session.id", session_id)} if session_id else set())
    point_ns = _point_time_ns(dp)

    return {
        "series_key": series_key,
        "start_time_ns": start_ns,
        "time_ns": point_ns if point_ns is not None else start_ns,
        "value": value,
        "counter": _TYPE_TO_COUNTER[counter_type],
        "model": attrs.get("model") or "unknown",
        "role_raw": attrs.get("agent.name"),
        "session_id": session_id,
        "cairn_issue": attrs.get("cairn.issue"),
    }


class ReceiverState:
    """The in-memory accumulator. Everything here is lost on process
    restart -- deliberately ("baseline on first sight"): the alternative
    (persisting per-session baselines) would mean persisting
    `session.id`, which the privacy ruling forbids outright."""

    def __init__(self) -> None:
        # (series_key, start_time_ns) -> max value ever seen for that
        # EXACT group -- idempotent against a retried/duplicated
        # delivery, correct under delta (each window is its own group,
        # max-then-sum reduces to plain sum) and under cumulative (every
        # point of a series shares one start time, the max is the final
        # running total, counted once).
        self.group_max: Dict[Tuple[SeriesKey, int], float] = {}
        # series_key -> the attribution inputs for that series (captured
        # once, at first sight -- they don't change mid-series).
        self.series_meta: Dict[SeriesKey, Dict[str, Optional[str]]] = {}
        # series_key -> the total already CONTRIBUTED to some prior
        # flush. The NEXT flush's contribution is
        # (current series total) - (this baseline), never the full total
        # again -- otherwise every flush of a long-lived series would
        # re-write everything it already wrote.
        self.flushed_baseline: Dict[SeriesKey, float] = {}
        # Earliest/latest datapoint timeUnixNano seen since the LAST
        # flush (reset after each flush) -- window_start/window_end and
        # the non-overlap check both key on this, not on wall-clock "now".
        self.pending_min_ns: Optional[int] = None
        self.pending_max_ns: Optional[int] = None
        self.last_issue_bucket: Optional[str] = None
        self.last_flush_monotonic: float = time.monotonic()
        self.lock = threading.RLock()
        # session_id -> resolved role (amendment B). Cached for the
        # receiver's LIFETIME once resolved -- but a "no transcript file
        # at all" result is never cached (see `_resolve_role_from_session`):
        # a session's transcript appears on its first turn, so a miss
        # must retry on the next datapoint, not pin an early false guard.
        self.role_cache: Dict[str, str] = {}


def fold(datapoints: List[Dict[str, Any]], state: ReceiverState) -> ReceiverState:
    """The (series, startTimeUnixNano) grouping. Thread-safe (the HTTP
    server is threaded -- concurrent teammates export concurrently, the
    normal case for this project's team-agents workflow, not an edge
    case) -- takes `state.lock` itself so both the HTTP handler and a
    test calling this directly get the same guarantee."""
    with state.lock:
        for dp in datapoints:
            group_key = (dp["series_key"], dp["start_time_ns"])
            state.group_max[group_key] = max(dp["value"], state.group_max.get(group_key, float("-inf")))
            state.series_meta.setdefault(dp["series_key"], {
                "role_raw": dp["role_raw"],
                "session_id": dp["session_id"],
                "model": dp["model"],
                "counter": dp["counter"],
                "cairn_issue": dp["cairn_issue"],
            })
            t = dp["time_ns"]
            state.pending_min_ns = t if state.pending_min_ns is None else min(state.pending_min_ns, t)
            state.pending_max_ns = t if state.pending_max_ns is None else max(state.pending_max_ns, t)
    return state


# --------------------------------------------------------------------------
# Attribution -- issue (branch-first) and role.
# --------------------------------------------------------------------------

def _current_branch(repo_root: Path) -> Optional[str]:
    """`git -C <repo_root> rev-parse --abbrev-ref HEAD` -- same `-C`
    contract as cairn.py's read_git_state/read_git_tags and
    check_dist_freshness.py's _run_git, never raises. `repo_root` is
    `--repo-root` when given, else this script's own on-disk location
    (`backfill_tokens._repo_root()`) -- CWD-independent by default (the
    PT-77/PT-80 defect class), with `--repo-root` as the explicit,
    test-only override for pointing at a throwaway checkout on a
    controlled branch.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_issue(branch: Optional[str], prefix: str, cairn_issue_hint: Optional[str]) -> str:
    """Branch first (PT-77's exact regex/bucketing function, imported not
    reimplemented), `cairn.issue` only when the branch yields `main`,
    otherwise `main`. One resolution per flush -- every datapoint accrued
    since the last flush is attributed to whatever the checkout is AT
    FLUSH TIME, since git branch carries no per-datapoint signal at all.
    """
    issue_re = backfill_tokens._issue_regex(prefix)
    from_branch = backfill_tokens._bucket_for_branch(branch, prefix, issue_re)
    if from_branch != "main":
        return from_branch
    if cairn_issue_hint:
        return cairn_issue_hint
    return "main"


_ROLE_SCAN_LIMIT = 50  # amendment B: measured 10x margin over the observed max (line 4-5)


def _resolve_role_from_session(
    session_id: Optional[str], transcripts_dir: Path, roster: Set[str], cache: Dict[str, str]
) -> str:
    """Amendment B (25d7a42): `agent.name` is confirmed absent on
    teammate-shaped processes, so role resolves per `session.id`, once,
    at first sight -- NOT from any OTel attribute. Reads
    `<transcripts_dir>/<session_id>.jsonl` (same file `backfill_tokens.py`
    would scan), the first `agentName` within the first `_ROLE_SCAN_LIMIT`
    records, normalised through PT-77's own roster-anchored function
    (shared, not copied). File exists with none found -> `team-lead`.
    File absent entirely -> `subagent-unattributed`, a loud guard: it
    means no transcript for this session (retention pruned it, or it
    belongs to another project's dir), not "role unknown, assume lead".

    Reads exactly one field (`agentName`) from at most
    `_ROLE_SCAN_LIMIT` records -- no message content, no prompts, no tool
    output ever reach this function's return value; the path is derived
    per lookup, never stored.
    """
    if not session_id:
        return "subagent-unattributed"
    if session_id in cache:
        return cache[session_id]

    transcript_path = transcripts_dir / f"{session_id}.jsonl"
    if not transcript_path.is_file():
        return "subagent-unattributed"  # NOT cached -- retry on the next datapoint

    role = "team-lead"
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for i, raw in enumerate(f):
                if i >= _ROLE_SCAN_LIMIT:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                agent_name = record.get("agentName")
                if agent_name:
                    role = backfill_tokens._normalize_role(agent_name, roster)
                    break
    except OSError:
        return "subagent-unattributed"  # vanished mid-read -- NOT cached either

    cache[session_id] = role  # a definitive resolution -- cached for the receiver's lifetime
    return role


def resolve_role(
    role_raw: Optional[str], session_id: Optional[str], transcripts_dir: Path, roster: Set[str], cache: Dict[str, str]
) -> str:
    """`agent.name` on the datapoint itself, when present, wins outright
    (amendment B's own labelled reversal path: "if a future Claude Code
    emits agent.name for teammate processes, prefer the attribute and
    demote this to the fallback" -- one condition). No current fixture
    or real capture sets it, so every real call today falls through to
    the session.id -> transcript lookup.
    """
    if role_raw:
        return backfill_tokens._normalize_role(role_raw, roster)
    return _resolve_role_from_session(session_id, transcripts_dir, roster, cache)


def _issue_hint_from_datapoints(datapoints_or_meta) -> Optional[str]:
    for item in datapoints_or_meta:
        hint = item.get("cairn_issue") if isinstance(item, dict) else None
        if hint:
            return hint
    return None


# --------------------------------------------------------------------------
# flush -- append under PT-77's lock, non-overlap invariant.
# --------------------------------------------------------------------------

def _latest_backfill_generated(out_path: Path) -> Optional[str]:
    """The `generated` of the newest `source: "transcript-backfill"` line
    in the data file, or None if there isn't one yet."""
    if not out_path.exists():
        return None
    latest: Optional[str] = None
    for line in backfill_tokens._read_existing_lines(out_path):
        if line.get("source") == "transcript-backfill":
            gen = line.get("generated")
            if gen and (latest is None or gen > latest):
                latest = gen
    return latest


def flush(
    state: ReceiverState,
    out_path: Path,
    issue: str,
    generated: str,
    roster: Optional[Set[str]] = None,
    transcripts_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Computes each series' delta since its last-flushed baseline,
    buckets by (issue, role, model), and appends the resulting `source:
    "otel"` lines under `process/cairn/metrics/.lock`. Returns the lines
    written (empty list -- and no write at all -- if nothing had accrued
    since the last flush). Raises ReceiverError on the non-overlap
    violation or a malformed existing file, naming both timestamps.

    `issue`/`generated` are resolved by the CALLER (branch/`cairn.issue`
    attribution needs `git`/cwd; this function stays a pure data
    transform otherwise, per the addendum's module-seam split). `roster`/
    `transcripts_dir` default to the real project's values (computed from
    this file's own on-disk location) when omitted -- the CLI always
    passes its own resolved values explicitly instead of relying on this
    fallback, so `--repo-root`/`--transcripts-dir` overrides take effect.
    """
    if roster is None:
        roster = backfill_tokens._roster_names(backfill_tokens._repo_root())
    if transcripts_dir is None:
        repo_root = backfill_tokens._repo_root()
        transcripts_dir = Path.home() / ".claude" / "projects" / backfill_tokens._transcript_dir_slug(repo_root)

    with state.lock:
        if state.pending_min_ns is None:
            return []  # nothing accrued since the last flush -- a no-op, not an error

        latest_backfill_generated = _latest_backfill_generated(out_path)
        earliest_iso = _ns_to_iso(state.pending_min_ns)
        if latest_backfill_generated is not None and earliest_iso < latest_backfill_generated:
            raise ReceiverError(
                f"non-overlap invariant violated: this flush's earliest datapoint "
                f"({earliest_iso}) predates the latest transcript-backfill generated "
                f"timestamp ({latest_backfill_generated}) already in {out_path}"
            )

        series_totals: Dict[SeriesKey, float] = {}
        for (series_key, _start_ns), value in state.group_max.items():
            series_totals[series_key] = series_totals.get(series_key, 0.0) + value

        buckets: Dict[Tuple[str, str, str], Dict[str, float]] = {}
        for series_key, total in series_totals.items():
            baseline = state.flushed_baseline.get(series_key, 0.0)
            delta = total - baseline
            if delta <= 0:
                continue
            meta = state.series_meta[series_key]
            role = resolve_role(meta.get("role_raw"), meta.get("session_id"), transcripts_dir, roster, state.role_cache)
            model = meta.get("model") or "unknown"
            counter = meta["counter"]
            acc = buckets.setdefault(
                (issue, role, model),
                {"input": 0.0, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0, "records": 0},
            )
            acc[counter] += delta
            acc["records"] += 1
            state.flushed_baseline[series_key] = total

        window_start = _ns_to_date(state.pending_min_ns)
        window_end = _ns_to_date(state.pending_max_ns)

        new_lines = []
        for (b_issue, b_role, b_model), acc in buckets.items():
            line = {
                "source": SOURCE_NAME,
                "generated": generated,
                "window_start": window_start,
                "window_end": window_end,
                "issue": b_issue,
                "role": b_role,
                "model": b_model,
                "input": int(round(acc["input"])),
                "cache_write": int(round(acc["cache_write"])),
                "cache_read": int(round(acc["cache_read"])),
                "output": int(round(acc["output"])),
                "records": int(acc["records"]),
            }
            new_lines.append({k: line[k] for k in _OUTPUT_KEY_ORDER})
        new_lines.sort(key=backfill_tokens._sort_key)

        if new_lines:
            _append_lines(out_path, new_lines)

        state.pending_min_ns = None
        state.pending_max_ns = None
        state.last_issue_bucket = issue
        state.last_flush_monotonic = time.monotonic()
        return new_lines


def _append_lines(out_path: Path, new_lines: List[Dict[str, Any]]) -> None:
    """Append-only -- reads every existing line (validated the same way
    backfill_tokens does), keeps ALL of them (never drops a
    `transcript-backfill` line, and never drops a PRIOR `otel` line
    either -- that would be the regenerating-rewrite behaviour `compact`
    below reserves, not the default write path), appends the fresh
    lines, and writes back under the shared lock. `backfill_tokens.
    merge_and_write` is not reused here: that function's contract is
    "drop every line whose source matches mine, then append" -- correct
    for a REGENERATING source (PT-77 re-running from scratch), but it
    would silently delete this receiver's own previously-flushed otel
    lines on every flush, which is exactly the data loss this must avoid.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_path.parent / ".lock"
    backfill_tokens._acquire_lock(lock_path)
    try:
        existing = backfill_tokens._read_existing_lines(out_path)
        combined = existing + new_lines
        combined.sort(key=backfill_tokens._sort_key)
        text = "".join(json.dumps(line) + "\n" for line in combined)
        backfill_tokens._atomic_write_text(out_path, text)
    finally:
        backfill_tokens._release_lock(lock_path)


def compact(out_path: Path) -> None:
    """May rewrite the receiver's OWN `source: "otel"` lines to coalesce
    same-(issue, role, model) lines by summing -- permitted because these
    lines are additive, and safe because it never touches a
    `transcript-backfill` line. Not called from the per-flush path; a
    separate, occasional operation."""
    lock_path = out_path.parent / ".lock"
    backfill_tokens._acquire_lock(lock_path)
    try:
        existing = backfill_tokens._read_existing_lines(out_path)
        others = [l for l in existing if l.get("source") != SOURCE_NAME]
        mine = [l for l in existing if l.get("source") == SOURCE_NAME]
        coalesced: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for line in mine:
            key = (line["issue"], line["role"], line["model"])
            if key not in coalesced:
                coalesced[key] = dict(line)
                continue
            acc = coalesced[key]
            for counter in ("input", "cache_write", "cache_read", "output", "records"):
                acc[counter] = acc.get(counter, 0) + line.get(counter, 0)
            if line["generated"] > acc["generated"]:
                acc["generated"] = line["generated"]
            if line["window_start"] < acc["window_start"]:
                acc["window_start"] = line["window_start"]
            if line["window_end"] > acc["window_end"]:
                acc["window_end"] = line["window_end"]
        combined = others + [{k: v[k] for k in _OUTPUT_KEY_ORDER} for v in coalesced.values()]
        combined.sort(key=backfill_tokens._sort_key)
        text = "".join(json.dumps(line) + "\n" for line in combined)
        backfill_tokens._atomic_write_text(out_path, text)
    finally:
        backfill_tokens._release_lock(lock_path)


# --------------------------------------------------------------------------
# Config resolution -- repo-root anchored, never Path.cwd().
# --------------------------------------------------------------------------

def _receiver_port(repo_root: Path) -> int:
    """Addendum: `--port` default from config.yml's flat `otel_port` key,
    falling back to 4318. Read directly rather than through
    `cairn.load_config`'s defaulting machinery -- `otel_port` is this
    ticket's own addition, out of that function's existing schema."""
    config_path = repo_root / "process" / "cairn" / "config.yml"
    if not config_path.exists():
        return DEFAULT_OTEL_PORT
    parsed = cairn.parse_yaml_subset(config_path.read_text(encoding="utf-8"))
    port = parsed.get("otel_port")
    return port if isinstance(port, int) else DEFAULT_OTEL_PORT


def _resolve_prefix(repo_root: Path) -> str:
    data_dir = repo_root / "process" / "cairn"
    return cairn.load_config(data_dir)["prefix"]


# --------------------------------------------------------------------------
# Daemon lifecycle -- pidfile, listen probe, detached start, signals.
# --------------------------------------------------------------------------

def _port_is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _read_pidfile(pidfile: Path) -> Optional[int]:
    try:
        return int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _compare_and_delete_pidfile(pidfile: Path, expected_pid: int) -> None:
    """Addendum §5: "unlink the pidfile compare-and-delete: read it back,
    delete only if it still holds our own pid" -- applies to EVERY
    shutdown path (`--stop`'s SIGTERM/SIGINT handler, `serve`'s own
    `finally`, and the PT-86 watchdog), not just the new one. As written
    before this ticket, an exiting receiver unconditionally unlinked the
    pidfile, which could delete a SUCCESSOR's pidfile if a new instance
    had already started and written its own pid to the same path in the
    narrow window between this process deciding to exit and actually
    removing the file."""
    if _read_pidfile(pidfile) != expected_pid:
        return
    try:
        pidfile.unlink()
    except OSError:
        pass


def _nudge_daemon(pidfile: Path, kill=os.kill) -> None:
    """PT-86: signals a running receiver (SIGUSR2) to re-evaluate its
    session registry right now instead of waiting for the watchdog's own
    next WATCHDOG_TICK_SECONDS poll -- sent after every
    `register_session`/`deregister_session` so an immediate `--status`
    (or the grace-window cancel/arm decision) reflects the change without
    a polling-latency window. Load-bearing for the on-decrement reap of a
    crashed SIBLING session (see `serve`'s watchdog docstring, and
    architect review Delta 1) -- a missed nudge never delays the stop for
    a clean exit (the registry file is already gone either way), but does
    skip that reap until the next `end` event, flush, or the slow
    periodic sweep (`--periodic-reap-seconds`) picks it up regardless.

    Architect review, Delta 6: gated on a capability marker
    (`NUDGE_CAPABLE_MARKER_NAME`, written by `serve` at startup, inside
    `_sessions_dir`) -- a receiver started before this change has no
    SIGUSR2 handler at all, and a Python process with no handler for a
    signal is TERMINATED by it (measured: exit -31), losing everything
    accrued since its last flush with no final flush at all. No marker
    present is the safe default (assume "maybe an old daemon", stay
    silent) -- the watchdog's own tick still does the work, just up to
    WATCHDOG_TICK_SECONDS later, for any daemon that IS new enough to
    have one.

    `kill` is injectable (default `os.kill`) so a test can assert exactly
    which signal was (or was not) sent without ever signalling a real
    process."""
    pid = _read_pidfile(pidfile)
    if pid is None or not _pid_is_alive(pid):
        return
    marker = _sessions_dir(pidfile) / NUDGE_CAPABLE_MARKER_NAME
    if not marker.exists():
        return
    try:
        kill(pid, signal.SIGUSR2)
    except OSError:
        pass


# --------------------------------------------------------------------------
# PT-86: session bookkeeping -- one small file per live session, named for
# the session id, holding its liveness-probe pid. A SIBLING of the pidfile
# (`_sessions_dir`), not a single JSON registry: two different sessions
# never touch the same path, so register/deregister/reap need no
# cross-process lock at all -- a plain create/read/unlink is already
# atomic enough for this, the same reasoning the pidfile itself already
# relies on.
# --------------------------------------------------------------------------

def _sessions_dir(pidfile: Path) -> Path:
    return pidfile.parent / SESSIONS_DIRNAME


def register_session(sessions_dir: Path, session_id: str, pid: Optional[int]) -> None:
    """Idempotent upsert -- a SessionStart hook firing twice for the same
    session id (shouldn't happen, but never fatal if it does) just
    rewrites the same file with the same content. `pid=None` (addendum
    C: "no usable pid -- record pid: null") is stored as an empty file,
    not the string "None" -- `live_session_ids` must be able to tell
    "no pid captured" apart from "a malformed entry" cheaply."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / session_id).write_text(str(pid) if pid is not None else "", encoding="utf-8")


def deregister_session(sessions_dir: Path, session_id: str) -> None:
    """No-op if the session was never registered (or already reaped) --
    a SessionEnd hook must never fail teardown over a missing file."""
    try:
        (sessions_dir / session_id).unlink()
    except FileNotFoundError:
        pass


def live_session_ids(sessions_dir: Path) -> Dict[str, Optional[int]]:
    """Non-mutating snapshot of every RECORDED session id and its pid
    (None when no pid was ever captured) -- deliberately does not probe
    liveness itself (a dead-but-not-yet-reaped id still appears here;
    `--status` depends on that to report an honest "dead" rather than
    silently vanishing it). Skips dotfiles -- `.closing` (the
    point-of-no-return marker, see `serve`) lives in this SAME directory
    and must never be mistaken for a session id."""
    if not sessions_dir.is_dir():
        return {}
    ids: Dict[str, Optional[int]] = {}
    for entry in sessions_dir.iterdir():
        if not entry.is_file() or entry.name.startswith("."):
            continue
        raw = entry.read_text(encoding="utf-8").strip()
        if not raw:
            ids[entry.name] = None
            continue
        try:
            ids[entry.name] = int(raw)
        except ValueError:
            continue  # genuinely malformed -- skip rather than crash a probe cycle
    return ids


def _transcript_is_stale(session_id: str, transcripts_dir: Path, now: Optional[float] = None) -> bool:
    """Addendum C's second independent signal: a session's own transcript
    (the same file role resolution already reads) hasn't been touched in
    >= 30 minutes. No transcript at all counts as stale (nothing to
    protect) -- it either never existed or already aged out."""
    transcript_path = transcripts_dir / f"{session_id}.jsonl"
    try:
        mtime = transcript_path.stat().st_mtime
    except OSError:
        return True
    return (now if now is not None else time.time()) - mtime >= TRANSCRIPT_STALE_SECONDS


def _is_session_dead(pid: int, session_id: str, transcripts_dir: Path) -> bool:
    """Addendum C: "two independent signals of death" -- reap only when
    BOTH the pid probe fails AND the transcript has gone quiet, so a
    single mis-detected pid (e.g. a future wrapper process between claude
    and the hook shell) can never silently cut off a live session's
    telemetry. The transcript stat only runs once the pid already looks
    dead -- no extra cost on the common (session still running) path."""
    if _pid_is_alive(pid):
        return False
    return _transcript_is_stale(session_id, transcripts_dir)


def _session_liveness_probe(transcripts_dir: Path):
    """Binds `_is_session_dead`'s two-signal check to a specific
    `transcripts_dir` and returns it as the `is_alive(pid, session_id)`
    callable `reap_dead_sessions` expects -- the real call sites
    (`serve`, `--session-ended`) always pass this bound to whatever
    `transcripts_dir` they already resolved (honouring a
    `--transcripts-dir` test override), instead of relying on
    `reap_dead_sessions`'s own default resolution."""
    return lambda pid, session_id: not _is_session_dead(pid, session_id, transcripts_dir)


def reap_dead_sessions(sessions_dir: Path, is_alive=None) -> List[str]:
    """The liveness probe (ruling item 1 / addendum §3): removes every
    recorded session confirmed dead, so a crashed session that never
    called `--session-ended` cannot pin the receiver forever. A `pid:
    null` entry (no pid ever captured) is NEVER reaped by this probe --
    addendum C: "never reaped, shown as unknown"; it only ever leaves the
    registry via its own `--session-ended`. Returns the reaped ids.

    `is_alive(pid, session_id) -> bool` is injectable (default: the real
    two-signal check against this script's own on-disk transcripts_dir)
    so a test can substitute a pure liveness function without needing a
    real dead pid or a real transcript file.
    """
    if is_alive is None:
        transcripts_dir = Path.home() / ".claude" / "projects" / backfill_tokens._transcript_dir_slug(backfill_tokens._repo_root())
        is_alive = _session_liveness_probe(transcripts_dir)
    removed: List[str] = []
    for session_id, pid in live_session_ids(sessions_dir).items():
        if pid is None:
            continue
        if not is_alive(pid, session_id):
            deregister_session(sessions_dir, session_id)
            removed.append(session_id)
    return removed


_STDIN_READ_BUDGET_SECONDS = 0.5  # total wall-clock cap, see docstring below


def _session_id_from_stdin() -> Optional[str]:
    """Addendum §2/§D: "absent -> read session_id from the hook's stdin
    JSON, and only when stdin is not a TTY. Never block on stdin." A
    command hook's stdin carries the hook's own JSON payload (session_id,
    transcript_path, cwd, hook_event_name, ...) and Claude Code closes it
    promptly, so this returns fast in the real hook path.

    The TTY check alone is NOT sufficient (measured: a non-interactive
    but still-OPEN pipe -- neither a TTY nor EOF-terminated -- makes a
    bare blocking `sys.stdin.read()` hang forever, exactly the "never
    block" violation this addendum forbids). `select.select` with a
    bounded per-chunk timeout, plus an overall `_STDIN_READ_BUDGET_SECONDS`
    wall-clock cap, is what actually guarantees this returns: if nothing
    is EVER readable, or the writer never closes, this gives up and
    returns None rather than hanging -- a missed session id degrades to
    "untracked" (§6: never pins the receiver), which is always the safe
    direction per §0.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        deadline = time.monotonic() + _STDIN_READ_BUDGET_SECONDS
        chunks: List[bytes] = []
        fd = sys.stdin.fileno()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                break  # nothing arrived within the budget -- give up, never hang
            chunk = os.read(fd, 65536)
            if not chunk:
                break  # EOF -- the writer closed stdin, exactly the real-hook case
            chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    return session_id if isinstance(session_id, str) and session_id else None


def _resolve_session_id(explicit_value: Optional[str], session_id_flag: Optional[str]) -> Optional[str]:
    """The fallback chain shared by `--ensure-running` and
    `--session-ended`: an id given directly to the flag wins, then
    `--session-id`, then the hook's stdin JSON (§2)."""
    if explicit_value:
        return explicit_value
    if session_id_flag:
        return session_id_flag
    return _session_id_from_stdin()


# PT-81 H1: the settings.json env block this ticket documents (TRACKER.md)
# already uses the bare string "1" for every boolean-shaped flag
# (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS, CLAUDE_CODE_ENABLE_TODO_TOOLS,
# CLAUDE_CODE_ENABLE_TELEMETRY itself) -- this accepts that plus the
# handful of other spellings a human might type by hand into
# settings.local.json or a shell profile. Unset/empty/anything else is
# falsy; there is no ambiguous "maybe" here on purpose.
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _env_flag_truthy(value: Optional[str]) -> bool:
    return value is not None and value.strip().lower() in _TRUTHY_ENV_VALUES


def _endpoint_port(endpoint: Optional[str]) -> Optional[int]:
    """The port named by OTEL_EXPORTER_OTLP_ENDPOINT (e.g.
    "http://127.0.0.1:4318" -> 4318), or None when the variable carries
    no explicit port (a malformed value -- not this function's job to
    diagnose further). Deliberately does NOT special-case an unset/empty
    `endpoint` -- see `_effective_endpoint_port`, the caller H3 actually
    uses, for why an unset variable is not "nothing to compare"."""
    if not endpoint:
        return None
    try:
        return urlparse(endpoint).port
    except ValueError:
        return None


def _effective_endpoint_port(endpoint: Optional[str]) -> int:
    """H3, architect's amendment (4c1b751, empirically confirmed live --
    `claude -p` with telemetry on and no endpoint var set genuinely POSTs
    claude_code.token.usage to 127.0.0.1:4318, a real scratch-sink
    capture, not just the OTel spec's documented default): an UNSET
    OTEL_EXPORTER_OTLP_ENDPOINT is not "nothing to compare" -- a
    conforming exporter falls back to the OTLP protocol default,
    `http://localhost:4318`, and keeps exporting there. A project with
    `otel_port: 4319` and telemetry on but no endpoint override gets a
    receiver bound to 4319 while the real exporter posts to 4318 --
    H3's exact silent mismatch, missed entirely by treating "unset" as
    "skip the check". Always returns a concrete port to compare against:
    the parsed value when the variable is set (and carries one), else
    DEFAULT_OTEL_PORT."""
    parsed = _endpoint_port(endpoint)
    return parsed if parsed is not None else DEFAULT_OTEL_PORT


def ensure_running(
    repo_root: Path, pidfile: Path, port: int,
    grace_period_seconds: float = DEFAULT_GRACE_PERIOD_SECONDS,
    session_id: Optional[str] = None, session_pid: Optional[int] = None,
    transcripts_dir: Optional[Path] = None,
    periodic_reap_seconds: float = DEFAULT_PERIODIC_REAP_SECONDS,
) -> bool:
    """Single instance enforced by pidfile + a listen probe; a second
    start is a no-op, never an error. Returns True if a (new or
    already-live) receiver is running, False if it declined to start --
    no cairn tracker at repo_root (a spin-off/non-cairn checkout must
    never get a background process it has no use for), telemetry off
    (H1), a port/endpoint disagreement (H3), or a genuine startup
    failure distinguished from an already-held port (H2). Every False
    path prints exactly why to stderr; the SessionStart hook still exits
    0 regardless -- telemetry must never fail a session -- but no longer
    swallows stderr, so these messages actually reach someone.

    `grace_period_seconds` (PT-86) only matters on a FRESH spawn -- it's
    threaded into the detached child's own argv so the long-lived daemon
    knows how long to wait after its last session ends before flushing
    and exiting. An already-running daemon keeps whatever value it was
    originally spawned with; a later `--ensure-running` cannot retune it.

    `session_id`/`session_pid` (PT-86, addendum §B) register a live
    session -- when `session_id` is given, this happens BEFORE deciding
    whether a receiver is already up ("both sides write first, then
    check": the registration file persists across a respawn, so it is
    never wasted even if this call ends up spawning a fresh daemon
    below), and the daemon's own `.closing` point-of-no-return marker is
    checked and waited out if present, so a session starting in the
    instant the daemon is mid-shutdown is never silently dropped.

    `transcripts_dir`, like `grace_period_seconds`, only matters on a
    FRESH spawn -- threaded into the child's own argv so its two-signal
    liveness probe (addendum C) consults the same transcripts directory
    this call resolved (a `--transcripts-dir` override in tests, or the
    real project's own).
    """
    data_dir = repo_root / "process" / "cairn"
    if not (data_dir / "config.yml").exists():
        return False

    # H1: gate on the SAME env block that controls the exporter -- one
    # block, two consumers, checked here so a project with telemetry off
    # gets no bound port and no idle daemon it never opted into.
    if not _env_flag_truthy(os.environ.get("CLAUDE_CODE_ENABLE_TELEMETRY")):
        return False

    sessions_dir = _sessions_dir(pidfile)
    if session_id:
        register_session(sessions_dir, session_id, session_pid)

    pid = _read_pidfile(pidfile)
    already_running = pid is not None and _pid_is_alive(pid) and _port_is_listening(port)

    closing_marker = sessions_dir / CLOSING_MARKER_NAME
    if closing_marker.exists():
        # Addendum §B: the daemon is (or very recently was) at its point
        # of no return. Wait for its socket to actually close, bounded --
        # never indefinitely, this runs synchronously inside a
        # SessionStart hook.
        deadline = time.monotonic() + 1.0
        port_freed = False
        while time.monotonic() < deadline:
            if not _port_is_listening(port):
                port_freed = True
                break
            time.sleep(0.1)
        if not port_freed:
            # Either the daemon aborted on seeing our fresh registration
            # above (and already removed `.closing`) or it simply hasn't
            # gotten there yet -- either way this is NOT a stranger
            # holding the port, so H2's "already held" alarm below would
            # be a false one. We're already registered; report success.
            return True
        already_running = False  # the old daemon is genuinely gone -- fall through to a fresh spawn

    if already_running:
        return True  # no-op -- already up, and (if given) now registered too

    # H3: otel_port (config.yml, the single source of truth -- `port`
    # here) vs. the port this process's OWN inherited
    # OTEL_EXPORTER_OTLP_ENDPOINT effectively names (architect's
    # amendment, 4c1b751: an UNSET endpoint still resolves to the OTLP
    # default 4318, not "nothing to compare" -- see
    # _effective_endpoint_port). A real disagreement doesn't lose
    # telemetry, it silently DELIVERS it to whatever else is listening on
    # the wrong port (PT-79's real contamination incident) -- refuse
    # rather than start a receiver nothing will actually reach, or start
    # one that reaches a stranger's.
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    effective_port = _effective_endpoint_port(endpoint)
    if effective_port != port:
        endpoint_desc = (
            f"unset (falls back to the OTLP default, {DEFAULT_OTEL_PORT})"
            if not endpoint else f"{effective_port!r}, from OTEL_EXPORTER_OTLP_ENDPOINT={endpoint!r}"
        )
        print(
            f"otel_receiver: refusing to start -- otel_port ({port}, from "
            f"process/cairn/config.yml) disagrees with the exporter's destination "
            f"port ({endpoint_desc}); these must name the same receiver or "
            "telemetry silently goes to the wrong place",
            file=sys.stderr,
        )
        return False

    # H2, first half: the pidfile check above already ruled out "this is
    # OUR OWN already-running instance" -- so if something is STILL
    # listening on this port, it's a DIFFERENT process (very plausibly
    # another project's receiver sharing the same default otel_port).
    # Spawning our own child anyway would just hand it a doomed
    # "Address already in use" exit, silently, into a gitignored log --
    # refuse up front and say so instead.
    if _port_is_listening(port):
        print(
            f"otel_receiver: port {port} (otel_port) is already held by another "
            "process -- not this project's own receiver, per its pidfile -- "
            "refusing to start a second one; set a different otel_port in "
            "process/cairn/config.yml if this is expected",
            file=sys.stderr,
        )
        return False

    logfile = repo_root / LOGFILE_REL
    logfile.parent.mkdir(parents=True, exist_ok=True)
    spawn_argv = [
        sys.executable, str(Path(__file__).resolve()),
        "--out-file", str(repo_root / backfill_tokens.DEFAULT_OUT_REL),
        "--pidfile", str(pidfile), "--port", str(port),
        "--grace-period-seconds", str(grace_period_seconds),
        "--periodic-reap-seconds", str(periodic_reap_seconds),
    ]
    if transcripts_dir is not None:
        spawn_argv += ["--transcripts-dir", str(transcripts_dir)]
    with open(logfile, "ab") as log:
        subprocess.Popen(
            spawn_argv,
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(repo_root),
        )
    # Give the child a brief window to bind before this call returns --
    # NOT a hard guarantee, just enough that a second SessionStart firing
    # moments later (team-agents spawns several teammates in a burst,
    # each running this same hook) sees a live port instead of racing a
    # duplicate start. Capped short (0.5s): this runs synchronously
    # inside a SessionStart hook, which must not stall session startup.
    for _ in range(5):
        if _port_is_listening(port):
            return True
        time.sleep(0.1)
    # H2, second half: distinguish "spawned but never came up" from
    # success instead of reporting True either way -- a caller (or a
    # human reading the hook's now-visible stderr) needs to know the
    # difference; the exit code alone can't carry it since --ensure-
    # running's own CLI path always returns 0 regardless (a SessionStart
    # hook must not fail a session over telemetry).
    print(
        f"otel_receiver: spawned but port {port} (otel_port) never started "
        f"listening within the wait window -- the child may have exited "
        f"immediately; see {logfile}",
        file=sys.stderr,
    )
    return False


def _status(pidfile: Path, port: int, out_path: Path, sessions_dir: Path, transcripts_dir: Path) -> int:
    """--status: running?, port, out-file, plus PT-86's session count and
    per-id liveness -- a caller-facing health check (what an operator or
    a test runs to ask "is it up"), distinct from --ensure-running (what
    the hook runs to make it so). Exit 0 when running, 1 when not -- the
    common status-command convention, scriptable without parsing stdout.

    The session lines are a FRESH, non-mutating probe every call -- a
    dead-but-not-yet-reaped id is reported honestly as "dead" rather than
    silently omitted; only `--session-ended` and a flush actually reap.

    Four states, not three (architect review Delta 3, then Follow-up 4
    at the re-review, 0d9f0b5 -- team-lead's final call): `alive` (pid
    probe says alive), `dead` (BOTH signals agree -- reap-eligible right
    now), `dead-pending` (pid probe says dead, but the transcript is
    still fresh -- protected from reaping for up to 30 minutes; this is
    the "why won't the receiver stop" diagnostic case an operator would
    otherwise have to infer from `alive`, which would hide it), and
    `unknown` (no pid ever captured -- never reaped, addendum C).

    The `dead`/`dead-pending` distinction reads `TRANSCRIPTS_DIR_MARKER_NAME`,
    written by the ACTUAL running daemon at its own startup, in
    preference to the `transcripts_dir` this (separate) invocation
    resolved on its own -- the two can legitimately differ (a test's
    `--transcripts-dir` override only ever accompanies the ORIGINAL
    `--ensure-running` spawn, not a later `--status` call) and only the
    daemon's own answer is correct. Falls back to the passed-in
    `transcripts_dir` when the marker is absent (no daemon has ever
    written one -- an old daemon, or one that hasn't started yet).
    """
    pid = _read_pidfile(pidfile)
    running = pid is not None and _pid_is_alive(pid) and _port_is_listening(port)
    print(f"running: {running}")
    print(f"port: {port}")
    print(f"out-file: {out_path}")
    try:
        marker_text = (sessions_dir / TRANSCRIPTS_DIR_MARKER_NAME).read_text(encoding="utf-8").strip()
        if marker_text:
            transcripts_dir = Path(marker_text)
    except OSError:
        pass
    ids = live_session_ids(sessions_dir)
    print(f"sessions: {len(ids)}")
    for session_id in sorted(ids):
        entry_pid = ids[session_id]
        if entry_pid is None:
            state = "unknown"  # addendum C/§7: no pid ever captured
        elif _pid_is_alive(entry_pid):
            state = "alive"
        elif _transcript_is_stale(session_id, transcripts_dir):
            state = "dead"  # both signals agree -- reap-eligible now
        else:
            state = "dead-pending"  # pid gone, transcript still fresh -- not yet reap-eligible
        print(f"session {session_id}: {state}")
    return 0 if running else 1


def _signal_running(pidfile: Path, sig: int, label: str) -> int:
    pid = _read_pidfile(pidfile)
    if pid is None or not _pid_is_alive(pid):
        print(f"error: no running receiver ({label} target not found via {pidfile})", file=sys.stderr)
        return 1
    os.kill(pid, sig)
    return 0


# --------------------------------------------------------------------------
# HTTP server -- thin wrapper over parse_export/fold/flush.
# --------------------------------------------------------------------------

def _handle_export_body(state: ReceiverState, body: bytes, content_encoding: Optional[str]) -> None:
    payload = decode_otlp_json(body, content_encoding)
    datapoints = parse_export(payload)
    fold(datapoints, state)


def make_handler(state: ReceiverState, on_export=None, on_request=None):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "cairn-otel-receiver/1.0"

        def log_message(self, fmt, *args):  # noqa: A003
            pass

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/v1/metrics":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            try:
                _handle_export_body(state, body, self.headers.get("Content-Encoding"))
            except ReceiverError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                if on_request:
                    on_request()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            if on_export:
                on_export()
            if on_request:
                on_request()

    return Handler


def run_once(port: int, out_path: Path, branch_repo_root: Path, prefix: str, roster: Set[str], transcripts_dir: Path) -> int:
    """`--once`: bind, accept exactly one **real POST /v1/metrics
    request**, flush, exit. Deliberately NOT a single bare
    `handle_request()` call: `HTTPServer.handle_request()` blocks until
    it accepts one CONNECTION, not one completed HTTP request -- a
    caller's own readiness probe (a bare `socket.create_connection`
    opened and immediately closed to confirm the port is listening, the
    same pattern this project's other subprocess-CLI tests already use)
    would itself consume the single shot and leave the real POST that
    follows moments later refused. Instead: loop `handle_request()`,
    tracked by `on_request` (fires once a real /v1/metrics POST has been
    handled, success or 400 alike), bounded by an overall deadline so a
    caller that never sends anything doesn't hang the process forever.
    """
    state = ReceiverState()
    got_one = threading.Event()
    handler_cls = make_handler(state, on_request=got_one.set)
    httpd = http.server.HTTPServer(("127.0.0.1", port), handler_cls)
    httpd.timeout = 5
    deadline = time.monotonic() + 30
    try:
        while not got_one.is_set() and time.monotonic() < deadline:
            httpd.handle_request()
    finally:
        httpd.server_close()

    branch = _current_branch(branch_repo_root)
    hint = _issue_hint_from_datapoints(state.series_meta.values())
    issue = resolve_issue(branch, prefix, hint)
    try:
        flush(state, out_path, issue, _now_iso(), roster=roster, transcripts_dir=transcripts_dir)
    except (ReceiverError, backfill_tokens.BackfillError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def serve(
    port: int, out_path: Path, pidfile: Path, flush_interval: int,
    branch_repo_root: Path, prefix: str, roster: Set[str], transcripts_dir: Path,
    sessions_dir: Optional[Path] = None, grace_period_seconds: float = DEFAULT_GRACE_PERIOD_SECONDS,
    periodic_reap_seconds: float = DEFAULT_PERIODIC_REAP_SECONDS,
) -> None:
    state = ReceiverState()
    sessions_dir = sessions_dir if sessions_dir is not None else _sessions_dir(pidfile)
    my_pid = os.getpid()
    session_is_alive = _session_liveness_probe(transcripts_dir)

    # A crash can leave a stale `.closing` marker from a predecessor that
    # never got to remove it (addendum §B) -- a fresh daemon must not
    # inherit a false "mid-shutdown" state.
    closing_marker = sessions_dir / CLOSING_MARKER_NAME
    try:
        closing_marker.unlink()
    except OSError:
        pass

    # Delta 6: declare "I understand SIGUSR2" before anything could ever
    # nudge this process -- a receiver started before this change has no
    # handler for it at all, so `_nudge_daemon` must never send one
    # without first confirming, via this marker, that whatever is
    # actually listening on the other end is new enough to survive it.
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / NUDGE_CAPABLE_MARKER_NAME).write_text("", encoding="utf-8")
    # So a LATER, separate `--status` invocation can label a `dead`/
    # `dead-pending` entry using the transcripts_dir THIS daemon actually
    # resolved, not whatever that separate CLI call would resolve on its
    # own -- see TRANSCRIPTS_DIR_MARKER_NAME's own comment.
    (sessions_dir / TRANSCRIPTS_DIR_MARKER_NAME).write_text(str(transcripts_dir), encoding="utf-8")

    def _do_flush() -> None:
        branch = _current_branch(branch_repo_root)
        hint = _issue_hint_from_datapoints(state.series_meta.values())
        issue = resolve_issue(branch, prefix, hint)
        try:
            flush(state, out_path, issue, _now_iso(), roster=roster, transcripts_dir=transcripts_dir)
        except (ReceiverError, backfill_tokens.BackfillError) as e:
            print(f"otel_receiver: flush refused: {e}", file=sys.stderr)
        # Addendum §3: the liveness probe also runs "at each flush" -- an
        # independent backstop to the on-`end` reap, for the scenario
        # where EVERY session that ever registered crashed without ever
        # calling `--session-ended`.
        reap_dead_sessions(sessions_dir, is_alive=session_is_alive)

    def _on_export() -> None:
        branch = _current_branch(branch_repo_root)
        hint = _issue_hint_from_datapoints(state.series_meta.values())
        issue_now = resolve_issue(branch, prefix, hint)
        elapsed = time.monotonic() - state.last_flush_monotonic
        if (state.last_issue_bucket is not None and issue_now != state.last_issue_bucket) or elapsed >= flush_interval:
            _do_flush()

    handler_cls = make_handler(state, on_export=_on_export)

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        # Multiple teammates are separate OS processes, each running
        # their own OTel SDK on its own export interval -- concurrent
        # POSTs are the normal case for this project's team-agents
        # workflow, not an edge case.
        daemon_threads = True

    httpd = Server(("127.0.0.1", port), handler_cls)

    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(my_pid), encoding="utf-8")

    def _on_sigusr1(signum, frame):
        _do_flush()

    def _on_shutdown(signum, frame):
        """`--stop` / SIGINT / a process manager -- addendum §5's
        ordering applies here too, not just the watchdog path: close the
        listening socket BEFORE flushing (so the flush is complete by
        construction, not by luck), and compare-and-delete the pidfile
        rather than an unconditional unlink (a successor could already
        have written its own pid to this same path). `server_close()`,
        not `httpd.shutdown()`, is correct HERE: this handler runs ON
        THE SAME (main) THREAD as `serve_forever()` -- calling
        `.shutdown()` from that thread would deadlock waiting for a loop
        iteration that can never run while this handler is executing.
        """
        httpd.server_close()
        _do_flush()
        _compare_and_delete_pidfile(pidfile, my_pid)
        sys.exit(0)

    # PT-86 (addendum §4/§B): the watchdog. `--ensure-running`/
    # `--session-ended` are separate, short-lived CLI processes that
    # mutate `sessions_dir` directly (one file per session id, no lock
    # needed -- see that section's docstring) and then send SIGUSR2 as
    # the nudge below; this background thread is what actually notices
    # and acts, waking either on that nudge or at least every
    # WATCHDOG_TICK_SECONDS regardless. `ever_nonempty` starts true if
    # this daemon INHERITED a non-empty registry (a respawn after a
    # crash, addendum A.1/§6) -- an inherited registry is authoritative
    # and may legitimately drain to empty and stop; a registry that has
    # never been non-empty (nobody ever registered a session with this
    # daemon) never arms the timer at all.
    #
    # Declared BEFORE the SIGUSR2 handler is registered (architect
    # review, Delta 4): the handler closes over `wake_event`, and a
    # signal arriving between `signal.signal(...)` and this assignment
    # would otherwise raise NameError on the main thread.
    wake_event = threading.Event()
    stopping = False

    # A lightweight "please re-evaluate the session registry right now"
    # nudge (PT-86) -- carries no data (the registry files, mutated
    # directly by `--ensure-running`/`--session-ended`, remain the only
    # source of truth), so it does not reopen anything the addendum's
    # withdrawal of the HTTP control endpoint closed: it is derived from
    # the SAME local `pidfile` a cross-repo caller could never discover
    # in the first place (addendum A.2). A missed/coalesced signal never
    # delays a clean stop (the registry file is already gone either way)
    # but DOES skip the crashed-sibling reap until the next `end` event,
    # flush, or the slow periodic reap below -- see architect review
    # Delta 1's correction to this comment's earlier, overstated claim.
    def _on_session_nudge(signum, frame):
        wake_event.set()

    signal.signal(signal.SIGUSR1, _on_sigusr1)
    signal.signal(signal.SIGUSR2, _on_session_nudge)
    signal.signal(signal.SIGTERM, _on_shutdown)
    signal.signal(signal.SIGINT, _on_shutdown)

    def _watchdog_loop() -> None:
        shutdown_deadline: Optional[float] = None
        ever_nonempty = bool(live_session_ids(sessions_dir))
        last_periodic_reap = time.monotonic()
        while True:
            nudged = wake_event.wait(WATCHDOG_TICK_SECONDS)
            wake_event.clear()
            if stopping:
                return
            # §3: the probe runs "on every end event", not on a bare
            # periodic tick that nothing prompted -- `--session-ended`
            # (only) sends the SIGUSR2 nudge, so `nudged` distinguishes
            # "an end event just happened, reap now" from "just the
            # regular WATCHDOG_TICK_SECONDS poll, don't reap yet" --
            # otherwise a session that's merely REGISTERED with an
            # already-dead pid (a synthetic id in a test, or a genuinely
            # crashed one that never got a chance to end cleanly) would
            # be silently reaped by the very next tick regardless of
            # whether anything actually decremented, which is both
            # surprising for `--status` (a "dead" entry vanishing with
            # nobody having ended anything) and NOT what "on every
            # decrement" says. The other two probe triggers -- at each
            # flush, and once more immediately before the point of no
            # return -- are unconditional, below and in `_do_flush`.
            #
            # Team-lead's ruling (PT-86, 138c03c, architect re-reviewed
            # at 0d9f0b5): when EVERY registered session has crashed,
            # neither the nudge nor a flush ever fires, so without a
            # THIRD, time-based trigger a fully-crashed registry pins
            # the receiver until some UNRELATED future session's own
            # SessionEnd happens to reap it. `due_for_periodic_reap`
            # below is that trigger -- deliberately far slower than
            # WATCHDOG_TICK_SECONDS (reaping every tick regardless of a
            # nudge was tried and rejected: it broke the "not yet
            # reaped" window LivenessReapTests relies on) so it can
            # never race that window in this suite's fast tests. It
            # goes through the SAME two-signal `session_is_alive` check
            # every other reap site uses -- a session that is merely
            # idle (alive pid, or a fresh transcript) can never be
            # removed by this or any other trigger, only one that is
            # confirmed dead by both signals.
            due_for_periodic_reap = (time.monotonic() - last_periodic_reap) >= periodic_reap_seconds
            if nudged or due_for_periodic_reap:
                reap_dead_sessions(sessions_dir, is_alive=session_is_alive)
                if due_for_periodic_reap:
                    last_periodic_reap = time.monotonic()
            if live_session_ids(sessions_dir):
                ever_nonempty = True
                shutdown_deadline = None
                continue
            if not ever_nonempty:
                continue
            if shutdown_deadline is None:
                shutdown_deadline = time.monotonic() + grace_period_seconds
                continue
            if time.monotonic() < shutdown_deadline:
                continue
            # Deadline passed and the registry was empty as of the top
            # of this tick -- addendum §3: "once more immediately before
            # the point of no return", a fresh probe right now, since a
            # session that looked dead a tick ago may since have proven
            # itself alive via a flush-triggered reap elsewhere, or a
            # brand new session may have registered between ticks.
            reap_dead_sessions(sessions_dir, is_alive=session_is_alive)
            if live_session_ids(sessions_dir):
                shutdown_deadline = None
                continue
            # The point of no return (addendum §B): exclusive-create
            # `.closing`, THEN re-read -- a session that registered in
            # the instant between the two must still cancel this.
            try:
                fd = os.open(str(closing_marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
            except FileExistsError:
                continue  # a single watchdog thread should never double-fire; be safe anyway
            if live_session_ids(sessions_dir):
                try:
                    closing_marker.unlink()
                except OSError:
                    pass
                shutdown_deadline = None
                continue
            # Nothing after this aborts. §5 ordering: socket closed
            # first, then flush, then compare-and-delete the pidfile,
            # then remove `.closing`. `.shutdown()` (cross-thread safe --
            # `serve_forever()` is running on the main thread right now)
            # only stops the accept LOOP; it blocks until that loop has
            # genuinely exited, but the fd stays bound until
            # `server_close()` actually runs -- and a racing
            # `--ensure-running`'s port-freed probe depends on the fd
            # being gone, not just unaccepted. Close it here, from this
            # thread, right after `.shutdown()` unblocks, rather than
            # leaving it to `serve()`'s own `finally` (whose timing
            # relative to this thread is not guaranteed) -- a second
            # `server_close()` there afterward is a harmless no-op.
            httpd.shutdown()
            httpd.server_close()
            _do_flush()
            _compare_and_delete_pidfile(pidfile, my_pid)
            try:
                closing_marker.unlink()
            except OSError:
                pass
            return

    watchdog = threading.Thread(target=_watchdog_loop, daemon=True)
    watchdog.start()
    try:
        httpd.serve_forever()
    finally:
        # Setting `stopping` + waking wakes an IDLING watchdog
        # immediately. But when THIS thread is here because the WATCHDOG
        # itself called `httpd.shutdown()` (the point-of-no-return path),
        # the watchdog is not idling -- it is mid-flight through its own
        # final flush / compare-and-delete-pidfile / `.closing` removal.
        # `daemon=True` means the interpreter will NOT wait for it once
        # this (main) thread finishes -- without an explicit join here, a
        # fast enough main-thread exit truncates that work mid-flush,
        # silently dropping the very grace-window datapoint AC 2 exists
        # to protect. Join (bounded, as a safety net -- this thread's own
        # work is already done at this point either way) before this
        # function is allowed to return.
        stopping = True
        wake_event.set()
        watchdog.join(timeout=10.0)
        try:
            httpd.server_close()
        except OSError:
            pass
        _compare_and_delete_pidfile(pidfile, my_pid)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="PT-78 OTLP token-usage receiver (cairn)")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--out-file", type=Path, default=None)
    parser.add_argument("--flush-interval", type=int, default=DEFAULT_FLUSH_INTERVAL_SECONDS)
    parser.add_argument("--pidfile", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--transcripts-dir", type=Path, default=None)
    parser.add_argument("--ingest", default=None, help="path to an OTLP-JSON payload, or '-' for stdin")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--ensure-running", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--flush-now", action="store_true")
    parser.add_argument("--stop", action="store_true")
    # PT-86: the last-session-ends-the-daemon-stops-itself lifecycle
    # (process/cairn/issues/PT-86.md, architect addendum §D -- the seam,
    # pinned). Both `--ensure-running`'s and `--session-ended`'s session
    # id are optional and fall back to the hook's stdin JSON when absent
    # (`_resolve_session_id`); `--session-ended` additionally accepts its
    # id as its OWN inline value (`nargs="?"`) since §D writes it as
    # `--session-ended [ID]` -- an explicit `--session-id` is still
    # accepted too and wins if the inline value is absent.
    parser.add_argument("--session-id", default=None, help="the SessionStart/SessionEnd hook's session_id")
    parser.add_argument("--session-pid", type=int, default=None, help="the liveness-probe pid ($PPID); absent/0 -> pid: null, never reaped")
    parser.add_argument(
        "--session-ended", nargs="?", const="", default=None, metavar="SESSION_ID",
        help="deregister SESSION_ID (or --session-id, or the hook's stdin JSON) -- the SessionEnd hook's target",
    )
    parser.add_argument("--grace-period-seconds", "--grace", dest="grace_period_seconds", type=float, default=DEFAULT_GRACE_PERIOD_SECONDS)
    parser.add_argument("--periodic-reap-seconds", type=float, default=DEFAULT_PERIODIC_REAP_SECONDS)
    args = parser.parse_args(argv)

    # `repo_root` anchors everything EXCEPT the branch read: prefix,
    # roster, --out-file's default, and the transcripts-dir slug always
    # come from the REAL project (this script's own on-disk location) --
    # this receiver operates on ONE tracker, always, never a fake one.
    # `--repo-root` overrides ONLY where `_current_branch` asks git,
    # which is the sole reason a test (or an operator) would ever need a
    # different one: to control the branch signal without touching cwd.
    repo_root = backfill_tokens._repo_root()
    branch_repo_root = args.repo_root or repo_root
    try:
        prefix = _resolve_prefix(repo_root)
    except cairn.CairnError as e:
        print(f"error: could not read the tracker prefix from config.yml: {e}", file=sys.stderr)
        return 1

    out_path = args.out_file or (repo_root / backfill_tokens.DEFAULT_OUT_REL)
    pidfile = args.pidfile or (repo_root / PIDFILE_REL)
    port = args.port if args.port is not None else _receiver_port(repo_root)
    roster = backfill_tokens._roster_names(repo_root)
    transcripts_dir = args.transcripts_dir or (
        Path.home() / ".claude" / "projects" / backfill_tokens._transcript_dir_slug(repo_root)
    )

    if args.ensure_running:
        # §2/§D: absent --session-id falls back to the hook's stdin JSON
        # (never blocks -- only reads when stdin is not a TTY). A bare
        # `--ensure-running` with no id anywhere (every pre-PT-86 call
        # site, and this project's own PT-81 hardening tests) registers
        # nothing -- back-compat, and §6: a registry that has never been
        # non-empty can never trigger a self-stop.
        session_id = _resolve_session_id(None, args.session_id)
        session_pid = args.session_pid if args.session_pid else None  # 0 or absent -> null
        ensure_running(
            repo_root, pidfile, port, grace_period_seconds=args.grace_period_seconds,
            session_id=session_id, session_pid=session_pid, transcripts_dir=transcripts_dir,
            periodic_reap_seconds=args.periodic_reap_seconds,
        )
        # Deliberately NOT nudged: the watchdog's regular
        # WATCHDOG_TICK_SECONDS tick already re-checks emptiness every
        # cycle regardless of any nudge (only the REAP call is nudge-
        # gated -- see `_watchdog_loop`), so a `start` still cancels a
        # pending grace-shutdown within one tick without this. Nudging
        # here too would make a freshly-registered (possibly
        # already-dead-pid, e.g. a crashed session respawned before its
        # own SessionEnd could ever fire) entry get swept on the very
        # next tick regardless of whether anything actually ended --
        # exactly the "on every decrement" boundary `--session-ended`'s
        # nudge exists to draw.
        return 0  # never an error -- a non-cairn checkout just declines

    if args.session_ended is not None:
        session_id = _resolve_session_id(args.session_ended or None, args.session_id)
        # §10: every control-path failure is non-fatal -- one stderr
        # line, exit 0. No session id resolved at all is not even a
        # failure: a SessionEnd hook must never fail teardown over
        # telemetry, and cannot block it either way.
        if not session_id:
            return 0
        # Architect review (ef000d5), Delta 2: deregistration is a LOCAL
        # FILE OPERATION and must be unconditional -- a session ending
        # while no daemon is running (or mid-shutdown, just after its
        # pidfile was compare-and-deleted) must still remove its own
        # `.sessions/<id>` file. Skipping this when the pidfile check
        # fails left a phantom entry for the NEXT daemon to inherit,
        # pinned by its own fresh transcript for up to 30 minutes. Only
        # the nudge below (which has nothing to nudge) is gated on a
        # live pid.
        sessions_dir = _sessions_dir(pidfile)
        deregister_session(sessions_dir, session_id)
        # §3's "on every decrement" reap is done by the DAEMON, not here:
        # only the daemon (spawned with its own, possibly test-overridden
        # `--transcripts-dir`) knows the transcripts_dir its two-signal
        # probe (addendum C) must consult -- this CLI process's own
        # resolution is not guaranteed to agree (and in the real,
        # single-project-per-machine case it always does, so nothing is
        # lost there). The nudge makes that reap near-immediate rather
        # than waiting up to WATCHDOG_TICK_SECONDS -- but only if a
        # daemon is actually alive to receive it.
        pid = _read_pidfile(pidfile)
        if pid is not None and _pid_is_alive(pid):
            _nudge_daemon(pidfile)
        return 0

    if args.status:
        return _status(pidfile, port, out_path, _sessions_dir(pidfile), transcripts_dir)

    if args.flush_now:
        return _signal_running(pidfile, signal.SIGUSR1, "--flush-now")

    if args.stop:
        return _signal_running(pidfile, signal.SIGTERM, "--stop")

    if args.ingest is not None:
        try:
            raw = sys.stdin.buffer.read() if args.ingest == "-" else Path(args.ingest).read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"error: malformed OTLP JSON in {args.ingest}: {e}", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"error: could not read {args.ingest}: {e}", file=sys.stderr)
            return 1
        try:
            datapoints = parse_export(payload)
        except ReceiverError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        state = ReceiverState()
        fold(datapoints, state)
        branch = _current_branch(branch_repo_root)
        hint = _issue_hint_from_datapoints(datapoints)
        issue = resolve_issue(branch, prefix, hint)
        try:
            lines = flush(state, out_path, issue, _now_iso(), roster=roster, transcripts_dir=transcripts_dir)
        except (ReceiverError, backfill_tokens.BackfillError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"flushed {len(lines)} line(s) to {out_path}")
        return 0

    if args.once:
        return run_once(port, out_path, branch_repo_root, prefix, roster, transcripts_dir)

    serve(
        port, out_path, pidfile, args.flush_interval, branch_repo_root, prefix, roster, transcripts_dir,
        sessions_dir=_sessions_dir(pidfile), grace_period_seconds=args.grace_period_seconds,
        periodic_reap_seconds=args.periodic_reap_seconds,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
