# PT-96 AC4 — per-file mutation table

Ruling (PT-96.md @ fed43a4): "the mutation is uniform (revert that site to the
no-interval `threading.Thread`), so guard 1 is what keeps the table from
being vacuous — it makes an unconverted site impossible, per file."

Sites and file list are `grep`-verified against `_SITE_RE` in
`tests/test_serve_in_thread.py` at b0cc8bd (pre-fix): 20 sites, 14 files —
matches the ruling's measured count exactly.

Mutation (same for every row): revert the converted call site from
`helpers.serve_in_thread(server[, poll_interval=...])` back to
`threading.Thread(target=server.serve_forever, daemon=True)` (no interval
passed, i.e. `serve_forever`'s own 0.5 s default).

Test it turns red (same for every row — a whole-tree scan, not a per-file
guard): `tests/test_serve_in_thread.py::NoRawServeForeverThreadOutsideHelpersTests::test_no_raw_site_remains_outside_helpers_py`.

| file | sites | mutation | test it turns red |
|---|---|---|---|
| test_board_fonts.py | 1 | revert to raw `threading.Thread(target=..., serve_forever)` | `NoRawServeForeverThreadOutsideHelpersTests::test_no_raw_site_remains_outside_helpers_py` |
| test_dashboard.py | 1 | same | same |
| test_dashboard_board_embed.py | 2 | same | same |
| test_dashboard_flow.py | 2 | same | same |
| test_dashboard_roster.py | 2 | same | same |
| test_engine_staleness.py | 1 | same | same |
| test_frontmatter_rewrite.py | 1 | same | same |
| test_migrate_archive_issues.py | 1 | same | same |
| test_multi_root.py | 1 | same | same |
| test_record_mutation.py | 3 | same | same |
| test_root_redirect.py | 1 | same | same |
| test_server.py | 1 | same | same |
| test_show_archived.py | 1 | same | same |
| test_tokens_endpoint.py | 2 | same | same |

**Total: 14 files, 20 sites.**

A green suite after this change is a prompt, not a result (AC3/AC4): the
mutation above, applied to any one of the 20 sites, must turn
`test_no_raw_site_remains_outside_helpers_py` red — verified live once the
conversion lands (gate 3), not asserted here in advance.
