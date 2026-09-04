"""PT-80 failing acceptance tests: `cairn.load_config` raises on a missing
data dir / missing `config.yml`, instead of silently returning built-in
defaults (`prefix: "ISS"`, default port, default board columns).

Found during the PT-77 architect review (comment at 0e8832c on
process/cairn/issues/PT-77.md): `backfill_tokens.py` called
`cairn.load_config(cairn.find_data_dir())` directly, bypassing the CLI's
existing `resolve_data_dir` guard entirely, and inherited the silent
default -- a run from outside the repo mis-attributed every issue to
`main` at exit 0. `resolve_data_dir` (the CLI's own pre-check, used by
every `cmd_*` function) already raises `CairnError` before ever reaching
`load_config` for the CLI surface -- that half is NOT broken and NOT
under test here (see test_cli.py's DiscoveryErrorTests, extended by this
same PT-80 slice with `check`/`serve` coverage). What IS broken, and is
what this file pins, is `load_config` ITSELF: any caller that calls it
directly -- as `backfill_tokens.py` did, as any future script will --
gets a false sense of safety from a loader that quietly hands back
defaults for a tracker that was never there.

Ruling (architect, at filing): "The fix is not a smarter find_data_dir.
A loader that returns defaults for a non-existent directory is the wrong
shape. load_config raises a named error carrying the path it looked for;
callers that legitimately want defaults (if any exist) opt in
explicitly."

Confirmed RED against current cairn.py before writing these (manual
probe): `cairn.load_config(Path(some_empty_tmpdir))` returns
`{'prefix': 'ISS', 'port': 8766, ...}` -- no exception, no hint that the
directory was empty.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import helpers  # noqa: F401

import cairn


class LoadConfigRaisesTests(unittest.TestCase):
    def test_raises_cairn_error_on_a_directory_that_exists_but_has_no_config_yml(self):
        data_dir = helpers.make_empty_tmp_dir(self)  # exists, deliberately no config.yml inside
        with self.assertRaises(cairn.CairnError) as ctx:
            cairn.load_config(data_dir)
        self.assertTrue(str(ctx.exception).strip(), "the exception must carry a real message, not an empty one")

    def test_raised_error_names_the_exact_path_it_looked_for(self):
        data_dir = helpers.make_empty_tmp_dir(self)
        with self.assertRaises(cairn.CairnError) as ctx:
            cairn.load_config(data_dir)
        self.assertIn(str(data_dir), str(ctx.exception), f"the error must name the path it looked for -- got: {ctx.exception!r}")

    def test_raises_cairn_error_when_the_data_dir_itself_does_not_exist_at_all(self):
        # Distinct from the above: not "a directory exists but lacks
        # config.yml", but "the directory was never created in the first
        # place" -- both are named in the issue title ("a missing data dir
        # or config.yml") as separate cases this loader must not paper
        # over silently.
        parent = helpers.make_empty_tmp_dir(self)
        nonexistent = parent / "does-not-exist-at-all" / "process" / "cairn"
        with self.assertRaises(cairn.CairnError) as ctx:
            cairn.load_config(nonexistent)
        self.assertIn(str(nonexistent), str(ctx.exception), f"the error must name the path it looked for -- got: {ctx.exception!r}")

    def test_still_loads_normally_when_config_yml_is_actually_present(self):
        # Regression guard: the raise must be scoped to "missing", not
        # turn into an over-broad raise on every call. Reuses the same
        # fixture test_yaml_parser.py's LoadConfigTests already asserts
        # against.
        config = cairn.load_config(helpers.FIXTURE_DATA_DIR)
        self.assertEqual(config["prefix"], "PT")
        self.assertEqual(config["port"], 8766)


if __name__ == "__main__":
    unittest.main()
