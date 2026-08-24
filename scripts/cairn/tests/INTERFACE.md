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

  **REVERSED 2026-08-19 — fence-awareness is explicitly NOT wanted.** This section originally required `split_comments` to track ` ``` ` fence state and suppress delimiter-shaped lines inside a fence, reasoning that `scripts/cairn/tests/fixtures/process/cairn/issues/PT-1.md`'s fenced `### @not-a-real-author — 2026-01-01` line was a trap to guard against. The architect's conformance review (`temp/2026-08-19-architect-cairn-conformance.md`, finding 4) caught the actual failure mode that reasoning missed: fence-tracking that toggles on every ` ``` ` line and never resets on an *unclosed* fence silently swallows every comment after it for the rest of the file — unbounded, invisible data loss, versus the one-comment-mis-split cost of not tracking fences at all. Team-lead ruled the spec's literal rule stands as canonical: **"a new comment starts at a line matching exactly `<regex>`; any other `###` line is body content"** has no fence exception. `split_comments` must NOT special-case fences — a line matching `COMMENT_DELIM_RE` is a boundary regardless of what's around it, fenced or not. PT-1.md's fenced `### @not-a-real-author — 2026-01-01` line is therefore a real third comment, not a trap to defeat; see the inverted test `test_fenced_delimiter_lookalike_now_splits_per_finding_4_ruling` in `test_issue_parsing.py`, and the new `test_unbalanced_fence_does_not_swallow_later_comments` pinning the actual failure mode.
- `parse_issue(text: str) -> dict` — merges the above: all frontmatter keys, plus `"description"` (== `split_comments(body)[0]`) and `"comments"` (== `split_comments(body)[1]`).
- `load_config(data_dir: Path) -> dict` — reads and parses `data_dir/config.yml`.

## Write-back

- `dump_frontmatter(fields: dict) -> str` — renders `"---\n" + ... + "---\n"` in `ISSUE_FIELD_ORDER`. Quotes any string that would otherwise round-trip as a different type when read back unquoted (numeric-looking milestone slugs like `"1.0"` above all). `None` → bare `null`. Lists → flow syntax.
- `apply_patch(path: Path, patch: dict) -> dict` — merges `patch` into the file's current frontmatter, sets `updated` to today (`date.today().isoformat()`) unless `patch` supplies it explicitly, re-renders via `dump_frontmatter`, writes through a same-directory temp file + `os.replace`. **Body bytes after the closing fence are untouched.** Returns the new frontmatter dict.
- `append_comment(path: Path, author: str, body: str, comment_date: str | None = None) -> dict` — appends one comment to the file tail (inserting a `## Comments` heading first if the file doesn't have one yet), stamped `comment_date or date.today().isoformat()`. Bumps `updated` **only for issue-shaped files** (`_is_issue_shaped`, PT-51 §4's prerequisite fix) — a milestone/major has no `updated` field in its schema at all, so the bump would inject an off-schema key the first time anyone comments on one. Returns the new frontmatter dict.
- `allocate_and_create_issue(data_dir: Path, fields: dict) -> Path` — PT-52: raises `CairnError` before any `O_EXCL` attempt if `legacy_archived_issue_paths(data_dir)` is non-empty (naming the count and the migrate command) — refuses to allocate rather than risk re-issuing an id a legacy-invisible archived issue already holds. Otherwise computes `max(numeric suffixes across data_dir/issues/*.md and archived_issue_paths(data_dir)) + 1` and atomically creates `data_dir/issues/<prefix>-<n>.md` via `O_CREAT|O_EXCL`, retrying `n+1` on collision up to 50 times. `fields` supplies everything except `id`/`created`/`updated`, which this function fills in. `prefix` comes from `load_config(data_dir)["prefix"]`.
- `archived_issue_paths(data_dir: Path) -> List[Path]` — PT-52: every archived issue `.md` file at `data_dir/archive/issues/*.md`. **The legacy flat `data_dir/archive/*.md` leg PT-50 kept for the transition is gone** — the engine does not read it at all. THE single point every archived-issue read site routes through — see [Archive](#archive) in the spec.
- `legacy_archived_issue_paths(data_dir: Path) -> List[Path]` — PT-52: the legacy flat `data_dir/archive/*.md` layout, for exactly two callers — `check_repo`'s lint scan and `migrate_archive_issues`'s source glob — which must never disagree about what counts as legacy.

## Lint

- `check_repo(data_dir: Path) -> list[str]` — pointed, human-readable error strings (mentions the offending file/id); `[]` means clean. Catches per-file `YamlError`/`FrontmatterError` internally rather than propagating.

## Snapshot

- `build_snapshot_markdown(data_dir: Path, generated_at: str | None = None) -> str` — PT-2: a point-in-time markdown rendering of the tracker (majors, milestones/roadmap, issues grouped by status), meant for `cairn snapshot >> process/STATE.md` (offline reading — a plane, a phone, a cold session before the board is up). A RENDERING, never an input; cairn never parses it back. Opens with a header containing the words "generated", "do not edit", and "cairn snapshot" (regeneration instructions) — exact wording is the implementation's choice, those substrings are what tests pin. Must not open with `"---"` (so a misplaced copy can't be mistaken for frontmatter — see `SnapshotNonIngestionTests`). `generated_at` is an injectable override for test determinism (mirrors `append_comment`'s `comment_date` pattern); when `None`, sources a real wall-clock timestamp (this is a CLI-facing function, not a workflow-script-sandbox one — wall-clock is fine here). Everything else must be deterministic given an unchanged tree, independent of on-disk iteration order: majors, then milestones, then issues grouped by status in `DEFAULT_COLUMNS` order (`backlog, todo, in-progress, in-review, done`) + `cancelled` last, each issue sorted **numerically** by id within its status group (not the lexicographic order `_dir_glob` returns — `PT-10` must sort after `PT-2`, not before).
- `cmd_snapshot(args) -> int` — CLI `cairn snapshot`. Prints `build_snapshot_markdown(resolve_data_dir(args))` to stdout (no `generated_at` override — real timestamp). Respects `--data-dir` in both positions per PT-9. Writes nothing to disk; STDOUT only, the caller decides whether/where to redirect (`>> process/STATE.md`).

## Multi-root (PT-3)

Full design: `temp/2026-08-21-architect-pt3-design.md` (architect) — that note is authoritative for this feature; this entry is just the pointer + the bits tests import directly.

- `Root = NamedTuple("Root", [("id", str), ("label", str), ("path", Path), ("primary", bool)])`
- `resolve_roots(data_dir, config, cli_repos=None) -> (List[Root], List[dict])` — never raises for a secondary root; primary (element 0) is always trusted as given. Warning dicts: `{"root": <entry as written>, "reason": <code>, "detail": <str>}`, reason codes per the design note §2.2 (`not_found`, `unreadable`, `bad_config`, `duplicate`, `bad_entry`, `parse_error`).
- `build_multi_board_payload(roots, warnings) -> dict` — `{"roots": [...], "warnings": [...], "majors": [...], "milestones": [...], "issues": [...]}`, every record in the last three stamped `"repo": root.id`. A root whose files include one that fails to parse contributes nothing (not just that file) and adds a `parse_error` warning.
- `compute_multi_etag(roots) -> str` — changes when any root's contents change.
- `find_issue_in_roots(roots, issue_id) -> Optional[Root]` — **must stay a separate function from `find_issue_path`**, and must never be called from `do_POST`'s write path (design note §5 — that separation is the read-only guarantee's structural enforcement, not a runtime check).
- `make_server(data_dir, config=None, port=None, roots=None)` — `roots=None` synthesises the single primary root (back-compat: every existing `test_server.py` call/test keeps working unmodified).
- `DataDirWatcher(roots, broadcaster, interval=1.0)` — takes `roots` (not `data_dir`); per-root scan keys are namespaced (e.g. `"<root.id>:<sub>/<file>.md"`) so identical relative paths across roots (two repos both having `milestones/0.5.md`) can't mask each other's changes.
- Read-only enforcement: `POST /api/issue/<id>` for an id that resolves to a secondary root → `403 {"error": "read_only_root", "message": "..."}`, and the secondary file is untouched. `GET /api/issue/<id>` stamps `"read_only": not root.primary` in addition to `"repo"`.
- `--repos` (team-lead ruling B, 2026-08-21): **REPLACES** `config["roots"]` entirely (not a union) — `resolve_roots(data_dir, config, cli_repos=[...])`. The primary root is always included regardless. `cli_repos=None` defers to `config["roots"]`; `cli_repos=[]` is an explicit "no secondaries" override, distinct from `None`. Unlike `config["roots"]` entries (must be relative, §4.1), `cli_repos` entries **may be absolute** (§4.3, ad-hoc/uncommitted so portability doesn't apply) — `resolve_roots` only rejects an absolute entry when it came from `config["roots"]`.
- `check_repo` (team-lead ruling C, 2026-08-21): validates `config.yml`'s `roots:` **shape only** — must be a list; each entry a non-empty, relative path string. Never checks reachability (that's `resolve_roots`'s runtime warn-and-skip job) — a sibling repo absent on a given clone/CI machine is not a lint error.

Swimlane/major-tab grouping when milestone ids collide across roots (§7-A) is ruled (repo-grouped, nested) but not yet server-testable — it's a `board.js`-only concern, out of this file's scope by construction.

## Engine staleness (PT-49)

Design + full rationale: `process/cairn/issues/PT-49.md`'s `@architect` ruling comment — authoritative; this entry is just the bits tests import directly.

- `engine_fingerprint(source_path: Path) -> dict` — `{"sha": sha256(bytes)[:12], "mtime_ns": int, "size": int}` for `source_path`. Content hash, not a git hash. Raises `OSError` if `source_path` can't be read (only called on a path expected to exist — the boot call in `make_server`, or a test's own fixture file).
- `engine_is_stale(source_path: Path, boot: dict) -> bool` — the two-tier self-check: `os.stat` first, `(mtime_ns, size)` equal to `boot` → `False` with no read; different → hash and compare `sha`; only a differing `sha` is `True`. Missing/unreadable `source_path` → `False` (never raises, never invents an alarm), one stderr line.
- `build_multi_board_payload(roots, warnings, archived=False, engine=None) -> dict` — new `engine` param, embedded verbatim under the `"engine"` key when not `None` (omitted entirely when `None` — every pre-PT-49 caller/test keeps working unmodified). The real `/api/board` handler always supplies it; computing the dict (fingerprint + `engine_is_stale`) is the caller's job, not this function's.
- `compute_multi_etag(roots, archived=False, boot_sha=None, source_path=None) -> str` — new `boot_sha`/`source_path` params, folded into the hasher ONCE at the top (not per root) when either is given; both `None` (back-compat default) skips the fold entirely, byte-identical to the pre-PT-49 etag. This fold is why a stale flip with no data-file change still changes the etag — without it the client would 304 forever and the banner would never appear.
- `make_server(data_dir, config=None, port=None, roots=None, source_path=Path(__file__)) -> HTTPServer` — new `source_path` param (§9's required test seam): defaults to `cairn.py`'s own file so a real server needs no caller effort, but overridable so a test can fingerprint/rewrite a throwaway file instead of the live, imported module. Fingerprinted exactly once at construction (the "boot" fingerprint); `/api/board`'s handler re-checks it via `engine_is_stale` on every build.
- `Handler._send_static` now sends `Cache-Control: no-store` on every static asset (`/board/*`) — matches what `/api/board` already sent. No client-side asset-version handshake; not testable as a separate unit, covered via `ServerTestCase`-style HTTP tests only.

## Record mutation (PT-51)

Design + full rationale: `process/cairn/issues/PT-51.md`'s `@architect` ruling comment (§1-§7) — authoritative; this entry is just the bits tests import directly.

- `find_record_path(data_dir, record_id) -> Optional[Path]` — pre-existing (PT-39, `cairn set`'s resolver), documented here for the first time since PT-51 gives it an HTTP caller. Resolves against `_RECORD_SEARCH_SUBDIRS` (issues, then milestones, then majors, live before archived, each) — an ISSUE id resolves too, which is exactly why `POST /api/record/<id>` must reject one with `400 wrong_endpoint` rather than silently writing it (see below).
- `find_record_in_roots(roots, record_id) -> Optional[Root]` — the `find_record_path` sibling of `find_issue_in_roots`, same contract: used ONLY to distinguish `403 read_only_root` from `404` in the HTTP handler, never to locate a file to write. `find_record_path` (`data_dir`-scoped) stays the only resolver `_mutate_record` can reach.
- `build_record_payload(data_dir, record_id) -> Optional[dict]` — the milestone/major analog of `build_issue_payload`; single-file, `O(1)`. Adds `archived`, `body` (pre-`## Comments`, via `split_comments`), `comments`, `seen`, `path`, and (milestones only) `released` (via `_release_status`, shared with `build_board_payload`'s own milestone loop — one derivation, not two). `None` when `record_id` resolves nowhere.
- `_validate_record_patch(schema, patch) -> Optional[dict]` — `schema` is `"milestone"` or `"major"` (from `_record_schema_for_path`). Returns a `{"error": "bad_request", "message": ...}` body, or `None` when clean. Checks `patch`'s keys against `_RECORD_BOARD_EDITABLE_FIELDS[schema]` (narrower than `_RECORD_FIELD_ORDER` — `id`/milestone `kind` are legal CLI fields but excluded here, so "unknown field" and "id/kind rejected" are the same check, not two), then `status` against `RECORD_STATUSES`, `health` against the new `MAJOR_HEALTH_VALUES` (major only), and `ga` against `isinstance(..., bool)` (milestone only, since a JS `<select>`'s value is always a string — the client-side DOM boundary coerces it to a real JSON bool before sending). Cross-record invariants (GA cap, `target_tag` shape, `major:` resolving) are NOT checked here — `cairn check` is the backstop.
- `NULLABLE_FIELDS` extended with `target_tag`, `owner`, `target_ship` — the record schema's own "(text, nullable)" board-editable fields get the same `"" -> None` coercion the issue fields already had; safe to share one tuple/one `apply_patch` code path since none of the three names collides with an issue field.
- `POST /api/record/<id>` (`Handler._mutate_record`) — the milestone/major sibling of `_mutate_issue`, a SEPARATE endpoint (never a widening of `/api/issue/<id>` — `find_issue_path` stays the only resolver that path can reach, PT-3/PT-39's structural read-only guarantee). Six checks, in this order: (1) resolve → `403 read_only_root` / `404 not_found`; (2) an issue id → `400 wrong_endpoint`; (3) archived → `403`, before the seen comparison; (4) `seen` missing → `400`, then the same `write_lock` critical section as `_mutate_issue`, mismatch → `409 {"error": "stale", "current": <build_record_payload(...)>}`; (5) `patch` → `_validate_record_patch` → `apply_patch`; (6) `comment` → `append_comment`. `200` returns `build_record_payload(...)`, same shape as the `409`'s `current`.
- `cmd_comment` — resolver switched `find_issue_path` → `find_record_path`, error string `"no such issue"` → `"no such record"`. Works uniformly on issues, milestones, majors, live or archived — matching `cmd_set`'s existing reach.

## CLI

- `main(argv: list[str]) -> int` — argparse-based. Global `--data-dir PATH` flag (tests always pass it explicitly). Subcommands: `new`, `ls`, `set`, `comment`, `show`, `archive`, `check`, `serve` — flags per the CLI table in the spec. Returns a process exit code.
- `scripts/cairn/cairn` — bash shim: `exec python3 "$(dirname "$0")/cairn.py" "$@"`.

## Server

- `build_board_payload(data_dir: Path) -> dict` — `{"majors": [...], "milestones": [...], "issues": [...]}`. Board issues have **no `"comments"` key** (spec: "without comment bodies"). Milestones/majors DO carry `"comments"` (PT-51 §2) plus `"seen"` — `"body"` is the pre-`## Comments` half via `split_comments`, byte-identical to the pre-PT-51 value for any record with no Comments section yet.
- `build_issue_payload(data_dir: Path, issue_id: str) -> dict` — frontmatter + `"description"` + full `"comments"` + `"seen"` (string form of `st_mtime_ns`).
- `build_record_payload(data_dir: Path, record_id: str) -> dict | None` — the milestone/major analog of `build_issue_payload` (PT-51 §1/§2) — see the Record mutation section above.
- `make_server(data_dir: Path, config: dict | None = None, port: int | None = None, roots: list[Root] | None = None, source_path: Path = Path(__file__)) -> http.server.HTTPServer` — binds `127.0.0.1`, does **not** call `serve_forever()` (caller's job, so tests can thread it). `port=0` → ephemeral, read back via `server.server_address[1]`. `port=None` → `load_config(data_dir)["port"]`. `roots=None` (PT-3) synthesises the single primary root via `resolve_roots(data_dir, config)` — every pre-PT-3 caller (including every `test_server.py` test) is therefore exercised by the same code path multi-root uses, unmodified. Routes: `GET /api/board` (ETag/If-None-Match → 304, now roots-aware via `compute_multi_etag`/`build_multi_board_payload`), `GET /api/issue/<id>` (roots-aware via `find_issue_in_roots`, stamps `repo`/`read_only`), `POST /api/issue`, `POST /api/issue/<id>` (409 on stale `seen`; 403 `read_only_root` for a secondary-root id — see Multi-root section), `POST /api/record/<id>` (PT-51 — see Record mutation section above), plus static `GET /`, `/list`, `/board/*`.

## Running the suite

```
python3 -m unittest discover scripts/cairn/tests
```

from the repo root. Tests add `scripts/cairn/` to `sys.path` themselves (see `helpers.py`) so this works regardless of `cairn.py`'s existence or the caller's cwd.
