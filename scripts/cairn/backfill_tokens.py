#!/usr/bin/env python3
"""backfill_tokens.py — PT-77: one-time backfill of per-issue token usage
from local Claude Code transcripts.

Not a `cairn` subcommand (architect's ruling on PT-77, § 3): this runs once
against a decaying local resource (`~/.claude/projects/<repo-slug>/`,
pruned by Claude Code's own retention window) and is never part of the
tracker's steady-state CLI surface. `check_dist_freshness.py` is the
standing precedent for a standalone script living beside `cairn.py`.

What it does, and — deliberately — nothing else (privacy scope ruling,
PT-77's "Scope ruling" section): scans every `*.jsonl` transcript file
under the transcript dir (recursively — nested subagent transcripts live
at `<session>/subagents/agent-*.jsonl`), reads ONLY `type`, `requestId`,
`uuid`, `timestamp`, `gitBranch`, `agentName`, `message.model`, and
`message.usage.*` from each `assistant` record — `message.content` is
never touched — and writes aggregate token COUNTS per (issue, role,
model) to `process/cairn/metrics/token-usage.jsonl`. No transcript text,
no prompts, no tool output, no session ids are recorded, and the
transcripts themselves are never copied into the repo.

PT-87 adds one more field, `agentSetting`, read once per file from a
separate header scan (`_scan_header_fields`) that -- unlike the
usage-accumulating walk above -- is NOT filtered to `type: "assistant"`:
`agentSetting` lives exclusively on `type: "agent-setting"` records
(measured against 69 real transcripts, architect's PT-87 ruling §4
amendment), so a scan confined to `assistant` records would never see
it. Still nothing beyond field names and small string values -- no
message content, no tool output.

Schema, merge semantics, and every constant below are pinned by the
architect's gating ruling on PT-77 (process/cairn/issues/PT-77.md,
"@architect — 2026-09-03") — that comment is the tie-breaker for any
"why does it do X" question this docstring doesn't answer. PT-78 (ongoing
OTel collection) writes the same schema into the same file; PT-79 (the
cost chart) reads it. PT-87 (process/cairn/issues/PT-87.md) governs role
resolution specifically -- `agentSetting` now wins over `agentName` when
present, verbatim, roster member or not.

CLI (flag names pinned by the architect's addendum, § "Flags" — qa's
fixtures bind to these exactly):
    python3 scripts/cairn/backfill_tokens.py [--transcripts-dir PATH]
        [--out-file PATH] [--dry-run]

    --transcripts-dir  override the default
                       ~/.claude/projects/<repo-root-slugified> directory.
    --out-file         override the output data file path (tests only).
    --dry-run          print the summary and top buckets to stdout; write
                       nothing.

Exit codes: 0 on success (including a clean --dry-run), 1 on a missing
transcript directory, a malformed non-final transcript line, a required
field absent from an in-scope record, or a metrics-file lock conflict.
"NEVER SILENTLY UNDER-COUNT" (PT-77 AC4): every failure listed above
aborts before anything is written — there is no partial-output path.

No network call anywhere in this script.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import cairn

# Architect's ruling § 1: new `metrics/` subdir. `cairn.py`'s `_dir_glob`
# only globs `*.md` inside `issues/` `milestones/` `majors/` `archive/`, so
# this file is invisible to every loader and to `cairn check` -- no lint
# guard needed on that account.
DEFAULT_OUT_REL = Path("process") / "cairn" / "metrics" / "token-usage.jsonl"
SOURCE_NAME = "transcript-backfill"

# Architect's ruling § 3: "one tolerated skip" -- the LAST line of a file
# may be a write-in-progress fragment (Claude Code appends live). A
# malformed line anywhere else is a hard fail.
_LOCK_STALE_SECONDS = 60

_REQUIRED_USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


class BackfillError(Exception):
    """Raised on anything this script must fail loudly for: a malformed
    non-final transcript line, a required field missing from an in-scope
    record, or a metrics-file lock/merge problem. Always caught at the
    CLI boundary in `main` -- never lets a partial result reach disk."""


# --------------------------------------------------------------------------
# Repo-relative paths
# --------------------------------------------------------------------------

def _repo_root() -> Path:
    # scripts/cairn/backfill_tokens.py -> scripts/cairn -> scripts -> root
    # (same derivation as check_dist_freshness.py's `main`).
    return Path(__file__).resolve().parent.parent.parent


def _transcript_dir_slug(repo_root: Path) -> str:
    """Architect's ruling § 3: `/`, `_`, and `.` in the absolute repo root
    each become `-`. Verified against the real dir on this machine:
    `/Users/mosko/Projects/project_template` ->
    `-Users-mosko-Projects-project-template`."""
    return re.sub(r"[/_.]", "-", str(repo_root))


def _resolve_tracker_prefix(repo_root: Path) -> str:
    """The configured issue-id prefix (`config.yml`'s `prefix:`), resolved
    from `repo_root` -- NEVER from `cairn.find_data_dir()`, which walks up
    from `Path.cwd()` (architect's blocking finding on 99725d0): run this
    script with a CWD outside the repo and `find_data_dir()` finds no
    `config.yml`. Anchoring to `repo_root` (already computed,
    CWD-independent) removes that dependence.

    `CAIRN_DATA_DIR` is honoured first (same override seam `cairn.py`
    itself uses), so a caller that legitimately points at a different data
    dir still works.

    PT-80: this used to also carry its own `config.yml`-missing check and
    raise directly, because `cairn.load_config` silently defaulted to
    `prefix: "ISS"` for a missing file instead of raising -- exactly the
    trap that fired here on the CWD bug above. `load_config` itself now
    raises `CairnError` naming the path in that case (PT-80's fix, in
    `cairn.py`), so the guard here would just be duplicating what the
    loader already does; this is now a thin, CWD-independent path
    computation plus one call into the loader.
    """
    env = os.environ.get("CAIRN_DATA_DIR")
    data_dir = Path(env).resolve() if env else (repo_root / "process" / "cairn")
    return cairn.load_config(data_dir)["prefix"]


def _roster_names(repo_root: Path) -> Set[str]:
    """Every agent stem under `.claude/agents/*.md` -- the "is this a
    roster name" check § 4's role-normalisation rule needs. Read live,
    never hard-coded: a project's roster is data, not a script constant."""
    agents_dir = repo_root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return set()
    return {p.stem for p in agents_dir.glob("*.md")}


# --------------------------------------------------------------------------
# Branch -> issue, agentName -> role (architect's ruling § 4)
# --------------------------------------------------------------------------

def _issue_regex(prefix: str) -> "re.Pattern[str]":
    """`^(?:feature|chore)/<prefix>-(\\d+)(?![\\d.])`, case-insensitive.

    Case-insensitive because real history has bare-uppercase branches
    (`feature/PT-47` .. `feature/PT-53`) with no trailing slug. The
    `(?![\\d.])` guard is load-bearing: without it, a milestone branch
    like `chore/pt-0.11-token-accounting` would partially match `pt-0` and
    fabricate a bogus `PT-0` issue bucket -- milestone branches must land
    in `main`, since PT-79 joins these keys against real issue files.
    """
    return re.compile(rf"^(?:feature|chore)/{re.escape(prefix)}-(\d+)(?![\d.])", re.IGNORECASE)


def _bucket_for_branch(branch: Optional[str], prefix: str, issue_re: "re.Pattern[str]") -> str:
    """A multi-issue branch (`feature/pt-7-8-9-13-cli-hardening`) attributes
    wholly to the FIRST id -- the transcript carries no finer signal, and
    inventing a split would be fabricating data the source doesn't have."""
    if not branch:
        return "main"
    m = issue_re.match(branch)
    if not m:
        return "main"
    return f"{prefix}-{int(m.group(1))}"


def _normalize_role(raw_agent_name: Optional[str], roster: Set[str]) -> str:
    """Absent `agentName` -> `team-lead` (the lead's own transcripts never
    carry the field). Strip a trailing `-<digits>` ONLY when what's left is
    itself a roster name (`qa-engineer-76` -> `qa-engineer`), never as a
    general numeric-suffix rule -- `impl2` has no hyphen so it is untouched,
    and `guide-pt18` doesn't end in `-<digits>` (it ends in `-pt18`, letters
    included) so it is untouched too. Anything else passes through verbatim;
    aliasing `impl`/`impl2` to a role is a guess this script refuses to make
    (architect's ruling § 4) -- see `_unmapped` below for the paper trail.
    """
    if not raw_agent_name:
        return "team-lead"
    m = re.match(r"^(.+)-\d+$", raw_agent_name)
    if m and m.group(1) in roster:
        return m.group(1)
    return raw_agent_name


# --------------------------------------------------------------------------
# PT-87: agentSetting-first role resolution -- shared by this module's own
# per-file walk and otel_receiver.py's per-session cache (imported, not
# copied, same pattern _normalize_role already established).
# --------------------------------------------------------------------------

# Architect's gating ruling on PT-87 (process/cairn/issues/PT-87.md,
# "@architect -- 2026-09-04", §1/§Q1, measured against 69 real transcripts):
# first `agentSetting` sighting is at line 1 (52 files) or line 2 (2 files)
# -- a 25x margin over this limit. The SAME window is also the `agentName`
# fallback's budget (§4 amendment, 0aa49be): "a second smaller constant buys
# nothing and adds something to reason about." One constant, shared by both
# consumers via this module, so the two can never drift apart.
_ROLE_SCAN_LIMIT = 50


def _scan_header_fields(transcript_path: Path, limit: int = _ROLE_SCAN_LIMIT) -> Tuple[Optional[str], Optional[str]]:
    """PT-87 §4, amended at 0aa49be (measured, not assumed): `agentSetting`
    lives ONLY on `type: "agent-setting"` records (541 occurrences across
    69 real transcripts, zero on `assistant`); `agentName` appears on
    `user`/`attachment`/`assistant`/`system` records but NEVER on an
    `agent-setting` record -- the two fields never share a record. A scan
    filtered to one record type would silently miss the other field
    entirely, which is exactly the bug this function exists to avoid: it
    reads EVERY record type within the first `limit` non-blank,
    JSON-parseable lines, tracking the FIRST sighting of each field
    independently, and does NOT stop as soon as one is found -- only once
    both are known (or the window ends) is there nothing left to learn.

    Both fields are measured session-constant (§Q3: `agentSetting` varies
    within a file in 0 of 69 real transcripts, `agentName` in 0 of 53) --
    resolving once per file/session from this single scan is therefore
    safe, not merely convenient; do not re-resolve per record.

    Returns `(agent_setting, agent_name)`, either or both possibly `None`.
    Reads exactly two fields -- no message content, no prompts, no tool
    output ever reach the return value. Raises nothing on a malformed
    line (skipped); an unreadable path is the caller's problem (`OSError`
    propagates, matching this module's fail-loud-on-real-errors stance --
    the receiver's own caller separately treats a MISSING file as
    `subagent-unattributed`, unrelated to a read failure on an existing
    one).
    """
    agent_setting: Optional[str] = None
    agent_name: Optional[str] = None
    with open(transcript_path, "r", encoding="utf-8") as f:
        for i, raw in enumerate(f):
            if i >= limit:
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if agent_setting is None:
                candidate = record.get("agentSetting")
                if candidate:
                    agent_setting = candidate
            if agent_name is None:
                candidate = record.get("agentName")
                if candidate:
                    agent_name = candidate
            if agent_setting is not None and agent_name is not None:
                break  # both known -- nothing left to learn from more lines
    return agent_setting, agent_name


def resolve_role_from_header(agent_setting: Optional[str], agent_name: Optional[str], roster: Set[str]) -> str:
    """PT-87 §2 (architect's gating ruling, the one deviation from the
    issue's original wording): `agentSetting` wins whenever present and
    non-empty, taken VERBATIM -- no roster gate, no `-<digits>` strip (it
    is a type name by construction, `subagent_type`, never a spawn nickname
    that would carry a disambiguating suffix). A roster-gated rule would
    discard a correct, harness-supplied type (e.g. `claude-code-guide`, a
    built-in with no roster file) in favour of a wrong spawn-name guess --
    PT-77 §4's no-alias-guessing rule forbids INVENTING a mapping, not
    reading the harness's own type field. A non-roster `agentSetting`
    still wins here; the caller is responsible for the unmapped paper
    trail (this function doesn't have the stats dict).

    Falls back to the existing, unchanged `_normalize_role(agent_name,
    roster)` when `agentSetting` is absent or empty -- which itself
    resolves an absent `agentName` to `team-lead`, so this function's own
    "neither field present" case needs no separate branch.
    """
    if agent_setting:
        return agent_setting
    return _normalize_role(agent_name, roster)


# --------------------------------------------------------------------------
# Transcript scanning
# --------------------------------------------------------------------------

def _new_bucket() -> Dict[str, int]:
    return {
        "input": 0,
        "cache_write": 0,
        "cache_read": 0,
        "output": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "records": 0,
    }


def _new_stats() -> Dict[str, Any]:
    return {
        "candidates": 0,
        "duplicates": 0,
        "unique": 0,
        "unmapped_roles": {},  # type: Dict[str, int]
        "window_start": None,  # type: Optional[str]
        "window_end": None,  # type: Optional[str]
    }


def _process_record(
    record: Dict[str, Any],
    location: str,
    prefix: str,
    issue_re: "re.Pattern[str]",
    roster: Set[str],
    buckets: Dict[Tuple[str, str, str], Dict[str, int]],
    seen_keys: Set[str],
    stats: Dict[str, Any],
    role: str,
    role_source_present: bool,
    milestone_windows_table: List[Tuple[str, str]],
) -> None:
    """`location` is `"<path>:<lineno>"`, used only in error messages --
    never anything read from record content.

    `role`/`role_source_present` (PT-87) are resolved ONCE per file by the
    caller (`_process_file`, via `_scan_header_fields` + `resolve_role_
    from_header`) -- not read from THIS record. Measured session-constant
    (architect's ruling §Q3): re-resolving per record would be both
    redundant (every record in a file already shares one answer) and
    wrong for `agentSetting`, which never appears on an `assistant`
    record at all (§4 amendment)."""
    if record.get("type") != "assistant":
        return
    message = record.get("message")
    if not isinstance(message, dict) or "usage" not in message:
        # Filter, not a failure: an assistant-type record that carries no
        # usage block is simply out of scope (architect's ruling § 3's
        # record filter is "type == assistant carrying message.usage").
        return
    model = message.get("model")
    if model == "<synthetic>":
        # Explicit filter (ruling § 3): all-zero usage, no requestId, no
        # API call behind it -- not a real cost, not an error.
        return

    # Past this point the record is a real, in-scope candidate: every
    # field below is required, and its absence is news, not noise
    # (ruling § 3: "all four are present on all 30,281 records today").
    branch = record.get("gitBranch")
    if not branch:
        raise BackfillError(f"{location}: missing gitBranch on an in-scope assistant record")
    if not model:
        raise BackfillError(f"{location}: missing message.model on an in-scope assistant record")
    usage = message["usage"]
    for field in _REQUIRED_USAGE_FIELDS:
        if field not in usage:
            raise BackfillError(f"{location}: missing message.usage.{field} on an in-scope assistant record")
    timestamp = record.get("timestamp")
    if not timestamp:
        raise BackfillError(f"{location}: missing timestamp on an in-scope assistant record")
    dedupe_key = record.get("requestId") or record.get("uuid")
    if not dedupe_key:
        raise BackfillError(f"{location}: missing both requestId and uuid -- cannot dedupe safely")

    stats["candidates"] += 1
    if dedupe_key in seen_keys:
        stats["duplicates"] += 1
        return
    seen_keys.add(dedupe_key)
    stats["unique"] += 1

    issue = _bucket_for_branch(branch, prefix, issue_re)
    if issue == "main":
        # PT-84: main-branch work belongs to whichever milestone was
        # active at THIS record's own timestamp, per-record (not
        # per-file/session like PT-87's role) -- a session can genuinely
        # cross a milestone boundary (or an issue<->main branch switch)
        # mid-transcript, so each record's own timestamp is the correct
        # granularity, matching how `_bucket_for_branch` itself already
        # reads THIS record's own branch, not a file-wide one.
        milestone_id = cairn.milestone_for_timestamp(str(timestamp), milestone_windows_table)
        if milestone_id:
            issue = f"milestone:{milestone_id}"
    if role_source_present and role not in roster:
        # PT-87: broadened from the old "raw_agent_name and ..." check --
        # a non-roster `agentSetting` (e.g. a future built-in type with no
        # roster file yet) belongs on the same unmapped paper trail a
        # non-roster `agentName` always has, per the architect's ruling
        # §2 ("keep the unmapped paper trail when it isn't a roster
        # name"). Still per-record (not per-file) so the count reflects
        # data VOLUME, matching every other stat in this dict.
        stats["unmapped_roles"][role] = stats["unmapped_roles"].get(role, 0) + 1

    acc = buckets.setdefault((issue, role, model), _new_bucket())
    acc["input"] += usage["input_tokens"]
    acc["cache_write"] += usage["cache_creation_input_tokens"]
    acc["cache_read"] += usage["cache_read_input_tokens"]
    acc["output"] += usage["output_tokens"]
    cache_creation = usage.get("cache_creation") or {}
    acc["cache_write_5m"] += cache_creation.get("ephemeral_5m_input_tokens", 0) or 0
    acc["cache_write_1h"] += cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
    acc["records"] += 1

    date = str(timestamp)[:10]
    if stats["window_start"] is None or date < stats["window_start"]:
        stats["window_start"] = date
    if stats["window_end"] is None or date > stats["window_end"]:
        stats["window_end"] = date


def _process_file(
    path: Path,
    prefix: str,
    issue_re: "re.Pattern[str]",
    roster: Set[str],
    buckets: Dict[Tuple[str, str, str], Dict[str, int]],
    seen_keys: Set[str],
    stats: Dict[str, Any],
    milestone_windows_table: List[Tuple[str, str]],
) -> None:
    # PT-87: role resolves ONCE per file, from a header scan across every
    # record type (§4 amendment, 0aa49be) -- separate from, and BEFORE,
    # the per-record walk below, which stays filtered to `type ==
    # "assistant"` for usage accumulation (two different questions, two
    # different filters; widening the usage filter would change what
    # gets COUNTED, which is not this ticket).
    agent_setting, agent_name = _scan_header_fields(path)
    role = resolve_role_from_header(agent_setting, agent_name, roster)
    role_source_present = bool(agent_setting or agent_name)

    raw = path.read_bytes()
    raw_lines = raw.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines = raw_lines[:-1]
    total = len(raw_lines)
    for idx, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip():
            continue
        is_last = idx == total
        try:
            decoded = raw_line.decode("utf-8")
            record = json.loads(decoded)
            if not isinstance(record, dict):
                raise ValueError("line is not a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
            if is_last:
                # Ruling § 3: Claude Code appends live, so a truncated
                # final line is expected, not an error -- warn and move on.
                print(f"warning: {path}:{idx}: skipping malformed final line ({e})", file=sys.stderr)
                continue
            raise BackfillError(f"{path}:{idx}: malformed line: {e}")
        _process_record(record, f"{path}:{idx}", prefix, issue_re, roster, buckets, seen_keys, stats, role, role_source_present, milestone_windows_table)


def scan_transcripts(
    transcript_dir: Path, prefix: str, roster: Set[str], repo_root: Optional[Path] = None
) -> Tuple[Dict[Tuple[str, str, str], Dict[str, int]], Dict[str, Any], List[Path], List[Tuple[str, str]]]:
    """Recursively scans `transcript_dir` for `*.jsonl` files (nested
    subagent transcripts live at `<session>/subagents/agent-*.jsonl`; no
    exclude list needed -- `memory/` and `<session>/tool-results/` hold no
    `.jsonl`, per the architect's ruling § 3). Returns
    `(buckets, stats, files_scanned, milestone_windows_table)`; raises
    `BackfillError` on the first fail-loud condition, before any bucket
    accumulates a partial count from that record.

    PT-84: `cairn.milestone_windows(repo_root)` is computed ONCE here, before
    the file loop -- one `git log` per milestone (14 today), not one per
    record or even per file -- and returned to the caller so `_build_
    lines`/`merge_and_write` can order "milestone:<id>" lines by the
    SAME table without a second round of git calls. `repo_root` defaults
    to this script's own on-disk location (`_repo_root()`) when omitted,
    matching every other repo-root-anchored default in this module; a
    test passes its own fake root to point the milestone lookup at a
    throwaway tracker.
    """
    issue_re = _issue_regex(prefix)
    buckets: Dict[Tuple[str, str, str], Dict[str, int]] = {}
    seen_keys: Set[str] = set()
    stats = _new_stats()
    milestone_windows_table = cairn.milestone_windows(repo_root if repo_root is not None else _repo_root())
    files = sorted(transcript_dir.rglob("*.jsonl"))
    for path in files:
        _process_file(path, prefix, issue_re, roster, buckets, seen_keys, stats, milestone_windows_table)
    return buckets, stats, files, milestone_windows_table


# --------------------------------------------------------------------------
# Output: schema, ordering, merge (architect's ruling §§ 1-2)
# --------------------------------------------------------------------------

def _build_lines(
    buckets: Dict[Tuple[str, str, str], Dict[str, int]],
    generated: str,
    window_start: str,
    window_end: str,
    milestone_windows_table: Optional[List[Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    lines = []
    for (issue, role, model), acc in buckets.items():
        lines.append({
            "source": SOURCE_NAME,
            "generated": generated,
            "window_start": window_start,
            "window_end": window_end,
            "issue": issue,
            "role": role,
            "model": model,
            "input": acc["input"],
            "cache_write": acc["cache_write"],
            "cache_read": acc["cache_read"],
            "output": acc["output"],
            "cache_write_5m": acc["cache_write_5m"],
            "cache_write_1h": acc["cache_write_1h"],
            "records": acc["records"],
        })
    rank_map = milestone_rank_map(milestone_windows_table)
    lines.sort(key=lambda line: _sort_key(line, rank_map))
    return lines


def milestone_rank_map(milestone_windows_table: Optional[List[Tuple[str, str]]]) -> Dict[str, int]:
    """`milestone_windows_table` is already sorted ascending by creation
    timestamp (`milestone_windows`'s own contract) -- so a milestone
    id's RANK is just its position in that list. Computed ONCE per sort
    call (by `_build_lines`/`merge_and_write`/the receiver's own
    `_append_lines`) and passed into `_sort_key` per line, rather than
    rebuilt on every one of the O(n) `_sort_key` calls a single `.sort()`
    already makes. `None`/empty (a caller with no table -- e.g. a test
    exercising `_sort_key` in isolation) yields an empty map; every
    "milestone:<id>" then falls back to rank 0, degrading to insertion
    order rather than raising -- still deterministic, just not
    creation-time-ordered without the table."""
    if not milestone_windows_table:
        return {}
    return {milestone_id: i for i, (_start, milestone_id) in enumerate(milestone_windows_table)}


def _sort_key(
    line: Dict[str, Any], milestone_rank_map: Optional[Dict[str, int]] = None
) -> Tuple[Tuple[int, int], str, str, str]:
    """Ruling § 1 (PT-77): "issues by numeric id ascending, `main` last,
    then role, then model, then source" -- deterministic so re-runs diff
    clean. Prefix-agnostic (matches any `<PREFIX>-<n>` shape) so this
    also sorts correctly when merged against PT-78's otel-sourced lines
    later.

    PT-84 §6: a THIRD tier, `issue: "milestone:<id>"`, ranks between
    issues and `main` -- ordered by the milestone's own CREATION
    timestamp, via `milestone_rank_map` (see that function -- already a
    plain rank lookup, no timestamp comparison needed here), never by
    string-comparing the id (`PT-0.10` sorts before `PT-0.5`
    lexicographically, which is exactly the wrong order)."""
    issue = line["issue"]
    if issue.startswith("milestone:"):
        milestone_id = issue[len("milestone:"):]
        rank = (1, (milestone_rank_map or {}).get(milestone_id, 0))
    else:
        m = re.match(r"^[A-Za-z]+-(\d+)$", issue)
        if issue == "main" or not m:
            rank = (2, 0)
        else:
            rank = (0, int(m.group(1)))
    return (rank, line["role"], line["model"], line["source"])


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _acquire_lock(lock_path: Path) -> None:
    """`O_CREAT|O_EXCL`, treated as stale after `_LOCK_STALE_SECONDS`
    (ruling § 2). One stale-clear retry, then give up loudly -- this
    script never silently proceeds without the lock."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue  # lock vanished between the open() and stat() -- retry
            if age > _LOCK_STALE_SECONDS:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise BackfillError(
                f"{lock_path}: another writer holds the metrics lock (age {age:.0f}s) -- try again shortly"
            )
    raise BackfillError(f"{lock_path}: could not acquire the metrics lock")


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


_SORT_KEY_REQUIRED_KEYS = ("source", "issue", "role", "model")


def _read_existing_lines(out_path: Path) -> List[Dict[str, Any]]:
    """Parses every existing line and validates the keys `_sort_key`
    (below) reads. Architect's review, minor 2: without this, a malformed
    FOREIGN line (e.g. a future `otel` line missing `role`) reached
    `_sort_key` unchecked and raised a bare `KeyError` -- correct exit
    code, lock released, atomic write never ran so nothing was corrupted,
    but a traceback instead of a named, actionable error. Same
    fail-loudly-with-a-location contract as every other malformed-input
    path in this script, extended to data this script did not itself
    write.
    """
    if not out_path.exists():
        return []
    lines = []
    text = out_path.read_text(encoding="utf-8")
    for idx, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BackfillError(f"{out_path}:{idx}: malformed existing data line: {e}")
        if not isinstance(record, dict):
            raise BackfillError(f"{out_path}:{idx}: existing data line is not a JSON object")
        missing = [k for k in _SORT_KEY_REQUIRED_KEYS if k not in record]
        if missing:
            raise BackfillError(f"{out_path}:{idx}: existing data line missing required key(s) {missing}")
        lines.append(record)
    return lines


def merge_and_write(
    out_path: Path, new_lines: List[Dict[str, Any]], source: str = SOURCE_NAME,
    milestone_windows_table: Optional[List[Tuple[str, str]]] = None,
) -> None:
    """Ruling § 2: a regenerating source (this script always is one) reads
    every existing line, drops every line whose `source` matches its own,
    appends its fresh lines, and writes the result via temp + `os.replace`
    under an exclusive lock -- re-running is idempotent, and lines from a
    different source (e.g. PT-78's `otel`) survive byte-for-byte.

    `milestone_windows_table` (PT-84) orders "milestone:<id>" lines by
    creation timestamp in the final combined write, covering BOTH the
    fresh lines this call is writing and any surviving lines from the
    other source -- a single, consistent sort of the whole file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_path.parent / ".lock"
    _acquire_lock(lock_path)
    try:
        existing = _read_existing_lines(out_path)
        kept = [l for l in existing if l.get("source") != source]
        combined = kept + new_lines
        rank_map = milestone_rank_map(milestone_windows_table)
        combined.sort(key=lambda line: _sort_key(line, rank_map))
        text = "".join(json.dumps(line) + "\n" for line in combined)
        _atomic_write_text(out_path, text)
    finally:
        _release_lock(lock_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        description=(
            "PT-77 one-time backfill: scrape existing Claude Code transcripts for "
            "per-issue/role/model token usage, nothing else. Read-only against "
            "transcripts; writes process/cairn/metrics/token-usage.jsonl."
        )
    )
    parser.add_argument(
        "--transcripts-dir", type=Path, default=None,
        help="override the default ~/.claude/projects/<repo-slug> transcript directory",
    )
    parser.add_argument(
        "--out-file", type=Path, default=None,
        help="override the output data file path (tests only)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the summary and top buckets to stdout; write nothing",
    )
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    transcript_dir = args.transcripts_dir or (Path.home() / ".claude" / "projects" / _transcript_dir_slug(repo_root))
    out_path = args.out_file or (repo_root / DEFAULT_OUT_REL)

    if not transcript_dir.is_dir():
        # TRACKER's standing rule, restated for this script (ruling § 3):
        # "no transcripts here" and "no data here" must not render
        # identically -- a missing dir is always an error, never silently
        # an empty result.
        print(f"error: transcript directory not found: {transcript_dir}", file=sys.stderr)
        print("pass --transcripts-dir to point at the right one", file=sys.stderr)
        return 1

    try:
        prefix = _resolve_tracker_prefix(repo_root)
    except cairn.CairnError as e:
        print(f"error: could not read the tracker prefix from config.yml: {e}", file=sys.stderr)
        return 1

    roster = _roster_names(repo_root)

    try:
        buckets, stats, files, milestone_windows_table = scan_transcripts(transcript_dir, prefix, roster, repo_root)
    except BackfillError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if stats["unmapped_roles"]:
        # PT-87: the value here can now come from either header field --
        # a non-roster agentSetting (kept verbatim, e.g. a built-in type
        # with no roster file yet) or the pre-existing agentName fallback
        # -- so the note no longer names just one of them.
        print("note: agentSetting/agentName values with no roster match, kept verbatim (no alias guessing):", file=sys.stderr)
        for name, count in sorted(stats["unmapped_roles"].items()):
            print(f"  {name}: {count}", file=sys.stderr)

    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_start = stats["window_start"] or generated[:10]
    window_end = stats["window_end"] or generated[:10]
    new_lines = _build_lines(buckets, generated, window_start, window_end, milestone_windows_table)

    print(f"scanned {len(files)} transcript file(s) under {transcript_dir}")
    print(
        f"in-scope assistant/usage records: {stats['candidates']} "
        f"({stats['unique']} unique, {stats['duplicates']} duplicate)"
    )
    print(f"window: {window_start} .. {window_end}")
    print(f"buckets: {len(new_lines)}")

    if args.dry_run:
        print("--dry-run: nothing written. Top buckets by output tokens:")
        for line in sorted(new_lines, key=lambda l: -l["output"])[:10]:
            print(f"  {line['issue']:<10} {line['role']:<20} {line['model']:<26} output={line['output']}")
        return 0

    try:
        merge_and_write(out_path, new_lines, milestone_windows_table=milestone_windows_table)
    except BackfillError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
