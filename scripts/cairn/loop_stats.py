"""Per-loop scorecard and step-by-step transcript audit (PT-94 E16).

`cairn loop-stats <ID>` prints the scorecard for the loop on the current
feature branch: commits, chore commits, issue-file comments and ruling
sections, KB added to the issue file, tests added, full-suite runs and
messages to the lead (from the transcript dir, inside the loop's window),
and $ from the tokens payload -- each against a soft cap. `--steps DIR`
writes the per-agent step tables the PT-94 audit was made from: every
tool call in order, classified, with waste flags.

Transcripts are the harness's own `~/.claude/projects/<repo-slug>/*.jsonl`
(same slug derivation as backfill_tokens); they decay, so the tables are
the durable record, not the transcripts.
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# PT-97 gate-4 delta 8: narrowing detection is shared with the two Bash
# hooks (.claude/hooks/_test_run_shared.py) rather than reimplemented here
# -- the substring bug delta 1 fixed there (`time -p` false-matching,
# `--pattern` never matching) was still live in this module's own
# classify_bash until this fix.
_HOOKS_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "hooks"
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))
from _test_run_shared import (  # noqa: E402
    _strip_heredocs, find_runner_invocation, is_full_suite_run, tokenize,
)

CODE_EXT = (".py", ".js", ".mjs", ".ts", ".svelte", ".css", ".html", ".sh", ".yml", ".yaml", ".toml")

DEFAULT_CAPS: Dict[str, int] = {"msgs_to_lead": 40, "ruling_sections": 3, "commits": 15, "full_suite_runs": 4}

# A full-suite run: `unittest discover` with no -p/-k narrowing. A run
# narrowed to one module, or `python -m unittest <module>`, is a module run.
_FULL_RE = re.compile(r"unittest\s+discover")
_CONFIRM_RE = re.compile(
    r"(please confirm|confirm before|before (I|you) (proceed|build|touch|write|start|lock)|should I|shall I|"
    r"your call|want me to|which (do you|would you)|ok to (proceed|build)|go ahead\?|awaiting your|"
    r"need (your|a) (decision|ruling|confirmation|answer))", re.I)
_STANDBY_RE = re.compile(r"(dropping (it )?silently|no reply needed|already (claimed|known)|standing by|"
                         r"waiting (for|on) (the )?(architect|suite|ruling|verdict|lead|merge|teardown)|nothing to do)", re.I)
_ECHO_RE = re.compile(r"^(claimed|task (claimed|updated|marked)|marked .* (done|complete)|noted\.?$)", re.I)

# PT-108: shutdown/plan-approval protocol messages carry a JSON object, not
# prose -- they must not reach the prose-shaped accounting below.
_PROTOCOL_MESSAGE_TYPES = {
    "shutdown_request", "shutdown_response",
    "plan_approval_request", "plan_approval_response",
}


def _message_body(inp: Dict[str, Any]) -> Optional[str]:
    """A SendMessage `message` input, normalised for the prose-shaped
    accounting below. `str` is returned unchanged. A protocol dict (a
    shutdown/plan-approval handshake) returns None -- it is a machine
    handshake, not a message to count. Any other non-string is coerced via
    `json.dumps`: fail toward counting, a real message must never be
    silently dropped."""
    body = inp.get("message", "") or ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict) and body.get("type") in _PROTOCOL_MESSAGE_TYPES:
        return None
    return json.dumps(body, sort_keys=True)
_NARRATE_RE = re.compile(r"^(now|next|let'?s|let me|running|i'?ll|checking|good[,. ]|ok[,. ])", re.I)
_CROSS_RE = re.compile(r"cross(ed|ing)", re.I)
_RULING_RE = re.compile(r"\b(ruling|addendum|correction|verdict)\b", re.I)
_COMMENT_HEADER_RE = re.compile(r"^### @(\S+) — (\S+)")


def parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def records(path: Path, since: datetime.datetime, until: datetime.datetime) -> Iterable[Tuple[datetime.datetime, Dict[str, Any]]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            ts = r.get("timestamp")
            if not ts:
                continue
            try:
                t = parse_ts(ts)
            except Exception:
                continue
            if since <= t <= until:
                yield t, r


def full_run_stats(path: Path, since: datetime.datetime, until: datetime.datetime) -> Dict[str, Any]:
    """PT-97 guard 9: `full_suite_runs`/`suite_seconds_added` derived from
    `process/cairn/metrics/test-runs.jsonl` (PostToolUse-recorded, `ts`
    field -- distinct schema from `records()`'s transcript `timestamp`
    field, so it is read directly rather than through that helper). A
    missing file or a window with no `full: true` records is 0/None, never
    a crash. `full_suite_runs` is the total record count in window,
    independent of configuration.

    `suite_seconds_added` is the last full record's `seconds` minus the
    first's, chronologically, **within the largest `jobs` group only**
    (gate-4 verdict delta 4, PT-97.md @ d896d8d): mixing configurations
    reported a `--serial` run (106.5s) minus a parallel run (19.9s) of
    IDENTICAL code as a 86.6s "regression" -- a config difference, not a
    measurement. Undefined (None) if the winning group has under two
    records. Rounded to 3 places (the same defect produced
    86.55799999999999 unrounded)."""
    full: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
    path = Path(path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("ts")
                if not ts:
                    continue
                try:
                    t = parse_ts(ts)
                except Exception:
                    continue
                if since <= t <= until and rec.get("full"):
                    full.append((t, rec))
    full.sort(key=lambda pair: pair[0])

    seconds_added = None
    if len(full) >= 2:
        groups: Dict[Any, List[Tuple[datetime.datetime, Dict[str, Any]]]] = {}
        for t, rec in full:
            groups.setdefault(rec.get("jobs"), []).append((t, rec))
        # Largest group wins; ties broken toward more workers (an
        # arbitrary but deterministic tiebreak -- no test exercises a tie).
        best_jobs = max(groups, key=lambda j: (len(groups[j]), j if isinstance(j, int) else -1))
        group = groups[best_jobs]
        if len(group) >= 2:
            first_seconds = group[0][1].get("seconds")
            last_seconds = group[-1][1].get("seconds")
            if isinstance(first_seconds, (int, float)) and isinstance(last_seconds, (int, float)):
                seconds_added = round(last_seconds - first_seconds, 3)
    return {"full_suite_runs": len(full), "suite_seconds_added": seconds_added}


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _role_of_file(p: Path) -> str:
    """Role from one transcript's header: `agentSetting` (the harness's
    own subagent_type) wins; a role-shaped `agentName` is the fallback; a
    transcript with neither is the main session -> team-lead."""
    role = "team-lead"
    try:
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("agentSetting"):
                    role = r["agentSetting"]
                    break
                # agentName is a spawn nickname or, on the main session, a
                # /rename title -- accept it only when it is shaped like a role.
                name = r.get("agentName")
                if name and re.fullmatch(r"[a-z][a-z0-9-]*", name):
                    role = re.sub(r"-\d+$", "", name)
                    break
    except OSError:
        pass
    return role


def transcript_roles(transcripts_dir: Path) -> Dict[Path, str]:
    """Role per transcript in a directory -- see `_role_of_file`."""
    out: Dict[Path, str] = {}
    for p in sorted(Path(transcripts_dir).glob("*.jsonl")):
        out[p] = _role_of_file(p)
    return out


# ---------------------------------------------------------------- classify

def classify_bash(c: str) -> str:
    c1 = _strip_heredocs(c.strip())
    if "unittest" in c1 or "run_tests" in c1:
        # PT-97 gate-4 delta 8: narrowing is flag-aware (shared with the
        # hooks), not a substring scan -- the substring form false-matched
        # `time`'s own `-p` in `/usr/bin/time -p ...` and never matched
        # `--pattern` (run_tests.py's own long form of `-p`) at all.
        invocation = find_runner_invocation(tokenize(c1))
        if invocation is not None:
            runner, _args_start = invocation
            # PT-93 (AC2): `run_tests.py` is a full-suite shape on its
            # own, unlike a bare `unittest <module>` -- only `unittest
            # discover` (_FULL_RE) counts there.
            full_shape = runner == "run_tests" or bool(_FULL_RE.search(c1))
            if full_shape and is_full_suite_run(c1):
                return "FULL_SUITE"
        return "module_test"
    if "node --test" in c1 or "npm test" in c1:
        return "js_suite"
    if re.search(r"\bcairn\s+check\b", c1):
        return "cairn_check"
    if re.search(r"\bcairn\s+(comment|set|new)\b", c1):
        return "cairn_write"
    if re.search(r"\bcairn\s+(show|ls)\b", c1):
        return "cairn_read"
    if re.search(r"\bgit\s+commit\b", c1):
        return "git_commit"
    if re.search(r"\bgit\s+(push|checkout|switch|merge|rebase|stash|reset|add)\b", c1):
        return "git_write"
    if re.search(r"\bgit\s+(log|show|diff|status|rev-parse|branch|blame|cat-file|ls-files)\b", c1):
        return "git_read"
    if re.search(r"\bgh\s+pr\b", c1):
        return "gh"
    if re.search(r"^(cat|sed -n|head|tail|grep|rg|ls|wc|find|diff)\b", c1) or re.search(r"\|\s*(head|tail|grep|wc)\b", c1):
        return "bash_read"
    if re.search(r"\b(curl|wget)\b", c1):
        return "http"
    return "bash_other"


def classify(name: str, inp: Dict[str, Any]) -> str:
    if name == "Bash":
        return classify_bash(inp.get("command", "") or "")
    if name == "Read":
        return "read"
    if name in ("Grep", "Glob"):
        return "search"
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit"
    if name == "SendMessage":
        return "message"
    if name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return "task_tool"
    if name.startswith("mcp__claude-in-chrome"):
        return "browser"
    return "other:" + name


def classify_text_turn(txt: str) -> str:
    t = txt.strip()
    if _STANDBY_RE.search(t) and len(t) < 600:
        return "idle:drop/standby"
    if _ECHO_RE.search(t):
        return "idle:task_echo"
    if _NARRATE_RE.search(t) and len(t) < 300:
        return "narration"
    return "report_text"


def _is_test_path(fp: str) -> bool:
    return os.path.basename(fp).startswith("test_") or "/tests/" in fp or fp.endswith(".test.js")


# ------------------------------------------------- blocked-run resolution (PT-111)

# The guard's own first sentence (`.claude/hooks/test_run_guard.py`) -- also
# present in that file's docstring, so this marker is only trusted when
# paired with an id-linked `toolDenialKind`, never on a free-text scan (a
# `Read` of the hook's own source must not count as a denial).
_DENIAL_MARKER = "test_run_guard: refusing an un-tiered full-suite run"
_RAN_TESTS_RE = re.compile(r"\bRan \d+ tests\b")
# start = ledger record's `ts` (end of run) minus its `seconds`; a step's own
# timestamp is the run's start. Measured residual for true pairs: p50 1.5s,
# p90 5.8s (PT-111.md @ ec75732) -- generous asymmetric window either side.
_LEDGER_WINDOW_SECONDS = (-120, 300)


def _load_ledger(path: Optional[Path]) -> List[Dict[str, Any]]:
    """`full: true` records from a test-runs.jsonl, each carrying a parsed
    `_ts` (`rec["ts"]`, the run's END). Missing file or path -> []."""
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("full"):
                continue
            ts_raw = rec.get("ts")
            if not ts_raw:
                continue
            try:
                t = parse_ts(ts_raw)
            except Exception:
                continue
            rec = dict(rec)
            rec["_ts"] = t
            out.append(rec)
    return out


def _match_ledger(step_time: datetime.datetime, who: Optional[str], ledger: List[Dict[str, Any]]) -> bool:
    """One-to-one: the first ledger record whose computed start
    (`_ts - seconds`) falls within `_LEDGER_WINDOW_SECONDS` of `step_time`,
    and whose `who` either matches or is null (49 of 166 real records are
    null -- main-session and unpatched runs), is consumed and reported as a
    match. Consumed records are removed so a second step can't reuse one."""
    for i, rec in enumerate(ledger):
        seconds = rec.get("seconds")
        if not isinstance(seconds, (int, float)):
            continue
        predicted_start = rec["_ts"] - datetime.timedelta(seconds=seconds)
        diff = (predicted_start - step_time).total_seconds()
        if not (_LEDGER_WINDOW_SECONDS[0] <= diff <= _LEDGER_WINDOW_SECONDS[1]):
            continue
        rec_who = rec.get("who")
        if rec_who is not None and rec_who != who:
            continue
        del ledger[i]
        return True
    return False


def _result_map(recs: List[Tuple[datetime.datetime, Dict[str, Any]]]) -> Dict[str, Tuple[bool, str, Optional[str]]]:
    """`tool_use_id -> (is_error, result text, toolDenialKind)`, built from
    every id-linked `tool_result` block in the record stream. `content` is
    read through `text_of` (str or block-list, same as a text turn) so
    either shape resolves."""
    out: Dict[str, Tuple[bool, str, Optional[str]]] = {}
    for _t, r in recs:
        if r.get("type") != "user":
            continue
        m = r.get("message", {}) or {}
        content = m.get("content")
        if not isinstance(content, list):
            continue
        denial_kind = r.get("toolDenialKind")
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tid = b.get("tool_use_id")
                if not tid:
                    continue
                out[tid] = (bool(b.get("is_error")), text_of(b.get("content")), denial_kind)
    return out


def _resolve_full_suite(tool_id: Optional[str], step_time: datetime.datetime, who: Optional[str],
                         result_map: Dict[str, Tuple[bool, str, Optional[str]]], ledger: List[Dict[str, Any]]) -> str:
    """PT-111 gate-4 verdict delta 1 (PT-111.md @57e6b6a, blocking):
    result evidence beats the ledger -- the gate-1 ruling had the ledger
    checked first, which on real data let a nearby unrelated (often
    null-`who`) record promote 3 of 5 true guard denials to executed. A
    denied step never ran, so any record matching it is by definition a
    mispairing; the ledger's job is to resolve the silent case only, never
    to overrule direct evidence. Resolve a FULL_SUITE-shaped Bash step to
    `FULL_SUITE` (executed) or `full_run_blocked`, in precedence order --
    (1) a `Ran N tests` result -> executed, exit status is not the
    discriminator; (2) an id-linked error result carrying `toolDenialKind`
    + the guard's own marker -> blocked; (3) any other error result ->
    blocked, unconditionally, a nearby ledger record never overrides it;
    (4) no result, or a result with neither a summary nor an error
    (redirected stdout) -> the ledger corroborates this silent case only
    (consumed for bookkeeping; harmless either way) -> executed regardless
    (absence of evidence is not evidence of refusal)."""
    result = result_map.get(tool_id) if tool_id else None
    if result is not None:
        is_error, text, denial_kind = result
        if _RAN_TESTS_RE.search(text):
            return "FULL_SUITE"
        if is_error and denial_kind and _DENIAL_MARKER in text:
            return "full_run_blocked"
        if is_error:
            return "full_run_blocked"
    _match_ledger(step_time, who, ledger)
    return "FULL_SUITE"


# ---------------------------------------------------------------- per-agent audit

def audit_agent(path: Path, since: datetime.datetime, until: datetime.datetime, lead: bool = False,
                 ledger_path: Optional[Path] = None):
    """Every step of one transcript in the window, in order, with a class
    and waste flags. Returns (steps, summary). A step is
    (time, kind, class, detail, flags) with kind in inbound|text|tool.
    `lead=True`: the main session's text turns face the user, not a
    mailbox, so they are never idle waste. `ledger_path`: optional
    `process/cairn/metrics/test-runs.jsonl` used to corroborate a
    FULL_SUITE-shaped step as actually executed (PT-111)."""
    steps: List[Tuple[datetime.datetime, str, str, str, str]] = []
    turn = 0
    reads_this_turn: collections.Counter = collections.Counter()
    reads_total: collections.Counter = collections.Counter()
    edited_since_full: List[str] = []
    last_full: Optional[datetime.datetime] = None
    last_edit_path: Optional[str] = None
    last_git_read: Optional[datetime.datetime] = None
    msgs: List[Tuple[datetime.datetime, str, int]] = []
    text_turns: collections.Counter = collections.Counter()
    waste: collections.Counter = collections.Counter()

    def add(t, kind, cls, detail, flags):
        steps.append((t, kind, cls, detail, " ".join(flags)))
        for f in flags:
            head = f.split("(")[0]
            if head[:1].isupper():
                waste[head] += 1

    recs = list(records(path, since, until))
    result_map = _result_map(recs)
    ledger = _load_ledger(ledger_path)
    who = _role_of_file(path) if ledger else None

    for t, r in recs:
        typ = r.get("type")
        m = r.get("message", {}) or {}
        if typ == "user":
            c = m.get("content")
            is_tool_result = isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tool_result:
                turn += 1
                reads_this_turn = collections.Counter()
                inbound = text_of(c)
                tag = re.search(r'teammate_id="([^"]+)"', inbound)
                add(t, "inbound", "from:" + (tag.group(1) if tag else "user/system"), inbound[:110].replace("\n", " "), [])
            continue
        if typ != "assistant":
            continue
        content = m.get("content", [])
        if not isinstance(content, list):
            continue
        tus = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        txt = text_of(content)
        if not tus and txt.strip():
            k = "report_text" if lead else classify_text_turn(txt)
            text_turns[k] += 1
            flags = ["IDLE_STANDBY"] if k == "idle:drop/standby" else (["TASK_ECHO"] if k == "idle:task_echo" else [])
            add(t, "text", k, txt[:110].replace("\n", " "), flags)
            continue
        for b in tus:
            inp = b.get("input", {}) or {}
            cls = classify(b["name"], inp)
            flags: List[str] = []
            detail = ""
            if cls == "read":
                fp = inp.get("file_path", "") or ""
                detail = fp
                reads_this_turn[fp] += 1
                reads_total[fp] += 1
                if reads_this_turn[fp] > 1:
                    flags.append("REREAD_SAME_TURN")
                if fp == last_edit_path:
                    flags.append("reread_after_own_edit")
            elif cls == "edit":
                fp = inp.get("file_path", "") or ""
                detail = fp
                last_edit_path = fp
                edited_since_full.append(fp)
            elif cls in ("FULL_SUITE", "module_test", "js_suite"):
                cmd = inp.get("command", "") or ""
                detail = cmd[:110].replace("\n", " ")
                if cls == "FULL_SUITE":
                    cls = _resolve_full_suite(b.get("id"), t, who, result_map, ledger)
                if cls == "FULL_SUITE":
                    code_edits = [p for p in edited_since_full if p.endswith(CODE_EXT)]
                    test_edits = [p for p in code_edits if _is_test_path(p)]
                    src_edits = [p for p in code_edits if p not in test_edits]
                    names = lambda ps: ",".join(sorted({os.path.basename(p) for p in ps}))
                    if last_full is not None and not code_edits:
                        flags.append("FULL_RERUN_NO_CODE_CHANGE(since %s; edits: %s)" % (last_full.strftime("%H:%M"), names(edited_since_full) or "none"))
                    elif not src_edits and test_edits:
                        flags.append("FULL_RUN_AFTER_TEST_ONLY_EDITS(%s)" % names(test_edits))
                    elif src_edits:
                        flags.append("full_run_after_src_edits(%s)" % names(src_edits))
                    else:
                        flags.append("first_full_run")
                    last_full = t
                    edited_since_full = []
            elif cls == "message":
                to = inp.get("to", "") or ""
                raw = inp.get("message", "") or ""
                body = _message_body(inp)
                if body is None:
                    cls = "message_protocol"
                    raw_type = raw.get("type") if isinstance(raw, dict) else ""
                    detail = "→%s: %s" % (to, raw_type)
                else:
                    detail = "→%s: %s" % (to, (inp.get("summary") or body)[:90].replace("\n", " "))
                    if _CONFIRM_RE.search(body):
                        flags.append("CONFIRM_ROUNDTRIP")
                    if _CROSS_RE.search(body):
                        flags.append("mentions_crossing")
                    lines = body.count("\n") + 1
                    if lines > 8:
                        flags.append("long(%d lines)" % lines)
                    msgs.append((t, to, lines))
            elif cls == "git_read":
                cmd = inp.get("command", "") or ""
                detail = cmd[:110].replace("\n", " ")
                if last_git_read and (t - last_git_read).total_seconds() < 120 and steps and steps[-1][2] == "git_read":
                    flags.append("git_read_repeat")
                last_git_read = t
            elif cls == "git_commit":
                cmd = inp.get("command", "") or ""
                detail = cmd[:110].replace("\n", " ")
                if " -- " not in cmd:
                    flags.append("commit_not_pathspec")
            elif cls == "task_tool":
                detail = b["name"]
                flags.append("task_tool")
            else:
                detail = (inp.get("command") or inp.get("pattern") or "")[:110].replace("\n", " ")
            add(t, "tool", cls, detail, flags)

    summary = {
        "turns_inbound": turn,
        "tool_calls": sum(1 for s in steps if s[1] == "tool"),
        "by_class": collections.Counter(s[2] for s in steps if s[1] == "tool"),
        "text_turns": text_turns,
        "waste": waste,
        "full_suite_runs": sum(1 for s in steps if s[2] == "FULL_SUITE"),
        "full_run_blocked": sum(1 for s in steps if s[2] == "full_run_blocked"),
        "blocked": sum(1 for s in steps if s[2] == "full_run_blocked"),
        "messages": len(msgs),
        "msgs_to_lead": sum(1 for x in msgs if x[1] == "team-lead"),
        "msgs_to_peers": sum(1 for x in msgs if x[1] != "team-lead"),
        "msg_lines_total": sum(x[2] for x in msgs),
        "rereads_total": {os.path.basename(p): n for p, n in reads_total.items() if n >= 3},
    }
    return steps, summary


def lead_inbound(path: Path, since: datetime.datetime, until: datetime.datetime):
    """Teammate messages in a lead transcript: (time, from, direct|idle,
    text, flag). An idle notification repeating >= 50 % of the words of the
    direct message the same teammate sent within ten minutes is a dup."""
    inbound = []
    for t, r in records(path, since, until):
        if r.get("type") != "user":
            continue
        txt = text_of((r.get("message") or {}).get("content"))
        if "teammate-message" not in txt:
            continue
        tag = re.search(r'teammate_id="([^"]+)"', txt)
        who = tag.group(1) if tag else "?"
        body = re.sub(r"</?teammate-message[^>]*>", "", txt.split("sent a message:", 1)[-1]).strip()
        kind, result = "direct", body
        if body.startswith("{") and "idle_notification" in body[:80]:
            kind = "idle"
            try:
                result = json.loads(body).get("result", "") or ""
            except Exception:
                result = body
        inbound.append((t, who, kind, result))
    last_direct: Dict[str, Tuple[datetime.datetime, set]] = {}
    dup = 0
    rows = []
    for t, who, kind, txt in inbound:
        words = set(re.findall(r"[a-z0-9`]{4,}", txt.lower()))
        flag = ""
        if kind == "direct":
            last_direct[who] = (t, words)
        else:
            if who in last_direct and (t - last_direct[who][0]).total_seconds() < 600 and words:
                ov = len(words & last_direct[who][1]) / len(words)
                if ov >= 0.5:
                    flag = "DUP_OF_DIRECT(%.0f%%)" % (ov * 100)
                    dup += 1
            if _STANDBY_RE.search(txt) and len(txt) < 600:
                flag = (flag + " " if flag else "") + "standby"
        rows.append((t, who, kind, txt[:100].replace("\n", " "), flag))
    return rows, dup


def write_steps(out_dir: Path, name: str, steps, since: str, until: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"steps-{name}.md"
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"# {name} — every step, {since} → {until}\n\n")
        f.write("Upper-case flags are waste classes (PT-94): FULL_RERUN_NO_CODE_CHANGE / FULL_RUN_AFTER_TEST_ONLY_EDITS → C9; "
                "CONFIRM_ROUNDTRIP → A3; IDLE_STANDBY / TASK_ECHO → A1; REREAD_SAME_TURN → one read per file per turn. "
                "Lower-case flags are context.\n\n| # | time | kind | class | detail | verdict |\n|---|---|---|---|---|---|\n")
        for i, (t, kind, cls, det, flags) in enumerate(steps, 1):
            waste = [x for x in flags.split() if x[:1].isupper()]
            verdict = ("waste: " + " ".join(waste)) if waste else (flags or "ok")
            f.write(f"| {i} | {t.strftime('%H:%M:%S')} | {kind} | {cls} | {det[:80].replace('|', '¦')} | {verdict} |\n")
    return p


def write_lead_inbound(out_dir: Path, rows) -> Path:
    p = Path(out_dir) / "lead-inbound.md"
    with open(p, "w", encoding="utf-8") as f:
        f.write("| # | time | from | kind | text | flag |\n|---|---|---|---|---|---|\n")
        for i, (t, w, k, txt, fl) in enumerate(rows, 1):
            f.write(f"| {i} | {t.strftime('%H:%M:%S')} | {w} | {k} | {txt.replace('|', '¦')} | {fl} |\n")
    return p


# ---------------------------------------------------------------- scorecard

def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=True).stdout


def _issue_path(data_dir: Path, issue_id: str) -> Optional[Path]:
    for sub in ("issues", "archive/issues"):
        p = Path(data_dir) / sub / f"{issue_id}.md"
        if p.exists():
            return p
    return None


def count_comments_and_rulings(text: str) -> Tuple[int, int]:
    """Comments = `### @author — date` headers. Ruling sections = comment
    blocks or headings whose first line names a ruling, addendum,
    correction, or verdict."""
    comments = 0
    rulings = 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _COMMENT_HEADER_RE.match(line):
            comments += 1
            first = next((l for l in lines[i + 1:i + 4] if l.strip()), "")
            if _RULING_RE.search(first):
                rulings += 1
        elif re.match(r"^#{2,4} ", line) and _RULING_RE.search(line):
            rulings += 1
    return comments, rulings


def scorecard(repo_root: Path, data_dir: Path, issue_id: str, base: str = "main",
              since: Optional[datetime.datetime] = None, until: Optional[datetime.datetime] = None,
              transcripts_dir: Optional[Path] = None, caps: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    repo_root = Path(repo_root)
    data_dir = Path(data_dir)
    caps = dict(DEFAULT_CAPS if caps is None else caps)
    rng = f"{base}..HEAD"
    log = _git(repo_root, "log", "--format=%H%x1f%s%x1f%aI", rng).strip()
    commits = [l.split("\x1f") for l in log.split("\n") if l]
    chore = sum(1 for c in commits if re.match(r"^(chore|docs)\b", c[1]))
    if since is None:
        since = parse_ts(commits[-1][2]) if commits else datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    if until is None:
        until = datetime.datetime.now(datetime.timezone.utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=datetime.timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=datetime.timezone.utc)
    # git's %aI carries the committer's local offset; the card is labelled in UTC.
    since = since.astimezone(datetime.timezone.utc)
    until = until.astimezone(datetime.timezone.utc)

    issue_path = _issue_path(data_dir, issue_id)
    comments = rulings = 0
    kb_added = 0.0
    if issue_path is not None:
        text = issue_path.read_text(encoding="utf-8")
        comments, rulings = count_comments_and_rulings(text)
        rel = os.path.relpath(issue_path, repo_root)
        try:
            base_text = _git(repo_root, "show", f"{base}:{rel}")
        except subprocess.CalledProcessError:
            base_text = ""
        kb_added = round((len(text.encode("utf-8")) - len(base_text.encode("utf-8"))) / 1024, 1)

    diff = _git(repo_root, "diff", rng)
    tests_added = sum(1 for l in diff.split("\n") if re.match(r"^\+\s*(def test_|(test|it)\()", l))

    full_runs = msgs_to_lead = idle = idle_dup = full_blocked = 0
    per_agent: Dict[str, Dict[str, Any]] = {}
    ledger_path = Path(data_dir) / "metrics" / "test-runs.jsonl"
    if transcripts_dir and Path(transcripts_dir).is_dir():
        for p, role in transcript_roles(Path(transcripts_dir)).items():
            steps, summ = audit_agent(p, since, until, lead=(role == "team-lead"), ledger_path=ledger_path)
            if not steps:
                continue
            full_runs += summ["full_suite_runs"]
            full_blocked += summ.get("full_run_blocked", 0)
            msgs_to_lead += summ["msgs_to_lead"]
            per_agent[role if role not in per_agent else f"{role}-{p.stem[:8]}"] = summ
            if role == "team-lead":
                rows, dup = lead_inbound(p, since, until)
                idle += sum(1 for r in rows if r[2] == "idle")
                idle_dup += dup

    cost = None
    try:
        import cairn  # local import: cairn imports nothing from here
        payload = cairn.build_tokens_payload(data_dir)
        for row in payload.get("issues", []):
            if row.get("issue") == issue_id:
                cost = row.get("total", {}).get("cost_usd")
    except Exception:
        cost = None

    # PT-97: process/cairn/metrics/test-runs.jsonl is authoritative when it
    # has full-run records in this window (real seconds, not a transcript
    # heuristic). No records in window (the file predates this issue, or
    # this loop never hit a gate) -- fall back to the transcript-derived
    # count above rather than reporting 0 runs that plainly happened.
    run_stats = full_run_stats(Path(data_dir) / "metrics" / "test-runs.jsonl", since, until)
    if run_stats["full_suite_runs"] > 0:
        full_runs = run_stats["full_suite_runs"]
    suite_seconds_added = run_stats["suite_seconds_added"]

    card: Dict[str, Any] = {
        "issue": issue_id, "base": base,
        "since": since.isoformat(), "until": until.isoformat(),
        "commits": len(commits), "chore_commits": chore,
        "comments": comments, "ruling_sections": rulings,
        "issue_kb_added": kb_added, "tests_added": tests_added,
        "suite_seconds_added": suite_seconds_added,
        "full_suite_runs": full_runs, "full_run_blocked": full_blocked, "msgs_to_lead": msgs_to_lead,
        "idle_notifications": idle, "idle_dup_of_direct": idle_dup,
        "cost_usd": cost, "per_agent": per_agent,
    }
    card["caps"] = {k: {"cap": v, "value": card.get(k), "over": (card.get(k) or 0) > v} for k, v in caps.items()}
    return card


ROW_ORDER = ["commits", "chore_commits", "comments", "ruling_sections", "issue_kb_added", "tests_added",
             "suite_seconds_added", "full_suite_runs", "msgs_to_lead", "idle_notifications", "idle_dup_of_direct", "cost_usd"]


def format_scorecard(card: Dict[str, Any]) -> str:
    out = [f"## Loop scorecard — {card['issue']}", "",
           f"Window {card['since'][:16]}Z → {card['until'][:16]}Z, commits `{card['base']}..HEAD`. "
           "A cap exceeded needs a one-line justification in the PR.", "",
           "| metric | value | cap | status |", "|---|---|---|---|"]
    # PT-111 gate-1 ruling: a blocked attempt (guard-refused or wrong-path)
    # is shown but never counted against the full_suite_runs cap, and gets
    # no cap of its own -- rename the executed-count row only when there is
    # something to distinguish it from (a nonzero blocked count in window).
    blocked = card.get("full_run_blocked")
    for k in ROW_ORDER:
        v = card.get(k)
        shown = "(no full-run records in window)" if k == "suite_seconds_added" and v is None else ("—" if v is None else v)
        label = f"{k} (executed)" if (k == "full_suite_runs" and blocked) else k
        if k in card["caps"]:
            c = card["caps"][k]
            out.append(f"| {label} | {shown} | {c['cap']} | {'OVER' if c['over'] else 'ok'} |")
        else:
            out.append(f"| {label} | {shown} | — | — |")
        if k == "full_suite_runs" and blocked:
            out.append(f"| full_run_blocked | {blocked} | — | — |")
    if card.get("per_agent"):
        # PT-97 gate-4 verdict delta 4: the per-agent breakdown is a
        # transcript-derived heuristic, distinct from the records-based
        # `full_suite_runs` row above -- they can legitimately disagree
        # (real output once showed "2" and "12" for the same loop, side
        # by side, with nothing telling a reader why). Label it whenever
        # they do, so the table can't be misread as a second measurement
        # of the same number.
        per_agent_total = sum(s.get("full_suite_runs", 0) for s in card["per_agent"].values())
        disagrees = per_agent_total != card.get("full_suite_runs")
        col = "full-suite runs (transcript)" if disagrees else "full-suite runs"
        out += [""]
        if disagrees:
            out.append(
                f"_Per-agent full-suite runs are transcript-derived and may disagree with the "
                f"authoritative records-based count above ({per_agent_total} vs {card.get('full_suite_runs')})._"
            )
            out.append("")
        out += [f"| agent | tool calls | {col} | blocked | msgs to lead | waste flags |", "|---|---|---|---|---|---|"]
        for role, s in card["per_agent"].items():
            w = ", ".join(f"{k} {n}" for k, n in sorted(s["waste"].items())) or "—"
            out.append(f"| {role} | {s['tool_calls']} | {s['full_suite_runs']} | {s.get('blocked', 0)} | {s['msgs_to_lead']} | {w} |")
    return "\n".join(out) + "\n"
