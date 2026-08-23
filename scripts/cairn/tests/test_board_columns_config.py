"""PASS 1 (Python/server side) failing tests for PT-38: `board.columns` and
`board.swimlane` plumbed from config.yml through to `/api/board`, with
validation + graceful fallback. Architect's ruling:
temp/arch-ruling-pt38-board-columns.md (§6 -- board.swimlane -- folded in
by team-lead's ruling, same doc).

§1 config shape: `board.columns` is an ORDERED SUBSET of the known column
statuses (STATUSES minus `cancelled`) -- not a new-status mechanism.
`cancelled` is explicitly rejected (owned by the Show-cancelled toggle,
PT-35) with a pointed message. Duplicates/empty/non-list/non-string
entries all rejected. `board.swimlane` is `milestone | none`.

§2 validation + failure behaviour -- TWO DIFFERENT postures for the SAME
bad input, by design (not a bug to reconcile):
  - `cairn check` (check_repo): every violation is a lint ERROR.
  - The server: never crashes, never refuses to start. Invalid
    `board.columns`/`board.swimlane` -> falls back to
    DEFAULT_COLUMNS/"milestone", plus ONE line to stderr naming the
    offending value.

§3 plumbing: `/api/board` (build_multi_board_payload, the payload every
`/api/board` request actually serves per cairn.py's do_GET) gains two
top-level keys, `columns` and `swimlane` -- always present, resolved
(config or default), never conditional on single- vs multi-root.
Multi-root: the PRIMARY root's config governs; secondary roots' board.*
config is ignored entirely.

§1 (last bullet): `cairn snapshot` (build_snapshot_markdown) ignores
`board.columns` ENTIRELY -- always renders the full STATUS_ORDER. Board
view is not canonical rendering; the snapshot artifact must never silently
drop a project's hidden-on-Kanban statuses.

UPDATED against implementation-lead's Pass-1 signature message (2026-08-23),
which settled the actual call shape -- superseding this file's first draft,
which tested through `load_config` directly and got it wrong (see below):

- `validate_board_columns(value) -> (bool, str)` / `validate_board_swimlane(value)
  -> (bool, str)`: the ONE validity check per field, backing BOTH `cairn
  check`'s hard error (check_repo calls these against the RAW `cfg` dict,
  same block as the existing roots/prefix checks) and the server's soft
  fallback.
- `resolve_board_columns(config) -> (list, Optional[str])` / `resolve_board_swimlane(config)
  -> (str, Optional[str])`: take an ALREADY-LOADED config dict (i.e. post
  `load_config`'s own defaulting -- `config["board"]["columns"]` is
  guaranteed present, possibly still carrying an invalid raw value load_config
  itself does NOT validate) and return `(resolved_value, None)` when valid,
  `(default, "<pointed warning>")` when not. These do NOT print anything --
  they return the warning as data.
- `build_multi_board_payload(roots, warnings)` is the actual print site:
  reads `load_config(roots[0].path)` (primary root governs, §3), calls
  `resolve_board_columns`/`resolve_board_swimlane`, and prints any warning
  to stderr -- ONE line, naming the offending value -- before returning the
  payload with its new `columns`/`swimlane` keys.

Why this matters, concretely: `load_config` itself is NOT the validation/
fallback/stderr entry point -- it only defaults an ABSENT key
(`board.setdefault("columns", list(DEFAULT_COLUMNS))`), it does not
validate a PRESENT-but-invalid one. A test asserting
`cairn.load_config(data_dir)["board"]["columns"] == list(DEFAULT_COLUMNS)`
for an invalid config would still FAIL after implementation-lead's fix
lands (load_config keeps passing the raw invalid value through untouched;
`resolve_board_columns` is where it actually gets caught) -- a permanently
wrong test dressed as a red one. Retargeted below to
`resolve_board_columns`/`resolve_board_swimlane` for the value+warning
contract, and to `build_multi_board_payload` for the actual stderr side
effect + the end-to-end payload shape.

`check_repo`'s tests are UNCHANGED from the first draft -- black-box
against `check_repo(data_dir)`'s error list, which was always the right
entry point regardless of which raw-cfg validator backs it internally.
Same for `build_multi_board_payload`'s payload-shape tests, multi-root,
and the snapshot-ignores-config test -- all already targeted the correct
public entry points.

Nothing under test exists yet: `validate_board_columns`/
`validate_board_swimlane`/`resolve_board_columns`/`resolve_board_swimlane`
are not defined, `/api/board`'s payload carries no `columns`/`swimlane`
key at all, and `cairn check` has no board.* lint rule. Every test below
is expected to fail until implementation-lead's PT-38 slice lands.
"""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


def write_config(data_dir: Path, board_yaml: str) -> None:
    (data_dir / "config.yml").write_text(
        f"prefix: PT\nport: 8766\ndata_dir: process/cairn\nboard:\n{board_yaml}",
        encoding="utf-8",
    )


def minimal_repo(testcase) -> Path:
    tmp = helpers.make_empty_tmp_dir(testcase)
    data_dir = tmp / "cairn"
    for sub in ("issues", "archive", "milestones", "majors"):
        (data_dir / sub).mkdir(parents=True)
    return data_dir


# --------------------------------------------------------------------------
# §1: validate_board_columns / validate_board_swimlane -- the ONE validity
# check per field, pure and side-effect-free ((bool, str) tuple, never
# prints, never raises). Backs BOTH check_repo's hard error and
# resolve_board_columns's soft fallback.
# --------------------------------------------------------------------------

class ValidateBoardColumnsTests(unittest.TestCase):
    def test_a_valid_ordered_subset_is_valid(self):
        ok, reason = cairn.validate_board_columns(["in-review", "todo"])
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "")

    def test_cancelled_is_rejected_with_a_pointed_reason(self):
        ok, reason = cairn.validate_board_columns(["todo", "cancelled", "done"])
        self.assertFalse(ok)
        self.assertIn("cancelled", reason)

    def test_duplicates_are_rejected(self):
        ok, reason = cairn.validate_board_columns(["todo", "todo", "done"])
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_empty_list_is_rejected(self):
        ok, reason = cairn.validate_board_columns([])
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_unknown_status_is_rejected_naming_the_value(self):
        ok, reason = cairn.validate_board_columns(["todo", "bogus-status"])
        self.assertFalse(ok)
        self.assertIn("bogus-status", reason)

    def test_a_non_list_value_is_rejected(self):
        ok, reason = cairn.validate_board_columns("todo")
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_a_list_with_a_non_string_entry_is_rejected(self):
        ok, reason = cairn.validate_board_columns(["todo", 5])
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_never_raises_on_any_of_the_above(self):
        for bad in (["cancelled"], ["todo", "todo"], [], "todo", ["todo", 5], None, {}, 5):
            try:
                cairn.validate_board_columns(bad)
            except Exception as e:  # noqa: BLE001
                self.fail(f"validate_board_columns must never raise, got {e!r} for {bad!r}")


class ValidateBoardSwimlaneTests(unittest.TestCase):
    def test_milestone_is_valid(self):
        ok, reason = cairn.validate_board_swimlane("milestone")
        self.assertTrue(ok, reason)

    def test_none_is_valid(self):
        ok, reason = cairn.validate_board_swimlane("none")
        self.assertTrue(ok, reason)

    def test_a_bogus_value_is_rejected_naming_it(self):
        ok, reason = cairn.validate_board_swimlane("bogus")
        self.assertFalse(ok)
        self.assertIn("bogus", reason)

    def test_never_raises(self):
        for bad in ("bogus", None, 5, [], {}):
            try:
                cairn.validate_board_swimlane(bad)
            except Exception as e:  # noqa: BLE001
                self.fail(f"validate_board_swimlane must never raise, got {e!r} for {bad!r}")


# --------------------------------------------------------------------------
# §1/§2: load_config -- DEFAULTING ONLY, does NOT validate a present-but-
# invalid value (confirmed against the real, now-stable cairn.py:
# load_config's own docstring is explicit about this -- it's called from
# every CLI path, not just board-rendering ones, so it deliberately does
# not print PT-38's warning on an unrelated invocation). A present invalid
# value passes through UNCHANGED; resolve_board_columns/resolve_board_swimlane
# below are where it actually gets caught.
#
# (This test file went through two prior drafts chasing a moving target
# while implementation-lead iterated live -- draft 1 assumed load_config
# itself validated, draft 2 (briefly) matched an intermediate state that
# folded validation into load_config, and this final draft matches what
# actually landed: load_config defaults only, resolve_board_columns/
# resolve_board_swimlane validate+fall back as pure functions, and
# build_multi_board_payload is the sole stderr print site. Flagged to
# team-lead/implementation-lead as it happened, not silently absorbed.)
# --------------------------------------------------------------------------

class LoadConfigIsDefaultingOnlyTests(unittest.TestCase):
    def test_an_invalid_value_passes_through_unchanged_not_validated_here(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo, cancelled]\n")
        config = cairn.load_config(data_dir)
        self.assertEqual(
            config["board"]["columns"], ["todo", "cancelled"],
            "load_config must pass an invalid value through UNCHANGED -- "
            "resolve_board_columns is where it gets caught, not here",
        )

    def test_an_absent_key_is_still_defaulted(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  swimlane: milestone\n")
        config = cairn.load_config(data_dir)
        self.assertEqual(config["board"]["columns"], list(cairn.DEFAULT_COLUMNS))

    def test_never_raises_on_an_invalid_value(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [cancelled]\n  swimlane: [not, a, string]\n")
        try:
            cairn.load_config(data_dir)
        except Exception as e:  # noqa: BLE001
            self.fail(f"load_config must never raise on invalid board.* values, got {e!r}")


class ResolveBoardColumnsTests(unittest.TestCase):
    """resolve_board_columns(config) -- PURE, takes an already-loaded
    config dict, returns (resolved_list, warning_or_None). Never prints,
    never raises; build_multi_board_payload is the print site (tested in
    BoardPayloadStderrWarningTests below)."""

    def _config_with_columns(self, columns_value) -> dict:
        return {"board": {"columns": columns_value, "swimlane": "milestone"}}

    def test_a_valid_subset_resolves_unchanged_with_no_warning(self):
        columns, warning = cairn.resolve_board_columns(self._config_with_columns(["done", "todo"]))
        self.assertEqual(columns, ["done", "todo"])
        self.assertIsNone(warning)

    def test_an_invalid_value_falls_back_to_default_with_a_pointed_warning(self):
        columns, warning = cairn.resolve_board_columns(self._config_with_columns(["todo", "cancelled"]))
        self.assertEqual(columns, list(cairn.DEFAULT_COLUMNS))
        self.assertIsNotNone(warning)
        self.assertIn("cancelled", warning)

    def test_never_raises_on_an_invalid_value(self):
        try:
            cairn.resolve_board_columns(self._config_with_columns(["cancelled"]))
        except Exception as e:  # noqa: BLE001
            self.fail(f"resolve_board_columns must never raise, got {e!r}")

    def test_composed_with_load_configs_own_default_resolves_cleanly(self):
        data_dir = minimal_repo(self)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        config = cairn.load_config(data_dir)
        columns, warning = cairn.resolve_board_columns(config)
        self.assertEqual(columns, list(cairn.DEFAULT_COLUMNS))
        self.assertIsNone(warning)


class ResolveBoardSwimlaneTests(unittest.TestCase):
    def _config_with_swimlane(self, value) -> dict:
        return {"board": {"columns": list(cairn.DEFAULT_COLUMNS), "swimlane": value}}

    def test_a_valid_value_resolves_unchanged_with_no_warning(self):
        swimlane, warning = cairn.resolve_board_swimlane(self._config_with_swimlane("none"))
        self.assertEqual(swimlane, "none")
        self.assertIsNone(warning)

    def test_an_invalid_value_falls_back_to_milestone_with_a_pointed_warning(self):
        swimlane, warning = cairn.resolve_board_swimlane(self._config_with_swimlane("bogus"))
        self.assertEqual(swimlane, "milestone")
        self.assertIsNotNone(warning)
        self.assertIn("bogus", warning)

    def test_never_raises_on_an_unhashable_value(self):
        # This is the exact input shape that caught a REAL bug (reported
        # separately) in validate_board_swimlane: `value not in
        # _VALID_SWIMLANE_VALUES` raised TypeError for an unhashable value
        # (a list) instead of returning (False, reason). Pinned here too,
        # one layer up, since this is resolve_board_swimlane's own never-
        # raises contract, not just validate_board_swimlane's.
        try:
            cairn.resolve_board_swimlane(self._config_with_swimlane(["not", "a", "string"]))
        except Exception as e:  # noqa: BLE001
            self.fail(f"resolve_board_swimlane must never raise, got {e!r}")


# --------------------------------------------------------------------------
# §2: cairn check -- the SAME bad configs are lint ERRORS (opposite posture
# from load_config's silent-fallback -- both are correct, for different
# callers).
# --------------------------------------------------------------------------

class CheckRepoBoardConfigLintTests(unittest.TestCase):
    def test_cancelled_in_columns_is_a_lint_error(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo, cancelled]\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("cancelled" in e and "columns" in e for e in errors), errors)

    def test_duplicate_columns_is_a_lint_error(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo, todo]\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("columns" in e for e in errors), errors)

    def test_empty_columns_is_a_lint_error(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: []\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("columns" in e for e in errors), errors)

    def test_unknown_status_in_columns_is_a_lint_error(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [bogus-status]\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("bogus-status" in e for e in errors), errors)

    def test_invalid_swimlane_is_a_lint_error(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  swimlane: bogus\n")
        errors = cairn.check_repo(data_dir)
        self.assertTrue(any("swimlane" in e and "bogus" in e for e in errors), errors)

    def test_a_valid_board_config_lints_clean(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo, done]\n  swimlane: none\n")
        (data_dir / "config.yml").write_text(
            "prefix: PT\nport: 8766\ndata_dir: process/cairn\n"
            "board:\n  columns: [todo, done]\n  swimlane: none\n",
            encoding="utf-8",
        )
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "board" in e.lower() or "columns" in e or "swimlane" in e], [])

    def test_no_board_key_at_all_lints_clean_defaults_apply(self):
        data_dir = minimal_repo(self)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        errors = cairn.check_repo(data_dir)
        self.assertEqual([e for e in errors if "columns" in e or "swimlane" in e], [])


# --------------------------------------------------------------------------
# §3: /api/board payload -- columns/swimlane always present, resolved.
# Tested via build_multi_board_payload directly (what do_GET actually
# calls for every /api/board request, single-root included -- PT-3
# precedent, no conditional payload shape).
# --------------------------------------------------------------------------

class BoardPayloadColumnsSwimlaneTests(unittest.TestCase):
    def _single_root_payload(self, data_dir: Path):
        config = cairn.load_config(data_dir)
        roots, warnings = cairn.resolve_roots(data_dir, config)
        return cairn.build_multi_board_payload(roots, warnings)

    def test_payload_carries_columns_key_with_the_default_when_unconfigured(self):
        data_dir = minimal_repo(self)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        payload = self._single_root_payload(data_dir)
        self.assertIn("columns", payload)
        self.assertEqual(payload["columns"], list(cairn.DEFAULT_COLUMNS))

    def test_payload_carries_a_configured_columns_subset_in_order(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [done, todo]\n")
        payload = self._single_root_payload(data_dir)
        self.assertEqual(payload["columns"], ["done", "todo"])

    def test_payload_columns_falls_back_to_default_on_invalid_config(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [cancelled]\n")
        payload = self._single_root_payload(data_dir)
        self.assertEqual(payload["columns"], list(cairn.DEFAULT_COLUMNS))

    def test_payload_never_carries_cancelled_in_columns(self):
        # Even with a maximal/all-statuses-ish config -- cancelled is
        # structurally never a member (§1: owned by the toggle, not columns).
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [backlog, todo, in-progress, in-review, done]\n")
        payload = self._single_root_payload(data_dir)
        self.assertNotIn("cancelled", payload["columns"])

    def test_payload_carries_swimlane_key_default_milestone(self):
        data_dir = minimal_repo(self)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        payload = self._single_root_payload(data_dir)
        self.assertIn("swimlane", payload)
        self.assertEqual(payload["swimlane"], "milestone")

    def test_payload_carries_configured_swimlane_none(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  swimlane: none\n")
        payload = self._single_root_payload(data_dir)
        self.assertEqual(payload["swimlane"], "none")


class BoardPayloadStderrWarningTests(unittest.TestCase):
    """build_multi_board_payload is the actual print site (implementation-
    lead's Pass-1 message) -- resolve_board_columns/resolve_board_swimlane
    only RETURN the warning as data; this is where it reaches stderr, one
    line, naming the offending value."""

    def _single_root_payload_capturing_stderr(self, data_dir: Path):
        config = cairn.load_config(data_dir)
        roots, warnings = cairn.resolve_roots(data_dir, config)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            payload = cairn.build_multi_board_payload(roots, warnings)
        return payload, stderr.getvalue()

    def test_invalid_columns_prints_one_pointed_stderr_line(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo, cancelled]\n")
        payload, stderr_output = self._single_root_payload_capturing_stderr(data_dir)
        self.assertEqual(payload["columns"], list(cairn.DEFAULT_COLUMNS))
        self.assertIn("cancelled", stderr_output)

    def test_invalid_swimlane_prints_one_pointed_stderr_line(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  swimlane: bogus\n")
        payload, stderr_output = self._single_root_payload_capturing_stderr(data_dir)
        self.assertEqual(payload["swimlane"], "milestone")
        self.assertIn("bogus", stderr_output)

    def test_a_valid_board_config_prints_nothing_to_stderr(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo, done]\n  swimlane: none\n")
        payload, stderr_output = self._single_root_payload_capturing_stderr(data_dir)
        self.assertEqual(stderr_output.strip(), "")

    def test_an_absent_board_key_prints_nothing_to_stderr(self):
        data_dir = minimal_repo(self)
        (data_dir / "config.yml").write_text("prefix: PT\nport: 8766\ndata_dir: process/cairn\n", encoding="utf-8")
        payload, stderr_output = self._single_root_payload_capturing_stderr(data_dir)
        self.assertEqual(stderr_output.strip(), "", "an ABSENT key is not an invalid one -- no warning")

    def test_never_raises_on_invalid_board_config(self):
        # The server posture, pinned at the actual print site: no
        # exception escapes even when both columns and swimlane are bad.
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [cancelled]\n  swimlane: bogus\n")
        try:
            self._single_root_payload_capturing_stderr(data_dir)
        except Exception as e:  # noqa: BLE001
            self.fail(f"build_multi_board_payload must never raise on invalid board.* config, raised: {e!r}")


class MultiRootPrimaryConfigGovernsTests(unittest.TestCase):
    """§3: secondary roots' board.* config is ignored entirely -- only the
    primary root's resolved columns/swimlane reach the payload."""

    def test_secondary_roots_board_columns_config_is_ignored(self):
        tmp = helpers.make_empty_tmp_dir(self)
        primary = tmp / "primary" / "cairn"
        secondary = tmp / "secondary" / "cairn"
        for d in (primary, secondary):
            for sub in ("issues", "archive", "milestones", "majors"):
                (d / sub).mkdir(parents=True)
        (primary / "config.yml").write_text(
            "prefix: PT\nport: 8766\ndata_dir: process/cairn\n"
            "board:\n  columns: [todo, done]\n"
            f"roots: [../../secondary/cairn]\n",
            encoding="utf-8",
        )
        (secondary / "config.yml").write_text(
            "prefix: SEC\nport: 8767\ndata_dir: process/cairn\nboard:\n  columns: [in-review]\n",
            encoding="utf-8",
        )
        config = cairn.load_config(primary)
        roots, warnings = cairn.resolve_roots(primary, config)
        payload = cairn.build_multi_board_payload(roots, warnings)
        self.assertEqual(payload["columns"], ["todo", "done"], "secondary root's [in-review] must never leak through")


# --------------------------------------------------------------------------
# §1 last bullet: cairn snapshot ignores board.columns entirely.
# --------------------------------------------------------------------------

class SnapshotIgnoresBoardColumnsTests(unittest.TestCase):
    def test_snapshot_renders_full_status_order_regardless_of_a_restrictive_columns_config(self):
        data_dir = minimal_repo(self)
        write_config(data_dir, "  columns: [todo]\n")  # would hide backlog/in-progress/in-review/done on Kanban
        (data_dir / "issues" / "PT-1.md").write_text(
            "---\nid: PT-1\ntitle: Backlogged\nstatus: backlog\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n---\n\nBody.\n",
            encoding="utf-8",
        )
        markdown = cairn.build_snapshot_markdown(data_dir, generated_at="2026-08-01T00:00:00Z")
        # The snapshot must still render the backlog section/issue even
        # though `columns: [todo]` would hide it entirely on the Kanban --
        # board view is not canonical rendering.
        self.assertIn("PT-1", markdown)
        self.assertIn("backlog", markdown.lower())


if __name__ == "__main__":
    unittest.main()
