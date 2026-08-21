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
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DEFAULT_PORT = 8766
DEFAULT_COLUMNS = ["backlog", "todo", "in-progress", "in-review", "done"]
STATUSES = {"backlog", "todo", "in-progress", "in-review", "done", "cancelled"}
DEFAULT_STATUS = "backlog"
PRIORITIES = {"P0", "P1", "P2", "P3"}

ISSUE_FIELD_ORDER = [
    "id", "title", "status", "milestone", "parent", "assignee",
    "labels", "priority", "pr", "created", "updated",
]

COMMENTS_HEADING_RE = re.compile(r"^## Comments\s*$")
COMMENT_DELIM_RE = re.compile(r"^### @([a-z0-9][a-z0-9-]*) — (\d{4}-\d{2}-\d{2})\s*$")
ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-(\d+)$")

BOARD_DIR = Path(__file__).resolve().parent / "board"


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


NULLABLE_FIELDS = ("milestone", "assignee", "parent", "priority", "pr")


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
    heading first if absent), and bump `updated` to today. Returns the new
    frontmatter dict.
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


def load_config(data_dir: Path) -> Dict[str, Any]:
    """Read and parse data_dir/config.yml. Missing keys fall back to defaults."""
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


# --------------------------------------------------------------------------
# Directory scanning helpers
# --------------------------------------------------------------------------

def _dir_glob(d: Path) -> List[Path]:
    return sorted(d.glob("*.md")) if d.exists() else []


def find_issue_path(data_dir: Path, issue_id: str) -> Optional[Path]:
    data_dir = Path(data_dir)
    candidate = data_dir / "issues" / f"{issue_id}.md"
    if candidate.exists():
        return candidate
    candidate = data_dir / "archive" / f"{issue_id}.md"
    if candidate.exists():
        return candidate
    return None


def _read_frontmatter_dict(path: Path) -> Dict[str, Any]:
    frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    return frontmatter


# --------------------------------------------------------------------------
# ID allocation — O_CREAT|O_EXCL atomic claim, retry on race
# --------------------------------------------------------------------------

def _next_id_candidate(data_dir: Path, prefix: str) -> int:
    max_n = 0
    for sub in ("issues", "archive"):
        d = Path(data_dir) / sub
        if not d.exists():
            continue
        for p in d.glob(f"{prefix}-*.md"):
            m = ID_RE.match(p.stem)
            if m and m.group(1) == prefix:
                max_n = max(max_n, int(m.group(2)))
    return max_n + 1


def allocate_and_create_issue(data_dir: Path, fields: Dict[str, Any], max_attempts: int = 50) -> Path:
    """Atomically claim the next free ID and create issues/<PREFIX>-<n>.md.

    `fields` supplies everything except id/created/updated, which this
    function fills in. `prefix` comes from load_config(data_dir)["prefix"].
    """
    data_dir = Path(data_dir)
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
    # concern (resolve_roots), not a lint error. A missing config.yml
    # isn't itself flagged here -- that's out of this function's existing
    # scope, unrelated to PT-3.
    config_path = data_dir / "config.yml"
    if config_path.exists():
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
        if fm.get("title") is not None:
            errors.append(f"{p.stem}: unexpected title {fm['title']!r} -- title is issue-only")
        known_majors.add(p.stem)

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

    for p, fm in parsed_milestones:
        major = fm.get("major")
        if major is None:
            errors.append(f"{p.stem}: missing major")
        elif str(major) not in known_majors:
            errors.append(f"{p.stem}: unknown major {major!r}")

    known_ids = set()
    parsed_issues: List[Tuple[Path, Dict[str, Any]]] = []
    for p in list(_dir_glob(data_dir / "issues")) + list(_dir_glob(data_dir / "archive")):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            errors.append(f"{p.stem}: {e}")
            continue
        parsed_issues.append((p, fm))
        issue_id = fm.get("id")
        if issue_id == p.stem:
            known_ids.add(issue_id)
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
        parent = fm.get("parent")
        if parent is not None and parent not in known_ids:
            errors.append(f"{label}: dangling parent {parent!r}")
        priority = fm.get("priority")
        if priority is not None and priority not in PRIORITIES:
            errors.append(f"{label}: unknown priority {priority!r}")

    return errors


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
    status_order = list(DEFAULT_COLUMNS) + ["cancelled"]
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

def build_board_payload(data_dir: Path) -> Dict[str, Any]:
    """{"majors": [...], "milestones": [...], "issues": [...]}.

    Board issues carry no "comments" key (spec: "without comment bodies").
    """
    data_dir = Path(data_dir)
    majors = [_read_frontmatter_dict(p) for p in _dir_glob(data_dir / "majors")]
    milestones = [_read_frontmatter_dict(p) for p in _dir_glob(data_dir / "milestones")]

    pairs = [(p, _read_frontmatter_dict(p)) for p in _dir_glob(data_dir / "issues")]
    child_counts: Dict[str, int] = {}
    for _, fm in pairs:
        parent = fm.get("parent")
        if parent:
            child_counts[parent] = child_counts.get(parent, 0) + 1

    issues = []
    for path, fm in pairs:
        issue = dict(fm)
        issue["seen"] = get_seen(path)
        issue["sub_issue_count"] = child_counts.get(fm.get("id"), 0)
        issue["path"] = str(path)  # PT-10: same contract as build_issue_payload's "path"
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
    return issue


def compute_etag(data_dir: Path) -> str:
    data_dir = Path(data_dir)
    hasher = hashlib.sha256()
    for sub in ("majors", "milestones", "issues"):
        for p in _dir_glob(data_dir / sub):
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


def build_multi_board_payload(roots: List[Root], warnings: List[Dict[str, str]]) -> Dict[str, Any]:
    """Aggregate `build_board_payload` across every root, stamping
    `record["repo"] = root.id` on every major/milestone/issue.

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
    """
    all_warnings = list(warnings)
    majors: List[Dict[str, Any]] = []
    milestones: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    for root in roots:
        try:
            payload = build_board_payload(root.path)
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

    return {
        "roots": [{"id": r.id, "label": r.label, "primary": r.primary} for r in roots],
        "warnings": all_warnings,
        "majors": majors,
        "milestones": milestones,
        "issues": issues,
    }


def compute_multi_etag(roots: List[Root]) -> str:
    """Fold `compute_etag` over every root -- correct with no key-collision
    risk, since `compute_etag` already hashes each file's full path (which
    differs across roots) plus its mtime."""
    hasher = hashlib.sha256()
    for root in roots:
        hasher.update(compute_etag(root.path).encode("utf-8"))
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

_WATCHED_SUBDIRS = ("majors", "milestones", "issues", "archive")


def scan_data_dir(data_dir: Path) -> Dict[str, int]:
    """{"<subdir>/<file>.md": mtime_ns} across majors/milestones/issues/
    archive -- the same directory set check_repo and build_board_payload
    already walk, via the same _dir_glob (so mkstemp's hidden ".*.tmp"
    temp files, which don't match "*.md", never show up as a false
    "change" mid-write). Missing subdirs are tolerated, mirroring
    _dir_glob's "if d.exists() else []".
    """
    data_dir = Path(data_dir)
    snapshot: Dict[str, int] = {}
    for sub in _WATCHED_SUBDIRS:
        for p in _dir_glob(data_dir / sub):
            try:
                snapshot[f"{sub}/{p.name}"] = p.stat().st_mtime_ns
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
# HTTP server — a lens, not a source of truth. No state held here.
# --------------------------------------------------------------------------

def make_server(
    data_dir: Path,
    config: Optional[Dict[str, Any]] = None,
    port: Optional[int] = None,
    roots: Optional[List[Root]] = None,
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
    """
    data_dir = Path(data_dir)
    if config is None:
        config = load_config(data_dir)
    if port is None:
        port = int(os.environ.get("CAIRN_PORT", config.get("port", DEFAULT_PORT)))
    if roots is None:
        roots, root_warnings = resolve_roots(data_dir, config)
    else:
        root_warnings = []
    host = "127.0.0.1"

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
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel_path: str) -> None:
            target = (BOARD_DIR / rel_path).resolve()
            try:
                target.relative_to(BOARD_DIR.resolve())
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
            }.get(target.suffix, "application/octet-stream")
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
                etag = compute_multi_etag(roots)
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                payload = build_multi_board_payload(roots, root_warnings)
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
                payload["read_only"] = not owning_root.primary
                self._send_json(200, payload)
                return
            if path == "/api/events":
                self._handle_sse()
                return
            if path in ("/", "/list"):
                self._send_static("board.html")
                return
            if path.startswith("/board/"):
                self._send_static(path[len("/board/"):])
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
            new_path = allocate_and_create_issue(data_dir, fields)
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
    if key == "labels":
        return [v.strip() for v in value.split(",") if v.strip()]
    if key in NULLABLE_FIELDS and value == "":
        return None
    if value.lower() == "null":
        return None
    return value


def cmd_new(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    fields = {
        "title": args.title,
        "status": args.status,
        "milestone": args.milestone,
        "parent": args.parent,
        "assignee": args.assignee,
        "labels": [l.strip() for l in args.labels.split(",") if l.strip()] if args.labels else [],
        "priority": args.priority,
        "pr": None,
    }
    path = allocate_and_create_issue(data_dir, fields)
    frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    print(frontmatter["id"])
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    matched: List[Dict[str, Any]] = []
    for p in _dir_glob(Path(data_dir) / "issues"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            print(f"warning: skipping {p}: {e}", file=sys.stderr)
            continue
        if args.status and fm.get("status") != args.status:
            continue
        if args.milestone and str(fm.get("milestone")) != args.milestone:
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


def cmd_set(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    path = find_issue_path(data_dir, args.id)
    if path is None:
        print(f"error: no such issue: {args.id}", file=sys.stderr)
        return 1
    patch: Dict[str, Any] = {}
    for kv in args.assignments:
        if "=" not in kv:
            print(f"error: expected key=value, got {kv!r}", file=sys.stderr)
            return 1
        key, _, value = kv.partition("=")
        if key not in ISSUE_FIELD_ORDER:
            print(f"error: unknown field {key!r}", file=sys.stderr)
            return 1
        patch[key] = _coerce_cli_value(key, value)
    try:
        apply_patch(path, patch)
    except CairnError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(args.id)
    return 0


def cmd_comment(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    path = find_issue_path(data_dir, args.id)
    if path is None:
        print(f"error: no such issue: {args.id}", file=sys.stderr)
        return 1
    body = sys.stdin.read() if args.body == "-" else args.body
    append_comment(path, args.author, body)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    path = find_issue_path(data_dir, args.id)
    if path is None:
        print(f"error: no such issue: {args.id}", file=sys.stderr)
        return 1
    issue = parse_issue(path.read_text(encoding="utf-8"))
    print(f"{issue.get('id')} — {issue.get('title')}")
    for key in ISSUE_FIELD_ORDER[2:]:
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
    return 0


def _git_mv_or_rename(src: Path, dest: Path) -> None:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "mv", str(src), str(dest)],
            cwd=str(src.parent), capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
    except FileNotFoundError:
        pass
    os.replace(str(src), str(dest))


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


def cmd_archive(args: argparse.Namespace) -> int:
    _validate_done_before(args.done_before)
    data_dir = resolve_data_dir(args)
    archive_dir = Path(data_dir) / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
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
        dest = archive_dir / p.name
        _git_mv_or_rename(p, dest)
        moved += 1
        print(f"archived {fm.get('id', p.stem)}")
    print(f"{moved} issue(s) archived")
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
    print(f"  Kanban: http://127.0.0.1:{bound_port}/")
    print(f"  List:   http://127.0.0.1:{bound_port}/list")
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

    p_archive = sub.add_parser("archive", parents=[common], help="move done/cancelled issues to archive/")
    p_archive.add_argument("--done-before", required=True, help="YYYY-MM-DD")
    p_archive.set_defaults(func=cmd_archive)

    p_check = sub.add_parser("check", parents=[common], help="lint the data dir")
    p_check.set_defaults(func=cmd_check)

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
