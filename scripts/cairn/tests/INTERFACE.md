# cairn.py — interface contract assumed by the test suite

This is not part of the spec (`process/TRACKER.md`); it is the concrete API surface
the tests in this directory import and call. The spec describes *behavior*, not
Python function names — someone has to pick names, and the tests need to pick the
same ones the implementation does. This file is that agreement.

If you (implementation-lead) find a function here awkward to implement as named,
change the name/signature and update this file in the same commit as the test fix —
just keep spec-compliance the north star, not this file's word choice.

## Module layout

Everything lives in `scripts/cairn/cairn.py`, a single stdlib-only module, executable
both as `python3 cairn.py ...` and via the bash shim `scripts/cairn/cairn`.

## Constants

- `ISSUE_FIELD_ORDER` — `["id", "title", "status", "milestone", "parent", "assignee", "labels", "priority", "pr", "created", "updated"]`, the canonical key order `dump_frontmatter` must emit (matches the Frontmatter schema table in the spec).
- `STATUSES` — `{"backlog", "todo", "in-progress", "in-review", "done", "cancelled"}`.
- `DEFAULT_STATUS` — `"backlog"`. Inferred: the spec doesn't state `cairn new`'s default status explicitly, but the CLI table's own example (`--status backlog`) and the vocabulary table's description of `backlog` ("Scoped, not queued" — the natural state of something just jotted down) both point here. Tests assert this default.
- `COMMENT_DELIM_RE` — compiled `re.compile(r'^### @([a-z0-9][a-z0-9-]*) — (\d{4}-\d{2}-\d{2})\s*$')`. The em dash (`—`, U+2014) is required, not a hyphen.

## Exceptions

- `YamlError(Exception)` — raised by `parse_yaml_subset` on anything outside the documented subset.
- `FrontmatterError(Exception)` — raised by `parse_frontmatter` when the `---`/`---` fences are missing or malformed.
- `ConflictError(Exception)` — raised by the server-side patch path on a stale `seen` token. Carries `.current: dict`, the on-disk payload at conflict time, so the HTTP layer can render the spec's 409 body directly.

## Parsing

- `parse_yaml_subset(text: str) -> dict` — parses a **fenceless** YAML-subset mapping (no surrounding `---` lines) into a dict, insertion order preserved. Supports: bare scalars (bare `true`/`false` → `bool`, bare integers → `int`, bare `null` → `None`, anything else bare → `str`), single/double-quoted strings (**always** `str`, even numeric-looking — `"1.0"` stays `"1.0"`, never `1.0` the float), flow lists (`[a, b]` → `["a", "b"]`, `[]` → `[]`), block lists (`- item` under a key), and **one or more levels of nested mappings via indentation** (see ruling below). Raises `YamlError` on: anchors (`&x`), aliases (`*x`), tags (`!!str`), flow mappings (`{a: b}`), block scalars (`|`, `>`), or any other construct outside this list.

  **Ruling — nested mappings are in-subset, not out-of-subset**, despite the spec's "errors loudly on anything else" line appearing to ban them. Evidence: `config.yml`'s own worked example in the spec nests `board: {columns: [...], swimlane: ...}` one level deep, and that file is parsed by this exact function. Reading "nested maps" in the banned list as referring to structure *beyond* what the four documented file shapes (issue/milestone/major frontmatter, `config.yml`) actually use — not to `config.yml`'s own nesting — is the only reading consistent with the spec's own example. Two-plus levels of nesting are still untested/unsupported since no example needs them; treat deeper nesting as a loud-error case if you have to choose.

- `parse_frontmatter(text: str) -> tuple[dict, str]` — `text` is a whole file's contents. Requires the first line to be exactly `---` and a later line to be exactly `---`; returns `(frontmatter_dict, body)` where `body` is **everything after the closing fence's newline, byte-for-byte**. Raises `FrontmatterError` if the fences are missing.
- `split_comments(body: str) -> tuple[str, list[dict]]` — splits on the first line matching `^## Comments\s*$`. Returns `(pre_comments_text, comments)`; each comment is `{"author": str, "date": "YYYY-MM-DD", "body": str}`, oldest first. No `## Comments` heading → `(body, [])`.

  **Fence-awareness is required, not optional.** `COMMENT_DELIM_RE` matches a *line's shape*; it does not know about markdown code fences. The spec's own trap case — "code fences containing delimiter-looking lines" — is a real hazard with a naive `re.MULTILINE.finditer` over the whole comment log: a fixture line inside a ` ``` ` block that happens to look like `### @foo — 2026-01-01` **will** match the regex. `split_comments` must track fence state line-by-line (toggle on a line matching `^```` `) and only treat a `COMMENT_DELIM_RE` match as a real boundary when not currently inside a fence. `scripts/cairn/tests/fixtures/process/cairn/issues/PT-1.md` exercises exactly this — verified by hand that a naive whole-body regex scan over it finds a false third delimiter inside the fence.
- `parse_issue(text: str) -> dict` — merges the above: all frontmatter keys, plus `"description"` (== `split_comments(body)[0]`) and `"comments"` (== `split_comments(body)[1]`).
- `load_config(data_dir: Path) -> dict` — reads and parses `data_dir/config.yml`.

## Write-back

- `dump_frontmatter(fields: dict) -> str` — renders `"---\n" + ... + "---\n"` in `ISSUE_FIELD_ORDER`. Quotes any string that would otherwise round-trip as a different type when read back unquoted (numeric-looking milestone slugs like `"1.0"` above all). `None` → bare `null`. Lists → flow syntax.
- `apply_patch(path: Path, patch: dict) -> dict` — merges `patch` into the file's current frontmatter, sets `updated` to today (`date.today().isoformat()`) unless `patch` supplies it explicitly, re-renders via `dump_frontmatter`, writes through a same-directory temp file + `os.replace`. **Body bytes after the closing fence are untouched.** Returns the new frontmatter dict.
- `append_comment(path: Path, author: str, body: str, comment_date: str | None = None) -> dict` — appends one comment to the file tail (inserting a `## Comments` heading first if the file doesn't have one yet), stamped `comment_date or date.today().isoformat()`. Also bumps `updated` (comment activity is an update). Returns the new frontmatter dict.
- `allocate_and_create_issue(data_dir: Path, fields: dict) -> Path` — computes `max(numeric suffixes across data_dir/issues/*.md and data_dir/archive/*.md) + 1` and atomically creates `data_dir/issues/<prefix>-<n>.md` via `O_CREAT|O_EXCL`, retrying `n+1` on collision up to 50 times. `fields` supplies everything except `id`/`created`/`updated`, which this function fills in. `prefix` comes from `load_config(data_dir)["prefix"]`.

## Lint

- `check_repo(data_dir: Path) -> list[str]` — pointed, human-readable error strings (mentions the offending file/id); `[]` means clean. Catches per-file `YamlError`/`FrontmatterError` internally rather than propagating.

## CLI

- `main(argv: list[str]) -> int` — argparse-based. Global `--data-dir PATH` flag (tests always pass it explicitly). Subcommands: `new`, `ls`, `set`, `comment`, `show`, `archive`, `check`, `serve` — flags per the CLI table in the spec. Returns a process exit code.
- `scripts/cairn/cairn` — bash shim: `exec python3 "$(dirname "$0")/cairn.py" "$@"`.

## Server

- `build_board_payload(data_dir: Path) -> dict` — `{"majors": [...], "milestones": [...], "issues": [...]}`. Board issues have **no `"comments"` key** (spec: "without comment bodies").
- `build_issue_payload(data_dir: Path, issue_id: str) -> dict` — frontmatter + `"description"` + full `"comments"` + `"seen"` (string form of `st_mtime_ns`).
- `make_server(data_dir: Path, config: dict | None = None, port: int | None = None) -> http.server.HTTPServer` — binds `127.0.0.1`, does **not** call `serve_forever()` (caller's job, so tests can thread it). `port=0` → ephemeral, read back via `server.server_address[1]`. `port=None` → `load_config(data_dir)["port"]`. Routes: `GET /api/board` (ETag/If-None-Match → 304), `GET /api/issue/<id>`, `POST /api/issue`, `POST /api/issue/<id>` (409 on stale `seen`, per spec's example body shape), plus static `GET /`, `/list`, `/board/*`.

## Running the suite

```
python3 -m unittest discover scripts/cairn/tests
```

from the repo root. Tests add `scripts/cairn/` to `sys.path` themselves (see `helpers.py`) so this works regardless of `cairn.py`'s existence or the caller's cwd.
