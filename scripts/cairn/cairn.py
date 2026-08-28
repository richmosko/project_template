#!/usr/bin/env python3
"""
cairn.py — cairn (the file-based issue tracker): parser, CLI, and board server.

Full design: process/TRACKER.md. Concrete function-level contract (names,
signatures) assumed by the test suite: scripts/cairn/tests/INTERFACE.md —
that file is the tie-breaker for "what is this function called", the spec
is the tie-breaker for "what must it do".

Summary:
  - Issues, milestones, and majors are markdown files with YAML frontmatter,
    living under a *data dir* (default: process/cairn/ in a project repo).
  - This module is the only non-file interface. It exists for the two jobs a
    plain Read/Write/Edit can't do safely: atomic ID allocation, and
    frontmatter-only rewrites that can't corrupt an issue's body.
  - A local, stateless HTTP server (`cairn serve`) renders a Kanban board by
    parsing the data dir at request time. It holds no state of its own.

Stdlib only. Targets stock macOS Python 3.9 — no `match`, no `X | Y` unions.

Locating the data dir (CLI):
  1. `--data-dir PATH`, if passed — used verbatim.
  2. Otherwise, `CAIRN_DATA_DIR` env var, if set.
  3. Otherwise, walk up from cwd looking for a `process/cairn/` directory
     (mirroring how git finds `.git`).
  4. Otherwise, fall back to `<cwd>/process/cairn`.

Run:
    scripts/cairn/cairn <command> ...     # via the bash shim
    python3 scripts/cairn/cairn.py ...    # direct invocation

Port override for `serve`: CAIRN_PORT=8899, or `--port`.
"""

import argparse
import datetime
import hashlib
import http.server
import json
import os
import queue
import re
import socketserver
import stat
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DEFAULT_PORT = 8766
DEFAULT_COLUMNS = ["backlog", "todo", "in-progress", "in-review", "done"]
# PT-36 (architect's ruling @ 49174b7, Part A): the append rule
# (`DEFAULT_COLUMNS` + `["cancelled"]`) had THREE Python-side copies
# (cairn.py:1277, tests/test_snapshot.py, and this constant's predecessor
# inline expression) -- collapsed to one real derivation here. A fresh list
# each import (`DEFAULT_COLUMNS + [...]` builds a new list, never mutates or
# aliases DEFAULT_COLUMNS), so mutating one can never touch the other.
STATUS_ORDER = DEFAULT_COLUMNS + ["cancelled"]
STATUSES = {"backlog", "todo", "in-progress", "in-review", "done", "cancelled"}
DEFAULT_STATUS = "backlog"
PRIORITIES = {"P0", "P1", "P2", "P3"}
MILESTONE_KINDS = {"process", "product"}

# PT-39 (architect's ruling § 1): the unified milestone/major status
# vocabulary -- one enum for BOTH schemas, not two that overlap by four
# values out of five. Deliberately a SEPARATE set object from STATUSES,
# never an alias: milestones have no `in-review`, majors have no
# `backlog` -- the issue-cycle vocabulary and the record-lifecycle
# vocabulary are related but distinct, and a milestone must never be able
# to carry `status: backlog` just because the two sets happened to be the
# same object. `completed` -> `done`, `active` -> `in-progress` is the
# migration this replaces (see migrate_lifecycle_status below); `paused`
# was already documented for milestones and is extended to majors here.
RECORD_STATUSES = {"planned", "in-progress", "paused", "done", "cancelled"}
MILESTONE_FIELD_ORDER = ["id", "name", "kind", "major", "status", "target_tag", "ga"]
MAJOR_FIELD_ORDER = ["id", "status", "owner", "target_ship", "health"]

# PT-51 §3: the major schema's `health` vocabulary (process/TRACKER.md's
# major-file example: "on-track | at-risk | off-track") -- validated at
# the record write path since it's a single-field syntactic check, unlike
# the cross-record invariants (GA cap, target_tag shape, major: resolves)
# this same section explicitly leaves to `cairn check`.
MAJOR_HEALTH_VALUES = {"on-track", "at-risk", "off-track"}

# PT-51 §3: board-editable fields per schema -- the ruling's "Editable in
# the drawer" list, encoded. Deliberately NARROWER than _RECORD_FIELD_ORDER
# (below): `id` (filename-authoritative; a rename is a `git mv`) and
# milestone `kind` (pinned to the id shape by lint, itself not board-
# editable) are legal CLI fields but excluded here on purpose, not
# special-cased in the validator -- "not in this set" already covers them.
_RECORD_BOARD_EDITABLE_FIELDS = {
    "milestone": {"name", "status", "major", "target_tag", "ga"},
    "major": {"status", "health", "owner", "target_ship"},
}

# PT-28: `prefix:` format -- the SAME regex /setup-tracker already uses for
# the interactive path (architect's ruling § 7), now also enforced at lint
# time so a hand-edited config.yml can't silently corrupt every id-shape
# regex below, all four of which are DERIVED from this value.
PREFIX_RE = re.compile(r"^[A-Z]{2,5}$")

# PT-27/PT-28: milestone id-shape <-> kind agreement, and (PT-28) major/issue
# id shape -- all four now PREFIXED (architect's ruling § 1, addendum-
# confirmed #1): `<P>-V<n>` (major), `<P>-<letter>` (definition milestone,
# `M`/`V` both reserved out of the letter sequence), `<P>-M<n>` or
# `<P>-<version>` (development milestone), `<P>-<n>` (issue). Functions, not
# module-level constants, because `<P>` is the repo's CONFIGURED prefix:,
# never a literal "PT" -- check_repo builds each of these once per call,
# after validating the prefix itself (see check_repo's own comment).
def _major_id_re(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^{re.escape(prefix)}-V\d+$")


# PT-41 (architect's Option A ruling, review finding #2): "V<n> means the
# line that culminates in v<n>.0.0". Extracts N only AFTER `major_re`
# (the caller's already-built, PREFIX-SCOPED `_major_id_re(prefix)`
# pattern -- PT-28's rule, same as the other three id-shape regexes)
# confirms `major_id` matches THIS repo's configured shape -- a
# prefix-agnostic literal regex could match a foreign-prefix or
# otherwise-malformed id (e.g. a stray "XX-V1" in a multi-root payload)
# and derive a meaningless N from it. Handles multi-digit N correctly
# (`PT-V10` -> `v10.0.0`, not a single-digit assumption).
_MAJOR_N_RE = re.compile(r"-V(\d+)$")


def _ga_target_tag_for_major(major_id: Any, major_re: Optional["re.Pattern[str]"]) -> Optional[str]:
    """The expected `v<N>.0.0` GA target_tag for `major_id`, or `None`
    when `major_re` is unavailable (the prefix itself didn't validate) or
    `major_id` doesn't match it -- a malformed/foreign-prefix major id is
    a DIFFERENT, already-reported lint error (the id-shape check above);
    this rider has nothing safe to check a GA milestone's target_tag
    against in that case, so it silently skips rather than raising a
    second, confusing error on the same root cause.
    """
    if major_re is None or not major_re.match(str(major_id)):
        return None
    m = _MAJOR_N_RE.search(str(major_id))
    return f"v{m.group(1)}.0.0" if m else None


def _definition_milestone_id_re(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^{re.escape(prefix)}-(?!M|V)[A-Z][a-z]?$")


def _development_milestone_id_re(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^{re.escape(prefix)}-(?:M\d+[a-z]?|\d+\.\d+(?:\.\d+)?)$")


def _issue_id_re(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^{re.escape(prefix)}-\d+$")


def _migrate_hint_if_bare(stem: str, prefix: str) -> str:
    """The ruling's error-string recipe (§ 6) -- named so it appears once,
    not re-typed at every id-shape error site. Only attached when `stem`
    doesn't already carry `prefix` at all: `cairn migrate prefix-ids` only
    ever prefixes a bare stem (PT-28's addendum § A.2 predicate), so a
    stem that's ALREADY prefixed but the wrong shape (e.g. a major named
    "PT-1", or a reserved letter like "PT-V") needs a human fix, not the
    migration command -- attaching this hint there would send someone to
    run a tool that can't help.
    """
    if stem.startswith(prefix + "-"):
        return ""
    return "  fix: scripts/cairn/cairn migrate prefix-ids --dry-run   (then re-run without --dry-run)"


def _lifecycle_migrate_hint_if_renamed(value: Any) -> str:
    """PT-39 (architect's ruling § 3 item 1): the migration-hint recipe for
    a milestone/major status lint error -- same pattern as
    _migrate_hint_if_bare above (named once, not re-typed at each call
    site). Only attached when `value` is literally one of the two OLD
    vocabulary values this migration knows how to rewrite ("completed" ->
    "done", "active" -> "in-progress") -- a garbage value ("wip") isn't
    something `cairn migrate lifecycle-status` can fix, so pointing at it
    there would send someone to run a tool that can't help (same
    reasoning as _migrate_hint_if_bare's already-prefixed-stem check).
    """
    if value in ("completed", "active"):
        return "  fix: scripts/cairn/cairn migrate lifecycle-status --dry-run   (then re-run without --dry-run)"
    return ""


def _check_record_status(errors: List[str], stem: str, status: Any) -> None:
    """PT-39 (architect's ruling § 3 item 1): the ONE status-validity check
    for a milestone/major record, called once per major and once per
    milestone in check_repo -- factored out (standing duplicated-inline-
    expression rule) so the two schemas' identical "missing or invalid
    status" condition can't drift into two slightly different messages.
    Appends to `errors` in place; returns nothing.
    """
    if status is None or status not in RECORD_STATUSES:
        errors.append(
            f"{stem}: missing or invalid status {status!r} -- "
            f"expected one of {sorted(RECORD_STATUSES)}"
            f"{_lifecycle_migrate_hint_if_renamed(status)}"
        )


def _check_archived_record_status(errors: List[str], stem: str, status: Any) -> None:
    """PT-46 (architect's Pass-2 finding on PT-39 § 3 item 2): the hand-
    `git mv` bypass, milestone/major half. `cairn archive --milestone`/
    `--major` refuses unless the record's own status is already
    done/cancelled (test_archive_records.py pins that precondition) --
    but nothing stops a human from `git mv`-ing a still-in-progress
    milestone/major file straight into archive/milestones/ or
    archive/majors/, skipping the precondition entirely. Same defect
    class PT-39 § 3 item 2 closed for an ARCHIVED ISSUE's milestone; this
    closes it for the record itself.

    Deliberately STRICTER than, and separate from, _check_record_status
    above: "planned"/"paused"/"in-progress" are all valid RECORD_STATUSES
    values (that general check passes them), but none is valid for a
    record that is ALREADY living in an archive dir -- this is an
    archive-location-specific rule the general check never asserted.
    Callers must scope this to archived records only; a live, in-progress
    milestone/major is normal and must never trip it. A missing status
    (`None`) also fails "not in (done, cancelled)" and is caught here too,
    not as a separately-shaped case.
    """
    if status not in ("done", "cancelled"):
        errors.append(
            f"{stem}: archived but status is {status!r}, not done/cancelled -- "
            f"looks like it was moved into archive/ by hand, bypassing "
            f"`cairn archive`'s precondition"
        )


ISSUE_FIELD_ORDER = [
    "id", "title", "status", "milestone", "parent", "blocked_by", "assignee",
    "labels", "priority", "pr", "created", "updated",
]

COMMENTS_HEADING_RE = re.compile(r"^## Comments\s*$")
COMMENT_DELIM_RE = re.compile(r"^### @([a-z0-9][a-z0-9-]*) — (\d{4}-\d{2}-\d{2})\s*$")
ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-(\d+)$")

BOARD_DIR = Path(__file__).resolve().parent / "board"

# PT-54 (architect ruling §1): sibling of BOARD_DIR, same cwd-independent
# shape. Points at the COMMITTED build output, not the app source --
# `scripts/cairn/dashboard/` (source) vs. `scripts/cairn/dashboard/dist/`
# (built, what actually gets served).
DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboard" / "dist"


def _today() -> str:
    return datetime.date.today().isoformat()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class CairnError(Exception):
    """Base error for cairn CLI/engine failures — caught at the CLI boundary."""


class YamlError(CairnError):
    """Raised by parse_yaml_subset on anything outside the documented subset."""


class FrontmatterError(CairnError):
    """Raised by parse_frontmatter when the '---'/'---' fences are missing or malformed."""


class ConflictError(CairnError):
    """Raised on the server-side patch path when a write's `seen` token is stale.

    Carries `.current`, the on-disk payload at conflict time, so the HTTP
    layer can render the spec's 409 body directly.
    """

    def __init__(self, message: str, current: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.current = current


# --------------------------------------------------------------------------
# Strict-subset YAML parser (fenceless — operates on a frontmatter block's
# inner text, or a whole file like config.yml that has no '---' fences).
#
# Supports: top-level and one-level-nested mappings, block lists of scalars,
# flow lists (`[a, b]`), single/double-quoted strings (always str), bare
# scalars (bare true/false -> bool, bare integers -> int, bare null/~ ->
# None, anything else bare -> str), and trailing `# comment` text.
#
# Rejects (raises YamlError): anchors (&x), aliases (*x), tags (!!str),
# flow mappings ({a: b}), block scalars (| or >), tabs in indentation,
# duplicate keys, list items shaped like mappings, and nesting deeper than
# one level. One parser, one behaviour.
# --------------------------------------------------------------------------

def _strip_inline_comment(s: str) -> str:
    """Strip a trailing ` # comment`, respecting simple quoted strings."""
    in_dq = False
    in_sq = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == '"' and not in_sq:
            in_dq = not in_dq
        elif c == "'" and not in_dq:
            in_sq = not in_sq
        elif c == "#" and not in_dq and not in_sq and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _split_flow(inner: str) -> List[str]:
    items: List[str] = []
    depth = 0
    in_dq = False
    in_sq = False
    cur: List[str] = []
    for c in inner:
        if c == '"' and not in_sq:
            in_dq = not in_dq
            cur.append(c)
        elif c == "'" and not in_dq:
            in_sq = not in_sq
            cur.append(c)
        elif c == "[" and not in_dq and not in_sq:
            depth += 1
            cur.append(c)
        elif c == "]" and not in_dq and not in_sq:
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0 and not in_dq and not in_sq:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if cur:
        items.append("".join(cur))
    return [i.strip() for i in items]


def _parse_scalar(raw: str, ctx: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return None
    if raw[0] == '"':
        if len(raw) < 2 or raw[-1] != '"':
            raise YamlError(f"{ctx}: unterminated double-quoted string: {raw!r}")
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if raw[0] == "'":
        if len(raw) < 2 or raw[-1] != "'":
            raise YamlError(f"{ctx}: unterminated single-quoted string: {raw!r}")
        return raw[1:-1]
    if raw in ("null", "~"):
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if re.match(r"^-?\d+$", raw):
        return int(raw)
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise YamlError(f"{ctx}: malformed flow list: {raw!r}")
        inner = raw[1:-1].strip()
        if inner == "":
            return []
        return [_parse_scalar(item, ctx) for item in _split_flow(inner)]
    if raw.startswith("{"):
        raise YamlError(f"{ctx}: flow mappings are not supported: {raw!r}")
    if raw[0] in "&*":
        raise YamlError(f"{ctx}: anchors/aliases are not supported: {raw!r}")
    if raw.startswith("!"):
        raise YamlError(f"{ctx}: tags are not supported: {raw!r}")
    if raw in ("|", ">") or raw[0] in "|>":
        raise YamlError(f"{ctx}: block scalars ('|'/'>') are not supported: {raw!r}")
    return raw


def _line_indent(line: str, lineno: int) -> int:
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    if i < len(line) and line[i] == "\t":
        raise YamlError(f"line {lineno}: tabs are not supported for indentation")
    return i


_MAPPING_LINE_RE = re.compile(r"^([^:\s][^:]*?):(?:\s+(.*))?$")
_LIST_MAPPING_ITEM_RE = re.compile(r'^[^:\s][^:]*:\s')


def parse_yaml_subset(text: str) -> Dict[str, Any]:
    """Parse a strict subset of fenceless YAML into a dict. See module docstring."""
    raw_lines = text.splitlines()
    entries: List[Tuple[int, int, str]] = []
    for i, line in enumerate(raw_lines, start=1):
        if line.strip() == "":
            continue
        if line.strip().startswith("#"):
            continue
        indent = _line_indent(line, i)
        content = _strip_inline_comment(line.strip())
        if content == "":
            continue
        entries.append((i, indent, content))

    pos = [0]

    def parse_list(indent: int) -> List[Any]:
        items: List[Any] = []
        while pos[0] < len(entries):
            lineno, cur_indent, content = entries[pos[0]]
            if cur_indent != indent or not content.startswith("- "):
                break
            item_raw = content[2:].strip()
            pos[0] += 1
            if _LIST_MAPPING_ITEM_RE.match(item_raw):
                raise YamlError(f"line {lineno}: list items must be scalars, not mappings")
            items.append(_parse_scalar(item_raw, f"line {lineno}"))
        return items

    def parse_mapping(indent: int, depth: int) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        while pos[0] < len(entries):
            lineno, cur_indent, content = entries[pos[0]]
            if cur_indent != indent:
                if cur_indent > indent:
                    raise YamlError(
                        f"line {lineno}: unexpected indentation (expected {indent}, got {cur_indent})"
                    )
                break
            if content.startswith("- "):
                raise YamlError(f"line {lineno}: unexpected list item in mapping")
            m = _MAPPING_LINE_RE.match(content)
            if not m:
                raise YamlError(f"line {lineno}: expected 'key: value', got {content!r}")
            key, value_raw = m.group(1), (m.group(2) or "")
            if key in result:
                raise YamlError(f"line {lineno}: duplicate key {key!r}")
            pos[0] += 1
            if value_raw.strip() == "":
                if pos[0] < len(entries) and entries[pos[0]][1] > cur_indent:
                    if depth >= 1:
                        raise YamlError(f"line {lineno}: nesting deeper than one level is not supported")
                    next_indent = entries[pos[0]][1]
                    next_content = entries[pos[0]][2]
                    if next_content.startswith("- "):
                        result[key] = parse_list(next_indent)
                    else:
                        result[key] = parse_mapping(next_indent, depth + 1)
                else:
                    result[key] = None
            else:
                result[key] = _parse_scalar(value_raw, f"line {lineno}")
        return result

    if not entries:
        return {}
    return parse_mapping(entries[0][1], 0)


# --------------------------------------------------------------------------
# Frontmatter fences + comment-log splitting
# --------------------------------------------------------------------------

def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a whole issue/milestone/major file into (frontmatter, body).

    Requires the first line to be exactly '---' and a later line to be
    exactly '---'. `body` is everything after the closing fence's newline,
    byte-for-byte (well, char-for-char post-decode).
    """
    if not text.startswith("---"):
        raise FrontmatterError("file must start with a '---' frontmatter delimiter")
    lines = text.split("\n")
    if lines[0] != "---":
        raise FrontmatterError("file must start with a '---' frontmatter delimiter")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            end_idx = i
            break
    if end_idx is None:
        raise FrontmatterError("no closing '---' frontmatter delimiter found")
    fm_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:])
    frontmatter = parse_yaml_subset(fm_text)
    return frontmatter, body


def split_comments(body: str) -> Tuple[str, List[Dict[str, str]]]:
    """Split an issue body on the first '^## Comments$' line.

    Returns (pre_comments_text, comments). Each comment is
    {"author": str, "date": "YYYY-MM-DD", "body": str}, oldest first.
    No '## Comments' heading -> (body, []).

    Spec-literal, no fence exception: "a new comment starts at a line
    matching exactly <COMMENT_DELIM_RE>; any other line is body content."
    A line inside a ```-fenced block that happens to match the delimiter
    shape IS a real boundary, full stop — fence-tracking was tried and
    reverted (architect conformance review, finding 4): it silently
    swallowed every comment after an *unclosed* fence for the rest of the
    file, an unbounded and invisible failure far worse than the one
    mis-split comment it was guarding against.
    """
    lines = body.split("\n")
    heading_idx = None
    for i, line in enumerate(lines):
        if COMMENTS_HEADING_RE.match(line):
            heading_idx = i
            break
    if heading_idx is None:
        return body, []

    pre = "\n".join(lines[:heading_idx])
    comment_lines = lines[heading_idx + 1:]
    comments: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    acc: List[str] = []
    for line in comment_lines:
        m = COMMENT_DELIM_RE.match(line)
        if m:
            if current is not None:
                current["body"] = "\n".join(acc).strip("\n")
                comments.append(current)
            current = {"author": m.group(1), "date": m.group(2)}
            acc = []
        else:
            if current is not None:
                acc.append(line)
    if current is not None:
        current["body"] = "\n".join(acc).strip("\n")
        comments.append(current)
    return pre, comments


def parse_issue(text: str) -> Dict[str, Any]:
    """Merge frontmatter + description + comments into one flat dict."""
    frontmatter, body = parse_frontmatter(text)
    description, comments = split_comments(body)
    issue = dict(frontmatter)
    issue["description"] = description
    issue["comments"] = comments
    return issue


# --------------------------------------------------------------------------
# Write-back: frontmatter-only rewrite, byte-preserving body
# --------------------------------------------------------------------------

_NUMERIC_LOOKING_RE = re.compile(r"^-?\d+(\.\d+)?$")
_BARE_RESERVED = {"null", "~", "true", "false"}


def _needs_quoting(s: str) -> bool:
    if s == "":
        return True
    if s in _BARE_RESERVED:
        return True
    if _NUMERIC_LOOKING_RE.match(s):
        return True
    if s != s.strip():
        return True
    if s[0] in "[]{}&*!|>#'\"":
        return True
    if s.startswith("- "):
        return True
    return False


def _quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _dump_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_dump_value(v) for v in value) + "]"
    s = str(value)
    return _quote(s) if _needs_quoting(s) else s


def _is_issue_shaped(fields: Dict[str, Any]) -> bool:
    """True if `fields` matches the issue schema.

    `title` is required on every issue (TRACKER.md) and absent from both
    the milestone and major schemas — the cheapest reliable signal to tell
    "this is an issue frontmatter dict" from "this is some other schema
    dump_frontmatter/apply_patch got called on" (PT-13). Non-issue-shaped
    dicts keep their own field order untouched and never get an `updated`
    key injected — that field belongs to the issue schema only.
    """
    return "title" in fields


def dump_frontmatter(fields: Dict[str, Any]) -> str:
    """Render `fields` as a '---\\n...---\\n' block.

    Emits keys actually present in `fields` — never synthesizes an absent
    one. For issue-shaped `fields` (has a `title` key): ISSUE_FIELD_ORDER's
    keys lead in their canonical order, then any remaining (non-issue-
    schema) keys in their original insertion order — this is what lets a
    hand-added unknown field round-trip intact instead of being silently
    dropped (architect conformance review, finding 1). For a milestone/
    major file's entirely different schema (no `title` key), field order
    is left exactly as given — the reordering above is an issue-schema-only
    convention, not something to impose on a different schema (PT-13).
    """
    if not _is_issue_shaped(fields):
        lines = [f"{key}: {_dump_value(fields[key])}" for key in fields]
        return "---\n" + "\n".join(lines) + "\n---\n"
    canonical = [key for key in ISSUE_FIELD_ORDER if key in fields]
    extra = [key for key in fields.keys() if key not in ISSUE_FIELD_ORDER]
    lines = [f"{key}: {_dump_value(fields[key])}" for key in canonical + extra]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` via a same-directory temp file + os.replace.

    Preserves the original file's mode (PT-7): `os.replace` is a rename,
    so the final file's permission bits come from the *source* -- without
    an explicit chmod, mkstemp's 0600 default silently replaces whatever
    mode the file had (e.g. 0644 -> 0600) on every frontmatter rewrite.
    """
    path = Path(path)
    try:
        original_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        original_mode = None
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if original_mode is not None:
            os.chmod(tmp_name, original_mode)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_seen(path: Path) -> str:
    """The `seen` mtime token for `path`: st_mtime_ns as a string."""
    return str(Path(path).stat().st_mtime_ns)


NULLABLE_FIELDS = (
    "milestone", "assignee", "parent", "priority", "pr",
    # PT-51 §3: the record schema's own "(text, nullable)" board-editable
    # fields (milestone target_tag; major owner/target_ship) -- same "" ->
    # None coercion the issue fields above already get, same mechanism
    # (apply_patch is the one place both schemas funnel through), just
    # extended to cover the record-only field names. Safe to share one
    # tuple: none of these three names collides with an issue field.
    "target_tag", "owner", "target_ship",
)

# PT-26: list-valued fields never join NULLABLE_FIELDS -- clearing one
# writes `[]`, never `null` (labels already worked this way; blocked_by
# follows the same precedent). The list branch in _coerce_cli_value must
# be checked *before* the nullable branch for exactly this reason.
LIST_FIELDS = ("labels", "blocked_by")


def _split_csv(value: str) -> List[str]:
    """Comma-split `value` into a list, stripping whitespace and dropping
    empty segments -- the shared helper behind both --labels/--blocked-by
    (cmd_new) and labels=/blocked_by= (cmd_set's _coerce_cli_value). One
    function, not two copies of the same comprehension (PT-26: cmd_new
    carried a pre-existing duplicate of _coerce_cli_value's labels split --
    the standing duplicated-inline-expression criterion, fixed here rather
    than adding a third copy for blocked_by).
    """
    return [v.strip() for v in value.split(",") if v.strip()]


def apply_patch(path: Path, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge `patch` into `path`'s frontmatter and rewrite it in place.

    On issue-shaped files (has a `title` key), sets `updated` to today
    unless `patch` supplies it explicitly. `updated` belongs to the issue
    schema only — a milestone/major file never gets it injected (PT-13).
    Body bytes after the closing fence are untouched. Returns the new
    frontmatter dict.

    Coerces `""` -> `None` for the five nullable fields (milestone,
    assignee, parent, priority, pr): clearing a field — via the CLI
    (`cairn set PT-1 milestone=`) or the board's inline drawer editors —
    must write `null`, not an empty string. This is the durable place for
    the fix: both entry points funnel through here (architect conformance
    review, finding 2), so an empty string never reaches disk regardless
    of caller.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    coerced_patch = dict(patch)
    for field in NULLABLE_FIELDS:
        if field in coerced_patch and coerced_patch[field] == "":
            coerced_patch[field] = None
    is_issue = _is_issue_shaped(frontmatter)
    frontmatter.update(coerced_patch)
    if is_issue and "updated" not in patch:
        frontmatter["updated"] = _today()
    new_text = dump_frontmatter(frontmatter) + body
    _atomic_write(path, new_text)
    return frontmatter


def append_comment(path: Path, author: str, body: str, comment_date: Optional[str] = None) -> Dict[str, Any]:
    """Append one comment to the tail of `path` (adding a '## Comments'
    heading first if absent), and bump `updated` to today -- issue-shaped
    files only. Returns the new frontmatter dict.

    PT-51 §4 prerequisite: gated on `_is_issue_shaped`, the same guard
    `apply_patch` already uses. Records (milestone/major) have no
    `updated` field in their schema (PT-13) -- an unconditional bump
    would inject an off-schema key the first time anyone comments on one,
    which `dump_frontmatter`'s non-issue branch would then faithfully
    (and wrongly) emit forever after.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    frontmatter, file_body = parse_frontmatter(text)
    date_str = comment_date or _today()
    comment_block = f"### @{author} — {date_str}\n\n{body.strip()}\n"

    has_heading = any(COMMENTS_HEADING_RE.match(l) for l in file_body.split("\n"))
    new_body = file_body
    if not new_body.endswith("\n"):
        new_body += "\n"
    if not new_body.endswith("\n\n"):
        new_body += "\n"
    if has_heading:
        new_body += comment_block
    else:
        new_body += "## Comments\n\n" + comment_block

    if _is_issue_shaped(frontmatter):
        frontmatter["updated"] = _today()
    new_text = dump_frontmatter(frontmatter) + new_body
    _atomic_write(path, new_text)
    return frontmatter


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def find_data_dir() -> Path:
    """Locate the data dir when no --data-dir was given. See module docstring."""
    env = os.environ.get("CAIRN_DATA_DIR")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd()
    for candidate in [cwd] + list(cwd.parents):
        d = candidate / "process" / "cairn"
        if (d / "config.yml").exists():
            return d
    return cwd / "process" / "cairn"


# PT-38 (architect's ruling § 1): board.columns is an ORDERED SUBSET of the
# known column statuses -- STATUSES minus "cancelled" (cancelled is owned
# by the Show-cancelled toggle, PT-35; two mechanisms producing one column
# is the drift class this ruling exists to avoid, not a feature to add).
# DEFAULT_COLUMNS already *is* exactly that five-status set, in the
# canonical order -- no second, separately-maintained set literal.
_VALID_COLUMN_STATUSES = frozenset(DEFAULT_COLUMNS)
# A tuple, not a frozenset -- `x in _VALID_SWIMLANE_VALUES` must stay safe
# for an UNHASHABLE `x` (a list, a dict -- both real inputs
# validate_board_swimlane's never-raises contract is tested against). `in`
# on a set/frozenset hashes its left operand before comparing, which
# raises TypeError for an unhashable value regardless of set membership;
# `in` on a tuple does a plain elementwise `==` scan, never hashes.
_VALID_SWIMLANE_VALUES = ("milestone", "none")


def validate_board_columns(value: Any) -> Tuple[bool, str]:
    """The ONE validity check for a `board.columns` config value (PT-38
    ruling § 1). Returns `(True, "")` when valid, `(False, <pointed
    reason>)` otherwise. This single function backs BOTH `cairn check`'s
    hard lint error and `load_config`'s soft fall-back-to-default warning
    -- one validator, two callers/postures, never two copies of the same
    condition that could drift apart (the ruling § 4's "one validator, not
    two that must agree" principle, applied server-side too).
    """
    if not isinstance(value, list):
        return False, f"board.columns must be a list, got {type(value).__name__}"
    if not value:
        return False, "board.columns must not be empty"
    seen: set = set()
    for entry in value:
        if not isinstance(entry, str):
            return False, f"board.columns entries must be strings, got {entry!r} ({type(entry).__name__})"
        if entry == "cancelled":
            return False, (
                "board.columns must not include \"cancelled\" -- it is owned by the "
                "Show-cancelled toggle, not column config"
            )
        if entry not in _VALID_COLUMN_STATUSES:
            return False, (
                f"board.columns entry {entry!r} is not a known status "
                f"(expected one of {sorted(_VALID_COLUMN_STATUSES)})"
            )
        if entry in seen:
            return False, f"board.columns contains a duplicate entry {entry!r}"
        seen.add(entry)
    return True, ""


def validate_board_swimlane(value: Any) -> Tuple[bool, str]:
    """The ONE validity check for a `board.swimlane` config value (PT-38
    ruling § 6, folded in by team-lead's ruling). Same one-validator,
    two-caller shape as validate_board_columns above.
    """
    if value not in _VALID_SWIMLANE_VALUES:
        return False, f"board.swimlane must be one of {sorted(_VALID_SWIMLANE_VALUES)}, got {value!r}"
    return True, ""


def load_config(data_dir: Path) -> Dict[str, Any]:
    """Read and parse data_dir/config.yml. Missing keys fall back to defaults.

    Defaulting only -- does NOT validate a present-but-invalid
    board.columns/board.swimlane value (that value is passed through
    UNCHANGED; `resolve_board_columns`/`resolve_board_swimlane` below are
    where a bad value actually gets caught). Called from many CLI paths
    that have nothing to do with the board (`cairn new`, `cairn ls`, ...),
    so it is deliberately NOT the validation/fallback/stderr entry point --
    that would print PT-38's warning on every unrelated invocation of a
    repo with a stale bad config, not just the ones that render a board.
    """
    data_dir = Path(data_dir)
    config_path = data_dir / "config.yml"
    parsed: Dict[str, Any] = {}
    if config_path.exists():
        parsed = parse_yaml_subset(config_path.read_text(encoding="utf-8"))

    config = dict(parsed)
    config.setdefault("prefix", "ISS")
    config.setdefault("port", DEFAULT_PORT)
    config.setdefault("data_dir", str(data_dir))
    board = dict(parsed.get("board") or {})
    board.setdefault("columns", list(DEFAULT_COLUMNS))
    board.setdefault("swimlane", "milestone")
    config["board"] = board
    return config


def resolve_board_columns(config: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """The RESOLVED `board.columns` for `config` (already `load_config`-
    defaulted, so `config["board"]["columns"]` is always present -- may
    still carry a raw invalid value, since `load_config` itself never
    validates). Returns `(value, None)` when valid, `(list(DEFAULT_COLUMNS),
    "<pointed warning>")` otherwise. PURE -- never prints, never raises;
    the warning is returned as DATA. `build_multi_board_payload` is the
    actual stderr print site (PT-38 ruling § 2), not this function.
    """
    value = (config.get("board") or {}).get("columns")
    ok, reason = validate_board_columns(value)
    if ok:
        return list(value), None
    return list(DEFAULT_COLUMNS), f"board.columns invalid ({reason}) -- falling back to the default column set"


def resolve_board_swimlane(config: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Mirror of resolve_board_columns for `board.swimlane` -- falls back
    to `"milestone"`. Same PURE, never-prints, never-raises contract.
    """
    value = (config.get("board") or {}).get("swimlane")
    ok, reason = validate_board_swimlane(value)
    if ok:
        return value, None
    return "milestone", f"board.swimlane invalid ({reason}) -- falling back to \"milestone\""


# --------------------------------------------------------------------------
# Directory scanning helpers
# --------------------------------------------------------------------------

def _dir_glob(d: Path) -> List[Path]:
    return sorted(d.glob("*.md")) if d.exists() else []


def archived_issue_paths(data_dir: Path) -> List[Path]:
    """Every archived issue .md file -- `archive/issues/` ONLY (PT-52:
    the legacy flat `archive/*.md` leg PT-50 kept for the transition is
    gone; the engine no longer reads it at all). `_dir_glob` is
    non-recursive, so this never touches `archive/milestones/` or
    `archive/majors/`.

    Kept as a named helper rather than inlined at its 8 call sites (PT-52
    §1, architect's ruling): the property that made PT-50 tractable --
    one place that answers "where do archived issues live" -- is worth
    keeping in reverse too, so a future layout change touches one line,
    not eight. See `legacy_archived_issue_paths` below for the (now
    lint-only) legacy path.
    """
    data_dir = Path(data_dir)
    return _dir_glob(data_dir / "archive" / "issues")


def legacy_archived_issue_paths(data_dir: Path) -> List[Path]:
    """The legacy flat `archive/*.md` layout PT-52 stopped reading -- NOT
    a general-purpose helper; it exists for exactly two callers, and both
    must stay in lockstep: `check_repo`'s legacy-layout lint scan (so the
    reported count is accurate) and `migrate_archive_issues`'s source glob
    (so the migration moves precisely the files the lint complained
    about). If the lint ever reported a file the migration didn't move,
    the error would be unactionable -- one definition point is what keeps
    that impossible. `_dir_glob` is non-recursive, so this never touches
    `archive/issues/`, `archive/milestones/`, or `archive/majors/`.
    """
    data_dir = Path(data_dir)
    return _dir_glob(data_dir / "archive")


def find_issue_path(data_dir: Path, issue_id: str) -> Optional[Path]:
    data_dir = Path(data_dir)
    candidate = data_dir / "issues" / f"{issue_id}.md"
    if candidate.exists():
        return candidate
    candidate = data_dir / "archive" / "issues" / f"{issue_id}.md"
    if candidate.exists():
        return candidate
    return None


# PT-39 (architect's ruling § 6): the six subdirs find_record_path resolves
# an id against, in precedence order. Issues first (the common case, and
# the shape find_issue_path already optimizes for), then milestones, then
# majors -- each schema's live dir before its archive dir.
_RECORD_SEARCH_SUBDIRS = (
    "issues", "archive/issues", "milestones", "archive/milestones", "majors", "archive/majors",
)


def find_record_path(data_dir: Path, record_id: str) -> Optional[Path]:
    """Resolves `record_id` against issues/archive/milestones/majors (live
    and archived), in `_RECORD_SEARCH_SUBDIRS` order. NEW for PT-39's
    `cairn set` extension -- CLI-only.

    Deliberately a SEPARATE function from find_issue_path, not a widening
    of it: find_issue_path stays the only resolver the HTTP write path can
    reach (PT-3's read-only guarantee is structural, not a runtime check --
    see find_issue_path's own callers). A milestone/major must never
    become reachable from POST /api/issue/<id> just because this function
    exists.
    """
    data_dir = Path(data_dir)
    for sub in _RECORD_SEARCH_SUBDIRS:
        candidate = data_dir / sub / f"{record_id}.md"
        if candidate.exists():
            return candidate
    return None


def _read_frontmatter_dict(path: Path) -> Dict[str, Any]:
    frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    return frontmatter


def is_archived_path(data_dir: Path, path: Path) -> bool:
    """Whether `path` lives under `data_dir`'s archive tree -- archive/
    (issues), archive/milestones/, or archive/majors/ alike. PT-42
    (architect's pre-PR extraction, security-relevant): the SINGLE
    predicate every "is this record archived" check routes through --
    four independently-typed spellings existed before this (three as
    `path.parent.name == "archive"`, one already as this parts-based
    form), and the parent-name spelling is a live correctness gap: it
    silently reads an issue under archive/milestones/ or archive/majors/
    as NOT archived (wrong directory depth), and would do the same for a
    hypothetical archive/issues/ -- for the HTTP-mutation 403 check
    specifically, that gap means an archived issue one directory level
    deeper than plain archive/ would stay wrongly writable over HTTP.
    Parts-based (`"archive" in path.relative_to(data_dir).parts`) is
    correct at any depth under archive/, not just one level in.
    """
    return "archive" in Path(path).relative_to(Path(data_dir)).parts


# --------------------------------------------------------------------------
# ID allocation — O_CREAT|O_EXCL atomic claim, retry on race
# --------------------------------------------------------------------------

def _next_id_candidate(data_dir: Path, prefix: str) -> int:
    # PT-50/PT-52: archived ids come from archived_issue_paths (archive/
    # issues/ only, post-PT-52) so `cairn new` never re-allocates an id an
    # archived issue already holds (the one invariant the id scheme exists
    # to protect). An UNMIGRATED repo's legacy-held ids are not covered by
    # this glob any more -- see allocate_and_create_issue's PT-52 §3 guard,
    # which refuses to allocate at all on such a repo rather than risk it.
    data_dir = Path(data_dir)
    max_n = 0
    live_dir = data_dir / "issues"
    candidates: List[Path] = (list(live_dir.glob(f"{prefix}-*.md")) if live_dir.exists() else [])
    candidates += [p for p in archived_issue_paths(data_dir) if p.stem.startswith(f"{prefix}-")]
    for p in candidates:
        m = ID_RE.match(p.stem)
        if m and m.group(1) == prefix:
            max_n = max(max_n, int(m.group(2)))
    return max_n + 1


def allocate_and_create_issue(data_dir: Path, fields: Dict[str, Any], max_attempts: int = 50) -> Path:
    """Atomically claim the next free ID and create issues/<PREFIX>-<n>.md.

    `fields` supplies everything except id/created/updated, which this
    function fills in. `prefix` comes from load_config(data_dir)["prefix"].

    PT-52 §3 (architect's ruling, required companion to the legacy-read
    deletion): the single allocation path both `cmd_new` and the HTTP
    `_create_issue` funnel through, so it's also the single place to guard.
    `_next_id_candidate` no longer counts ids held by a legacy-layout
    archived issue (PT-52 §1 collapsed `archived_issue_paths` to
    `archive/issues/` only) -- on an unmigrated repo, allocating anyway
    would silently re-issue an id an archived issue already holds, the one
    invariant the id scheme exists to protect, and NOT repairable by
    running the migration afterwards (the new issue would already exist).
    Refuse before any O_EXCL attempt: one non-recursive glob per
    allocation, on an operation measured in units per day. Self-clearing --
    run the migration and this raise stops firing.
    """
    data_dir = Path(data_dir)
    legacy = legacy_archived_issue_paths(data_dir)
    if legacy:
        raise CairnError(
            f"{len(legacy)} archived issue(s) at the legacy archive/*.md layout -- refusing to allocate a "
            f"new id (it could collide with one an archived issue already holds). "
            f"fix: scripts/cairn/cairn migrate archive-issues --dry-run   (then re-run without --dry-run)"
        )
    config = load_config(data_dir)
    prefix = config["prefix"]
    issues_dir = data_dir / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    n = _next_id_candidate(data_dir, prefix)
    today_str = _today()

    for _ in range(max_attempts):
        issue_id = f"{prefix}-{n}"
        path = issues_dir / f"{issue_id}.md"
        full_fields = dict(fields)
        full_fields["id"] = issue_id
        full_fields["created"] = today_str
        full_fields["updated"] = today_str
        content = dump_frontmatter(full_fields) + "\n"
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            continue
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)
        return path
    raise CairnError(f"could not allocate an ID for prefix {prefix!r} after {max_attempts} attempts")


# --------------------------------------------------------------------------
# Lint
# --------------------------------------------------------------------------

def check_repo(data_dir: Path) -> List[str]:
    """Lint the data dir. Returns pointed error strings; [] means clean.

    Catches per-file YamlError/FrontmatterError internally rather than
    propagating them.
    """
    data_dir = Path(data_dir)
    errors: List[str] = []

    # PT-3 (team-lead ruling C): `roots:` shape only, never reachability --
    # `cairn check` runs in CI and on any clone lacking a sibling repo, so
    # a missing/unreachable secondary root is a runtime warn-and-skip
    # concern (resolve_roots), not a lint error.
    #
    # PT-28 (architect's ruling § 3.1, confirmation #2): a missing or
    # prefix-less config.yml STOPS being tolerable the moment id shapes are
    # derived from `prefix:` -- every regex below needs it, and a lint that
    # quietly stops linting (or guesses) is worse than no lint. `prefix`
    # stays None on any failure path here, which is this function's single
    # signal to every id-shape check below to skip itself rather than run
    # against a regex it can't safely build -- never a guess, and never a
    # silent partial lint (PrefixFormatLintTests.
    # test_a_malformed_prefix_does_not_silently_skip_the_rest_of_the_lint:
    # the prefix error itself, appended immediately below, is what keeps
    # `errors` non-empty even when nothing else fires).
    config_path = data_dir / "config.yml"
    prefix: Optional[str] = None
    if not config_path.exists():
        errors.append(f"config.yml: missing at {config_path} -- required for the id-shape prefix lint")
        cfg: Dict[str, Any] = {}
    else:
        try:
            cfg = parse_yaml_subset(config_path.read_text(encoding="utf-8"))
        except CairnError as e:
            errors.append(f"config.yml: {e}")
            cfg = {}
        roots_val = cfg.get("roots")
        if roots_val is not None:
            if not isinstance(roots_val, list):
                errors.append(f"config.yml: roots must be a list of paths, got {type(roots_val).__name__}")
            else:
                for idx, entry in enumerate(roots_val):
                    if not isinstance(entry, str):
                        errors.append(f"config.yml: roots[{idx}] must be a path string, not {type(entry).__name__}")
                    elif not entry:
                        errors.append(f"config.yml: roots[{idx}] must be a non-empty relative path")
                    elif Path(entry).is_absolute():
                        errors.append(f"config.yml: roots[{idx}] {entry!r} must be relative to the repo root")

        raw_prefix = cfg.get("prefix")
        if raw_prefix is None:
            errors.append("config.yml: missing prefix: key -- required for the id-shape lint")
        elif not PREFIX_RE.match(str(raw_prefix)):
            errors.append(f"config.yml: prefix {raw_prefix!r} must match {PREFIX_RE.pattern}")
        else:
            prefix = str(raw_prefix)

        # PT-38 (ruling § 2): the HARD-error posture -- an explicitly
        # present but invalid board.columns/board.swimlane value is a lint
        # error, the opposite posture from load_config's silent fallback
        # for the SAME bad input (by design, not a discrepancy -- see
        # load_config's own docstring). An ABSENT key is not an error;
        # defaulting is fine, so these only run when the key is actually
        # present in the RAW parsed config (pre-load_config-defaulting).
        board_val = cfg.get("board")
        if isinstance(board_val, dict):
            if "columns" in board_val:
                ok, reason = validate_board_columns(board_val["columns"])
                if not ok:
                    errors.append(f"config.yml: board.columns invalid -- {reason}")
            if "swimlane" in board_val:
                ok, reason = validate_board_swimlane(board_val["swimlane"])
                if not ok:
                    errors.append(f"config.yml: board.swimlane invalid -- {reason}")
        elif board_val is not None:
            errors.append(f"config.yml: board must be a mapping, got {type(board_val).__name__}")

    # PT-28: built once per call, only when the prefix validated -- every
    # id-shape check below reads through these four, never rebuilding its
    # own regex inline (that would be the exact "two copies must agree"
    # hazard PT-22/PT-29 exist to close, one layer down).
    major_re = _major_id_re(prefix) if prefix else None
    definition_re = _definition_milestone_id_re(prefix) if prefix else None
    development_re = _development_milestone_id_re(prefix) if prefix else None
    issue_re = _issue_id_re(prefix) if prefix else None

    known_majors = set()
    for p in _dir_glob(data_dir / "majors"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            errors.append(f"{p.stem}: {e}")
            continue
        mid = fm.get("id")
        if mid is None or str(mid) != p.stem:
            errors.append(f"{p.stem}: id {mid!r} does not match filename {p.stem!r}")
        elif major_re is not None and not major_re.match(p.stem):
            # PT-28: NEW enforcement -- pre-PT-28, check_repo never
            # validated a major's id shape at all, only id==filename.
            errors.append(
                f"{p.stem}: major id shape {p.stem!r} does not match {major_re.pattern!r} "
                f"(configured prefix {prefix!r}){_migrate_hint_if_bare(p.stem, prefix)}"
            )
        if fm.get("title") is not None:
            errors.append(f"{p.stem}: unexpected title {fm['title']!r} -- title is issue-only")
        # PT-39 (architect's ruling § 3 item 1): NEW enforcement -- a
        # major's status: must be present and in RECORD_STATUSES. Pre-
        # PT-39, check_repo never validated a major's status value at
        # all, which is how "active" (not even documented anywhere)
        # survived undetected.
        _check_record_status(errors, p.stem, fm.get("status"))
        known_majors.add(p.stem)

    # PT-39 (architect's ruling § 3 item 3): known_majors ALSO resolves
    # against archive/majors/ -- an archived major is still a legitimate
    # reference target (a milestone naming it, or the archive precondition
    # itself), and excluding it here would dangle every reference to it
    # the moment `cairn archive --major` runs, self-defeating for a
    # command whose whole point is a clean post-archive lint. Resolution
    # ONLY -- id-shape/title/GENERAL-status validation is NOT re-run on
    # archived files: they already passed those checks at the moment they
    # were archived (archive_major moves files verbatim, never rewriting
    # frontmatter), so re-validating here would be redundant at best.
    #
    # PT-46 (architect's Pass-2 finding): the ONE exception -- an archived
    # record's OWN status must be done/cancelled, a stricter,
    # archive-location-specific rule the general check above never
    # asserted (the hand-`git mv` bypass this file's own precondition
    # exists to catch). This is why this loop parses frontmatter now,
    # unlike before PT-46.
    for p in _dir_glob(data_dir / "archive" / "majors"):
        known_majors.add(p.stem)
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        _check_archived_record_status(errors, p.stem, fm.get("status"))

    known_milestones = set()
    parsed_milestones: List[Tuple[Path, Dict[str, Any]]] = []
    for p in _dir_glob(data_dir / "milestones"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            errors.append(f"{p.stem}: {e}")
            continue
        parsed_milestones.append((p, fm))
        mid = fm.get("id")
        if mid is None or str(mid) != p.stem:
            errors.append(f"{p.stem}: id {mid!r} does not match filename {p.stem!r}")
        if fm.get("title") is not None:
            errors.append(f"{p.stem}: unexpected title {fm['title']!r} -- title is issue-only")
        known_milestones.add(p.stem)

    # PT-39 (ruling § 3 item 3, milestones half): same widening as
    # known_majors above, and the same reason -- archive_milestone moves a
    # milestone file into archive/milestones/ without rewriting any of the
    # issues that still name it (its own now-archived issues included),
    # so those refs must keep resolving. `milestone_status_by_id` is built
    # alongside it (live status from parsed_milestones, archived status
    # from this same scan) -- item 2 below is the one check that needs a
    # STATUS, not just a yes/no "does this id exist".
    milestone_status_by_id: Dict[str, Any] = {p.stem: fm.get("status") for p, fm in parsed_milestones}
    # PT-41 (architect's review finding #3): archived ga:true milestones
    # count toward their major's "at most one GA" cap too -- populated in
    # THIS SAME archive/milestones scan (not a second one -- the standing
    # duplicated-directory-read rule) alongside the two things PT-39/PT-46
    # already collect here. The live half is added to this dict further
    # down, once parsed_milestones' own loop runs.
    ga_milestones_by_major: Dict[str, List[str]] = {}
    # PT-47: which ga_milestones_by_major entries came from THIS (archived)
    # scan vs. the live one further down -- collected here, not a second
    # directory read, so the cap error below can mark siblings instead of
    # rendering an unlabeled stem list a reader has to go re-derive by hand.
    ga_milestones_archived: Set[str] = set()
    for p in _dir_glob(data_dir / "archive" / "milestones"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        known_milestones.add(p.stem)
        milestone_status_by_id[p.stem] = fm.get("status")
        # PT-46 (architect's Pass-2 finding): the same archive-location-
        # specific done/cancelled requirement as the majors loop above --
        # the hand-`git mv` bypass, milestone half.
        _check_archived_record_status(errors, p.stem, fm.get("status"))
        if fm.get("ga") is True:
            major_id = str(fm.get("major"))
            if major_id in known_majors:
                ga_milestones_by_major.setdefault(major_id, []).append(p.stem)
                ga_milestones_archived.add(p.stem)

    for p, fm in parsed_milestones:
        major = fm.get("major")
        if major is None:
            errors.append(f"{p.stem}: missing major")
        elif str(major) not in known_majors:
            errors.append(f"{p.stem}: unknown major {major!r}")

        # PT-39 (architect's ruling § 3 item 1): NEW enforcement -- a
        # milestone's status: must be present and in RECORD_STATUSES.
        # Same check as the major loop above -- routed through the one
        # shared helper (_check_record_status) rather than a second
        # inline copy of the condition (standing duplicated-inline-
        # expression rule: this exact "missing or invalid status" shape
        # would otherwise exist twice, one per schema, and could drift).
        _check_record_status(errors, p.stem, fm.get("status"))

        # PT-27/PT-28: milestone id-shape <-> kind agreement, now against
        # the PREFIXED shapes (definition_re/development_re, built above --
        # `V` joined `M` as a reserved definition letter, architect's
        # ruling § 1). The filename stem is authoritative (id/filename
        # mismatch is its own check above), so the shape check runs
        # against p.stem rather than the raw fm["id"]. Skipped entirely
        # when the prefix didn't validate (definition_re is None) -- there
        # is no safe shape to check against.
        stem = p.stem
        kind = fm.get("kind")
        if kind not in MILESTONE_KINDS:
            errors.append(
                f"{stem}: missing or invalid kind {kind!r} -- expected 'product' or 'process'"
            )
        elif definition_re is not None and development_re is not None:
            is_definition_shape = bool(definition_re.match(stem))
            is_development_shape = bool(development_re.match(stem))
            if not is_definition_shape and not is_development_shape:
                errors.append(
                    f"{stem}: unrecognised milestone id {stem!r} -- expected {prefix}-<letter> "
                    f"(e.g. {prefix}-A) for kind: process, or {prefix}-<version> / {prefix}-M<n> "
                    f"for kind: product{_migrate_hint_if_bare(stem, prefix)}"
                )
            elif kind == "process" and not is_definition_shape:
                errors.append(
                    f"{stem}: id shape {stem!r} is a development milestone but kind is 'process' -- "
                    f"definition milestones use letter ids ({prefix}-A, {prefix}-B, {prefix}-C...); "
                    f"rename the file and its id, then retarget its issues, or set kind: product"
                )
            elif kind == "product" and not is_development_shape:
                errors.append(
                    f"{stem}: id shape {stem!r} is a definition milestone but kind is 'product' -- "
                    f"development milestones use a version id ({prefix}-1.0) or {prefix}-M<n>"
                )

    # PT-41 (architect's Option A ruling, refined by their PT-41 review):
    # binds "V<n> means the line that culminates in v<n>.0.0" to the DATA
    # rather than leaving it as prose nobody enforces. Two riders, both
    # scoped PER MAJOR (two different major lines each designating their
    # own GA milestone is the normal concurrent-majors shape, not a
    # conflict):
    #
    #   1. At most one ga: true milestone per major -- counting an
    #      ARCHIVED ga:true milestone too (review finding #3): a shipped
    #      GA milestone that got archived is still that major's GA;
    #      ignoring it would let a second one be silently designated.
    #      Scoped only to milestones whose major ref actually RESOLVES
    #      (a dangling ref already produces "unknown major" elsewhere --
    #      not counted here, one broken field, one error).
    #   2. A LIVE ga: true milestone's target_tag must be EXACTLY
    #      v<N>.0.0 for its own major's N (a v1.1.0/v1.0.1/null
    #      target_tag all fail this). Also skipped for a dangling major
    #      ref (review finding #1) -- and N is derived only once
    #      major_re (this repo's configured-prefix shape, review finding
    #      #2) confirms the major id actually matches it, never from a
    #      prefix-agnostic literal. Not re-run on an ALREADY-ARCHIVED
    #      milestone -- same "don't re-validate archived files" posture
    #      PT-39 §3 item 1 already established (it passed this check at
    #      the moment it was archived; archive_milestone moves files
    #      verbatim, never rewriting frontmatter).
    #
    # ZERO ga: true milestones for a major is explicitly NOT an error --
    # a young major legitimately hasn't designated its GA milestone yet
    # (this repo's own PT-V1, today). The ARCHIVED half of
    # ga_milestones_by_major was already collected above, in the same
    # archive/milestones scan PT-39/PT-46 already read this directory
    # for -- this loop adds the LIVE half.
    for p, fm in parsed_milestones:
        if fm.get("ga") is True:
            major_id = str(fm.get("major"))
            if major_id in known_majors:
                ga_milestones_by_major.setdefault(major_id, []).append(p.stem)
    for major_id, ga_stems in ga_milestones_by_major.items():
        if len(ga_stems) > 1:
            # PT-47: mark archived siblings inline -- an unlabeled stem
            # list left a reader guessing which sibling was the (legit,
            # shipped) archived GA and which one is the actual conflict.
            sibling_list = ", ".join(
                f"{stem} (archived)" if stem in ga_milestones_archived else stem
                for stem in sorted(ga_stems)
            )
            for stem in ga_stems:
                errors.append(
                    f"{stem}: more than one ga: true milestone under major {major_id!r} "
                    f"({sibling_list}) -- exactly one GA milestone per major"
                )
    for p, fm in parsed_milestones:
        if fm.get("ga") is not True:
            continue
        major_id = str(fm.get("major"))
        if major_id not in known_majors:
            continue  # dangling major ref -- already reported above, not this rider's job
        expected_tag = _ga_target_tag_for_major(major_id, major_re)
        if expected_tag is None:
            continue  # major id doesn't match this repo's configured shape -- already reported elsewhere
        if fm.get("target_tag") != expected_tag:
            errors.append(
                f"{p.stem}: ga: true milestone's target_tag {fm.get('target_tag')!r} must be "
                f"{expected_tag!r} for major {major_id!r} (V<N> means the line that culminates in v<N>.0.0)"
            )

    known_ids = set()
    parsed_issues: List[Tuple[Path, Dict[str, Any]]] = []
    for p in list(_dir_glob(data_dir / "issues")) + archived_issue_paths(data_dir):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            errors.append(f"{p.stem}: {e}")
            continue
        parsed_issues.append((p, fm))
        issue_id = fm.get("id")
        if issue_id == p.stem:
            known_ids.add(issue_id)
            # PT-28: NEW enforcement -- pre-PT-28, check_repo only ever
            # checked id == filename for issues, never the shape itself.
            if issue_re is not None and not issue_re.match(p.stem):
                errors.append(
                    f"{p.stem}: issue id shape {p.stem!r} does not match {issue_re.pattern!r} "
                    f"(configured prefix {prefix!r}){_migrate_hint_if_bare(p.stem, prefix)}"
                )
        else:
            errors.append(f"{p.stem}: id {issue_id!r} does not match filename {p.stem!r}")

    for p, fm in parsed_issues:
        label = p.stem
        if fm.get("title") is None:
            errors.append(f"{label}: missing title")
        status = fm.get("status")
        if status is not None and status not in STATUSES:
            errors.append(f"{label}: unknown status {status!r}")
        milestone = fm.get("milestone")
        if milestone is not None and str(milestone) not in known_milestones:
            errors.append(f"{label}: unknown milestone {milestone!r}")
        # PT-39 (architect's ruling § 3 item 2): the hand-`git mv` bypass
        # catch. `cairn archive --milestone` refuses unless the milestone
        # AND every issue under it are done/cancelled (test_archive_records
        # pins that precondition) -- but nothing stops a human from
        # `git mv`-ing ONE issue into archive/ directly, skipping the
        # precondition entirely. Scoped to issues actually living in
        # archive/ (is_archived_path) -- a LIVE issue under an
        # in-progress milestone is the normal, expected shape of every
        # unfinished milestone and must never trip this. Only fires once
        # the milestone ref has already resolved (str(milestone) in
        # known_milestones) -- a genuinely dangling ref is the check
        # above's job alone, not a second, confusing error on the same ref.
        if (
            is_archived_path(data_dir, p)
            and milestone is not None
            and str(milestone) in known_milestones
        ):
            ms_status = milestone_status_by_id.get(str(milestone))
            if ms_status not in ("done", "cancelled"):
                errors.append(
                    f"{label}: archived issue's milestone {milestone!r} is not done/cancelled "
                    f"(status: {ms_status!r}) -- looks like it was moved into archive/ by hand, "
                    f"bypassing `cairn archive`'s precondition"
                )
        parent = fm.get("parent")
        if parent is not None and parent not in known_ids:
            errors.append(f"{label}: dangling parent {parent!r}")
        priority = fm.get("priority")
        if priority is not None and priority not in PRIORITIES:
            errors.append(f"{label}: unknown priority {priority!r}")
        # PT-26: blocked_by dangling reference + self-reference. Same terse
        # vocabulary as the dangling-parent check above (architect's
        # ruling #2) -- a self-reference gets its OWN message, never
        # folded into the cycle detector's verbose treatment below, so a
        # 1-node self-loop is reported once, here, not twice.
        for ref in fm.get("blocked_by") or []:
            issue_id = fm.get("id")
            if ref == issue_id:
                errors.append(f"{label}: blocked_by contains itself")
            elif ref not in known_ids:
                errors.append(f"{label}: dangling blocked_by {ref!r}")

    # PT-26: dependency cycles. The graph excludes self-edges (already
    # reported above, on their own) and dangling refs (already reported
    # above; you cannot walk to a node that doesn't exist, and including
    # one here could mask a real cycle behind it or fabricate a false
    # one) -- both anti-double-reporting rules from the architect's ruling.
    id_to_blocked: Dict[str, List[str]] = {}
    for p, fm in parsed_issues:
        issue_id = fm.get("id")
        if issue_id not in known_ids:
            continue  # id/filename mismatch already reported above
        id_to_blocked[issue_id] = [
            ref for ref in (fm.get("blocked_by") or []) if ref != issue_id and ref in known_ids
        ]
    for cycle in _detect_blocked_by_cycles(id_to_blocked):
        path_str = " -> ".join(cycle + [cycle[0]])
        errors.append(
            f"{cycle[0]}: dependency cycle {path_str} -- an issue cannot "
            f"transitively block itself; break the loop by removing one "
            f"blocked_by entry along that path"
        )

    # PT-52 (architect's ruling § 2): the engine no longer reads the
    # legacy flat archive/*.md layout at all -- this scan is the ONLY
    # remaining reader of it, via legacy_archived_issue_paths (its other
    # caller is migrate_archive_issues' source glob; the two must never
    # disagree about what counts as legacy, or this error becomes
    # unactionable). Under PT-50 this meant "lint fails, everything still
    # works"; it now means "the engine cannot see these files" -- the
    # wording below says that, keeps the literal fix command, and warns
    # about the cascade (a legacy file's dangling parent/blocked_by/
    # milestone refs surface as SEPARATE errors elsewhere in this list,
    # which read as unrelated unless this one flags the actual cause).
    # Inserted FIRST, not appended: a root cause read after fifteen
    # cascade symptoms gets read last.
    legacy_archived = legacy_archived_issue_paths(data_dir)
    if legacy_archived:
        errors.insert(
            0,
            f"{len(legacy_archived)} archived issue(s) at the legacy archive/*.md layout are NOT read "
            f"by the engine -- invisible to the board, to id allocation, and to reference resolution "
            f"(dangling-reference errors below may be caused by this). "
            f"fix: scripts/cairn/cairn migrate archive-issues --dry-run   (then re-run without --dry-run)"
        )

    return errors


# --------------------------------------------------------------------------
# PT-28: `cairn migrate prefix-ids` -- one-shot 0.6.1 migration
#
# Architect's finalized ruling + addendum (process/cairn/issues/PT-28.md,
# dbdbb7e § 5, corrected by 4ac505e § A.2). Named migration ("prefix-ids"),
# not a bare "migrate" -- each breaking tracker change gets its own name so
# an invocation in a runbook still means one specific thing a year later.
# --------------------------------------------------------------------------

def _migration_prefix(data_dir: Path) -> str:
    """Read+validate `prefix:` for a migration run. Raises CairnError (hard
    stop, nothing written) on a missing config.yml, a parse failure, or a
    prefix that doesn't match PREFIX_RE -- every rewrite below depends on
    this value, so there is no partial-migration path when it's absent.
    """
    config_path = Path(data_dir) / "config.yml"
    if not config_path.exists():
        raise CairnError(f"no config.yml found at {config_path} -- cannot determine prefix, nothing migrated")
    cfg = parse_yaml_subset(config_path.read_text(encoding="utf-8"))
    raw_prefix = cfg.get("prefix")
    if raw_prefix is None or not PREFIX_RE.match(str(raw_prefix)):
        raise CairnError(
            f"config.yml: prefix {raw_prefix!r} must match {PREFIX_RE.pattern} -- cannot migrate, nothing written"
        )
    return str(raw_prefix)


def migrate_prefix_ids(data_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Run (`dry_run=False`) or preview (`dry_run=True`) the prefix-ids
    migration. Returns a report describing every change made or planned --
    {"prefix": str, "majors": [...], "milestones": [...], "issues": [...]}
    -- which cmd_migrate_prefix_ids renders for both --dry-run and a real
    run (the plan IS the report; there is no second, separately-maintained
    "describe what would happen" path).

    Does NOT gate on `check_repo` first (architect's ruling: that would
    deadlock the exact situation this command exists to resolve -- a repo
    whose lint is already failing on bare ids).

    Idempotency and crash-recovery (addendum § A.2, corrected): phase 1's
    unit of work is keyed on the FILENAME STEM, not the id -- "the old-
    named file is still present" stays true exactly until that file's
    work is finished, which survives a crash between the write and the
    unlink (an id-keyed predicate does not: migrating one file is two
    observable actions, the content-write and the rename, and an id-based
    check can't tell those apart). If the new-named file already exists on
    entry, a prior run wrote it -- it was written atomically, so it is
    complete; do not rewrite it, only unlink the stale old file.

    Phase 2 (issues/) is keyed on VALUE per file: a `milestone:` ref is
    rewritten iff it's non-null and not already prefixed. Idempotent by
    construction.

    Touches exactly three fields across the whole run: `id:`, `major:`,
    `milestone:`. Everything else (target_tag included -- addendum § A.1:
    it is a git tag name, not a cairn id) is carried through byte-for-byte
    via dump_frontmatter's "emit keys actually present" contract.
    """
    data_dir = Path(data_dir)
    prefix = _migration_prefix(data_dir)
    stamp = prefix + "-"
    report: Dict[str, Any] = {"prefix": prefix, "majors": [], "milestones": [], "issues": []}

    for subdir, report_key in (("majors", "majors"), ("milestones", "milestones")):
        dir_path = data_dir / subdir
        for p in _dir_glob(dir_path):
            if p.stem.startswith(stamp):
                continue  # already migrated -- the hyphen-qualified check (§5)
            new_name = f"{stamp}{p.stem}.md"
            new_path = dir_path / new_name
            if new_path.exists():
                # A prior run wrote the new file completely before being
                # interrupted before the unlink -- finish just that, don't
                # re-derive or rewrite content that's already correct.
                report[report_key].append({"old": p.name, "new": new_name, "resumed": True})
                if not dry_run:
                    p.unlink()
                continue
            fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            fm = dict(fm)
            fm["id"] = f"{stamp}{p.stem}"
            if subdir == "milestones":
                major = fm.get("major")
                if major is not None and not str(major).startswith(stamp):
                    fm["major"] = f"{stamp}{major}"
            report[report_key].append({"old": p.name, "new": new_name, "resumed": False})
            if not dry_run:
                # id: (and major:, for a milestone) written together in
                # ONE atomic write to the NEW path -- "new file exists
                # with the right id but a stale major:" must not be a
                # reachable crash state (addendum § A.2).
                _atomic_write(new_path, dump_frontmatter(fm) + body)
                p.unlink()

    # PT-28 fix (found dogfooding the migration against this repo's own
    # fixture tree, see the commit body): archive/ too, not just issues/ --
    # check_repo validates an archived issue's `milestone:` ref exactly the
    # same way it validates a live one (its known_ids/parsed_issues loop
    # reads both directories), so skipping archive/ here would leave any
    # archived issue with a bare ref that lints dangling the moment its
    # milestone file is renamed -- a repo with archived history could never
    # reach a clean post-migration state.
    for p in list(_dir_glob(data_dir / "issues")) + archived_issue_paths(data_dir):
        fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        milestone = fm.get("milestone")
        if milestone is None or str(milestone).startswith(stamp):
            continue  # null refs survive untouched; already-prefixed refs are idempotent no-ops
        new_milestone = f"{stamp}{milestone}"
        report["issues"].append({"file": p.name, "old_milestone": str(milestone), "new_milestone": new_milestone})
        if not dry_run:
            fm = dict(fm)
            fm["milestone"] = new_milestone
            _atomic_write(p, dump_frontmatter(fm) + body)

    return report


def _format_migration_report(report: Dict[str, Any], dry_run: bool) -> str:
    """Human-legible plan/summary for cmd_migrate_prefix_ids -- one line per
    change (or "nothing to do"), loosely worded (INTERFACE.md convention:
    pin content, not exact wording) so it reads sensibly for either mode.
    """
    verb = "would rename" if dry_run else "renamed"
    ref_verb = "would rewrite" if dry_run else "rewrote"
    lines = []
    for key, label in (("majors", "major"), ("milestones", "milestone")):
        for entry in report[key]:
            if entry["resumed"]:
                lines.append(f"{label} {entry['old']} -> {entry['new']} (already written by a prior run, resuming)")
            else:
                lines.append(f"{verb} {label} {entry['old']} -> {entry['new']}")
    for entry in report["issues"]:
        lines.append(
            f"{ref_verb} {entry['file']}: milestone {entry['old_milestone']!r} -> {entry['new_milestone']!r}"
        )
    if not lines:
        return "nothing to do -- every id is already prefixed"
    return "\n".join(lines)


# --------------------------------------------------------------------------
# PT-39: `cairn migrate lifecycle-status` -- unify milestone/major status
# vocabulary onto RECORD_STATUSES.
#
# Architect's ruling (temp/arch-ruling-pt39-lifecycle.md § 2): PT-28's
# named-migration precedent verbatim -- a NAMED migration, not a bare
# "migrate", same reasoning as prefix-ids (an invocation in a runbook
# still means one specific thing a year later).
# --------------------------------------------------------------------------

_LIFECYCLE_STATUS_RENAMES = {"completed": "done", "active": "in-progress"}


def migrate_lifecycle_status(data_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Run (`dry_run=False`) or preview (`dry_run=True`) the
    lifecycle-status migration. Returns a report describing every change
    made or planned -- {"majors": [...], "milestones": [...]} -- which
    cmd_migrate_lifecycle_status renders for both --dry-run and a real
    run (the plan IS the report, same convention as migrate_prefix_ids).

    Rewrites `status:` in majors/*.md and milestones/*.md ONLY -- never
    archive/majors/ or archive/milestones/ (those subdirs don't predate
    PT-39; nothing there could carry the old vocabulary that wasn't
    already caught by a live-tree migration first) and never issues/ or
    archive/ (issues already use STATUSES, untouched by this migration).

    `completed` -> `done`, `active` -> `in-progress`; any other value
    (including an already-migrated one, or a garbage value like "wip")
    is left byte-for-byte untouched -- value-keyed, so idempotent by
    construction with no crash-recovery phase needed (unlike
    migrate_prefix_ids's filename-keyed phase 1, there is no
    old-name/new-name pair here to leave half-renamed).

    Does NOT gate on `check_repo` first (same reasoning as prefix-ids:
    that would deadlock the exact situation this command exists to
    resolve -- a repo whose lint is already failing on the old
    vocabulary). Single-writer rule: rewrites go through
    parse_frontmatter/dump_frontmatter/_atomic_write, the same path
    apply_patch uses -- no second writer.
    """
    data_dir = Path(data_dir)
    report: Dict[str, Any] = {"majors": [], "milestones": []}
    for subdir, report_key in (("majors", "majors"), ("milestones", "milestones")):
        for p in _dir_glob(data_dir / subdir):
            fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            old_status = fm.get("status")
            new_status = _LIFECYCLE_STATUS_RENAMES.get(old_status)
            if new_status is None:
                continue  # not one of the two known old values -- a lint concern, not this command's
            report[report_key].append({"file": p.name, "old_status": old_status, "new_status": new_status})
            if not dry_run:
                fm = dict(fm)
                fm["status"] = new_status
                _atomic_write(p, dump_frontmatter(fm) + body)
    return report


def _format_lifecycle_migration_report(report: Dict[str, Any], dry_run: bool) -> str:
    """Human-legible plan/summary for cmd_migrate_lifecycle_status -- same
    shape as _format_migration_report (INTERFACE.md convention: pin
    content, not exact wording).
    """
    verb = "would rewrite" if dry_run else "rewrote"
    lines = []
    for key, label in (("majors", "major"), ("milestones", "milestone")):
        for entry in report[key]:
            lines.append(
                f"{verb} {label} {entry['file']}: status {entry['old_status']!r} -> {entry['new_status']!r}"
            )
    if not lines:
        return "nothing to do -- every major/milestone already uses the unified vocabulary"
    return "\n".join(lines)


# --------------------------------------------------------------------------
# PT-50: `cairn migrate archive-issues` -- move every legacy flat
# `archive/*.md` issue into `archive/issues/`, matching milestones/majors'
# existing archive/<schema>/ shape and closing the asymmetry PT-39 left
# behind.
#
# Architect's ruling (process/cairn/issues/PT-50.md, § 1): a NAMED
# migration, not a bare "migrate" -- same PT-28 precedent as prefix-ids/
# lifecycle-status (an invocation in a shell history means one specific
# thing forever). Filesystem-only: unlike the other two migrations, this
# one touches zero bytes inside any file, only paths.
# --------------------------------------------------------------------------

def migrate_archive_issues(data_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Run (`dry_run=False`) or preview (`dry_run=True`) the
    archive-issues migration. Returns a report describing every change
    made or planned -- {"issues": [{"old", "new", "resumed"}, ...]} --
    which cmd_migrate_archive_issues renders for both --dry-run and a
    real run (the plan IS the report, same convention as the other two
    migrations).

    Moves every `archive/*.md` file to `archive/issues/<name>` via
    `_git_mv_or_rename`, so git records a rename. Never touches
    `archive/milestones/` or `archive/majors/` -- `legacy_archived_issue_
    paths`'s underlying `_dir_glob` is non-recursive, so those two subdirs
    are invisible to it.

    Does NOT gate on `check_repo` first -- same reasoning as the other
    two migrations: it must run on the repo whose lint it is fixing (the
    legacy-layout error this migration exists to resolve). This
    migration's read path (legacy_archived_issue_paths) is separate from
    the engine's own archived-issue read path (archived_issue_paths, PT-52
    -- archive/issues/ only), so PT-52's deletion cannot break it.

    Idempotency and crash-recovery: keyed on the SOURCE file's presence
    (prefix-ids' filename-keyed precedent) -- "archive/<id>.md exists" is
    the whole unit of work, so a crash before or after a single rename
    always leaves a well-defined next state. If the destination already
    exists on entry (a prior run wrote it and crashed before unlinking
    the source): byte-identical content means the prior run completed
    that file's work -- report `resumed: True` and unlink the stale
    source, never re-copy. Differing content means a human put a
    genuinely different file at the destination; a rename can never
    produce that on its own, so this command has no basis to pick a
    winner and REFUSES THE ENTIRE RUN, naming the offending file, moving
    nothing (archive_major's two-phase all-or-nothing precedent: the
    whole set is validated -- reads only -- before any file moves).
    """
    data_dir = Path(data_dir)
    archive_dir = data_dir / "archive"
    archive_issues_dir = archive_dir / "issues"
    # PT-52: routed through legacy_archived_issue_paths -- its ONLY other
    # caller is check_repo's lint scan, deliberately, so the two can never
    # disagree about what counts as legacy (§2).
    sources = legacy_archived_issue_paths(data_dir)

    # Phase 1 (reads only): validate the WHOLE set before moving anything.
    plan: List[Dict[str, Any]] = []
    for p in sources:
        dest = archive_issues_dir / p.name
        if dest.exists():
            if dest.read_bytes() == p.read_bytes():
                plan.append({"old": p.name, "new": dest.name, "resumed": True, "_src": p, "_dest": dest})
            else:
                raise CairnError(
                    f"{p.name}: already exists at archive/issues/{p.name} with different content -- "
                    f"refusing to overwrite; nothing moved"
                )
        else:
            plan.append({"old": p.name, "new": dest.name, "resumed": False, "_src": p, "_dest": dest})

    report: Dict[str, Any] = {
        "issues": [{"old": e["old"], "new": e["new"], "resumed": e["resumed"]} for e in plan]
    }
    if dry_run:
        return report

    # Phase 2: every entry validated above -- now safe to move files.
    if plan:
        archive_issues_dir.mkdir(parents=True, exist_ok=True)
    for e in plan:
        if e["resumed"]:
            e["_src"].unlink()
        else:
            _git_mv_or_rename(e["_src"], e["_dest"])
    return report


def _format_archive_issues_migration_report(report: Dict[str, Any], dry_run: bool) -> str:
    """Human-legible plan/summary for cmd_migrate_archive_issues -- same
    shape as the other two migrations' formatters (INTERFACE.md
    convention: pin content, not exact wording).
    """
    verb = "would move" if dry_run else "moved"
    lines = []
    for entry in report["issues"]:
        if entry["resumed"]:
            lines.append(
                f"issue {entry['old']} -> archive/issues/{entry['new']} (already written by a prior run, resuming)"
            )
        else:
            lines.append(f"{verb} issue {entry['old']} -> archive/issues/{entry['new']}")
    if not lines:
        return "nothing to do -- no archived issues at the legacy archive/*.md layout"
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------

_ID_SORT_RE = re.compile(r"^(.*?)-(\d+)$")


def _id_sort_key(issue_id: Any) -> Tuple[str, int, str]:
    """Numeric-aware sort key for an issue id ("PT-2" < "PT-9" < "PT-10").

    `_dir_glob`'s filename order is lexicographic ("PT-10" sorts before
    "PT-2") -- wrong once a tracker passes 10 issues (QA's PT-2 finding;
    also a latent, out-of-scope bug in `cmd_ls` today). Falls back to a
    pure string key for anything that doesn't match the "<prefix>-<digits>"
    shape, so a malformed id still sorts (just not meaningfully) instead of
    raising.
    """
    s = str(issue_id or "")
    m = _ID_SORT_RE.match(s)
    if m:
        return (m.group(1), int(m.group(2)), s)
    return (s, -1, s)


def _rotate_cycle_to_canonical(cycle: List[str]) -> List[str]:
    """Rotate `cycle` (a list of ids in edge order) so the `_id_sort_key`-
    smallest id leads -- the canonical form for deduping "the same cycle,
    discovered from a different entry point" down to one reported error
    (PT-26). A rotation, never a re-sort: the edge order within the cycle
    is preserved, only the starting point moves.
    """
    smallest_idx = min(range(len(cycle)), key=lambda i: _id_sort_key(cycle[i]))
    return cycle[smallest_idx:] + cycle[:smallest_idx]


def _detect_blocked_by_cycles(id_to_blocked: Dict[str, List[str]]) -> List[List[str]]:
    """Iterative three-colour (white/grey/black) DFS over the blocked_by
    graph. Returns one path per distinct cycle (each on its canonical
    rotation, deduped), in the order discovered.

    Iterative, not recursive, because `check_repo` must never raise on
    user data -- a long enough dependency chain would blow the recursion
    limit. A plain visited set is not enough: it cannot distinguish
    "already fully explored" from "on the current path", and reports a
    false cycle on any reconvergent DAG (two nodes both blocked_by a third,
    unrelated, common ancestor). Grey (on the current path) is the only
    color a real back-edge can land on.

    Callers must pre-filter self-edges and dangling refs out of
    `id_to_blocked` -- this function assumes every edge target is itself a
    key in `id_to_blocked`. Walks roots in `_id_sort_key` order and, within
    each node, neighbours in `blocked_by` order (a plain dict/list walk,
    already in file order) -- deterministic output regardless of
    filesystem iteration order.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in id_to_blocked}
    cycles: List[List[str]] = []
    seen_rotations = set()

    for root in sorted(id_to_blocked, key=_id_sort_key):
        if color[root] != WHITE:
            continue
        color[root] = GREY
        path = [root]
        stack = [iter(id_to_blocked[root])]
        while stack:
            try:
                nxt = next(stack[-1])
            except StopIteration:
                finished = path.pop()
                color[finished] = BLACK
                stack.pop()
                continue
            if color[nxt] == WHITE:
                color[nxt] = GREY
                path.append(nxt)
                stack.append(iter(id_to_blocked[nxt]))
            elif color[nxt] == GREY:
                # Back-edge to a node on the current path -- the slice from
                # its first occurrence to here is the cycle.
                idx = path.index(nxt)
                rotated = _rotate_cycle_to_canonical(path[idx:])
                key = tuple(rotated)
                if key not in seen_rotations:
                    seen_rotations.add(key)
                    cycles.append(rotated)
            # BLACK: already fully explored via another path -- no new info.
    return cycles


def build_snapshot_markdown(data_dir: Path, generated_at: Optional[str] = None) -> str:
    """Render a point-in-time markdown view of the tracker: majors, then
    milestones (roadmap), then issues grouped by status (`DEFAULT_COLUMNS`
    order + "cancelled" last) and sorted numerically by id within each
    group. Meant for `cairn snapshot >> process/STATE.md` (TRACKER.md --
    "Relationship to STATE.md").

    A RENDERING only -- never parsed back by cairn. The output deliberately
    never opens with "---" (`parse_frontmatter`'s fence) so it can't be
    mistaken for tracker data even if misplaced under issues/, milestones/,
    or majors/ -- `check_repo` reports (not silently ingests) a misplaced
    copy as a per-file parse error, same as any other malformed file.

    `generated_at` is injectable so callers (tests; a future `--as-of`) get
    determinism without wall-clock noise -- `cmd_snapshot` sources a real
    timestamp when it's None. Everything else is a pure function of
    `data_dir`'s contents, independent of filesystem scan order (majors/
    milestones sorted by id; issues grouped/sorted as above) -- two
    snapshots of an unchanged tree, given the same `generated_at`, are
    byte-identical, so appended snapshots diff cleanly.

    Per-file parse errors are skipped, not raised (mirrors `check_repo`) --
    one broken file shouldn't crash the whole rendering.
    """
    data_dir = Path(data_dir)
    if generated_at is None:
        generated_at = datetime.datetime.now().isoformat()

    majors: List[Dict[str, Any]] = []
    for p in _dir_glob(data_dir / "majors"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        majors.append(fm)
    majors.sort(key=lambda fm: str(fm.get("id", "")))

    milestones: List[Dict[str, Any]] = []
    for p in _dir_glob(data_dir / "milestones"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        milestones.append(fm)
    milestones.sort(key=lambda fm: str(fm.get("id", "")))

    issues: List[Dict[str, Any]] = []
    for p in _dir_glob(data_dir / "issues"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        issues.append(fm)

    lines: List[str] = []
    lines.append(f"<!-- cairn snapshot -- generated {generated_at}. Do not edit; regenerate with `cairn snapshot`. -->")
    lines.append("")
    lines.append(f"## cairn snapshot ({generated_at})")
    lines.append("")
    lines.append(
        "_Generated by `cairn snapshot` -- a point-in-time rendering, "
        "never re-parsed by cairn. Do not hand-edit; regenerate instead._"
    )
    lines.append("")

    lines.append("### Majors")
    lines.append("")
    if majors:
        for m in majors:
            lines.append(
                f"- **{m.get('id')}** — status: {m.get('status')}, "
                f"owner: {m.get('owner') or '-'}, health: {m.get('health') or '-'}"
            )
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("### Roadmap")
    lines.append("")
    if milestones:
        for m in milestones:
            extras = []
            if m.get("target_tag"):
                extras.append(str(m["target_tag"]))
            if m.get("ga"):
                extras.append("GA")
            suffix = f" ({', '.join(extras)})" if extras else ""
            lines.append(
                f"- **{m.get('id')}** — {m.get('name') or '-'} "
                f"(major {m.get('major') or '-'}, {m.get('status')}){suffix}"
            )
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("### Issues")
    lines.append("")
    status_order = list(STATUS_ORDER)
    if issues:
        for status in status_order:
            group = sorted(
                (i for i in issues if i.get("status") == status),
                key=lambda fm: _id_sort_key(fm.get("id")),
            )
            if not group:
                continue
            lines.append(f"#### {status}")
            lines.append("")
            for i in group:
                milestone = i.get("milestone") or "-"
                assignee = i.get("assignee") or "-"
                lines.append(
                    f"- **{i.get('id')}** — {i.get('title')} "
                    f"(milestone: {milestone}, assignee: {assignee})"
                )
            lines.append("")
        known = set(status_order)
        leftover = sorted(
            (i for i in issues if i.get("status") not in known),
            key=lambda fm: _id_sort_key(fm.get("id")),
        )
        if leftover:
            lines.append("#### (other)")
            lines.append("")
            for i in leftover:
                lines.append(f"- **{i.get('id')}** — {i.get('title')}")
            lines.append("")
    else:
        lines.append("_None._")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------
# Board API payloads
# --------------------------------------------------------------------------

def read_git_tags(data_dir: Path) -> Tuple[Optional[Set[str]], Optional[str]]:
    """PT-44 (joint ruling § 4): the release-state source of truth. Reads
    the local tag set via `git -C <data_dir> for-each-ref --format=
    %(refname:short) refs/tags` -- measured 8ms, called once per
    `build_board_payload` call (once per root, matching "once per payload
    build"). `-C data_dir` still finds the repo root by walking up from
    `data_dir` (same as any git invocation from a subdirectory) -- reads
    no file outside `process/cairn/` directly (the subprocess's own
    internal `.git` reads are not this engine touching a file, same
    reasoning `_git_mv_or_rename` already relies on for the spin-off
    constraint).

    Returns `(tag_set, None)` on success, `(None, "<warning>")` when git
    is missing or `data_dir` isn't inside a git working tree -- NEVER
    raises (the `_git_mv_or_rename` precedent: fall back, don't crash).
    Callers print the warning themselves (this function has no stderr
    side effect of its own -- matches resolve_board_columns/
    resolve_board_swimlane's "return the warning as data" convention).
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", str(data_dir), "for-each-ref", "--format=%(refname:short)", "refs/tags"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, OSError) as e:
        return None, f"git unavailable ({e}) -- every milestone's released will be null"
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return None, f"git tag read failed ({detail}) -- every milestone's released will be null"
    tags = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return tags, None


def _release_status(target_tag: Optional[str], tag_set: Optional[Set[str]]) -> Optional[bool]:
    """Whether `target_tag` has shipped, per `tag_set` (PT-44 §4's
    formula) -- extracted so `build_board_payload`'s milestone loop and
    `build_record_payload` (PT-51, the POST /api/record/<id> response)
    compute it identically, one derivation rather than two copies that
    could drift. `None` when there's nothing to check: no `target_tag`
    (a definition milestone) or `tag_set` itself is `None` (a git read
    failure -- degrades to "unknown", never a false `False`).
    """
    if target_tag is None or tag_set is None:
        return None
    return target_tag in tag_set


_SEMVER_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _latest_semver_tag(tags: Optional[Set[str]]) -> Optional[str]:
    """The highest-semver tag in a tag SET (`read_git_tags`'s return type
    carries no ordering or dates to sort by) -- WORKFLOW.md's "strict
    semver" convention is what makes "latest" well-defined at all. A
    non-conforming tag sorts lowest (never raises), so one stray
    non-release tag can't take down the whole /api/dashboard payload.
    `None`/empty input -> `None`, never a crash.

    PT-54 (architect's diff-review fix, blocking): a pre-release suffix
    (`-alpha`/`-beta`/`-rc*`, all three prescribed by WORKFLOW.md) must
    rank BELOW its own final release -- `(major, minor, patch)` alone
    ties `v1.0.0` and `v1.0.0-rc1`, and the string tiebreak that followed
    put the rc ahead (`'v1.0.0-rc1' > 'v1.0.0'` lexicographically),
    which is backwards per semver §11 and silently wrong the first time
    this project's own rc-tag procedure is followed: the Release card
    would show the rc as latest, then the tracker/git join returns null
    (the shipped milestone's `target_tag` is the FINAL tag, never the
    rc). `is_release` (1 for a bare `vX.Y.Z`, 0 for anything with a
    `-`-prefixed suffix after it) breaks that tie explicitly.
    """
    if not tags:
        return None

    def _key(tag: str) -> Tuple[int, int, int, int, str]:
        m = _SEMVER_TAG_RE.match(tag)
        if not m:
            return (-1, -1, -1, -1, tag)
        rest = tag[m.end():]
        is_release = 0 if rest.startswith("-") else 1  # 1.0.0-rc.1 < 1.0.0
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), is_release, tag)

    return max(tags, key=_key)


def read_git_state(data_dir: Path) -> Dict[str, Any]:
    """PT-54 (architect ruling §4): the `/api/dashboard` "git" group --
    `{branch, dirty, head, latest_tag, warning}`. Same `-C data_dir, walk
    up to find the repo, never raise` contract as `read_git_tags`/
    `_git_mv_or_rename`; reuses `read_git_tags` for the tag set rather
    than a fourth subprocess call, per the ruling.

    A single failure anywhere in this group (git missing, or `data_dir`
    not inside a worktree) degrades the WHOLE group to `None` fields plus
    a warning -- never a partially-populated dict that could look more
    trustworthy than it is. `dirty` is `None` (not `False`) when the
    `status --porcelain` read itself failed, so "no changes" and "we
    don't know" stay distinguishable.
    """
    import subprocess

    def _run(*args: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(data_dir), *args],
                capture_output=True, text=True, timeout=5,
            )
        except (FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    branch = _run("rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return {
            "branch": None,
            "dirty": None,
            "head": None,
            "latest_tag": None,
            "warning": "git unavailable or not a worktree -- every dashboard git field is null",
        }

    head = _run("rev-parse", "--short", "HEAD")
    # --untracked-files=no: "dirty" means uncommitted changes to TRACKED
    # files -- an untracked issue/milestone file sitting in the tree (the
    # routine, expected state of a repo mid-`cairn new`) must not read as
    # a dirty working tree.
    status_out = _run("status", "--porcelain", "--untracked-files=no")
    dirty = None if status_out is None else bool(status_out)
    tag_set, tags_warning = read_git_tags(data_dir)

    return {
        "branch": branch,
        "dirty": dirty,
        "head": head,
        "latest_tag": _latest_semver_tag(tag_set),
        "warning": tags_warning,
    }


def _find_release_milestone(data_dir: Path, target_tag: str) -> Optional[Dict[str, Any]]:
    """The milestone whose `target_tag` matches, for `build_dashboard_payload`'s
    release join -- searches BOTH live and archived milestones. A small,
    targeted glob + frontmatter read (two dirs, non-recursive), not a
    second full `/api/board` parse: this template's own workflow archives
    a milestone shortly after its tag ships, so a live-only search would
    make a shipped release invisible almost immediately. `None` if
    nothing matches.
    """
    data_dir = Path(data_dir)
    for p in _dir_glob(data_dir / "milestones") + _dir_glob(data_dir / "archive" / "milestones"):
        fm = _read_frontmatter_dict(p)
        if fm.get("target_tag") == target_tag:
            return fm
    return None


def build_dashboard_payload(data_dir: Path) -> Dict[str, Any]:
    """`GET /api/dashboard`'s payload (PT-54) -- assembled server-side
    only, for the PRIMARY root's `data_dir` (git state is inherently
    single-repo; there is no multi-root "current branch"). Four
    independent groups, one honest join:

    - `git`: `read_git_state(data_dir)` -- branch/dirty/head/latest_tag,
      never raises.
    - `tracker`: issue counts BY THE SAME parse path `/api/board` uses --
      `build_board_payload(data_dir)`'s own `issues` list, tallied by
      `status`. Never a second parser over the same files (architect's
      ruling §4).
    - `check`: `check_repo(data_dir)`'s lint result, `{ok, errors}`.
    - `release`: the join the ruling's §4 spells out explicitly -- latest
      tag -> the milestone whose `target_tag` matches it -> that
      milestone's `id`/`name`/`status`/`ga`. Deliberately NOT parsed from
      STATE.md: that would read a file outside `process/cairn/` (breaking
      the same engine constraint `read_git_tags` protects) and couple the
      server to a human-maintained table. `None` when there's no matching
      milestone (including "no tags at all").

      This lookup searches BOTH live and archived milestones (a small,
      targeted glob -- `_find_release_milestone`, not a second full
      `/api/board` parse): this project's own workflow archives a
      milestone shortly after its tag ships (WORKFLOW.md's archive-on-done
      convention), so a live-only search would make `release` null for
      almost every real shipped tag -- verified against this very repo
      end to end (v0.7.1's milestone is archived). `tracker.
      counts_by_status` stays live-only on purpose (matches what
      `/api/board` shows by default) -- only this lookup widens.
    """
    data_dir = Path(data_dir)
    git_state = read_git_state(data_dir)

    board = build_board_payload(data_dir)
    counts_by_status = {status: 0 for status in STATUS_ORDER}
    for issue in board["issues"]:
        status = issue.get("status")
        if status in counts_by_status:
            counts_by_status[status] += 1

    check_errors = check_repo(data_dir)

    release = None
    latest_tag = git_state["latest_tag"]
    if latest_tag:
        milestone = _find_release_milestone(data_dir, latest_tag)
        if milestone:
            release = {
                "id": milestone.get("id"),
                "name": milestone.get("name"),
                "status": milestone.get("status"),
                "ga": milestone.get("ga"),
            }

    return {
        "git": git_state,
        "tracker": {"counts_by_status": counts_by_status},
        "check": {"ok": check_errors == [], "errors": check_errors},
        "release": release,
        "generated_at": datetime.datetime.now().isoformat(),
    }


# --------------------------------------------------------------------------
# Agent roster (PT-56) -- a SEPARATE composed reader + GET /api/roster,
# deliberately NOT part of build_dashboard_payload/the engine proper.
# `.claude/agents/` and `.claude/roles/` are a template concept, not a
# tracker one -- reading them from inside cairn.py's engine functions would
# cross the same "reads nothing outside process/cairn/ + git" boundary
# read_git_tags's docstring protects, and would survive a cairn spin-off
# incorrectly (the module would ship with cairn; the ruling says it must
# stay with the template instead). Isolated here so an unreadable/missing
# `.claude/` tree degrades the roster panel alone, never the rest of the
# dashboard.
# --------------------------------------------------------------------------

_SENTENCE_END_RE = re.compile(r"^(.*?[.!?])(\s|$)")


def _first_sentence(text: str) -> str:
    """The role line's source text (architect ruling § "Identity"): an
    agent's frontmatter `description` is usually several sentences of
    operating detail (`.claude/agents/*.md` convention) -- the roster
    card only has room for the first one. Falls back to the whole
    (stripped) string if no sentence-ending punctuation is found, rather
    than returning an empty role.
    """
    text = (text or "").strip()
    if not text:
        return ""
    match = _SENTENCE_END_RE.match(text)
    return match.group(1) if match else text


def _repo_root_for(data_dir: Path) -> Path:
    """The repo root `.claude/` lives at -- `git -C data_dir rev-parse
    --show-toplevel`, falling back to `data_dir.parent.parent` (this
    project's own process/cairn -> repo-root convention) when git is
    unavailable or `data_dir` isn't inside a worktree. Same never-raises
    contract as `read_git_tags`: the fallback is a plain Path computation
    that cannot itself fail.
    """
    import subprocess

    data_dir = Path(data_dir)
    try:
        result = subprocess.run(
            ["git", "-C", str(data_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out:
                return Path(out)
    except (FileNotFoundError, OSError):
        pass
    return data_dir.parent.parent


def _read_agent_identities(repo_root: Path) -> List[Dict[str, Any]]:
    """PT-56 (architect ruling § "Identity"): `.claude/agents/*.md`
    (`name`/`description` frontmatter) plus `.claude/roles/team-lead.md`
    -- every clone of this template ships these, so a roster with zero
    live team running still shows every identity (the ruling's "empty
    state is not empty" point). `id` and `name` are both the frontmatter
    `name` value -- this system has no separate "display name" concept.
    Never raises: a missing `.claude/agents/` dir, a missing role file,
    or one malformed agent file among many all degrade quietly (an
    unreadable individual file is skipped, not fatal to the rest).
    """
    repo_root = Path(repo_root)
    identities: List[Dict[str, Any]] = []

    agents_dir = repo_root / ".claude" / "agents"
    if agents_dir.is_dir():
        for p in sorted(agents_dir.glob("*.md")):
            try:
                fm = _read_frontmatter_dict(p)
            except Exception:  # noqa: BLE001 -- one bad file must not blank the roster
                continue
            name = fm.get("name")
            if not name:
                continue
            identities.append({"id": name, "name": name, "role": _first_sentence(fm.get("description"))})

    role_path = repo_root / ".claude" / "roles" / "team-lead.md"
    if role_path.is_file():
        try:
            fm = _read_frontmatter_dict(role_path)
            name = fm.get("name") or "team-lead"
            identities.append({"id": name, "name": name, "role": _first_sentence(fm.get("description"))})
        except Exception:  # noqa: BLE001
            pass

    return identities


_WORKING_STATUSES = ("in-progress", "in-review")


def build_roster_payload(data_dir: Path) -> Dict[str, Any]:
    """`GET /api/roster`'s payload (PT-56) -- architect's presence-source
    ruling in full: identity from `_read_agent_identities` (never
    fabricated), work attribution from the tracker's `assignee` field on
    LIVE issues only (`archive/` excluded -- matches every other
    "live by default" convention in this codebase, PT-42's own
    precedent), presence strictly one of `working`/`idle`/`unknown` --
    never "active"/"online"/"live", which would claim an observation
    this engine cannot make.

    - `working`: assignee of >=1 live issue with status in
      `in-progress`/`in-review` AND that issue's `updated` is today.
    - `idle`: an assignment exists but doesn't qualify as `working`
      right now -- a backlog/todo/done/cancelled assignment, or a
      `working`-shaped one that's gone stale (its `updated` predates
      today). Staleness degrades one-directionally: never silently
      stays `working`.
    - `unknown`: no live issue references this identity at all. This is
      every agent's value on a fresh clone with no live team running --
      the ruling's stated correct output, not a defect.

    `work` carries a human-readable line for the card's "work line" --
    `None` for `unknown` (nothing to report).
    """
    data_dir = Path(data_dir)
    repo_root = _repo_root_for(data_dir)
    identities = _read_agent_identities(repo_root)

    live_issues = [_read_frontmatter_dict(p) for p in _dir_glob(data_dir / "issues")]
    today = _today()

    agents: List[Dict[str, Any]] = []
    for identity in identities:
        agent_id = identity["id"]
        assigned = [issue for issue in live_issues if issue.get("assignee") == agent_id]

        presence = "unknown"
        work: Optional[str] = None
        stale_since: Optional[str] = None
        if assigned:
            presence = "idle"
            working_issue = next(
                (i for i in assigned if i.get("status") in _WORKING_STATUSES and i.get("updated") == today),
                None,
            )
            if working_issue is not None:
                presence = "working"
                work = f"{working_issue.get('id')}: {working_issue.get('title')}"
            else:
                stale = next((i for i in assigned if i.get("status") in _WORKING_STATUSES), None)
                if stale is not None:
                    # PT-56 (architect's explicit follow-up): the staleness
                    # date must be a SURFACED field, not just implied by
                    # `presence == "idle"` -- a UI can't render "last
                    # tracker update 2026-08-01" from the enum value alone.
                    stale_since = stale.get("updated")
                    work = f"{stale.get('id')}: {stale.get('title')} (last tracker update {stale_since})"
                else:
                    other = assigned[0]
                    work = f"{other.get('id')}: {other.get('title')} ({other.get('status')})"

        agents.append({
            "id": agent_id,
            "name": identity["name"],
            "role": identity["role"],
            "presence": presence,
            "work": work,
            "stale_since": stale_since,
        })

    return {"agents": agents}


def build_board_payload(data_dir: Path, archived: bool = False) -> Dict[str, Any]:
    """{"majors": [...], "milestones": [...], "issues": [...]}.

    Board issues carry no "comments" key (spec: "without comment bodies").

    PT-40 (joint PT-40/43/44 ruling § 1): majors/milestones ALSO carry a
    `body` key -- the markdown after the closing frontmatter fence, so the
    client can render a viewable card (name, status, DoD text, ...) with
    NO second fetch/endpoint (`GET /api/milestone/<id>` was considered and
    rejected -- a second read path for data already in this payload).
    Issues are deliberately UNCHANGED: the issue drawer already has its
    own separate body-carrying fetch (`build_issue_payload`/`parse_issue`),
    and this ruling is milestone/major-only.

    PT-42 (architect's ruling § 0/1): `archived=False` (the default) is
    THE IDENTICAL code path that existed before this parameter -- a
    synthetic 1400-issue archive/ tree measured a 28x cost parsing it
    unconditionally, so it is paid only when a caller explicitly asks.
    Every major/milestone/issue ALWAYS carries an `archived` key (never
    absent -- PT-3's no-conditional-payload-shape precedent): `False` for
    every live record regardless of the flag. When `archived=True`, ALSO
    reads archive/ (issues), archive/milestones/, archive/majors/ -- ONE
    archive read path for all three record types via `_dir_glob`, exactly
    like the live dirs -- and every record from those three is stamped
    `archived: True`. Archived issues land in the SAME `issues` list,
    never a parallel array: a second array would need a second counting
    path, degrading PT-31/PT-35's "visible must equal counted" from a
    structural property of one producer to a hand-maintained agreement
    between two.
    """
    data_dir = Path(data_dir)

    # PT-44 (ruling § 4): read once per call (== once per root, once per
    # payload build) -- never crashes (git missing / not a repo -> every
    # milestone's `released` below falls back to None, one stderr line).
    tag_set, git_tags_warning = read_git_tags(data_dir)
    if git_tags_warning:
        print(f"cairn: warning: {git_tags_warning}", file=sys.stderr)

    major_paths = list(_dir_glob(data_dir / "majors"))
    milestone_paths = list(_dir_glob(data_dir / "milestones"))
    issue_paths = list(_dir_glob(data_dir / "issues"))
    if archived:
        major_paths += _dir_glob(data_dir / "archive" / "majors")
        milestone_paths += _dir_glob(data_dir / "archive" / "milestones")
        issue_paths += archived_issue_paths(data_dir)  # PT-52: archive/issues/ only

    def _stamped(p: Path) -> Dict[str, Any]:
        fm = dict(_read_frontmatter_dict(p))
        # is_archived_path (PT-42's pre-PR extraction) is True for all
        # three archive shapes (archive/<id>.md, archive/milestones/
        # <id>.md, archive/majors/<id>.md) and none of the three live
        # shapes -- one derivation, not a per-record-type branch.
        fm["archived"] = is_archived_path(data_dir, p)
        return fm

    def _stamped_with_body(p: Path, include_released: bool = False) -> Dict[str, Any]:
        # PT-40 § 1: majors/milestones only -- reads via parse_frontmatter
        # (not _stamped's _read_frontmatter_dict) so the body half of its
        # (frontmatter, body) return isn't discarded. `body.strip() == ""`
        # for a record with no text after the fence is a real, present
        # empty string, never a missing key (PT-3 no-conditional-shape
        # precedent, same posture `archived` already gets on every record).
        fm, raw_body = parse_frontmatter(p.read_text(encoding="utf-8"))
        fm = dict(fm)
        fm["archived"] = is_archived_path(data_dir, p)
        # PT-51 §2: `body` becomes the PRE-`## Comments` half, via the
        # SAME split_comments issues already use -- one parser, not a
        # second body-vs-comments convention. For every record that
        # exists today (none has a Comments section yet) this is
        # byte-identical to the old `body` value: split_comments returns
        # `(body, [])` verbatim when there's no heading to split on.
        pre_comments_body, comments = split_comments(raw_body)
        fm["body"] = pre_comments_body
        fm["comments"] = comments
        # PT-51 §2: `seen` -- exactly `get_seen(p)`, the same mtime token
        # the issue loop below already stamps, so a record's inline
        # editors/comment box has a real seen to send back on write.
        fm["seen"] = get_seen(p)
        # PT-40 § 5: the card's file-path line, same contract as an
        # issue's own "path" (PT-10) -- the record's real on-disk path,
        # correct for an archived major/milestone too.
        fm["path"] = str(p)
        # PT-44 § 4: `released` is a MILESTONE-only key -- majors have no
        # `target_tag` in their schema at all, so `include_released` is
        # False for them and the key is never added (not even as `None`;
        # a key present-but-always-null on a schema it doesn't apply to
        # would be its own kind of confusing "always false-ish" signal).
        if include_released:
            fm["released"] = _release_status(fm.get("target_tag"), tag_set)
        return fm

    majors = [_stamped_with_body(p) for p in major_paths]
    milestones = [_stamped_with_body(p, include_released=True) for p in milestone_paths]

    # PT-25: no server-side child count -- the board's n/m badge is
    # computed client-side (board-logic.js's childProgress), mirroring
    # milestoneProgress. /api/board already carries every issue's `parent`
    # and `status`, which is everything that needs; a second, server-side
    # answer to "how many children does this have" is exactly the
    # duplicated-expression class the standing Validate criterion exists
    # to catch, so there is one producer, not two.
    issues = []
    for p in issue_paths:
        issue = _stamped(p)
        issue["seen"] = get_seen(p)
        issue["path"] = str(p)  # PT-10: same contract as build_issue_payload's "path"
        issues.append(issue)

    return {"majors": majors, "milestones": milestones, "issues": issues}


def build_issue_payload(data_dir: Path, issue_id: str) -> Optional[Dict[str, Any]]:
    """Frontmatter + description + full comments + seen + path. None if not found.

    `path` (PT-10) is `str(path)` exactly as constructed by find_issue_path
    (data_dir joined with "issues" or "archive" and the filename) — not a
    hardcoded "issues/" guess. This is deliberately *not* normalized to
    absolute or to any fixed root: it inherits whatever relativity/
    absoluteness `data_dir` itself has, so it reads as
    "process/cairn/issues/PT-1.md" when the server is run the documented
    way (relative --data-dir from a repo root) and as a real absolute path
    under any other --data-dir setup — either way it's the file's actual
    on-disk path, correct for an archived issue (archive/) too, which the
    old hardcoded drawer string never was.
    """
    path = find_issue_path(data_dir, issue_id)
    if path is None:
        return None
    issue = parse_issue(path.read_text(encoding="utf-8"))
    issue["seen"] = get_seen(path)
    issue["path"] = str(path)
    # PT-42 (ruling § 5): so the HTTP handler can fold "this issue is
    # archived" into the SAME `read_only` stamp a foreign-root issue
    # already gets (do not invent a second read-only flag) -- the drawer's
    # inline editors already suppress on `read_only`, no client change
    # needed beyond that one flag's computation widening.
    issue["archived"] = is_archived_path(data_dir, path)
    return issue


def build_record_payload(data_dir: Path, record_id: str) -> Optional[Dict[str, Any]]:
    """The milestone/major analog of `build_issue_payload` -- single-file,
    O(1) in the tree size. Backs `POST /api/record/<id>`'s 200/409
    response body (PT-51 §1/§2): "the fresh record payload, same shape as
    the 409's `current`".

    Resolves via `find_record_path`, which ALSO resolves issue ids (it's
    the shared six-subdir resolver PT-39 built for `cairn set`/`cairn
    comment`) -- but the HTTP handler rejects an issue id with `400
    wrong_endpoint` before ever calling this, so in practice this is only
    ever reached for a milestone or major. None if `record_id` resolves
    nowhere at all.

    Same fields `build_board_payload`'s per-record stamping adds (§2):
    `archived`, `body` (the PRE-`## Comments` half via `split_comments`),
    `comments`, `seen`, `path`, and -- milestones only -- `released`
    (`_release_status`, the SAME derivation the board payload's milestone
    loop uses, not a second copy).
    """
    data_dir = Path(data_dir)
    path = find_record_path(data_dir, record_id)
    if path is None:
        return None
    fm, raw_body = parse_frontmatter(path.read_text(encoding="utf-8"))
    fm = dict(fm)
    fm["archived"] = is_archived_path(data_dir, path)
    pre_comments_body, comments = split_comments(raw_body)
    fm["body"] = pre_comments_body
    fm["comments"] = comments
    fm["seen"] = get_seen(path)
    fm["path"] = str(path)
    if _record_schema_for_path(data_dir, path) == "milestone":
        tag_set, git_tags_warning = read_git_tags(data_dir)
        if git_tags_warning:
            print(f"cairn: warning: {git_tags_warning}", file=sys.stderr)
        fm["released"] = _release_status(fm.get("target_tag"), tag_set)
    return fm


def _validate_record_patch(schema: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """PT-51 §3: the record write path's field policy. Returns a 400
    error body (`{"error": "bad_request", "message": ...}`), or `None`
    when `patch` is clean.

    `id`/`kind` are legal CLI fields (`_RECORD_FIELD_ORDER`) but
    deliberately NOT board-editable -- both are simply absent from
    `_RECORD_BOARD_EDITABLE_FIELDS`, not special-cased here; "unknown
    field for the resolved schema" and "id/kind rejected" are the SAME
    check by construction, not two.

    Cross-record invariants (one `ga: true` per major, `target_tag ==
    v<N>.0.0`, `major:` resolves) are explicitly NOT checked here --
    `cairn check` is the backstop, the same posture `cairn set` and
    `blocked_by` already take (a write-path re-implementation of a lint
    rule has nowhere to report a SIBLING record's failure).
    """
    editable = _RECORD_BOARD_EDITABLE_FIELDS[schema]
    for key in patch:
        if key not in editable:
            return {
                "error": "bad_request",
                "message": f"{key!r} is not board-editable for a {schema} -- use `cairn set` instead",
            }
    if "status" in patch and patch["status"] not in RECORD_STATUSES:
        return {
            "error": "bad_request",
            "message": f"invalid status {patch['status']!r} -- expected one of {sorted(RECORD_STATUSES)}",
        }
    if schema == "major" and "health" in patch and patch["health"] not in MAJOR_HEALTH_VALUES:
        return {
            "error": "bad_request",
            "message": f"invalid health {patch['health']!r} -- expected one of {sorted(MAJOR_HEALTH_VALUES)}",
        }
    if schema == "milestone" and "ga" in patch and not isinstance(patch["ga"], bool):
        return {"error": "bad_request", "message": "ga must be a boolean"}
    return None


def compute_etag(data_dir: Path, archived: bool = False) -> str:
    """PT-42 (ruling § 1): folds `archived` into the hash input, and --
    only when it's True -- ALSO hashes the three archive dirs' (path,
    mtime_ns) pairs, mirroring the live-dir loop below. Two representations
    (with/without archive/ data) must never collide on one etag; hashing
    the literal flag first (not just conditionally adding more input)
    means even an archive/ tree that happens to produce the same combined
    mtime-hash as some live tree still can't collide across the two modes.
    """
    data_dir = Path(data_dir)
    hasher = hashlib.sha256()
    hasher.update(f"archived:{archived}\n".encode("utf-8"))
    paths: List[Path] = (
        _dir_glob(data_dir / "majors") + _dir_glob(data_dir / "milestones") + _dir_glob(data_dir / "issues")
    )
    if archived:
        paths += _dir_glob(data_dir / "archive" / "majors")
        paths += _dir_glob(data_dir / "archive" / "milestones")
        paths += archived_issue_paths(data_dir)  # PT-52: archive/issues/ only
    for p in paths:
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        hasher.update(f"{p}:{st.st_mtime_ns}\n".encode("utf-8"))
    return hasher.hexdigest()[:16]


# --------------------------------------------------------------------------
# Multi-root (PT-3): read-only cross-project aggregation for `cairn serve`.
#
# Every single-root function above stays byte-identical. This layer adds a
# thin aggregation on top: `resolve_roots` turns config + an optional CLI
# override into an ordered list of `Root`s (primary always element 0,
# unconditionally trusted; secondaries warn-and-skip on any problem rather
# than raising), `build_multi_board_payload` calls the existing
# `build_board_payload` once per root and stamps `repo` on every record,
# and `compute_multi_etag`/`find_issue_in_roots` are the multi-root
# counterparts of `compute_etag`/`find_issue_path`.
#
# The read-only guarantee is structural, not a check someone has to
# remember: `find_issue_in_roots` is deliberately a separate function from
# `find_issue_path`, and the write handlers (`_create_issue`,
# `_mutate_issue` in `make_server`) close over `data_dir` -- the primary
# root -- only. Nothing in this section is ever reachable from a POST
# handler except the explicit, truthful 403 guard in `_mutate_issue`.
# --------------------------------------------------------------------------

Root = NamedTuple("Root", [("id", str), ("label", str), ("path", Path), ("primary", bool)])


def resolve_roots(
    data_dir: Path,
    config: Dict[str, Any],
    cli_repos: Optional[List[str]] = None,
) -> Tuple[List[Root], List[Dict[str, str]]]:
    """Resolve the primary root plus any configured/CLI secondary roots.

    Returns `(roots, warnings)`. The primary (`data_dir`, already resolved
    and validated upstream by `resolve_data_dir`) is always `roots[0]` and
    is never skipped or warned about -- a broken primary is a hard
    `CairnError` raised before this function is ever called, not a
    warn-and-skip candidate.

    `cli_repos`, when given (not `None`), REPLACES `config["roots"]`
    entirely rather than extending it (team-lead ruling, PT-3 §7-B) --
    "what I typed is what I get". The primary root is included either way.
    `cli_repos=[]` (an explicit empty override) means "no secondaries",
    distinct from `cli_repos=None` (defer to `config["roots"]`).

    Each secondary entry must be a non-empty string. `config["roots"]`
    entries must additionally be relative (not absolute) -- committed,
    portable across clones/machines (§4.1); `cli_repos` entries may be
    absolute (§4.3) -- ad-hoc and uncommitted, so portability doesn't
    apply. It resolves against the repo root (`data_dir.parent.parent`)
    two ways, tried in order: `<entry>/config.yml` (points directly at a
    data dir) or `<entry>/process/cairn/config.yml` (points at a repo
    root, the normal case). Anything else -- missing, unreadable,
    malformed config.yml, or a prefix colliding with an already-loaded
    root -- is skipped with a warning (reason codes: not_found,
    unreadable, bad_config, duplicate, bad_entry), never raised.
    """
    data_dir = Path(data_dir)
    repo_root = data_dir.parent.parent
    primary = Root(
        id=str(config.get("prefix") or "ISS"),
        label=repo_root.name,
        path=data_dir,
        primary=True,
    )
    roots: List[Root] = [primary]
    warnings: List[Dict[str, str]] = []
    seen_ids = {primary.id}

    from_cli = cli_repos is not None
    if from_cli:
        entries: List[Any] = list(cli_repos)
    else:
        raw = config.get("roots")
        entries = raw if isinstance(raw, list) else []

    for entry in entries:
        if not isinstance(entry, str) or not entry:
            warnings.append({
                "root": str(entry), "reason": "bad_entry",
                "detail": "roots entries must be non-empty relative path strings",
            })
            continue
        # §4.3: config.yml's roots: must be relative (committed, portable
        # across clones/machines) -- --repos is ad-hoc/uncommitted, so an
        # absolute path there is fine and deliberately allowed.
        if Path(entry).is_absolute() and not from_cli:
            warnings.append({
                "root": entry, "reason": "bad_entry",
                "detail": "roots entries must be relative to the repo root",
            })
            continue

        candidate = (repo_root / entry).resolve()
        if (candidate / "config.yml").is_file():
            secondary_data_dir = candidate
        elif (candidate / "process" / "cairn" / "config.yml").is_file():
            secondary_data_dir = candidate / "process" / "cairn"
        else:
            warnings.append({"root": entry, "reason": "not_found", "detail": str(candidate)})
            continue

        cfg_path = secondary_data_dir / "config.yml"
        try:
            cfg_text = cfg_path.read_text(encoding="utf-8")
        except OSError as e:
            warnings.append({"root": entry, "reason": "unreadable", "detail": str(e)})
            continue
        try:
            parsed_cfg = parse_yaml_subset(cfg_text)
        except CairnError as e:
            warnings.append({"root": entry, "reason": "bad_config", "detail": str(e)})
            continue

        secondary_id = str(parsed_cfg.get("prefix") or "")
        if not secondary_id or secondary_id in seen_ids:
            warnings.append({"root": entry, "reason": "duplicate", "detail": secondary_id})
            continue

        label = secondary_data_dir.parent.parent.name
        roots.append(Root(id=secondary_id, label=label, path=secondary_data_dir, primary=False))
        seen_ids.add(secondary_id)

    return roots, warnings


def build_multi_board_payload(
    roots: List[Root],
    warnings: List[Dict[str, str]],
    archived: bool = False,
    engine: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate `build_board_payload` across every root, stamping
    `record["repo"] = root.id` on every major/milestone/issue.

    PT-42 (ruling § 1): `archived` threads straight through to every
    per-root `build_board_payload(root.path, archived=archived)` call --
    applied per root, same as everything else this function aggregates.

    A per-root `CairnError` (any file in that root fails to parse) is
    caught here and converted into a `parse_error` warning -- that root
    contributes nothing to the payload, the same warn-and-skip contract
    `resolve_roots` applies one level up, applied to file-level breakage
    inside an otherwise-reachable root.

    `warnings` is the caller's existing list (typically `resolve_roots`'s
    second return value); this function returns a **new** list that
    includes it plus any parse_error entries discovered here -- callers
    must use the returned `payload["warnings"]`, not assume their input
    list was mutated in place.

    PT-38 (ruling § 3): also carries `columns`/`swimlane`, the RESOLVED
    (config-or-default) values -- always present, single-root included (no
    conditional payload shape, the PT-3 precedent). Sourced from
    `load_config(roots[0].path)` ONLY -- the PRIMARY root's config governs;
    a secondary root's own `board.*` config is read (nothing stops a
    secondary root having one) but never reaches this payload. `roots[0]`
    is always the primary by `resolve_roots`'s own contract, so no
    `root.primary` scan is needed here.

    THE stderr print site for an invalid board.columns/board.swimlane
    (ruling § 2's server posture): `resolve_board_columns`/
    `resolve_board_swimlane` only return a warning as data; this function
    -- called fresh on every `/api/board` request, no caching, matching
    this whole module's stateless-lens design -- is where it actually
    reaches stderr, one line per field, naming the offending value.

    PT-49 (ruling § 4): `engine`, when given, is embedded VERBATIM under
    the top-level `engine` key -- `{source_sha, started_at, stale}`,
    per-process (belongs beside `roots`/`warnings`, never on a record,
    never per root). Computing that dict (the boot fingerprint, the §3
    self-check) is the caller's job (`do_GET`'s `/api/board` handler) --
    this function only places it, same posture it already takes with
    `warnings`. `None` (every pre-PT-49 caller/test) omits the key
    entirely rather than a fabricated placeholder.
    """
    all_warnings = list(warnings)
    majors: List[Dict[str, Any]] = []
    milestones: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    primary_config = load_config(roots[0].path) if roots else load_config(Path("."))
    resolved_columns, columns_warning = resolve_board_columns(primary_config)
    resolved_swimlane, swimlane_warning = resolve_board_swimlane(primary_config)
    if columns_warning:
        print(f"cairn: warning: {columns_warning}", file=sys.stderr)
    if swimlane_warning:
        print(f"cairn: warning: {swimlane_warning}", file=sys.stderr)

    for root in roots:
        try:
            payload = build_board_payload(root.path, archived=archived)
        except CairnError as e:
            all_warnings.append({"root": root.id, "reason": "parse_error", "detail": str(e)})
            continue
        for m in payload["majors"]:
            m = dict(m)
            m["repo"] = root.id
            majors.append(m)
        for m in payload["milestones"]:
            m = dict(m)
            m["repo"] = root.id
            milestones.append(m)
        for i in payload["issues"]:
            i = dict(i)
            i["repo"] = root.id
            issues.append(i)

    result = {
        "roots": [{"id": r.id, "label": r.label, "primary": r.primary} for r in roots],
        "warnings": all_warnings,
        "columns": resolved_columns,
        "swimlane": resolved_swimlane,
        "majors": majors,
        "milestones": milestones,
        "issues": issues,
    }
    if engine is not None:
        result["engine"] = engine
    return result


def compute_multi_etag(
    roots: List[Root],
    archived: bool = False,
    boot_sha: Optional[str] = None,
    source_path: Optional[Path] = None,
) -> str:
    """Fold `compute_etag` over every root -- correct with no key-collision
    risk, since `compute_etag` already hashes each file's full path (which
    differs across roots) plus its mtime.

    PT-42 (ruling § 1): `archived` threads through to each per-root
    `compute_etag` call, same as build_multi_board_payload above -- the
    two representations get two etags, never one shared between them.

    PT-49 (ruling § 5, the part that would otherwise silently defeat the
    whole feature): `boot_sha` + the CURRENT `(mtime_ns, size)` of
    `source_path` are folded in ONCE, at the top -- not per root. Without
    this, a stale flip with no data-file change leaves every per-root
    etag unchanged, the client 304s, and the banner never appears. Both
    args default to `None` (opt-in, back-compat with every pre-PT-49
    caller/test): `None` skips the fold entirely rather than hashing a
    literal "None" string, so an omitted engine identity can never
    collide with a real one.
    """
    hasher = hashlib.sha256()
    if boot_sha is not None or source_path is not None:
        hasher.update(f"engine_boot_sha:{boot_sha}\n".encode("utf-8"))
        if source_path is not None:
            try:
                st = Path(source_path).stat()
                hasher.update(f"engine_source:{st.st_mtime_ns}:{st.st_size}\n".encode("utf-8"))
            except OSError:
                hasher.update(b"engine_source:missing\n")
    for root in roots:
        hasher.update(compute_etag(root.path, archived=archived).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()[:16]


def find_issue_in_roots(roots: List[Root], issue_id: str) -> Optional[Root]:
    """The root `issue_id` lives in, or `None`.

    Deliberately a *separate* function from `find_issue_path` -- never
    called from `do_POST` -- so there is no code path from a mutation
    handler to a secondary root's filesystem. That separation is what
    makes read-only structural rather than a check someone has to
    remember (design note §5.1).
    """
    for root in roots:
        if find_issue_path(root.path, issue_id) is not None:
            return root
    return None


def find_record_in_roots(roots: List[Root], record_id: str) -> Optional[Root]:
    """The `find_issue_in_roots` sibling for `POST /api/record/<id>`
    (PT-51 §1 step 1). Same contract, one resolver over: used ONLY to
    tell `403 read_only_root` from a genuine `404` for the HTTP mutation
    handler, NEVER to locate a file to write -- `find_record_path`
    (`data_dir`-scoped, i.e. primary-root-only by construction) stays the
    only resolver `_mutate_record` can reach, exactly like
    `find_issue_path`/`_mutate_issue`.
    """
    for root in roots:
        if find_record_path(root.path, record_id) is not None:
            return root
    return None


# --------------------------------------------------------------------------
# Live push (PT-1): a periodic fs-scan watcher + SSE broadcaster.
#
# Stdlib only, per the boring-stack principle -- no watchdog/inotify dep.
# A background thread os.scandirs the four tracked subdirs on a fixed
# cadence and diffs (relative path, mtime_ns) against the previous scan;
# any difference is one coarse "something changed" event broadcast to
# every subscribed SSE client (never a per-id targeted diff -- deferred,
# see the PT-1 issue file). Purely in-memory: no durable state, killing
# the server drops every subscriber and the watcher with it (stateless
# lens, unchanged).
# --------------------------------------------------------------------------

_WATCHED_SUBDIRS = (
    "majors", "milestones", "issues",
    # PT-39 (architect's ruling § 4): additive -- the two new archive
    # subdirs, else the SSE watcher never notices a milestone/major
    # getting archived. _dir_glob/scan_data_dir already handle a
    # multi-segment subdir string fine (Path / str splits on "/").
    "archive/milestones", "archive/majors",
    # PT-50/PT-52: bare "archive" (issues) deliberately not in this tuple
    # -- archived-issue watching is handled below via archived_issue_paths,
    # the single read site every other archived-issue consumer routes
    # through. No change needed here across the PT-52 deletion: this
    # tuple never carried the legacy leg to begin with.
)


def scan_data_dir(data_dir: Path) -> Dict[str, int]:
    """{"<relative path>": mtime_ns} across majors/milestones/issues/
    archive/{issues,milestones,majors} -- the same directory set
    check_repo and build_board_payload already walk, via the same
    _dir_glob (so mkstemp's hidden ".*.tmp" temp files, which don't match
    "*.md", never show up as a false "change" mid-write). Missing subdirs
    are tolerated, mirroring _dir_glob's "if d.exists() else []".
    """
    data_dir = Path(data_dir)
    snapshot: Dict[str, int] = {}
    for sub in _WATCHED_SUBDIRS:
        for p in _dir_glob(data_dir / sub):
            try:
                snapshot[f"{sub}/{p.name}"] = p.stat().st_mtime_ns
            except FileNotFoundError:
                continue  # raced with a delete between the glob and the stat
    # PT-52: archived issues (archive/issues/ only) -- keys land as
    # "archive/issues/<id>.md", matching the pre-existing "<sub>/<file>.md"
    # key shape above (p is already under data_dir/archive/issues/).
    for p in archived_issue_paths(data_dir):
        try:
            snapshot[str(p.relative_to(data_dir))] = p.stat().st_mtime_ns
        except FileNotFoundError:
            continue  # raced with a delete between the glob and the stat
    return snapshot


def diff_scans(previous: Dict[str, int], current: Dict[str, int]) -> Dict[str, List[str]]:
    """{"created": [...], "changed": [...], "removed": [...]} of relative
    path strings, sorted. `any(diff.values())` is the watcher's cheap
    "did anything happen at all" signal before it bothers broadcasting.
    """
    created = sorted(k for k in current if k not in previous)
    removed = sorted(k for k in previous if k not in current)
    changed = sorted(k for k in current if k in previous and current[k] != previous[k])
    return {"created": created, "changed": changed, "removed": removed}


class _SSEBroadcaster:
    """In-memory registry of connected SSE clients' queues -- no durable
    state, exactly the stateless-lens contract: killing the server drops
    every subscriber with it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List["queue.Queue[Dict[str, Any]]"] = []

    def subscribe(self) -> "queue.Queue[Dict[str, Any]]":
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[Dict[str, Any]]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast(self, event: Dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(event)


class DataDirWatcher:
    """Periodic fs-scan watcher (PT-1). Every `interval` seconds, rescans
    every root in `roots` and diffs the merged scan against the previous
    one; any change gets broadcast as one coarse event to every subscribed
    SSE client (the COARSE event contract, per team-lead's ruling --
    clients refetch the whole board on any event, no per-id targeted
    diff).

    PT-3: takes `roots` (a `List[Root]`), not a bare `data_dir` --
    `scan_data_dir`'s keys ("<sub>/<file>.md") collide across roots (two
    repos can each have a milestones/0.5.md), so each root's scan is
    merged under a `"<root.id>:<sub>/<file>.md"` prefix before diffing.
    Single-root callers pass a one-element `roots` list; the merged-key
    format costs them nothing since there's nothing to collide with.

    Lifecycle is bound to the caller that constructs it (make_server),
    not to `cmd_serve`: the baseline snapshot is taken synchronously in
    __init__, before `start()` -- so a client that connects to the SSE
    endpoint immediately after the server object exists never sees the
    data dir's pre-existing files misreported as freshly "created".
    `stop()` is idempotent and returns promptly (Event.wait, not a sleep
    loop) so server teardown in tests isn't slowed down by it.
    """

    def __init__(self, roots: List[Root], broadcaster: _SSEBroadcaster, interval: float = 1.0) -> None:
        self._roots = roots
        self._broadcaster = broadcaster
        self._interval = interval
        self._stop_event = threading.Event()
        self._snapshot = self._scan_all()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _scan_all(self) -> Dict[str, int]:
        merged: Dict[str, int] = {}
        for root in self._roots:
            for key, mtime in scan_data_dir(root.path).items():
                merged[f"{root.id}:{key}"] = mtime
        return merged

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            current = self._scan_all()
            diff = diff_scans(self._snapshot, current)
            self._snapshot = current
            if any(diff.values()):
                self._broadcaster.broadcast(diff)


# --------------------------------------------------------------------------
# Engine staleness detection (PT-49, architect's ruling in the issue file).
#
# The running Python PROCESS, not the data files it re-reads on every
# request, is the thing that can go stale: `_send_static`/`build_board_
# payload` already re-parse disk on every call, so an upgraded cairn.py
# is invisible to a server that was started before the upgrade landed --
# exactly the "?archived=1 does nothing" bug this closes. Fingerprints
# `cairn.py` ONLY (§1) -- a content hash, not a git hash (§2): git names
# the checked-out commit, not which bytes the running process imported,
# and an uncommitted edit (the actual incident) has no commit at all.
# --------------------------------------------------------------------------

def engine_fingerprint(source_path: Path) -> Dict[str, Any]:
    """`{"sha": sha256(bytes)[:12], "mtime_ns": ..., "size": ...}` for
    `source_path` (§2). Captured ONCE, at server construction
    (`make_server`), and held on the handler closure as the immutable
    "boot" fingerprint every later `engine_is_stale` call compares
    against -- never recomputed mid-process."""
    source_path = Path(source_path)
    data = source_path.read_bytes()
    st = source_path.stat()
    return {"sha": hashlib.sha256(data).hexdigest()[:12], "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def engine_is_stale(source_path: Path, boot: Dict[str, Any]) -> bool:
    """§3's two-tier self-check, run fresh on each `/api/board` build.
    `os.stat` first: `(mtime_ns, size)` equal to `boot` -> not stale, no
    read at all (the common case, one stat). Different -> hash the file
    and compare shas; only a DIFFERING sha is stale -- a `git checkout`
    that touches mtime without changing bytes must never raise a false
    alarm. Source missing/unreadable -> not stale (never invent an
    alarm from a read failure), one stderr line."""
    source_path = Path(source_path)
    try:
        st = source_path.stat()
    except OSError as e:
        print(f"cairn: warning: engine staleness check could not stat {source_path}: {e}", file=sys.stderr)
        return False
    if st.st_mtime_ns == boot["mtime_ns"] and st.st_size == boot["size"]:
        return False
    try:
        current_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()[:12]
    except OSError as e:
        print(f"cairn: warning: engine staleness check could not read {source_path}: {e}", file=sys.stderr)
        return False
    return current_sha != boot["sha"]


# --------------------------------------------------------------------------
# HTTP server — a lens, not a source of truth. No state held here.
# --------------------------------------------------------------------------

def make_server(
    data_dir: Path,
    config: Optional[Dict[str, Any]] = None,
    port: Optional[int] = None,
    roots: Optional[List[Root]] = None,
    source_path: Path = Path(__file__),
    dashboard_dir: Path = DASHBOARD_DIR,
):
    """Build (but do not start) the board's HTTPServer, bound to 127.0.0.1.

    port=0 -> ephemeral (read back via server.server_address[1]).
    port=None -> load_config(data_dir)["port"].
    Caller owns serve_forever() so tests can run it in a thread.

    PT-3: `roots`, when omitted (`None`), is synthesised by calling
    `resolve_roots(data_dir, config)` -- the exact same function multi-root
    callers use -- so single-root behaviour (the overwhelming majority of
    callers: every existing test, `cmd_serve` without `--repos`) is
    exercised by the *same* code path multi-root uses, not a separate one
    that could silently drift. `cmd_serve` resolves roots itself (for its
    startup banner) and passes the result in explicitly.

    PT-49 (§9's required test seam): `source_path` defaults to THIS
    module's own file -- a real server fingerprints the actual running
    `cairn.py` with zero caller effort -- but is overridable so a test can
    point it at a throwaway file and rewrite THAT, never the live,
    imported `cairn.py`. Fingerprinted exactly once here, at construction
    (§2's "boot" fingerprint); every later `/api/board` build re-checks
    against it via `engine_is_stale`, never re-fingerprints from scratch.

    PT-54 (architect ruling §4): `dashboard_dir` defaults to the real
    committed `DASHBOARD_DIR` -- overridable so a test can exercise the
    missing-dist 503 branch (or serve a throwaway fixture) without
    touching the real `scripts/cairn/dashboard/dist/`, same seam
    `source_path` already established.
    """
    data_dir = Path(data_dir)
    dashboard_dir = Path(dashboard_dir)
    if config is None:
        config = load_config(data_dir)
    if port is None:
        port = int(os.environ.get("CAIRN_PORT", config.get("port", DEFAULT_PORT)))
    if roots is None:
        roots, root_warnings = resolve_roots(data_dir, config)
    else:
        root_warnings = []
    host = "127.0.0.1"

    # PT-49 §2: captured once, held on the handler closure below, compared
    # against on every /api/board build (§3) -- never recomputed here.
    engine_boot = engine_fingerprint(source_path)
    engine_started_at = datetime.datetime.now().isoformat()

    # PT-1: Server is per-connection threaded (ThreadingMixIn below) so a
    # held-open SSE connection can't starve the accept loop for every
    # other client. That's a real behavior change from the old
    # single-threaded HTTPServer, where request handling was inherently
    # serialized -- two concurrent POST /api/issue/<id> on the *same*
    # issue could never race, because the server processed one full
    # request/response cycle at a time. Once concurrent request threads
    # are possible, that serialization has to be re-created explicitly:
    # write_lock below serializes only the mutate path (the
    # seen-check-then-write critical section), so two concurrent writers
    # to the same issue can't both pass the staleness check against the
    # same pre-write state and silently lose one of their patches. Reads
    # (GET /api/board, GET /api/issue/<id>, the SSE stream) stay fully
    # concurrent -- only writes serialize. allocate_and_create_issue's own
    # O_EXCL retry loop already makes concurrent *creates* safe without
    # this lock (each gets a distinct ID), so _create_issue isn't wrapped.
    write_lock = threading.Lock()

    # PT-1: watcher lifecycle is bound to make_server itself (server
    # object exists => watching), not to cmd_serve -- so every test (and
    # every other caller) that builds a server via make_server gets a
    # live watcher for free. Baseline snapshot happens synchronously
    # inside DataDirWatcher.__init__, below, before .start() is called.
    broadcaster = _SSEBroadcaster()
    watcher = DataDirWatcher(roots, broadcaster)

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "cairn/1.0"

        def log_message(self, fmt, *fmt_args):  # noqa: A003
            # PT-34 (architect's E0 prerequisite, ruled permanent): the
            # prior override discarded every argument log_request/log_error
            # pass through fmt_args, including the HTTP status code -- a
            # request that returned 200 and one that returned 503 produced
            # an identical server-log line. That gap is what turned this
            # investigation into an afternoon of Chrome-side reasoning
            # instead of a grep. BaseHTTPRequestHandler.log_request's own
            # call shape (kept here as the reference format) is
            # `log_message('"%s" %s %s', requestline, code, size)` --
            # fmt_args[1] is the status code on that path.
            #
            # PT-31 (architect's comment-accuracy fix, item 8): the
            # previous version of this comment claimed any OTHER call
            # shape (log_error, etc.) "degrades to the terse form" -- that
            # is false. log_error's own call shape is
            # `log_message("code %d, message %s", code, message)`, so at
            # fmt_args[1] it carries the MESSAGE ("Not Found"), not a
            # status code -- that string lands in this line's status
            # column verbatim, not a "-" placeholder. Harmless for E0's
            # actual purpose (the real numeric status still appears on
            # log_request's own line for the same request), but the prior
            # comment described a fallback that doesn't exist. No
            # format-string guard added to distinguish the two shapes --
            # that would couple this handler to a CPython stdlib internal
            # (the exact positional args http.server happens to pass)
            # for a cosmetic gain on an already-non-blocking log line.
            status = fmt_args[1] if len(fmt_args) >= 2 else "-"
            sys.stderr.write("  %s %s %s\n" % (self.command, self.path, status))

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel_path: str, base: Path = BOARD_DIR) -> None:
            # PT-54 (architect ruling §4): widened to take `base` so the
            # dashboard's static assets go through the SAME traversal
            # guard as the board's (BOARD_DIR stays the default -- every
            # pre-PT-54 caller is unaffected).
            target = (base / rel_path).resolve()
            try:
                target.relative_to(base.resolve())
            except ValueError:
                self.send_error(403)
                return
            if not target.is_file():
                self.send_error(404)
                return
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".woff2": "font/woff2",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
                ".json": "application/json",
                ".map": "application/json",
            }.get(target.suffix, "application/octet-stream")
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            # PT-49 §7: closes the browser-cache half of staleness cheaply
            # -- matches what /api/board already sends. No client-side
            # asset-version handshake: with no-store, a stale board.js/
            # board.css is not a reachable state, so there is nothing left
            # for a handshake to protect against.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_dashboard_unbuilt_503(self) -> None:
            """PT-54 (architect ruling §3/§4): the dashboard's `dist/` is
            COMMITTED, never built at serve time -- when it's missing (a
            clone that hasn't run `npm ci && npm run build` under
            `scripts/cairn/dashboard/` specifically; the rest of `cairn
            serve` needs nothing but python3), name the literal fix
            rather than a bare 404/500. `/api/dashboard` is unaffected --
            it's pure python, no build dependency.
            """
            body = (
                "<!doctype html><html><head><title>Dashboard not built</title></head>"
                "<body><h1>503 &mdash; Dashboard not built</h1>"
                "<p>Run <code>cd scripts/cairn/dashboard &amp;&amp; npm ci &amp;&amp; "
                "npm run build</code>, then restart <code>cairn serve</code>.</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _handle_sse(self) -> None:
            """GET /api/events -- an SSE stream. Holds the connection
            open (no Content-Length, no keep-alive) and pushes one
            `data: <json>\\n\\n` frame per broadcaster event -- coarse
            per team-lead's ruling: the frame's contents (created/
            changed/removed path lists) are informational only, the
            client refetches the whole board on any event, never a
            per-id targeted diff.

            A 30s heartbeat comment (standard SSE keep-alive cadence)
            bounds how long a dead connection's thread can sit blocked
            on q.get() with nothing to detect the disconnect -- 30s is
            comfortably above every test's read-timeout budget (this is
            a localhost single-user tool, not proxied through anything
            with its own idle-connection timeout, so nothing here is
            tuned to the test suite's timing). A write failure on either
            a heartbeat or a real event (client gone) ends the loop and
            unsubscribes.
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            q = broadcaster.subscribe()
            try:
                while True:
                    try:
                        event = q.get(timeout=30.0)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                    body = json.dumps(event).encode("utf-8")
                    self.wfile.write(b"data: " + body + b"\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                broadcaster.unsubscribe(q)

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/api/board":
                # PT-42 (ruling § 1): `?archived=1` is the ONLY accepted
                # spelling -- absent, empty, or any other value is OFF, so
                # a typo'd/garbage query param can never accidentally
                # trigger the 28x-cost archive/ read. `parse_qs` (not a
                # hand-split on "&"/"="): stdlib, handles the usual query-
                # string edge cases (repeated keys, missing values, url-
                # decoding) this endpoint doesn't otherwise need to worry
                # about the first time it grows a query param at all.
                query = urllib.parse.parse_qs(parsed.query)
                archived = query.get("archived", [""])[0] == "1"
                # PT-49 §3/§5: the self-check runs on EVERY build (cheap:
                # one stat in the common case), folded into the etag (§5,
                # the part that would otherwise silently defeat the whole
                # feature -- without it a stale flip with no data change
                # 304s forever and the banner never appears).
                engine_stale = engine_is_stale(source_path, engine_boot)
                engine_status = {
                    "source_sha": engine_boot["sha"],
                    "started_at": engine_started_at,
                    "stale": engine_stale,
                }
                etag = compute_multi_etag(
                    roots, archived=archived, boot_sha=engine_boot["sha"], source_path=source_path
                )
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                payload = build_multi_board_payload(
                    roots, root_warnings, archived=archived, engine=engine_status
                )
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/api/issue/"):
                issue_id = urllib.parse.unquote(path[len("/api/issue/"):])
                # PT-3: read side is roots-aware -- an issue from ANY
                # loaded root is readable, stamped with which root it came
                # from and whether that root is writable. The write side
                # (_mutate_issue below) is deliberately NOT roots-aware in
                # the same way -- that asymmetry is the read-only guarantee.
                owning_root = find_issue_in_roots(roots, issue_id)
                if owning_root is None:
                    self._send_json(404, {"error": "not_found", "message": f"no such issue: {issue_id}"})
                    return
                payload = build_issue_payload(owning_root.path, issue_id)
                payload["repo"] = owning_root.id
                # PT-42 (ruling § 5): folds the archived stamp
                # build_issue_payload already computes into the SAME
                # read_only flag a foreign-root issue gets -- the drawer's
                # inline editors already suppress on this one flag (PT-3),
                # so an archived issue's read-only-ness needs no second
                # client-side flag to check.
                payload["read_only"] = (not owning_root.primary) or payload["archived"]
                self._send_json(200, payload)
                return
            if path == "/api/events":
                self._handle_sse()
                return
            if path == "/api/dashboard":
                # PT-54 (architect ruling §4): primary-root only -- git
                # state is inherently single-repo, there is no multi-root
                # "current branch". Same ETag/no-store posture as
                # /api/board, but hashing the SERIALIZED BODY (the
                # ruling's own words: "cheap to write") rather than a
                # file-mtime fold -- every field here already comes from
                # either a bounded git subprocess or a fresh parse, so
                # there's no cheaper fingerprint to reuse.
                payload = build_dashboard_payload(roots[0].path)
                body = json.dumps(payload).encode("utf-8")
                # `generated_at` is excluded from the hash input --
                # otherwise every request's own timestamp would change
                # the ETag, defeating 304 entirely even when nothing
                # else in the payload moved.
                etag_input = {k: v for k, v in payload.items() if k != "generated_at"}
                etag = hashlib.sha256(json.dumps(etag_input, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/roster":
                # PT-56 (architect ruling § "Where the code lives"): a
                # SEPARATE endpoint, never a key on /api/dashboard --
                # keeps PT-54's five-key payload contract intact and
                # isolates failure (an unreadable .claude/agents/ degrades
                # only this endpoint). No SSE-driven freshness: the
                # watcher scans process/cairn/ only, so a change under
                # .claude/agents/ would emit nothing regardless -- the
                # dashboard client polls this on its own cadence instead.
                payload = build_roster_payload(roots[0].path)
                self._send_json(200, payload)
                return
            if path in ("/", "/list"):
                self._send_static("board.html")
                return
            if path.startswith("/board/"):
                self._send_static(path[len("/board/"):])
                return
            if path in ("/dashboard", "/dashboard/"):
                if not dashboard_dir.is_dir():
                    self._send_dashboard_unbuilt_503()
                    return
                self._send_static("index.html", base=dashboard_dir)
                return
            if path.startswith("/dashboard/"):
                # PT-54 (architect ruling §4): SPA fallback, narrowly --
                # a real file wins; a no-suffix path (client-side route)
                # falls back to index.html; a SUFFIXED path that doesn't
                # exist (a missing .js/.css) stays a 404, never silently
                # becomes index.html -- "the classic hours-lost debugging
                # trap."
                if not dashboard_dir.is_dir():
                    self._send_dashboard_unbuilt_503()
                    return
                rel = path[len("/dashboard/"):]
                if (dashboard_dir / rel).is_file():
                    self._send_static(rel, base=dashboard_dir)
                elif Path(rel).suffix == "":
                    self._send_static("index.html", base=dashboard_dir)
                else:
                    self.send_error(404)
                return
            self.send_error(404)

        def do_POST(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "bad_request", "message": "invalid JSON body"})
                return

            if path == "/api/issue":
                self._create_issue(payload)
                return
            if path.startswith("/api/issue/"):
                issue_id = urllib.parse.unquote(path[len("/api/issue/"):])
                self._mutate_issue(issue_id, payload)
                return
            if path.startswith("/api/record/"):
                record_id = urllib.parse.unquote(path[len("/api/record/"):])
                self._mutate_record(record_id, payload)
                return
            self.send_error(404)

        def _create_issue(self, payload: Dict[str, Any]) -> None:
            title = payload.get("title")
            if not title:
                self._send_json(400, {"error": "bad_request", "message": "title is required"})
                return
            fields = {
                "title": title,
                "status": payload.get("status") or DEFAULT_STATUS,
                "milestone": payload.get("milestone"),
                "parent": payload.get("parent"),
                "assignee": payload.get("assignee"),
                "labels": payload.get("labels") or [],
                "priority": payload.get("priority"),
                "pr": None,
            }
            # PT-52 §3: allocate_and_create_issue's legacy-layout guard
            # raises CairnError on an unmigrated repo -- without this catch
            # it would surface as an uncaught-exception 500. 400
            # legacy_archive is the truthful status: a client retry can't
            # fix this, only running the migration can.
            try:
                new_path = allocate_and_create_issue(data_dir, fields)
            except CairnError as e:
                self._send_json(400, {"error": "legacy_archive", "message": str(e)})
                return
            self._send_json(200, build_issue_payload(data_dir, new_path.stem))

        def _mutate_issue(self, issue_id: str, payload: Dict[str, Any]) -> None:
            # PT-3: find_issue_path is scoped to `data_dir` (the primary
            # root) only -- structurally, not by a check that could be
            # forgotten (design note §5.1). A foreign id is truthfully
            # refused with 403 read_only_root; an id no root recognizes at
            # all is a genuine 404. find_issue_in_roots is only ever
            # called here to produce that distinction -- never to locate a
            # file to write to.
            issue_path = find_issue_path(data_dir, issue_id)
            if issue_path is None:
                foreign_root = find_issue_in_roots(roots, issue_id)
                if foreign_root is not None and not foreign_root.primary:
                    self._send_json(403, {
                        "error": "read_only_root",
                        "message": f"{issue_id} lives in root {foreign_root.id} — "
                                   "the board is read-only across roots",
                    })
                    return
                self._send_json(404, {"error": "not_found", "message": f"no such issue: {issue_id}"})
                return

            # PT-42 (ruling § 5): an id that resolves in archive/ is
            # refused 403, file untouched -- mirrors read_only_root's
            # shape exactly. find_issue_path itself is UNCHANGED (still
            # resolves archive/, same PT-3/PT-39 precedent) -- this check
            # is HTTP-only; the CLI (`cairn set`/`cairn comment`, which
            # calls find_issue_path directly, never through here) stays
            # deliberately able to write an archived issue. A drag is a
            # one-pixel gesture that would leave a live-looking issue
            # sitting in archive/, invisible the moment Show-archived goes
            # off -- un-archiving is `git mv`, deliberately.
            if is_archived_path(data_dir, issue_path):
                self._send_json(403, {
                    "error": "archived",
                    "message": f"{issue_id} is archived — read-only on the board; use the CLI instead",
                })
                return

            if "seen" not in payload:
                self._send_json(400, {
                    "error": "bad_request",
                    "message": "seen is required (send the loaded token, or explicit null to override)",
                })
                return

            # PT-1: serializes the seen-check-then-write critical section
            # across request threads -- see write_lock's docstring above
            # for why this became necessary once Server went threaded.
            with write_lock:
                seen = payload["seen"]
                current_seen = get_seen(issue_path)
                if seen is not None and str(seen) != current_seen:
                    current = build_issue_payload(data_dir, issue_id)
                    self._send_json(409, {
                        "error": "stale",
                        "message": f"{issue_id} changed on disk since you loaded it",
                        "current": current,
                    })
                    return

                patch = payload.get("patch")
                if patch:
                    apply_patch(issue_path, patch)
                comment = payload.get("comment")
                if comment:
                    append_comment(issue_path, comment.get("author", "board"), comment.get("body", ""))

                self._send_json(200, build_issue_payload(data_dir, issue_id))

        def _mutate_record(self, record_id: str, payload: Dict[str, Any]) -> None:
            """`POST /api/record/<id>` -- the milestone/major sibling of
            `_mutate_issue` (PT-51 §1). A NEW endpoint, not a widening of
            `/api/issue/<id>`: `find_issue_path` stays the only resolver
            THAT path can reach (PT-3/PT-39's structural read-only/single-
            write-path guarantee), and this one is scoped to
            `find_record_path` the same way. Six checks, in the ruled
            order -- the order is part of the ruling, not an
            implementation detail:
              1. resolve (403 read_only_root / 404 not_found)
              2. an issue id -> 400 wrong_endpoint (this is NOT a second
                 write path to issues)
              3. archived -> 403, BEFORE the seen comparison
              4. seen missing -> 400; then the critical section + 409 stale
              5. patch -> field policy (§3) -> apply_patch
              6. comment -> append_comment (§4)
            """
            # Step 1 -- same distinguishing pattern as _mutate_issue:
            # find_record_path is data_dir- (primary root-) scoped by
            # construction; find_record_in_roots is ONLY ever called here
            # to tell 403 from 404, never to locate a file to write.
            record_path = find_record_path(data_dir, record_id)
            if record_path is None:
                foreign_root = find_record_in_roots(roots, record_id)
                if foreign_root is not None and not foreign_root.primary:
                    self._send_json(403, {
                        "error": "read_only_root",
                        "message": f"{record_id} lives in root {foreign_root.id} — "
                                   "the board is read-only across roots",
                    })
                    return
                self._send_json(404, {"error": "not_found", "message": f"no such record: {record_id}"})
                return

            # Step 2 -- an issue id resolves here too (find_record_path
            # searches issues/ first); rejecting it is what stops this
            # endpoint from becoming a second write path to issues with a
            # different field policy, the exact drift the single-write-
            # path rule exists to prevent.
            schema = _record_schema_for_path(data_dir, record_path)
            if schema == "issue":
                self._send_json(400, {
                    "error": "wrong_endpoint",
                    "message": f"{record_id} is an issue — use /api/issue/{record_id}",
                })
                return

            # Step 3 -- verbatim _mutate_issue's archived rule, checked
            # BEFORE the seen comparison so it holds regardless of body
            # (proven by the archived-with-a-garbage-body test).
            if is_archived_path(data_dir, record_path):
                self._send_json(403, {
                    "error": "archived",
                    "message": f"{record_id} is archived — read-only on the board; use the CLI instead",
                })
                return

            # Step 4a
            if "seen" not in payload:
                self._send_json(400, {
                    "error": "bad_request",
                    "message": "seen is required (send the loaded token, or explicit null to override)",
                })
                return

            # Step 4b/5/6 -- same write_lock critical section _mutate_issue
            # uses (write_lock serializes across BOTH endpoints; it's one
            # lock for the whole write surface, not per-endpoint).
            with write_lock:
                seen = payload["seen"]
                current_seen = get_seen(record_path)
                if seen is not None and str(seen) != current_seen:
                    current = build_record_payload(data_dir, record_id)
                    self._send_json(409, {
                        "error": "stale",
                        "message": f"{record_id} changed on disk since you loaded it",
                        "current": current,
                    })
                    return

                patch = payload.get("patch")
                if patch:
                    error = _validate_record_patch(schema, patch)
                    if error is not None:
                        self._send_json(400, error)
                        return
                    apply_patch(record_path, patch)
                comment = payload.get("comment")
                if comment:
                    append_comment(record_path, comment.get("author", "board"), comment.get("body", ""))

                self._send_json(200, build_record_payload(data_dir, record_id))

    # PT-1: ThreadingMixIn -- one thread per connection, so a long-held
    # SSE stream can't block the accept loop for every other client
    # (see write_lock above for the write-safety half of this change).
    # daemon_threads=True so a request thread (notably an open SSE
    # connection) never blocks process/test-suite shutdown.
    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True

        def server_close(self) -> None:
            # PT-1 lifecycle ruling: server close => watcher stopped.
            watcher.stop()
            super().server_close()

    server = Server((host, port), Handler)
    watcher.start()  # PT-1 lifecycle ruling: server object exists => watcher running
    return server


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def resolve_data_dir(args: argparse.Namespace) -> Path:
    """Resolve the data dir for a CLI invocation, or fail loudly.

    A missing or config-less data dir is an error, never an empty result
    (process/TRACKER.md, "The layout is fixed at process/cairn/ in v1" —
    architect conformance review, finding 3): "no tracker here" and "no
    issues here" must never render identically. Applies uniformly whether
    the path came from an explicit --data-dir or from find_data_dir()'s
    walk-up, since every command downstream assumes a real tracker.
    """
    explicit = getattr(args, "data_dir", None)
    data_dir = Path(explicit) if explicit else find_data_dir()
    if not (data_dir / "config.yml").exists():
        raise CairnError(
            f"no cairn tracker found at {data_dir} (missing config.yml) — "
            "pass --data-dir to an existing tracker, or run /setup-tracker to create one"
        )
    return data_dir


def _coerce_cli_value(key: str, value: str) -> Any:
    if key in LIST_FIELDS:
        return _split_csv(value)
    if key in NULLABLE_FIELDS and value == "":
        return None
    if value.lower() == "null":
        return None
    return value


def _normalize_milestone_input(value: Optional[str], prefix: str) -> Optional[str]:
    """PT-28 (architect's ruling § 3, item 2). Accepts the BARE form on any
    CLI input that carries a milestone value -- `cairn ls --milestone 0.6`,
    `cairn new --milestone 0.6`, `cairn set <id> milestone=0.6` -- and
    normalizes to the configured prefix, since the prefix is fixed per repo
    and typing it on every local invocation is pure friction where it adds
    nothing. An already-prefixed value passes through unchanged (idempotent
    -- typing the full form still works). Falsy (`None`/`""`) passes through
    unchanged too -- "no milestone" / "clear this field" is not "a bare
    value", and must keep coercing to `null`, not `"PT-"`.
    This is CLI input leniency only, distinct from the lint (files must
    still be prefixed) -- see check_repo's id-shape enforcement.

    PT-28 Validate-phase finding (QA, adf1cce): originally wired into
    cmd_ls's read-path filter ONLY. cmd_new/cmd_set's write paths wrote
    the bare value straight to disk, succeeding (exit 0) while leaving
    the repo lint-failing with a dangling milestone: ref -- worse than no
    leniency at all, since the failure surfaced later at `cairn check`
    time, disconnected from the command that caused it. All three call
    sites route through this one function now, so they can't drift out
    of agreement the way the pre-fix two-out-of-three state did.
    """
    if not value or value.startswith(f"{prefix}-"):
        return value
    return f"{prefix}-{value}"


def cmd_new(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    prefix = load_config(data_dir)["prefix"]
    fields = {
        "title": args.title,
        "status": args.status,
        "milestone": _normalize_milestone_input(args.milestone, prefix),
        "parent": args.parent,
        "blocked_by": _split_csv(args.blocked_by) if args.blocked_by else [],
        "assignee": args.assignee,
        "labels": _split_csv(args.labels) if args.labels else [],
        "priority": args.priority,
        "pr": None,
    }
    path = allocate_and_create_issue(data_dir, fields)
    frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    print(frontmatter["id"])
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    milestone_filter = _normalize_milestone_input(args.milestone, load_config(data_dir)["prefix"])
    matched: List[Dict[str, Any]] = []
    for p in _dir_glob(Path(data_dir) / "issues"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            print(f"warning: skipping {p}: {e}", file=sys.stderr)
            continue
        if args.status and fm.get("status") != args.status:
            continue
        if milestone_filter and str(fm.get("milestone")) != milestone_filter:
            continue
        if args.assignee and fm.get("assignee") != args.assignee:
            continue
        matched.append(fm)
    # PT-21: _dir_glob's filename order is lexicographic ("PT-10" sorts
    # before "PT-2") -- print in numeric-by-id order instead, reusing the
    # same _id_sort_key PT-2's build_snapshot_markdown already introduced
    # rather than a second copy of the same sort key.
    matched.sort(key=lambda fm: _id_sort_key(fm.get("id")))
    for fm in matched:
        milestone = fm.get("milestone") if fm.get("milestone") is not None else "-"
        assignee = fm.get("assignee") if fm.get("assignee") is not None else "-"
        print(f"{fm.get('id')}\t{fm.get('status')}\t{milestone}\t{assignee}\t{fm.get('title')}")
    return 0


_RECORD_FIELD_ORDER = {"issue": ISSUE_FIELD_ORDER, "milestone": MILESTONE_FIELD_ORDER, "major": MAJOR_FIELD_ORDER}


def _record_schema_for_path(data_dir: Path, path: Path) -> str:
    """"issue" | "milestone" | "major", by which subdir `path` resolved
    under (PT-39 § 6) -- the classifier cmd_set uses to pick
    ISSUE_FIELD_ORDER/MILESTONE_FIELD_ORDER/MAJOR_FIELD_ORDER and
    STATUSES/RECORD_STATUSES. Checked via relative-path PARTS membership,
    not just the immediate parent dir name: "milestones" is the immediate
    parent for BOTH milestones/<id>.md and archive/milestones/<id>.md, so
    parts-membership handles the live and archived cases identically with
    no separate archive branch.
    """
    parts = Path(path).relative_to(Path(data_dir)).parts
    if "milestones" in parts:
        return "milestone"
    if "majors" in parts:
        return "major"
    return "issue"


def cmd_set(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    path = find_record_path(data_dir, args.id)
    if path is None:
        print(f"error: no such record: {args.id}", file=sys.stderr)
        return 1
    schema = _record_schema_for_path(data_dir, path)
    field_order = _RECORD_FIELD_ORDER[schema]
    valid_statuses = STATUSES if schema == "issue" else RECORD_STATUSES
    prefix = load_config(data_dir)["prefix"]
    patch: Dict[str, Any] = {}
    for kv in args.assignments:
        if "=" not in kv:
            print(f"error: expected key=value, got {kv!r}", file=sys.stderr)
            return 1
        key, _, value = kv.partition("=")
        if key not in field_order:
            print(f"error: unknown field {key!r} for {schema} {args.id}", file=sys.stderr)
            return 1
        coerced = _coerce_cli_value(key, value)
        # PT-28 (Validate-phase fix): `milestone=0.6` must normalize the
        # same way `cairn ls --milestone 0.6` does -- _coerce_cli_value
        # already turned "" / "null" into None (clear the field), which
        # _normalize_milestone_input passes through unchanged (falsy is
        # not "a bare value"). Only reachable for the issue schema --
        # "milestone" isn't a MILESTONE_FIELD_ORDER/MAJOR_FIELD_ORDER key,
        # so the field_order check above already excludes it there.
        if key == "milestone" and coerced is not None:
            coerced = _normalize_milestone_input(coerced, prefix)
        # PT-39 (architect's ruling § 6): status= is now validated inline
        # against the resolved schema's vocabulary -- cmd_set previously
        # did zero status-value validation, relying entirely on a later
        # `cairn check` to catch a bad value. Checked before `patch` is
        # written to (not just before apply_patch is called) so a
        # multi-assignment invocation with an early valid key and a later
        # invalid status writes NOTHING, same all-or-nothing contract as
        # the unknown-field check above.
        if key == "status" and coerced not in valid_statuses:
            print(
                f"error: invalid status {coerced!r} for {schema} {args.id} -- "
                f"expected one of {sorted(valid_statuses)}",
                file=sys.stderr,
            )
            return 1
        patch[key] = coerced
    try:
        apply_patch(path, patch)
    except CairnError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(args.id)
    return 0


def cmd_comment(args: argparse.Namespace) -> int:
    # PT-51 §4: find_issue_path -> find_record_path -- records may now
    # carry a '## Comments' section too (identical format/parser/author
    # vocabulary as issues, no second convention), so `cairn comment`
    # works uniformly on issues, milestones, majors, and archived records
    # -- matching what `cairn set` (PT-39) already does. append_comment
    # itself already gates its `updated` bump on _is_issue_shaped, so a
    # record comment injects no off-schema key.
    data_dir = resolve_data_dir(args)
    path = find_record_path(data_dir, args.id)
    if path is None:
        print(f"error: no such record: {args.id}", file=sys.stderr)
        return 1
    body = sys.stdin.read() if args.body == "-" else args.body
    append_comment(path, args.author, body)
    return 0


def _scan_issues(data_dir: Path, exclude: Path, predicate) -> List[Dict[str, Any]]:
    """Frontmatter of every issue in issues/ (except `exclude`) satisfying
    `predicate` -- the one scan behind cmd_show's Children and Blocks
    sections. Per-file parse errors are skipped, not raised (mirrors
    check_repo). One function, not two copies differing only in the
    predicate -- the Python-side twin of board.js's issueLinkListEl.
    """
    out = []
    for p in _dir_glob(Path(data_dir) / "issues"):
        if p == exclude:
            continue
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        if predicate(fm):
            out.append(fm)
    return out


def _print_issue_list(heading: str, records: List[Dict[str, Any]]) -> None:
    """Print a `_id_sort_key`-ordered id/status/title block under `heading`,
    or nothing at all when `records` is empty -- an issue with no
    dependencies must print no section header for them."""
    if not records:
        return
    print(f"\n{heading}:")
    for fm in sorted(records, key=lambda fm: _id_sort_key(fm.get("id"))):
        print(f"  {fm.get('id')}\t{fm.get('status')}\t{fm.get('title')}")


def cmd_show(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    path = find_issue_path(data_dir, args.id)
    if path is None:
        print(f"error: no such issue: {args.id}", file=sys.stderr)
        return 1
    issue = parse_issue(path.read_text(encoding="utf-8"))
    print(f"{issue.get('id')} — {issue.get('title')}")
    for key in ISSUE_FIELD_ORDER[2:]:
        # PT-26: blocked_by gets its own "Blocked by:"/"Blocks:" sections
        # below (sorted, both directions, blank when there's nothing to
        # show) rather than a raw `blocked_by: [...]` line here -- an
        # issue with no dependencies at all must print no "block"-shaped
        # text anywhere in the output.
        if key == "blocked_by":
            continue
        print(f"  {key}: {issue.get(key)}")
    print()
    print(issue.get("description", ""))
    comments = issue.get("comments") or []
    if comments:
        print("\nComments:")
        for c in comments:
            print(f"  @{c['author']} — {c['date']}")
            for line in c["body"].split("\n"):
                print(f"    {line}")

    # PT-25: a parent issue also lists its children (id, status, title),
    # sorted numerically by id. The child->parent half of the acceptance
    # criterion needs no code here: `parent:` is already printed above via
    # the ISSUE_FIELD_ORDER[2:] loop (verified against real output,
    # architect's PT-25 ruling #3).
    _print_issue_list(
        "Children", _scan_issues(data_dir, path, lambda fm: fm.get("parent") == args.id)
    )

    # PT-26: this issue's own blockers (its blocked_by field -- direct
    # find_issue_path lookups, no scan) and the reverse "blocks" list (who
    # names THIS issue in their own blocked_by -- a directory scan, same
    # shape as the children scan above). Both sorted by _id_sort_key.
    blocked_by = issue.get("blocked_by") or []
    blockers = []
    for ref in blocked_by:
        ref_path = find_issue_path(data_dir, ref)
        if ref_path is not None:
            blockers.append(parse_issue(ref_path.read_text(encoding="utf-8")))
        else:
            # Dangling ref on an unchecked tree -- cairn check would flag
            # this; cmd_show still renders it rather than crash.
            blockers.append({"id": ref, "status": "?", "title": "(not found)"})
    _print_issue_list("Blocked by", blockers)
    _print_issue_list(
        "Blocks", _scan_issues(data_dir, path, lambda fm: args.id in (fm.get("blocked_by") or []))
    )

    return 0


def _git_mv_or_rename(src: Path, dest: Path) -> None:
    """`git mv src dest`, falling back to a plain filesystem move when
    git isn't applicable (no git binary, or `src`/`dest` aren't inside a
    git worktree at all -- both legitimate, expected outcomes for a
    non-git data dir, never an error).

    PT-53: `src`/`dest` are resolved to ABSOLUTE paths before the
    subprocess call. The subprocess's `cwd=src.parent` is unchanged --
    still needed so a relative `--data-dir` invocation's git command runs
    from somewhere that exists -- but the ARGUMENT strings used to be
    whatever `src`/`dest` were handed as (relative, when `--data-dir` is
    relative -- `resolve_data_dir` never calls `.resolve()`), which
    `git mv` then read relative to the WRONG base once the subprocess's
    cwd had already changed to `src.parent`. `git mv` looked for a
    source file that didn't exist there, failed, and the failure was
    swallowed (only `returncode == 0` was ever checked, stderr never
    surfaced) -- silently downgrading a real invocation to the plain-move
    fallback, which leaves an untracked add + unstaged delete instead of
    a staged rename. Resolving both paths up front makes the argument
    correct regardless of the caller's cwd or the relativity of what it
    was given; `.resolve()` doesn't require either path to already exist.
    """
    import subprocess
    src = Path(src).resolve()
    dest = Path(dest).resolve()
    try:
        result = subprocess.run(
            ["git", "mv", str(src), str(dest)],
            cwd=str(src.parent), capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        # PT-53: surfaced, not swallowed -- this fallback stays
        # LEGITIMATE for a non-git data dir ("fatal: not a git
        # repository" is exactly what a plain move should silently
        # absorb), but a genuine failure for a data dir that IS a git
        # repo (a dirty index mid-merge, permissions, ...) was previously
        # indistinguishable from that case. One warning line, never
        # raised -- the operation still completes via the fallback below.
        if result.stderr:
            print(f"cairn: warning: git mv fell back to a plain move ({result.stderr.strip()})", file=sys.stderr)
    except FileNotFoundError:
        pass
    os.replace(str(src), str(dest))


# --------------------------------------------------------------------------
# PT-39 (architect's ruling § 5): milestone/major archiving. "Archive never
# sweeps issues out from under a live milestone" is the load-bearing
# invariant -- a milestone/major can only be archived when IT and every
# issue/milestone under it is already done/cancelled. This is what lets
# the board compute an honest n/m progress count from issues/ alone, with
# zero archive reads (PT-40/43/44 ruling § 3).
# --------------------------------------------------------------------------

def _issues_for_milestone(data_dir: Path, milestone_id: str) -> List[Tuple[Path, Dict[str, Any]]]:
    """Every LIVE issue (issues/ only) whose `milestone:` resolves to
    `milestone_id`. Never reads archive/ -- an already-archived issue, by
    construction, already passed this exact precondition at the moment it
    was archived; re-checking it here would be redundant at best and,
    for --milestone/--major's refuse-on-failure semantics, could wrongly
    block a valid archive on an issue this operation was never going to
    touch again.
    """
    data_dir = Path(data_dir)
    out: List[Tuple[Path, Dict[str, Any]]] = []
    for p in _dir_glob(data_dir / "issues"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        if str(fm.get("milestone")) == milestone_id:
            out.append((p, fm))
    return out


def _milestone_precondition(data_dir: Path, milestone_fm: Dict[str, Any]) -> None:
    """Raises CairnError (nothing written -- callers check this BEFORE
    moving any file) unless `milestone_fm`'s own status AND every live
    issue under it are done/cancelled. Silent (no return value) when
    clear -- callers call this for its raise-or-not effect only.
    """
    milestone_id = milestone_fm.get("id")
    status = milestone_fm.get("status")
    if status not in ("done", "cancelled"):
        raise CairnError(
            f"milestone {milestone_id} is not done/cancelled (status: {status!r}) -- refusing to archive"
        )
    for _, ifm in _issues_for_milestone(data_dir, milestone_id):
        if ifm.get("status") not in ("done", "cancelled"):
            raise CairnError(
                f"milestone {milestone_id} has an issue that is not done/cancelled "
                f"({ifm.get('id')}: status {ifm.get('status')!r}) -- refusing to archive"
            )


def archive_milestone(data_dir: Path, milestone_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """Archive `milestone_id`: moves its done/cancelled issues (no date
    filter) then the milestone file itself into archive/ / archive/
    milestones/ respectively. Raises CairnError (nothing written) if the
    milestone is unknown or fails `_milestone_precondition`. Returns
    `{"milestone": id, "issues": [ids moved]}` -- the report is still
    returned in `dry_run` mode, just without touching disk.
    """
    data_dir = Path(data_dir)
    ms_path = data_dir / "milestones" / f"{milestone_id}.md"
    if not ms_path.exists():
        raise CairnError(f"unknown milestone {milestone_id!r} -- nothing archived")
    fm, _body = parse_frontmatter(ms_path.read_text(encoding="utf-8"))
    _milestone_precondition(data_dir, fm)
    issues = _issues_for_milestone(data_dir, milestone_id)
    report: Dict[str, Any] = {"milestone": milestone_id, "issues": [ifm.get("id") for _, ifm in issues]}
    if not dry_run:
        # PT-50 (§2 write target #10): issues land in archive/issues/, NOT
        # bare archive/ -- writes only ever produce the new layout.
        archive_issues_dir = data_dir / "archive" / "issues"
        archive_ms_dir = data_dir / "archive" / "milestones"
        archive_issues_dir.mkdir(parents=True, exist_ok=True)
        archive_ms_dir.mkdir(parents=True, exist_ok=True)
        for p, _ in issues:
            _git_mv_or_rename(p, archive_issues_dir / p.name)
        _git_mv_or_rename(ms_path, archive_ms_dir / ms_path.name)
    return report


def archive_major(data_dir: Path, major_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """Archive `major_id`: archives each of its milestones (per
    archive_milestone above) then the major file itself into archive/
    majors/. Two-phase, all-or-nothing: validates the major's OWN status
    AND every one of its milestones' `_milestone_precondition` BEFORE
    moving anything -- a partially-archived major (some milestones moved,
    one refused) must never be a reachable state. Raises CairnError
    (nothing written) if the major is unknown or any precondition fails.
    Returns `{"major": id, "milestones": [archive_milestone's report, ...]}`.
    """
    data_dir = Path(data_dir)
    major_path = data_dir / "majors" / f"{major_id}.md"
    if not major_path.exists():
        raise CairnError(f"unknown major {major_id!r} -- nothing archived")
    mfm, _mbody = parse_frontmatter(major_path.read_text(encoding="utf-8"))
    if mfm.get("status") not in ("done", "cancelled"):
        raise CairnError(
            f"major {major_id} is not done/cancelled (status: {mfm.get('status')!r}) -- refusing to archive"
        )
    milestones: List[Dict[str, Any]] = []
    for p in _dir_glob(data_dir / "milestones"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        if str(fm.get("major")) == major_id:
            milestones.append(fm)
    # Phase 1: validate every milestone's own precondition first -- nothing
    # written yet. A failure here must leave the tree byte-identical to
    # how it started, even if an earlier milestone in this same major
    # would otherwise have archived cleanly on its own.
    for fm in milestones:
        _milestone_precondition(data_dir, fm)
    # Phase 2: every precondition passed -- now it's safe to move files.
    report: Dict[str, Any] = {"major": major_id, "milestones": []}
    for fm in milestones:
        report["milestones"].append(archive_milestone(data_dir, fm.get("id"), dry_run=dry_run))
    if not dry_run:
        archive_major_dir = data_dir / "archive" / "majors"
        archive_major_dir.mkdir(parents=True, exist_ok=True)
        _git_mv_or_rename(major_path, archive_major_dir / major_path.name)
    return report


_DONE_BEFORE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_done_before(value: str) -> str:
    """Validate `value` as a real YYYY-MM-DD calendar date; returns it unchanged.

    PT-8: `cmd_archive` string-compares this against each issue's `updated`
    with no validation at all — malformed input either silently skips
    issues it should archive, or (worse) archives issues it shouldn't,
    depending on how the garbage string happens to sort lexicographically.
    Called before any file is touched. `date.fromisoformat` alone is too
    lenient (accepts "20260201", ISO week dates, etc.) — the regex pins
    the exact YYYY-MM-DD shape the CLI documents; fromisoformat then
    proves it's a real calendar date, not just the right shape.
    """
    if not _DONE_BEFORE_RE.match(value):
        raise CairnError(f"--done-before must be a YYYY-MM-DD date, got {value!r}")
    try:
        datetime.date.fromisoformat(value)
    except ValueError as e:
        raise CairnError(f"--done-before is not a real calendar date: {value!r} ({e})")
    return value


def _print_archive_milestone_report(report: Dict[str, Any], dry_run: bool) -> None:
    """Shared print body for a single archive_milestone report -- used both
    directly (--milestone) and once per entry from archive_major's report
    (--major), so the two selectors render identically for the same unit
    of work (PT-39 standing dedupe convention).
    """
    verb = "would archive" if dry_run else "archived"
    print(f"{verb} milestone {report['milestone']}")
    for issue_id in sorted(report["issues"]):
        print(f"  {verb} issue {issue_id}")


def cmd_archive(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)

    # PT-39 (architect's ruling § 5): --milestone/--major are new,
    # mutually-exclusive-with-each-other-and-with---done-before selectors
    # (enforced by argparse's mutually exclusive group at parse time --
    # by the time we're here, exactly one of the three is set).
    if args.milestone is not None:
        report = archive_milestone(data_dir, args.milestone, dry_run=args.dry_run)
        _print_archive_milestone_report(report, args.dry_run)
        return 0
    if args.major is not None:
        report = archive_major(data_dir, args.major, dry_run=args.dry_run)
        verb = "would archive" if args.dry_run else "archived"
        print(f"{verb} major {report['major']}")
        for ms_report in report["milestones"]:
            _print_archive_milestone_report(ms_report, args.dry_run)
        return 0

    # Existing --done-before path.
    _validate_done_before(args.done_before)
    # PT-50 (§2 write target #9): issues land in archive/issues/, NOT bare
    # archive/ -- writes only ever produce the new layout.
    archive_dir = Path(data_dir) / "archive" / "issues"
    if not args.dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)

    # PT-39 (ruling § 5 table, NEW column): an issue whose milestone isn't
    # done/cancelled is SKIPPED, not archived -- "archive never sweeps
    # issues out from under a live milestone" applies here too, not just
    # to the new selectors. Milestone statuses looked up once into a dict
    # rather than re-parsed per issue.
    #
    # Architect's review finding (PT-39 Slice C, post-§3-items-2/3): reads
    # BOTH milestones/ and archive/milestones/ -- once a milestone can
    # live in archive/milestones/ (§4), an issue whose milestone was
    # already archived would otherwise miss this dict entirely and print
    # the FALSE "milestone X is not done/cancelled" skip reason for a
    # milestone that's actually done (that's WHY it was archived).
    milestone_status: Dict[str, Any] = {}
    for sub in ("milestones", "archive/milestones"):
        for p in _dir_glob(Path(data_dir) / sub):
            try:
                mfm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            except CairnError:
                continue
            milestone_status[str(mfm.get("id"))] = mfm.get("status")

    verb = "would archive" if args.dry_run else "archived"
    moved = 0
    skipped = 0
    for p in _dir_glob(Path(data_dir) / "issues"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError:
            continue
        if fm.get("status") not in ("done", "cancelled"):
            continue
        updated = fm.get("updated")
        if not updated or str(updated) >= args.done_before:
            continue
        milestone = fm.get("milestone")
        if milestone is not None and milestone_status.get(str(milestone)) not in ("done", "cancelled"):
            print(f"skipped {fm.get('id', p.stem)}: milestone {milestone} is not done/cancelled")
            skipped += 1
            continue
        if not args.dry_run:
            _git_mv_or_rename(p, archive_dir / p.name)
        moved += 1
        print(f"{verb} {fm.get('id', p.stem)}")
    summary = f"{moved} issue(s) {verb}"
    if skipped:
        summary += f", {skipped} skipped (non-done/cancelled milestone)"
    print(summary)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    errors = check_repo(data_dir)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n{len(errors)} error(s)", file=sys.stderr)
        return 1
    print("ok")
    return 0


def cmd_migrate_prefix_ids(args: argparse.Namespace) -> int:
    """`cairn migrate prefix-ids [--dry-run]` (PT-28, architect's ruling § 5).

    Deliberately does NOT gate on a clean `cairn check` first -- that would
    deadlock the exact bare-id situation this command exists to resolve.
    `resolve_data_dir` still hard-errors on a missing config.yml (nothing
    written, per ExitCodeTests); `migrate_prefix_ids` itself hard-errors on
    a missing/malformed `prefix:` the same way. Exit code is 0 for any
    completed run (dry or real, migrated or "nothing to do") -- an
    UNRELATED lint error surviving the migration (e.g. a dangling parent
    ref this command never touches) is reported, not treated as this
    command's own failure; only "could not proceed" (bad prefix, an
    unwritable file) is non-zero, per the ruling's Exit codes section.
    """
    data_dir = resolve_data_dir(args)
    report = migrate_prefix_ids(data_dir, dry_run=args.dry_run)
    print(_format_migration_report(report, args.dry_run))
    if args.dry_run:
        return 0
    errors = check_repo(data_dir)
    if errors:
        print(f"\nwarning: {len(errors)} lint error(s) remain after migration:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    else:
        print("\nok")
    return 0


def cmd_migrate_lifecycle_status(args: argparse.Namespace) -> int:
    """`cairn migrate lifecycle-status [--dry-run]` (PT-39, architect's
    ruling § 2).

    Same posture as cmd_migrate_prefix_ids: does NOT gate on a clean
    `cairn check` first -- that would deadlock the exact old-vocabulary
    situation this command exists to resolve. Exit code is 0 for any
    completed run (dry or real, migrated or "nothing to do") -- an
    UNRELATED lint error surviving the migration is reported, not treated
    as this command's own failure.
    """
    data_dir = resolve_data_dir(args)
    report = migrate_lifecycle_status(data_dir, dry_run=args.dry_run)
    print(_format_lifecycle_migration_report(report, args.dry_run))
    if args.dry_run:
        return 0
    errors = check_repo(data_dir)
    if errors:
        print(f"\nwarning: {len(errors)} lint error(s) remain after migration:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    else:
        print("\nok")
    return 0


def cmd_migrate_archive_issues(args: argparse.Namespace) -> int:
    """`cairn migrate archive-issues [--dry-run]` (PT-50, architect's
    ruling § 1).

    Same posture as the other two migrations: does NOT gate on a clean
    `cairn check` first -- that would deadlock the exact legacy-layout
    situation this command exists to resolve. Exit code is 0 for any
    COMPLETED run (dry or real, migrated or "nothing to do") -- a
    surviving UNRELATED lint error is reported as a warning, not treated
    as this command's own failure. A differing-destination refusal raises
    CairnError (main() turns that into a nonzero exit, nothing written --
    same posture as a missing/malformed prefix in migrate_prefix_ids).
    """
    data_dir = resolve_data_dir(args)
    report = migrate_archive_issues(data_dir, dry_run=args.dry_run)
    print(_format_archive_issues_migration_report(report, args.dry_run))
    if args.dry_run:
        return 0
    errors = check_repo(data_dir)
    if errors:
        print(f"\nwarning: {len(errors)} lint error(s) remain after migration:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    else:
        print("\nok")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    sys.stdout.write(build_snapshot_markdown(data_dir))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    config = load_config(data_dir)
    port = args.port if args.port is not None else None

    # PT-3: --repos REPLACES config.yml's roots: list (team-lead ruling B)
    # -- primary root is always included regardless, by resolve_roots
    # itself. Comma-split, same convention as `cairn new --labels`.
    cli_repos = None
    if args.repos is not None:
        cli_repos = [r.strip() for r in args.repos.split(",") if r.strip()]

    roots, warnings = resolve_roots(data_dir, config, cli_repos)
    for w in warnings:
        detail = f" ({w['detail']})" if w.get("detail") else ""
        print(f"cairn: warning: skipping root {w['root']!r} — {w['reason']}{detail}", file=sys.stderr)

    # seceng D: multi-root widens cairn serve's read surface to whatever
    # roots: (or --repos) names -- a human tripwire so a fat-fingered or
    # stale entry that silently serves the wrong project's tracker becomes
    # visible instead of silent, printed as a RESOLVED ABSOLUTE path. This
    # is the CLI operator's own terminal, not a network-exposed surface --
    # unlike the /api/board payload's `roots[]` array, which deliberately
    # withholds every root's filesystem path (design note §3.1: keeps a
    # localhost HTTP surface from leaking the user's directory layout).
    # That withholding is scoped to `roots[]` specifically, not the whole
    # payload -- GET /api/issue/<id>'s `path` field (PT-10, unchanged by
    # PT-3) already carries a real on-disk path for any root, primary or
    # secondary; seceng's nit (2026-08-21) was this comment overclaiming
    # "the payload" withholds path info in general, which it doesn't.
    if len(roots) > 1:
        print("Serving across multiple roots:", file=sys.stderr)
        for root in roots:
            marker = " (primary)" if root.primary else ""
            print(f"  {root.id}: {root.path.resolve()}{marker}", file=sys.stderr)

    server = make_server(data_dir, config, port, roots=roots)
    bound_port = server.server_address[1]
    print(f"Serving cairn board at http://127.0.0.1:{bound_port}/")
    print(f"  Kanban:    http://127.0.0.1:{bound_port}/")
    print(f"  List:      http://127.0.0.1:{bound_port}/list")
    print(f"  Dashboard: http://127.0.0.1:{bound_port}/dashboard")
    print("\nCtrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    # default=SUPPRESS (PT-9): when --data-dir isn't given after the
    # subcommand, this parser must not set the dest at all, so the
    # subparsers dispatch (which parses into a *new* namespace and copies
    # every key back onto the parent, per argparse's _SubParsersAction)
    # doesn't stomp a value the top-level --data-dir already set. See
    # build_arg_parser's top-level --data-dir for the precedence contract.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", dest="data_dir", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(prog="cairn", description="cairn — the file-based issue tracker")
    parser.add_argument(
        "--data-dir", dest="data_dir", default=None,
        help="path to the cairn data dir (default: walk up from cwd for process/cairn/). "
             "May be given here (before the subcommand) or after it — if given in both "
             "places, the value after the subcommand takes precedence.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", parents=[common], help="create a new issue")
    p_new.add_argument("title")
    p_new.add_argument("--milestone", default=None)
    p_new.add_argument("--assignee", default=None)
    p_new.add_argument("--status", default=DEFAULT_STATUS, choices=sorted(STATUSES))
    p_new.add_argument("--parent", default=None)
    p_new.add_argument("--priority", default=None)
    p_new.add_argument("--labels", default=None, help="comma-separated")
    p_new.add_argument("--blocked-by", default=None, help="comma-separated issue ids")
    p_new.set_defaults(func=cmd_new)

    p_ls = sub.add_parser("ls", parents=[common], help="list issues")
    p_ls.add_argument("--status", default=None)
    p_ls.add_argument("--milestone", default=None)
    p_ls.add_argument("--assignee", default=None)
    p_ls.set_defaults(func=cmd_ls)

    p_set = sub.add_parser("set", parents=[common], help="set frontmatter fields on an issue")
    p_set.add_argument("id")
    p_set.add_argument("assignments", nargs="+", help="key=value pairs")
    p_set.set_defaults(func=cmd_set)

    p_comment = sub.add_parser("comment", parents=[common], help="append a comment to an issue")
    p_comment.add_argument("id")
    p_comment.add_argument("--author", required=True)
    p_comment.add_argument("--body", required=True, help="comment text, or '-' to read from stdin")
    p_comment.set_defaults(func=cmd_comment)

    p_show = sub.add_parser("show", parents=[common], help="print a single issue")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_archive = sub.add_parser(
        "archive", parents=[common],
        help="move done/cancelled issues (or a done/cancelled milestone/major) to archive/",
    )
    # PT-39 (architect's ruling § 5): exactly one selector, required,
    # mutually exclusive -- --milestone/--major are new, --done-before is
    # the pre-existing (previously standalone-required) flag.
    archive_selector = p_archive.add_mutually_exclusive_group(required=True)
    archive_selector.add_argument("--done-before", default=None, help="YYYY-MM-DD")
    archive_selector.add_argument(
        "--milestone", default=None, help="archive a done/cancelled milestone and its done/cancelled issues",
    )
    archive_selector.add_argument(
        "--major", default=None, help="archive a done/cancelled major and its milestones (each per --milestone)",
    )
    p_archive.add_argument(
        "--dry-run", action="store_true", help="preview without moving anything (all three selectors)",
    )
    p_archive.set_defaults(func=cmd_archive)

    p_check = sub.add_parser("check", parents=[common], help="lint the data dir")
    p_check.set_defaults(func=cmd_check)

    # PT-28 (architect's ruling § 5): a NAMED migration, not a bare
    # "migrate" -- each one-shot tracker migration gets its own
    # sub-subcommand under `migrate`, so an invocation in a shell history
    # or a runbook still means one specific thing regardless of which
    # cairn version wrote it.
    p_migrate = sub.add_parser("migrate", parents=[common], help="run a one-shot tracker migration")
    migrate_sub = p_migrate.add_subparsers(dest="migration", required=True)
    p_migrate_prefix_ids = migrate_sub.add_parser(
        "prefix-ids", parents=[common],
        help="prefix bare major/milestone ids with the configured prefix: (PT-28)",
    )
    p_migrate_prefix_ids.add_argument(
        "--dry-run", action="store_true", help="preview the plan without writing or renaming anything",
    )
    p_migrate_prefix_ids.set_defaults(func=cmd_migrate_prefix_ids)
    p_migrate_lifecycle_status = migrate_sub.add_parser(
        "lifecycle-status", parents=[common],
        help="unify milestone/major status onto RECORD_STATUSES: completed->done, active->in-progress (PT-39)",
    )
    p_migrate_lifecycle_status.add_argument(
        "--dry-run", action="store_true", help="preview the plan without writing anything",
    )
    p_migrate_lifecycle_status.set_defaults(func=cmd_migrate_lifecycle_status)
    p_migrate_archive_issues = migrate_sub.add_parser(
        "archive-issues", parents=[common],
        help="move legacy flat archive/*.md issues into archive/issues/ (PT-50)",
    )
    p_migrate_archive_issues.add_argument(
        "--dry-run", action="store_true", help="preview the plan without moving anything",
    )
    p_migrate_archive_issues.set_defaults(func=cmd_migrate_archive_issues)

    p_snapshot = sub.add_parser(
        "snapshot", parents=[common],
        help="render a point-in-time markdown snapshot of the tracker to stdout",
    )
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_serve = sub.add_parser("serve", parents=[common], help="run the board server")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument(
        "--repos", default=None,
        help="comma-separated root paths (relative to the repo root, or absolute) -- "
             "REPLACES config.yml's roots: list entirely; the primary root is always included",
    )
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CairnError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
