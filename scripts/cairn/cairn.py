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
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DEFAULT_PORT = 8766
DEFAULT_COLUMNS = ["backlog", "todo", "in-progress", "in-review", "done"]
STATUSES = {"backlog", "todo", "in-progress", "in-review", "done", "cancelled"}
DEFAULT_STATUS = "backlog"

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

    Fence-aware: a ```-fenced line that looks like a comment delimiter is
    never treated as a real boundary.
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
    in_fence = False
    for line in comment_lines:
        if line.startswith("```"):
            in_fence = not in_fence
            if current is not None:
                acc.append(line)
            continue
        m = None if in_fence else COMMENT_DELIM_RE.match(line)
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


def dump_frontmatter(fields: Dict[str, Any]) -> str:
    """Render `fields` as a '---\\n...---\\n' block in ISSUE_FIELD_ORDER."""
    lines = [f"{key}: {_dump_value(fields.get(key))}" for key in ISSUE_FIELD_ORDER]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` via a same-directory temp file + os.replace."""
    path = Path(path)
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


def get_seen(path: Path) -> str:
    """The `seen` mtime token for `path`: st_mtime_ns as a string."""
    return str(Path(path).stat().st_mtime_ns)


def apply_patch(path: Path, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge `patch` into `path`'s frontmatter and rewrite it in place.

    Sets `updated` to today unless `patch` supplies it explicitly. Body
    bytes after the closing fence are untouched. Returns the new
    frontmatter dict.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    frontmatter.update(patch)
    if "updated" not in patch:
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

    known_milestones = set()
    for p in _dir_glob(data_dir / "milestones"):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        except CairnError as e:
            errors.append(f"{p.stem}: {e}")
            continue
        mid = fm.get("id")
        if mid is None or str(mid) != p.stem:
            errors.append(f"{p.stem}: id {mid!r} does not match filename {p.stem!r}")
        known_milestones.add(p.stem)

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
        status = fm.get("status")
        if status is not None and status not in STATUSES:
            errors.append(f"{label}: unknown status {status!r}")
        milestone = fm.get("milestone")
        if milestone is not None and str(milestone) not in known_milestones:
            errors.append(f"{label}: unknown milestone {milestone!r}")
        parent = fm.get("parent")
        if parent is not None and parent not in known_ids:
            errors.append(f"{label}: dangling parent {parent!r}")

    return errors


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
        issues.append(issue)

    return {"majors": majors, "milestones": milestones, "issues": issues}


def build_issue_payload(data_dir: Path, issue_id: str) -> Optional[Dict[str, Any]]:
    """Frontmatter + description + full comments + seen. None if not found."""
    path = find_issue_path(data_dir, issue_id)
    if path is None:
        return None
    issue = parse_issue(path.read_text(encoding="utf-8"))
    issue["seen"] = get_seen(path)
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
# HTTP server — a lens, not a source of truth. No state held here.
# --------------------------------------------------------------------------

def make_server(data_dir: Path, config: Optional[Dict[str, Any]] = None, port: Optional[int] = None):
    """Build (but do not start) the board's HTTPServer, bound to 127.0.0.1.

    port=0 -> ephemeral (read back via server.server_address[1]).
    port=None -> load_config(data_dir)["port"].
    Caller owns serve_forever() so tests can run it in a thread.
    """
    data_dir = Path(data_dir)
    if config is None:
        config = load_config(data_dir)
    if port is None:
        port = int(os.environ.get("CAIRN_PORT", config.get("port", DEFAULT_PORT)))
    host = "127.0.0.1"

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

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/api/board":
                etag = compute_etag(data_dir)
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                payload = build_board_payload(data_dir)
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
                payload = build_issue_payload(data_dir, issue_id)
                if payload is None:
                    self._send_json(404, {"error": "not_found", "message": f"no such issue: {issue_id}"})
                    return
                self._send_json(200, payload)
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
            issue_path = find_issue_path(data_dir, issue_id)
            if issue_path is None:
                self._send_json(404, {"error": "not_found", "message": f"no such issue: {issue_id}"})
                return

            seen = payload.get("seen")
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

    class Server(http.server.HTTPServer):
        allow_reuse_address = True

    return Server((host, port), Handler)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def resolve_data_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "data_dir", None)
    if explicit:
        return Path(explicit)
    return find_data_dir()


def _coerce_cli_value(key: str, value: str) -> Any:
    if key == "labels":
        return [v.strip() for v in value.split(",") if v.strip()]
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


def cmd_archive(args: argparse.Namespace) -> int:
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


def cmd_serve(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    config = load_config(data_dir)
    port = args.port if args.port is not None else None
    server = make_server(data_dir, config, port)
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
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", dest="data_dir", default=None)

    parser = argparse.ArgumentParser(prog="cairn", description="cairn — the file-based issue tracker")
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

    p_serve = sub.add_parser("serve", parents=[common], help="run the board server")
    p_serve.add_argument("--port", type=int, default=None)
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
