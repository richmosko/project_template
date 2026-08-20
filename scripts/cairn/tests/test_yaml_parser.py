"""Tests for cairn.parse_yaml_subset and cairn.load_config.

See INTERFACE.md for the full contract. This file covers only the
fenceless YAML-subset mapping parser -- frontmatter fence handling lives
in test_issue_parsing.py.
"""
from __future__ import annotations

import unittest

import helpers  # noqa: F401  (sys.path shim side effect)

import cairn


class ScalarsTests(unittest.TestCase):
    def test_bare_string(self):
        self.assertEqual(cairn.parse_yaml_subset("status: in-progress\n"), {"status": "in-progress"})

    def test_bare_integer_becomes_int(self):
        # config.yml's `port: 8766` must round-trip as an int, not a string --
        # the server binds a socket with it.
        self.assertEqual(cairn.parse_yaml_subset("port: 8766\n"), {"port": 8766})

    def test_bare_true_false_become_bool(self):
        # milestones/*.md's `ga: true` / `ga: false` field.
        self.assertEqual(cairn.parse_yaml_subset("ga: true\n"), {"ga": True})
        self.assertEqual(cairn.parse_yaml_subset("ga: false\n"), {"ga": False})

    def test_bare_null(self):
        self.assertEqual(cairn.parse_yaml_subset("parent: null\n"), {"parent": None})

    def test_quoted_numeric_looking_string_stays_string(self):
        # The spec calls this out explicitly: milestone: "1.0" must never
        # become the float 1.0.
        self.assertEqual(cairn.parse_yaml_subset('milestone: "1.0"\n'), {"milestone": "1.0"})

    def test_single_quoted_string(self):
        self.assertEqual(cairn.parse_yaml_subset("milestone: '1.0'\n"), {"milestone": "1.0"})

    def test_quoted_string_is_str_even_when_it_looks_like_null_or_bool(self):
        self.assertEqual(cairn.parse_yaml_subset('status: "null"\n'), {"status": "null"})
        self.assertEqual(cairn.parse_yaml_subset('status: "true"\n'), {"status": "true"})

    def test_multiple_keys_preserve_insertion_order(self):
        text = "id: PT-1\ntitle: Thing\nstatus: todo\n"
        self.assertEqual(list(cairn.parse_yaml_subset(text).keys()), ["id", "title", "status"])


class InlineCommentTests(unittest.TestCase):
    """Regression tests for a gap identified when reconciling against
    implementation-lead's superseded scratch suite (see
    temp/2026-08-19-implementation-lead-cairn-engine-report.md): trailing
    `# comment` support is implemented (`_strip_inline_comment`) and
    correct, but had no committed regression test -- none of the fixtures
    happen to use inline comments, so a regression here wouldn't have been
    caught by anything else in the suite."""

    def test_trailing_comment_is_stripped(self):
        self.assertEqual(cairn.parse_yaml_subset("status: todo  # was backlog\n"), {"status": "todo"})

    def test_full_line_comment_is_ignored(self):
        text = "# this whole line is a comment\nstatus: todo\n"
        self.assertEqual(cairn.parse_yaml_subset(text), {"status": "todo"})

    def test_hash_inside_a_quoted_string_is_not_stripped(self):
        # The critical case: a bare `#` is a comment marker, but one that's
        # part of an actual quoted value (e.g. a hex color, a URL fragment)
        # must survive. A naive `line.split('#')[0]` would corrupt this.
        self.assertEqual(cairn.parse_yaml_subset('title: "Fix #42"\n'), {"title": "Fix #42"})
        self.assertEqual(cairn.parse_yaml_subset("title: 'Fix #42'\n"), {"title": "Fix #42"})


class FlowListTests(unittest.TestCase):
    def test_flow_list_of_bare_strings(self):
        self.assertEqual(cairn.parse_yaml_subset("labels: [auth, api]\n"), {"labels": ["auth", "api"]})

    def test_empty_flow_list(self):
        self.assertEqual(cairn.parse_yaml_subset("labels: []\n"), {"labels": []})

    def test_flow_list_single_element(self):
        self.assertEqual(cairn.parse_yaml_subset("labels: [auth]\n"), {"labels": ["auth"]})

    def test_flow_list_elements_are_trimmed(self):
        self.assertEqual(cairn.parse_yaml_subset("labels: [auth,   api]\n"), {"labels": ["auth", "api"]})


class BlockListTests(unittest.TestCase):
    def test_block_list_of_bare_strings(self):
        text = "labels:\n  - auth\n  - api\n"
        self.assertEqual(cairn.parse_yaml_subset(text), {"labels": ["auth", "api"]})

    def test_empty_block_list_key_still_parses(self):
        # Not exercised by any fixture, but the parser is documented to
        # support block lists as a first-class scalar-list type.
        text = "a: 1\nlabels:\n  - only\nb: 2\n"
        result = cairn.parse_yaml_subset(text)
        self.assertEqual(result["labels"], ["only"])
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)

    def test_block_list_item_shaped_like_a_mapping_is_rejected(self):
        # Regression test for a gap identified when reconciling against
        # implementation-lead's superseded scratch suite (see
        # temp/2026-08-19-implementation-lead-cairn-engine-report.md):
        # `- key: value` as a list item looks like it could be a one-entry
        # mapping, which is outside the documented subset (list items are
        # scalars only). Must raise, not silently produce a dict-shaped
        # list item or misparse as a plain string.
        text = "items:\n  - key: value\n"
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset(text)


class NestedMappingTests(unittest.TestCase):
    """See INTERFACE.md's ruling: nested maps are in-subset because config.yml's
    own spec example requires one level of nesting (the `board:` key)."""

    def test_config_yml_shape_parses(self):
        text = (
            "prefix: PT\n"
            "port: 8766\n"
            "data_dir: process/cairn\n"
            "board:\n"
            "  columns: [backlog, todo, in-progress, in-review, done]\n"
            "  swimlane: milestone\n"
        )
        result = cairn.parse_yaml_subset(text)
        self.assertEqual(result["prefix"], "PT")
        self.assertEqual(result["port"], 8766)
        self.assertEqual(result["data_dir"], "process/cairn")
        self.assertEqual(
            result["board"],
            {"columns": ["backlog", "todo", "in-progress", "in-review", "done"], "swimlane": "milestone"},
        )


class LoudErrorTests(unittest.TestCase):
    """Everything here is outside the documented subset. Each must raise
    YamlError rather than silently misparsing or crashing with some other
    exception type."""

    def test_anchor_is_rejected(self):
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("foo: &anchor bar\n")

    def test_alias_is_rejected(self):
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("foo: bar\nbaz: *anchor\n")

    def test_tag_is_rejected(self):
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("foo: !!str bar\n")

    def test_flow_mapping_is_rejected(self):
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("foo: {a: 1, b: 2}\n")

    def test_block_scalar_literal_is_rejected(self):
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("body: |\n  line one\n  line two\n")

    def test_block_scalar_folded_is_rejected(self):
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("body: >\n  line one\n  line two\n")

    def test_sibling_key_at_inconsistent_indentation_is_rejected(self):
        # Regression test for a gap identified when reconciling against
        # implementation-lead's superseded scratch suite. `b` here isn't
        # nested under `a` (no trailing-colon-then-indent parent) -- it's a
        # second top-level key that's merely mis-indented. One level of
        # *intentional* nesting is in-subset (NestedMappingTests), but
        # accidental/inconsistent indentation between true siblings is a
        # different failure mode and must still be a loud YamlError, not a
        # silent misparse into a nested value under `a`.
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset("a: 1\n   b: 2\n")

    def test_deeply_nested_mapping_is_rejected(self):
        # One level (config.yml's `board:`) is in-subset; two is not --
        # nothing in the spec's examples needs it.
        text = "a:\n  b:\n    c: 1\n"
        with self.assertRaises(cairn.YamlError):
            cairn.parse_yaml_subset(text)

    def test_error_message_is_pointed(self):
        # Not pinning exact wording, but a bare "parse error" with no
        # location is useless for `cairn check` to report -- require the
        # message to be non-trivial.
        with self.assertRaises(cairn.YamlError) as ctx:
            cairn.parse_yaml_subset("foo: &anchor bar\n")
        self.assertTrue(str(ctx.exception).strip())


class LoadConfigTests(unittest.TestCase):
    def test_load_config_from_fixture(self):
        config = cairn.load_config(helpers.FIXTURE_DATA_DIR)
        self.assertEqual(config["prefix"], "PT")
        self.assertEqual(config["port"], 8766)
        self.assertEqual(config["board"]["swimlane"], "milestone")
        self.assertEqual(
            config["board"]["columns"],
            ["backlog", "todo", "in-progress", "in-review", "done"],
        )


if __name__ == "__main__":
    unittest.main()
