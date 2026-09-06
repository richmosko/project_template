# PT-93 — suite timings

Machine: darwin 25.6.0, 10 logical cores (`sysctl -n hw.logicalcpu`), python 3.14.7.
Baseline sha 5fd6db1. All runs from `scripts/cairn/`.

## Whole-suite wall time (before)

| Configuration | Command | Wall | Tests | Skipped | Failed files |
|---|---|---|---|---|---|
| serial `discover` | `/usr/bin/time -p python3 -m unittest discover -s tests` | **171.44 s** | 1379 | 1 | — |
| runner `-j1` (per-file, sequential) | prototype | 173.84 s | 1379 | 1 | 0 |
| runner `-j4`, size-desc order | prototype | 47.73 s | 1379 | 1 | 0 |
| runner `-j4`, oracle (longest-first) order | prototype | 44.34 / 45.01 / 46.00 s | 1379 | 1 | 0 |
| runner `-j6`, oracle order | prototype | 29.93 / 30.31 s | 1379 | 1 | 0 |
| runner `-j8`, name order | prototype | 35.58 / 36.92 s | 1379 | 1 | 0 |
| runner `-j8`, size-desc order | prototype | **26.24 / 27.59 s** | 1379 | 1 | 0 |
| runner `-j8`, oracle order | prototype | 22.87 / 23.25 s | 1379 | 1 | 0 |
| runner `-j10`, oracle order | prototype | 22.59 s | 1379 | 1 | 0 |

`-j1` sums to 173.8 s against `discover`'s 171.4 s: the 2.4 s delta is 82 extra interpreter
starts (~0.03 s each). Count parity holds in every configuration: 1379 / skipped=1.

The suite is **not CPU-bound**: `/usr/bin/time -p` on the serial run reports user 49.41 s +
sys 29.59 s = 79.0 s of CPU against 171.4 s wall, so 54 % of the wall time is a process
waiting (subprocess spawn, server start, grace-window sleeps). That is why 8 workers on 10
cores scales past the naive CPU-count ceiling.

**Ordering is load-bearing** and file size is a usable stateless proxy for duration
(Pearson r = 0.474 against measured per-file time): at `-j8`, name order costs 36 s, size-desc
26 s, and a perfect oracle 23 s. Size-desc captures ~75 % of the available gain with no cached
state to go stale.

**Floor**: `-j10` beats `-j8` by 1.6 % because `test_server.py` (23.06 s) is still running
when every other file has finished. No worker count goes below it — see PT-96.

## Per-file (before) — all 82 files, `python3 -m unittest discover -s tests -p <file>`, sequential

| File | Seconds |
|---|---|
| `test_server.py` | 23.06 |
| `test_otel_receiver_self_stop.py` | 18.64 |
| `test_dashboard.py` | 13.75 |
| `test_show_archived.py` | 12.67 |
| `test_backfill_tokens.py` | 10.55 |
| `test_record_mutation.py` | 9.88 |
| `test_root_redirect.py` | 8.46 |
| `test_cli.py` | 6.16 |
| `test_comment_guard.py` | 5.26 |
| `test_otel_receiver.py` | 5.10 |
| `test_otel_receiver_hardening.py` | 4.99 |
| `test_dashboard_roster.py` | 4.36 |
| `test_agent_setting_role.py` | 3.95 |
| `test_flow_throughput.py` | 3.64 |
| `test_migrate_archive_issues.py` | 3.62 |
| `test_multi_root.py` | 3.54 |
| `test_engine_staleness.py` | 3.41 |
| `test_migrate_prefix_ids.py` | 3.27 |
| `test_dashboard_flow.py` | 2.85 |
| `test_milestone_overhead.py` | 2.45 |
| `test_dashboard_board_embed.py` | 2.32 |
| `test_concurrent_board_load.py` | 2.19 |
| `test_dist_freshness.py` | 2.13 |
| `test_tokens_endpoint.py` | 1.89 |
| `test_migrate_lifecycle_status.py` | 1.41 |
| `test_archive_records.py` | 1.37 |
| `test_set_records.py` | 1.20 |
| `test_check_lint.py` | 1.13 |
| `test_loop_stats.py` | 1.13 |
| `test_dashboard_roster_structured_work.py` | 0.81 |
| `test_frontmatter_rewrite.py` | 0.77 |
| `test_milestone_input_normalization.py` | 0.64 |
| `test_board_fonts.py` | 0.63 |
| `test_snapshot.py` | 0.63 |
| `test_gate_head.py` | 0.62 |
| `test_milestone_release_state.py` | 0.37 |
| `test_check_budgets.py` | 0.32 |
| `test_dashboard_repo_name.py` | 0.31 |
| `test_shell_readonly_embed.py` | 0.26 |
| `test_git_mv_or_rename.py` | 0.23 |
| `test_theme_variants_generator.py` | 0.22 |
| `test_message_cap_hook.py` | 0.21 |
| `test_base_theme_contrast_gate.py` | 0.19 |
| `test_board_columns_config.py` | 0.19 |
| `test_dashboard_agent_roster.py` | 0.14 |
| `test_pt43_never_zero_zero.py` | 0.14 |
| `test_icon_consistency.py` | 0.12 |
| `test_id_shape_prefix.py` | 0.12 |
| `test_milestone_card_body.py` | 0.12 |
| `test_id_allocation.py` | 0.11 |
| `test_lint_archive_milestone_status.py` | 0.11 |
| `test_lint_archived_record_own_status.py` | 0.11 |
| `test_theme_bootstrap_and_dropdown.py` | 0.11 |
| `test_watcher.py` | 0.11 |
| `test_ga_milestone_lint.py` | 0.10 |
| `test_receiver_flush_drop.py` | 0.10 |
| `test_css_parse_sanity.py` | 0.09 |
| `test_load_config_raises.py` | 0.09 |
| `test_prices_table.py` | 0.09 |
| `test_skill_id_literals.py` | 0.09 |
| `test_archived_milestone_paths.py` | 0.08 |
| `test_column_parity.py` | 0.08 |
| `test_dashboard_chart_ramp.py` | 0.08 |
| `test_issue_parsing.py` | 0.08 |
| `test_yaml_parser.py` | 0.08 |
| `test_board_small_label_face.py` | 0.07 |
| `test_id_sort.py` | 0.07 |
| `test_shell_routing_and_nav.py` | 0.07 |
| `test_board_css_js_class_contract.py` | 0.05 |
| `test_board_tokens_parity.py` | 0.05 |
| `test_dashboard_chrome_polish.py` | 0.05 |
| `test_dashboard_error_branch.py` | 0.05 |
| `test_dashboard_header_padding.py` | 0.05 |
| `test_dashboard_polish.py` | 0.05 |
| `test_dashboard_role_palette.py` | 0.05 |
| `test_dashboard_sidebar_nav.py` | 0.05 |
| `test_dashboard_token_block.py` | 0.05 |
| `test_embed_theme_followup_and_ptr_disable.py` | 0.05 |
| `test_flow_series_distinctness.py` | 0.05 |
| `test_state_releases_bound.py` | 0.05 |
| `test_theme_menu_embed_close_behavior.py` | 0.05 |
| `test_theme_menu_popover_row_behavior.py` | 0.05 |

Sum: 173.8 s across 82 files.

## After

_Filled at gate 4 from `run_tests.py --json`._

