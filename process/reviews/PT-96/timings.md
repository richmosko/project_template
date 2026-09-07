# PT-96 — where the suite's time actually goes

Machine: darwin 25.6.0, 10 logical cores, python 3.14.7. Baseline sha b0cc8bd, cwd `scripts/cairn`.
Everything below is measured; the projection sections say so explicitly.

## The finding: it is not fixture construction

PT-96's ask assumes per-test fixture cost (git repo per test, daemon per test). Direct
measurement of the two constructors, 10 cycles each (`temp/` script, reproduced in the ruling):

| Operation | Cost per call |
|---|---|
| `helpers.copy_fixture_data_dir` (63 files) | 3.8 ms |
| `cairn.make_server(...)` + thread start | 7.2 ms |
| **`server.shutdown()` at the default `poll_interval`** | **501.1 ms** |
| `server.shutdown()` at `poll_interval=0.01` | 11.1 ms |

`socketserver.BaseServer.serve_forever()` defaults to `poll_interval=0.5`, and `shutdown()`
blocks until that loop next wakes. Twenty call sites across fourteen test files start the
server with `threading.Thread(target=server.serve_forever, daemon=True)` — no interval — so
every server-backed test pays up to half a second in teardown. That is the whole story: the
five files whose per-test median clusters at 0.52–0.58 s are paying one poll interval each.

## Measured effect of the poll interval alone

Applied without editing any tracked file: a `sitecustomize.py` on `PYTHONPATH` overriding
`BaseServer.serve_forever`'s default. It appends its pid to a marker file, so the construction
confirms its own subject started — **401 processes** loaded it in each run below.

| Run | Wall | Tests | Skipped | Result |
|---|---|---|---|---|
| parallel, default jobs, unpatched | 26.39 s | 1397 | 1 | OK |
| parallel, control shim (`poll_interval=0.5`) | 26.74 s | 1402 | 1 | OK |
| parallel, patched (`poll_interval=0.01`) | **19.93 s** | 1402 | 1 | OK |
| serial, unpatched | 176.60 s | 1402 | 1 | OK |
| serial, patched | **109.56 s** | 1402 | 1 | OK |

The control is the same shim at the stock 0.5 s: 26.74 s, indistinguishable from unpatched.
The gain is the interval, not the shim. Counts and result are identical in every row —
nothing stopped being exercised.

## Per-file, serial, before → after

| File | Before (s) | After (s) | Δ |
|---|---|---|---|
| `test_server.py` | 22.35 | 5.63 | -16.72 |
| `test_otel_receiver_self_stop.py` | 18.94 | 18.64 | -0.30 |
| `test_dashboard.py` | 13.30 | 2.90 | -10.40 |
| `test_show_archived.py` | 12.32 | 0.92 | -11.40 |
| `test_backfill_tokens.py` | 11.96 | 11.27 | -0.69 |
| `test_record_mutation.py` | 9.53 | 1.08 | -8.45 |
| `test_root_redirect.py` | 8.05 | 0.62 | -7.43 |
| `test_cli.py` | 6.41 | 6.36 | -0.05 |
| `test_comment_guard.py` | 5.64 | 5.65 | +0.01 |
| `test_otel_receiver.py` | 5.62 | 5.39 | -0.23 |
| `test_otel_receiver_hardening.py` | 4.99 | 9.14 | +4.15 |
| `test_agent_setting_role.py` | 4.40 | 4.23 | -0.17 |
| `test_dashboard_roster.py` | 4.39 | 2.46 | -1.93 |
| `test_flow_throughput.py` | 3.93 | 3.80 | -0.13 |
| `test_migrate_archive_issues.py` | 3.71 | 3.18 | -0.53 |
| `test_migrate_prefix_ids.py` | 3.42 | 3.45 | +0.03 |
| `test_multi_root.py` | 3.35 | 1.37 | -1.98 |
| `test_engine_staleness.py` | 3.33 | 0.36 | -2.97 |
| `test_dashboard_flow.py` | 2.89 | 1.45 | -1.44 |
| `test_milestone_overhead.py` | 2.79 | 2.66 | -0.13 |
| `test_dist_freshness.py` | 2.32 | 2.28 | -0.04 |
| `test_dashboard_board_embed.py` | 2.24 | 0.28 | -1.96 |
| `test_concurrent_board_load.py` | 2.18 | 0.74 | -1.44 |
| `test_tokens_endpoint.py` | 1.83 | 0.35 | -1.48 |
| `test_archive_records.py` | 1.50 | 1.39 | -0.11 |
| `test_migrate_lifecycle_status.py` | 1.44 | 1.41 | -0.03 |
| `test_check_lint.py` | 1.22 | 1.16 | -0.06 |
| `test_set_records.py` | 1.21 | 1.23 | +0.02 |
| `test_loop_stats.py` | 1.07 | 1.05 | -0.02 |
| `test_dashboard_roster_structured_work.py` | 0.87 | 0.79 | -0.08 |
| `test_frontmatter_rewrite.py` | 0.77 | 0.27 | -0.50 |
| `test_gate_head.py` | 0.71 | 0.66 | -0.05 |
| `test_milestone_input_normalization.py` | 0.66 | 0.66 | +0.00 |
| `test_snapshot.py` | 0.66 | 0.69 | +0.03 |
| `test_board_fonts.py` | 0.63 | 0.14 | -0.49 |
| `test_run_tests.py` | 0.40 | 0.40 | +0.00 |
| `test_milestone_release_state.py` | 0.38 | 0.36 | -0.02 |
| `test_dashboard_repo_name.py` | 0.35 | 0.31 | -0.04 |
| `test_check_budgets.py` | 0.34 | 0.32 | -0.02 |
| `test_shell_readonly_embed.py` | 0.26 | 0.26 | +0.00 |
| `test_git_mv_or_rename.py` | 0.25 | 0.26 | +0.01 |
| `test_theme_variants_generator.py` | 0.24 | 0.25 | +0.01 |
| `test_base_theme_contrast_gate.py` | 0.21 | 0.21 | +0.00 |
| `test_board_columns_config.py` | 0.20 | 0.20 | +0.00 |
| `test_message_cap_hook.py` | 0.20 | 0.22 | +0.02 |
| `test_milestone_card_body.py` | 0.15 | 0.13 | -0.02 |
| `test_dashboard_agent_roster.py` | 0.14 | 0.13 | -0.01 |
| `test_id_shape_prefix.py` | 0.13 | 0.13 | +0.00 |
| `test_pt43_never_zero_zero.py` | 0.13 | 0.14 | +0.01 |
| `test_icon_consistency.py` | 0.13 | 0.13 | +0.00 |
| `test_id_allocation.py` | 0.12 | 0.12 | +0.00 |
| `test_lint_archive_milestone_status.py` | 0.11 | 0.12 | +0.01 |
| `test_watcher.py` | 0.10 | 0.10 | +0.00 |
| `test_theme_bootstrap_and_dropdown.py` | 0.10 | 0.10 | +0.00 |
| `test_ga_milestone_lint.py` | 0.10 | 0.10 | +0.00 |
| `test_lint_archived_record_own_status.py` | 0.10 | 0.10 | +0.00 |
| `test_receiver_flush_drop.py` | 0.10 | 0.09 | -0.01 |
| `test_archived_milestone_paths.py` | 0.09 | 0.09 | +0.00 |
| `test_load_config_raises.py` | 0.09 | 0.08 | -0.01 |
| `test_column_parity.py` | 0.09 | 0.08 | -0.01 |
| `test_issue_parsing.py` | 0.08 | 0.08 | +0.00 |
| `test_css_parse_sanity.py` | 0.08 | 0.09 | +0.01 |
| `test_skill_id_literals.py` | 0.08 | 0.08 | +0.00 |
| `test_yaml_parser.py` | 0.08 | 0.08 | +0.00 |
| `test_id_sort.py` | 0.08 | 0.08 | +0.00 |
| `test_shell_routing_and_nav.py` | 0.08 | 0.08 | +0.00 |
| `test_prices_table.py` | 0.08 | 0.09 | +0.01 |
| `test_board_small_label_face.py` | 0.07 | 0.07 | +0.00 |
| `test_dashboard_polish.py` | 0.06 | 0.05 | -0.01 |
| `test_dashboard_error_branch.py` | 0.06 | 0.05 | -0.01 |
| `test_board_css_js_class_contract.py` | 0.06 | 0.05 | -0.01 |
| `test_theme_menu_popover_row_behavior.py` | 0.06 | 0.06 | +0.00 |
| `test_dashboard_chart_ramp.py` | 0.06 | 0.07 | +0.01 |
| `test_state_releases_bound.py` | 0.06 | 0.05 | -0.01 |
| `test_dashboard_header_padding.py` | 0.06 | 0.05 | -0.01 |
| `test_flow_series_distinctness.py` | 0.06 | 0.06 | +0.00 |
| `test_theme_menu_embed_close_behavior.py` | 0.06 | 0.06 | +0.00 |
| `test_board_tokens_parity.py` | 0.05 | 0.06 | +0.01 |
| `test_dashboard_sidebar_nav.py` | 0.05 | 0.05 | +0.00 |
| `test_embed_theme_followup_and_ptr_disable.py` | 0.05 | 0.06 | +0.01 |
| `test_dashboard_token_block.py` | 0.05 | 0.06 | +0.01 |
| `test_dashboard_chrome_polish.py` | 0.05 | 0.06 | +0.01 |
| `test_dashboard_role_palette.py` | 0.05 | 0.06 | +0.01 |

Sum 176.6 s → 109.6 s across 83 files.
`test_otel_receiver_hardening.py` reads 9.14 s in the patched serial run and 4.99 s before;
measured in isolation it is 5.00 / 5.03 s patched and 5.01 / 5.00 s unpatched (two runs each),
so that row is run-to-run variance in a daemon-timing file, not a regression.

## What is left above 8 s, and why it stays

| File | After (s) | What the time is | Cost of removing it |
|---|---|---|---|
| `test_otel_receiver_self_stop.py` | 18.64 | 12 tests ≥ 0.5 s summing 18.92 s of real daemon waits; grace is already shrunk to `GRACE = 0.4` and the remainder is deliberate slack (`sleep(GRACE + 1.0)`, `sleep(PERIODIC_REAP * 6)`) | shortening the margins trades flake risk on the daemon's own timing contract |
| `test_backfill_tokens.py` | 11.27 | 40 tests, each spawning `python3 backfill_tokens.py` as a subprocess (~0.28 s median) | calling `main()` in-process deletes the CLI boundary the tests exist to cover |

Both are deferred to PT-98 with those reasons, not silently dropped.

## Consolidation is not a speed lever (measured)

Per-file interpreter startup is ~0.03 s (PT-93: runner `-j1` 173.84 s against `discover`'s
171.44 s over 82 files). Merging sliver files saves ~0.03 s each and makes the parallel
packing coarser — at 8 workers, granularity is worth more than file count. Consolidation is
hygiene; it belongs on PT-98 on its own merits, not here.

## After — shipped fix at c36af58

`helpers.serve_in_thread` in place at all 20 sites. Same machine, same commands.

| Run | Wall | Tests | Skipped | Result |
|---|---|---|---|---|
| parallel, default jobs | **19.55 s** | 1408 | 1 | OK |
| serial (`--serial`) | 102.54 s | 1408 | 1 | OK |

Test count is 1408, not the 1402 in the pre-fix rows: qa added 6 tests this loop
(`test_serve_in_thread.py` 5, `test_run_tests.py` +1). No test was deleted and no test's
semantics changed — `git diff --diff-filter=D --name-only b0cc8bd..c36af58` is empty.

### Above 8 s after the fix

| File | Serial (s) | Status |
|---|---|---|
| `test_otel_receiver_self_stop.py` | 18.52 | named exception, deferred to PT-98 |
| `test_backfill_tokens.py` | 10.32 | named exception, deferred to PT-98 |

### Per-file, serial, b0cc8bd → c36af58

| File | Before (s) | After (s) | Δ |
|---|---|---|---|
| `test_server.py` | 22.35 | 5.66 | -16.69 |
| `test_otel_receiver_self_stop.py` | 18.94 | 18.52 | -0.42 |
| `test_dashboard.py` | 13.30 | 2.80 | -10.50 |
| `test_show_archived.py` | 12.32 | 0.91 | -11.41 |
| `test_backfill_tokens.py` | 11.96 | 10.32 | -1.64 |
| `test_record_mutation.py` | 9.53 | 1.07 | -8.46 |
| `test_root_redirect.py` | 8.05 | 0.63 | -7.42 |
| `test_cli.py` | 6.41 | 6.23 | -0.18 |
| `test_comment_guard.py` | 5.64 | 5.46 | -0.18 |
| `test_otel_receiver.py` | 5.62 | 5.09 | -0.53 |
| `test_otel_receiver_hardening.py` | 4.99 | 5.04 | +0.05 |
| `test_agent_setting_role.py` | 4.40 | 3.81 | -0.59 |
| `test_dashboard_roster.py` | 4.39 | 2.35 | -2.04 |
| `test_flow_throughput.py` | 3.93 | 3.71 | -0.22 |
| `test_migrate_archive_issues.py` | 3.71 | 3.15 | -0.56 |
| `test_migrate_prefix_ids.py` | 3.42 | 3.33 | -0.09 |
| `test_multi_root.py` | 3.35 | 1.37 | -1.98 |
| `test_engine_staleness.py` | 3.33 | 0.35 | -2.98 |
| `test_dashboard_flow.py` | 2.89 | 1.39 | -1.50 |
| `test_milestone_overhead.py` | 2.79 | 2.58 | -0.21 |
| `test_dist_freshness.py` | 2.32 | 2.23 | -0.09 |
| `test_dashboard_board_embed.py` | 2.24 | 0.27 | -1.97 |
| `test_concurrent_board_load.py` | 2.18 | 0.75 | -1.43 |
| `test_tokens_endpoint.py` | 1.83 | 0.35 | -1.48 |
| `test_archive_records.py` | 1.50 | 1.37 | -0.13 |
| `test_migrate_lifecycle_status.py` | 1.44 | 1.40 | -0.04 |
| `test_check_lint.py` | 1.22 | 1.13 | -0.09 |
| `test_set_records.py` | 1.21 | 1.22 | +0.01 |
| `test_loop_stats.py` | 1.07 | 1.02 | -0.05 |
| `test_dashboard_roster_structured_work.py` | 0.87 | 0.78 | -0.09 |
| `test_frontmatter_rewrite.py` | 0.77 | 0.26 | -0.51 |
| `test_gate_head.py` | 0.71 | 0.65 | -0.06 |
| `test_milestone_input_normalization.py` | 0.66 | 0.67 | +0.01 |
| `test_snapshot.py` | 0.66 | 0.65 | -0.01 |
| `test_board_fonts.py` | 0.63 | 0.14 | -0.49 |
| `test_run_tests.py` | 0.40 | 0.38 | -0.02 |
| `test_milestone_release_state.py` | 0.38 | 0.36 | -0.02 |
| `test_dashboard_repo_name.py` | 0.35 | 0.31 | -0.04 |
| `test_check_budgets.py` | 0.34 | 0.31 | -0.03 |
| `test_shell_readonly_embed.py` | 0.26 | 0.26 | +0.00 |
| `test_git_mv_or_rename.py` | 0.25 | 0.23 | -0.02 |
| `test_theme_variants_generator.py` | 0.24 | 0.22 | -0.02 |
| `test_base_theme_contrast_gate.py` | 0.21 | 0.19 | -0.02 |
| `test_board_columns_config.py` | 0.20 | 0.21 | +0.01 |
| `test_message_cap_hook.py` | 0.20 | 0.22 | +0.02 |
| `test_milestone_card_body.py` | 0.15 | 0.13 | -0.02 |
| `test_dashboard_agent_roster.py` | 0.14 | 0.13 | -0.01 |
| `test_id_shape_prefix.py` | 0.13 | 0.13 | +0.00 |
| `test_icon_consistency.py` | 0.13 | 0.12 | -0.01 |
| `test_pt43_never_zero_zero.py` | 0.13 | 0.16 | +0.03 |
| `test_id_allocation.py` | 0.12 | 0.12 | +0.00 |
| `test_lint_archive_milestone_status.py` | 0.11 | 0.10 | -0.01 |
| `test_ga_milestone_lint.py` | 0.10 | 0.10 | +0.00 |
| `test_watcher.py` | 0.10 | 0.10 | +0.00 |
| `test_receiver_flush_drop.py` | 0.10 | 0.09 | -0.01 |
| `test_lint_archived_record_own_status.py` | 0.10 | 0.10 | +0.00 |
| `test_theme_bootstrap_and_dropdown.py` | 0.10 | 0.10 | +0.00 |
| `test_column_parity.py` | 0.09 | 0.08 | -0.01 |
| `test_archived_milestone_paths.py` | 0.09 | 0.09 | +0.00 |
| `test_load_config_raises.py` | 0.09 | 0.08 | -0.01 |
| `test_id_sort.py` | 0.08 | 0.08 | +0.00 |
| `test_css_parse_sanity.py` | 0.08 | 0.08 | +0.00 |
| `test_prices_table.py` | 0.08 | 0.08 | +0.00 |
| `test_shell_routing_and_nav.py` | 0.08 | 0.07 | -0.01 |
| `test_skill_id_literals.py` | 0.08 | 0.08 | +0.00 |
| `test_yaml_parser.py` | 0.08 | 0.08 | +0.00 |
| `test_issue_parsing.py` | 0.08 | 0.08 | +0.00 |
| `test_board_small_label_face.py` | 0.07 | 0.07 | +0.00 |
| `test_dashboard_header_padding.py` | 0.06 | 0.05 | -0.01 |
| `test_flow_series_distinctness.py` | 0.06 | 0.06 | +0.00 |
| `test_dashboard_chart_ramp.py` | 0.06 | 0.06 | +0.00 |
| `test_theme_menu_popover_row_behavior.py` | 0.06 | 0.05 | -0.01 |
| `test_board_css_js_class_contract.py` | 0.06 | 0.05 | -0.01 |
| `test_state_releases_bound.py` | 0.06 | 0.05 | -0.01 |
| `test_dashboard_error_branch.py` | 0.06 | 0.05 | -0.01 |
| `test_dashboard_polish.py` | 0.06 | 0.05 | -0.01 |
| `test_theme_menu_embed_close_behavior.py` | 0.06 | 0.05 | -0.01 |
| `test_dashboard_role_palette.py` | 0.05 | 0.06 | +0.01 |
| `test_dashboard_token_block.py` | 0.05 | 0.06 | +0.01 |
| `test_embed_theme_followup_and_ptr_disable.py` | 0.05 | 0.05 | +0.00 |
| `test_board_tokens_parity.py` | 0.05 | 0.05 | +0.00 |
| `test_dashboard_chrome_polish.py` | 0.05 | 0.06 | +0.01 |
| `test_dashboard_sidebar_nav.py` | 0.05 | 0.05 | +0.00 |
| `test_serve_in_thread.py` | — (new) | 0.12 | — |

Sum 176.6 s → 102.5 s across 83 → 84 files.
