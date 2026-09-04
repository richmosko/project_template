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
        [--ensure-running] [--flush-now] [--stop]

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
        way, never an error (what the SessionStart hook calls).
    --flush-now / --stop  -- signal a running instance (SIGUSR1 / SIGTERM)
        via its pidfile.

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
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import cairn
import backfill_tokens

SOURCE_NAME = "otel"
DEFAULT_OTEL_PORT = 4318
DEFAULT_FLUSH_INTERVAL_SECONDS = 30 * 60  # ruling §7: "at most every 30 minutes"
PIDFILE_REL = Path("process") / "cairn" / "metrics" / ".receiver.pid"
LOGFILE_REL = Path("process") / "cairn" / "metrics" / "otel_receiver.log"

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


def ensure_running(repo_root: Path, pidfile: Path, port: int) -> bool:
    """Single instance enforced by pidfile + a listen probe; a second
    start is a no-op, never an error. Returns True if a (new or
    already-live) receiver is running, False if it declined to start
    (no cairn tracker at repo_root -- a spin-off/non-cairn checkout must
    never get a background process it has no use for)."""
    data_dir = repo_root / "process" / "cairn"
    if not (data_dir / "config.yml").exists():
        return False

    pid = _read_pidfile(pidfile)
    if pid is not None and _pid_is_alive(pid) and _port_is_listening(port):
        return True  # already running -- no-op

    logfile = repo_root / LOGFILE_REL
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with open(logfile, "ab") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()),
             "--out-file", str(repo_root / backfill_tokens.DEFAULT_OUT_REL),
             "--pidfile", str(pidfile), "--port", str(port)],
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
    return True  # spawned; whether it bound in time is not this call's problem


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
) -> None:
    state = ReceiverState()

    def _do_flush() -> None:
        branch = _current_branch(branch_repo_root)
        hint = _issue_hint_from_datapoints(state.series_meta.values())
        issue = resolve_issue(branch, prefix, hint)
        try:
            flush(state, out_path, issue, _now_iso(), roster=roster, transcripts_dir=transcripts_dir)
        except (ReceiverError, backfill_tokens.BackfillError) as e:
            print(f"otel_receiver: flush refused: {e}", file=sys.stderr)

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
    pidfile.write_text(str(os.getpid()), encoding="utf-8")

    def _on_sigusr1(signum, frame):
        _do_flush()

    def _on_shutdown(signum, frame):
        _do_flush()
        try:
            pidfile.unlink()
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGUSR1, _on_sigusr1)
    signal.signal(signal.SIGTERM, _on_shutdown)
    signal.signal(signal.SIGINT, _on_shutdown)
    try:
        httpd.serve_forever()
    finally:
        try:
            pidfile.unlink()
        except OSError:
            pass


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
    parser.add_argument("--flush-now", action="store_true")
    parser.add_argument("--stop", action="store_true")
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
        ensure_running(repo_root, pidfile, port)
        return 0  # never an error -- a non-cairn checkout just declines

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

    serve(port, out_path, pidfile, args.flush_interval, branch_repo_root, prefix, roster, transcripts_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
