"""Tests for cairn.dump_frontmatter, cairn.apply_patch, cairn.append_comment.

The core guarantee under test: after a frontmatter-only rewrite, every byte
after the closing `---` fence is untouched -- byte-for-byte, not just
text-equal (CRLF, trailing whitespace, no-trailing-newline, and unicode
bodies are all exercised explicitly).
"""
from __future__ import annotations

import datetime
import json
import os
import stat
import subprocess
import threading
import time
import unittest
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

import cairn


def write_issue(path: Path, frontmatter_text: str, body: str) -> None:
    path.write_bytes(("---\n" + frontmatter_text + "---\n" + body).encode("utf-8"))


def tail_bytes_after_second_fence(raw: bytes) -> bytes:
    """Everything after the second `---\n` line, as raw bytes."""
    first = raw.index(b"---\n")
    second = raw.index(b"---\n", first + len(b"---\n"))
    return raw[second + len(b"---\n"):]


class DumpFrontmatterTests(unittest.TestCase):
    def test_canonical_key_order_regardless_of_input_order(self):
        fields = {
            "updated": "2026-08-19",
            "id": "PT-1",
            "title": "Thing",
            "created": "2026-08-14",
            "status": "todo",
            "milestone": None,
            "parent": None,
            "blocked_by": [],
            "assignee": None,
            "labels": [],
            "priority": None,
            "pr": None,
        }
        text = cairn.dump_frontmatter(fields)
        lines = [line for line in text.splitlines() if ":" in line]
        keys_in_order = [line.split(":", 1)[0] for line in lines]
        self.assertEqual(keys_in_order, cairn.ISSUE_FIELD_ORDER)

    def test_fenced_by_triple_dash(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[])
        text = cairn.dump_frontmatter(fields)
        self.assertTrue(text.startswith("---\n"))
        self.assertTrue(text.endswith("---\n"))

    def test_numeric_looking_milestone_is_quoted(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[], milestone="1.0")
        text = cairn.dump_frontmatter(fields)
        self.assertIn('milestone: "1.0"', text)

    def test_null_is_bare_not_quoted(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[])
        text = cairn.dump_frontmatter(fields)
        self.assertIn("parent: null", text)
        self.assertNotIn('parent: "null"', text)

    def test_labels_render_as_flow_list(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=["auth", "api"])
        text = cairn.dump_frontmatter(fields)
        self.assertIn("labels: [auth, api]", text)

    def test_empty_labels_render_as_empty_flow_list(self):
        fields = {k: None for k in cairn.ISSUE_FIELD_ORDER}
        fields.update(id="PT-1", title="Thing", status="todo", labels=[])
        text = cairn.dump_frontmatter(fields)
        self.assertIn("labels: []", text)

    def test_round_trip_through_parse_yaml_subset(self):
        fields = {
            "id": "PT-7",
            "title": "Round trip me",
            "status": "in-review",
            "milestone": "1.0",
            "parent": "PT-1",
            "assignee": "qa-engineer",
            "labels": ["auth", "api"],
            "priority": "P2",
            "pr": "https://example.com/pr/7",
            "created": "2026-08-01",
            "updated": "2026-08-19",
        }
        text = cairn.dump_frontmatter(fields)
        inner = text[len("---\n"):-len("---\n")]
        self.assertEqual(cairn.parse_yaml_subset(inner), fields)


class ApplyPatchByteBoundaryTests(unittest.TestCase):
    """Each test writes a deliberately awkward body, patches the frontmatter,
    and asserts the tail bytes after the closing fence are identical before
    and after -- not just string-equal, but byte-identical."""

    def _run(self, body: str) -> None:
        tmp = helpers.make_empty_tmp_dir(self)
        path = tmp / "PT-1.md"
        frontmatter_text = (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )
        write_issue(path, frontmatter_text, body)
        before_raw = path.read_bytes()
        before_tail = tail_bytes_after_second_fence(before_raw)

        cairn.apply_patch(path, {"status": "in-review"})

        after_raw = path.read_bytes()
        after_tail = tail_bytes_after_second_fence(after_raw)
        self.assertEqual(before_tail, after_tail, "body bytes changed across a frontmatter-only rewrite")

        # And the patch itself did take effect.
        new_frontmatter, _ = cairn.parse_frontmatter(after_raw.decode("utf-8"))
        self.assertEqual(new_frontmatter["status"], "in-review")

    def test_body_with_trailing_whitespace_on_lines(self):
        self._run("Some text.   \nAnother line.\t\n\nTrailing blank line above.\n")

    def test_body_with_no_trailing_newline(self):
        self._run("Body with no trailing newline at all")

    def test_body_with_unicode(self):
        self._run("Uses unicode: café, 日本語, emoji 🎉, em dash —.\n")

    def test_body_with_code_fence_and_delimiter_lookalike(self):
        self._run("## Comments\n\n### @a — 2026-01-01\n\n```\n### @fake — 2026-01-01\n```\n")

    def test_body_that_is_empty(self):
        self._run("")


class ApplyPatchBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "PT-1.md"
        frontmatter_text = (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )
        write_issue(self.path, frontmatter_text, "Body text.\n")

    def test_patch_bumps_updated_to_today_by_default(self):
        cairn.apply_patch(self.path, {"status": "in-review"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())

    def test_explicit_updated_in_patch_is_honored(self):
        cairn.apply_patch(self.path, {"status": "done", "updated": "2026-01-01"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["updated"], "2026-01-01")

    def test_patch_only_touches_given_fields(self):
        cairn.apply_patch(self.path, {"status": "in-review"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["title"], "Thing")
        self.assertEqual(frontmatter["id"], "PT-1")

    def test_patch_returns_new_frontmatter_dict(self):
        result = cairn.apply_patch(self.path, {"status": "in-review"})
        self.assertEqual(result["status"], "in-review")

    def test_no_stray_temp_files_left_behind(self):
        cairn.apply_patch(self.path, {"status": "in-review"})
        leftovers = [p for p in self.tmp.iterdir() if p.name != "PT-1.md"]
        self.assertEqual(leftovers, [], f"unexpected leftover files: {leftovers}")


class UnknownFrontmatterKeyPreservationTests(unittest.TestCase):
    """MUST-FIX finding 1 (architect conformance review,
    temp/2026-08-19-architect-cairn-conformance.md): dump_frontmatter today
    emits exactly ISSUE_FIELD_ORDER and nothing else, so any key not on
    that list is silently destroyed by the next frontmatter-only rewrite --
    verified by the architect by hand-adding `epic: platform` to an issue
    and watching it vanish after `cairn set`. Ruled fix: emit keys present
    in the dict -- ISSUE_FIELD_ORDER keys first in canonical order, then
    any remaining keys in insertion order. All tests here are RED against
    current cairn.py."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "PT-1.md"

    def _canonical_frontmatter_text(self):
        return (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "blocked_by: []\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )

    def _frontmatter_keys_in_file(self) -> list:
        raw = self.path.read_text(encoding="utf-8")
        inner = raw.split("---\n", 2)[1]  # between the two fence lines
        return [line.split(":", 1)[0] for line in inner.splitlines() if ":" in line]

    def test_single_unknown_key_survives_a_patch(self):
        write_issue(self.path, self._canonical_frontmatter_text() + "epic: platform\n", "Body.\n")
        cairn.apply_patch(self.path, {"status": "in-review"})

        raw = self.path.read_text(encoding="utf-8")
        self.assertIn("epic: platform", raw, "unknown key 'epic' was dropped on rewrite")
        frontmatter, _ = cairn.parse_frontmatter(raw)
        self.assertEqual(frontmatter["status"], "in-review")  # the patch itself still applied

    def test_canonical_keys_lead_in_order_then_unknown_keys_follow_in_insertion_order(self):
        write_issue(
            self.path,
            self._canonical_frontmatter_text() + "epic: platform\nteam: growth\n",
            "Body.\n",
        )
        cairn.apply_patch(self.path, {"status": "in-review"})

        keys = self._frontmatter_keys_in_file()
        self.assertEqual(
            keys[: len(cairn.ISSUE_FIELD_ORDER)], cairn.ISSUE_FIELD_ORDER,
            "canonical keys must still lead, in their documented order",
        )
        self.assertEqual(
            keys[len(cairn.ISSUE_FIELD_ORDER):], ["epic", "team"],
            "unknown keys must survive in their original insertion order",
        )

    def test_apply_patch_on_a_milestone_file_does_not_obliterate_it(self):
        # The architect's sharper point: apply_patch is public and
        # generically named, so calling it on a milestone/major file (which
        # has a completely different schema) currently substitutes a
        # null-filled *issue* schema over the real fields. This is the same
        # root cause as the unknown-key-dropping bug, at higher stakes.
        milestone_path = self.tmp / "1.0.md"
        milestone_path.write_text(
            '---\nid: "1.0"\nname: MVP\nkind: product\nmajor: V1\nstatus: planned\n'
            "target_tag: v1.0.0\nga: true\n---\n\nDoD.\n",
            encoding="utf-8",
        )
        cairn.apply_patch(milestone_path, {"status": "in-progress"})

        frontmatter, _ = cairn.parse_frontmatter(milestone_path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["status"], "in-progress")
        self.assertEqual(frontmatter["name"], "MVP", "milestone-only field 'name' was obliterated")
        self.assertEqual(frontmatter["kind"], "product", "milestone-only field 'kind' was obliterated")
        self.assertEqual(frontmatter["major"], "V1", "milestone-only field 'major' was obliterated")
        self.assertEqual(frontmatter["target_tag"], "v1.0.0")
        self.assertTrue(frontmatter["ga"])
        self.assertNotIn("labels", frontmatter, "issue-only field 'labels' must not appear on a milestone")


class ClearedNullableFieldTests(unittest.TestCase):
    """MUST-FIX finding 2 (architect conformance review): `_coerce_cli_value`
    only maps the literal string "null" to None; clearing a field to empty
    (`cairn set PT-1 milestone=`, or a board drawer field cleared to "")
    writes a bare `""` instead, and `cairn check` then rejects the repo's
    own output (`unknown milestone ''`). Ruled fix: coerce "" -> None for
    the nullable fields (milestone, assignee, parent, priority, pr), in
    BOTH `_coerce_cli_value` (CLI) and `apply_patch` (server-side -- the
    durable place, since it also catches the board). All tests here are RED
    against current cairn.py."""

    NULLABLE_FIELDS = ("milestone", "assignee", "parent", "priority", "pr")

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.path = self.data_dir / "issues" / "PT-1.md"

    def test_apply_patch_coerces_empty_string_to_null_for_each_nullable_field(self):
        for field in self.NULLABLE_FIELDS:
            with self.subTest(field=field):
                cairn.apply_patch(self.path, {field: ""})
                frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
                self.assertIsNone(
                    frontmatter[field],
                    f"apply_patch wrote {field}='' instead of coercing to null",
                )

    def test_cleared_milestone_via_cli_set_is_null_and_check_stays_clean(self):
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "set", "PT-1", "milestone=", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertIsNone(frontmatter["milestone"], "cairn set milestone= must clear to null, not ''")

        check_errors = cairn.check_repo(self.data_dir)
        self.assertEqual(
            check_errors, [],
            f"a repo cairn set just wrote must not be rejected by cairn check's own lint: {check_errors}",
        )

    def test_cleared_milestone_via_server_patch_is_null_and_check_stays_clean(self):
        server = cairn.make_server(self.data_dir, port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=5)))
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base_url}/api/board", timeout=1).close()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.05)

        seen = json.loads(urllib.request.urlopen(f"{base_url}/api/issue/PT-1").read())["seen"]
        data = json.dumps({"seen": seen, "patch": {"milestone": ""}}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/issue/PT-1", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        resp = urllib.request.urlopen(req)
        payload = json.loads(resp.read())
        self.assertIsNone(payload["milestone"], "server-side patch must coerce '' to null too, not just the CLI")

        check_errors = cairn.check_repo(self.data_dir)
        self.assertEqual(check_errors, [], f"post-patch repo must stay lint-clean: {check_errors}")


class AppendCommentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "PT-1.md"

    def _frontmatter_text(self):
        return (
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n"
        )

    def test_append_to_file_with_existing_comments_section(self):
        write_issue(self.path, self._frontmatter_text(), "Body.\n\n## Comments\n\n### @a — 2026-08-01\n\nFirst.\n")
        cairn.append_comment(self.path, "mosko", "Second comment.", comment_date="2026-08-19")
        _, body = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[1]["author"], "mosko")
        self.assertEqual(comments[1]["date"], "2026-08-19")
        self.assertEqual(comments[1]["body"].strip(), "Second comment.")

    def test_append_to_file_with_no_comments_section_yet(self):
        write_issue(self.path, self._frontmatter_text(), "Body with no comments section at all.\n")
        cairn.append_comment(self.path, "mosko", "First ever comment.", comment_date="2026-08-19")
        _, body = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertIn("## Comments", body)
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["author"], "mosko")

    def test_append_preserves_earlier_comment_bodies_byte_for_byte(self):
        original_body = "Body.\n\n## Comments\n\n### @a — 2026-08-01\n\nFirst, with trailing space.   \n"
        write_issue(self.path, self._frontmatter_text(), original_body)
        cairn.append_comment(self.path, "mosko", "Second.", comment_date="2026-08-19")
        raw = self.path.read_bytes()
        self.assertIn(b"First, with trailing space.   \n", raw)

    def test_append_bumps_updated(self):
        write_issue(self.path, self._frontmatter_text(), "Body.\n")
        cairn.append_comment(self.path, "mosko", "A comment.", comment_date="2026-08-19")
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())

    def test_append_defaults_date_to_today(self):
        write_issue(self.path, self._frontmatter_text(), "Body.\n")
        cairn.append_comment(self.path, "mosko", "A comment.")
        _, body = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        _, comments = cairn.split_comments(body)
        self.assertEqual(comments[-1]["date"], datetime.date.today().isoformat())

    def test_append_comment_on_a_record_injects_no_updated_key(self):
        # PT-51 §4's prerequisite engine fix: records (milestone/major) have
        # no `updated` field in their schema (PT-13 deliberately kept it
        # off them) -- append_comment unconditionally bumping it would
        # inject an off-schema key the first time anyone comments on a
        # record. Gate the bump on _is_issue_shaped, the same guard
        # apply_patch already uses.
        record_path = self.tmp / "PT-1.0.md"
        record_path.write_bytes((
            "---\nid: PT-1.0\nname: MVP\nkind: product\nmajor: PT-V1\nstatus: planned\n"
            "target_tag: v1.0.0\nga: false\n---\n\nDoD.\n"
        ).encode("utf-8"))
        cairn.append_comment(record_path, "mosko", "A record comment.", comment_date="2026-08-24")
        frontmatter, body = cairn.parse_frontmatter(record_path.read_text(encoding="utf-8"))
        self.assertNotIn("updated", frontmatter, "a record frontmatter must never gain an updated key")
        _, comments = cairn.split_comments(body)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["author"], "mosko")
        self.assertEqual(comments[0]["date"], "2026-08-24")


class PT7FileModePreservationTests(unittest.TestCase):
    """PT-7: a frontmatter rewrite must preserve the original file's mode.
    `_atomic_write` writes through `tempfile.mkstemp` (mode 0600 by
    default) then `os.replace`s it over the target -- `os.replace` is a
    rename, so the final file's permission bits come from the *source*
    (the 0600 temp file), silently flipping any other starting mode to
    0600. Exercised across three distinct starting modes, on both
    apply_patch and append_comment (both funnel through _atomic_write)."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "PT-1.md"
        write_issue(
            self.path,
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n",
            "Body.\n",
        )

    def _mode(self) -> int:
        return stat.S_IMODE(self.path.stat().st_mode)

    def test_mode_0644_survives_apply_patch(self):
        os.chmod(self.path, 0o644)
        cairn.apply_patch(self.path, {"status": "in-review"})
        self.assertEqual(self._mode(), 0o644)

    def test_mode_0664_survives_apply_patch(self):
        os.chmod(self.path, 0o664)
        cairn.apply_patch(self.path, {"status": "in-review"})
        self.assertEqual(self._mode(), 0o664)

    def test_mode_0600_survives_apply_patch(self):
        # The "already matches mkstemp's default" case -- must still be
        # provably preserved by an explicit chmod + assert, not just
        # accidentally correct because it happens to equal the default.
        os.chmod(self.path, 0o600)
        cairn.apply_patch(self.path, {"status": "in-review"})
        self.assertEqual(self._mode(), 0o600)

    def test_mode_survives_append_comment_too(self):
        # append_comment shares _atomic_write with apply_patch -- same bug,
        # same fix should cover both call sites.
        os.chmod(self.path, 0o644)
        cairn.append_comment(self.path, "mosko", "A comment.")
        self.assertEqual(self._mode(), 0o644)


class PT13MilestoneFieldOrderAndNoUpdatedInjectionTests(unittest.TestCase):
    """PT-13: apply_patch on a milestone-shaped file must preserve the
    milestone schema's own field order and must NOT inject an `updated:`
    key (that field belongs to the issue schema only). Today
    dump_frontmatter unconditionally reorders every dict to lead with
    whichever ISSUE_FIELD_ORDER keys are present -- for a milestone that
    means `status` (present in both schemas) jumps ahead of `name`/`kind`/
    `major`, and apply_patch unconditionally sets `frontmatter["updated"]`
    regardless of schema. Issue-file behavior (own field order + updated
    bump) must remain unchanged -- pinned here too as a regression guard.
    """

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)
        self.path = self.tmp / "1.0.md"
        self.original_frontmatter_text = (
            'id: "1.0"\nname: MVP\nkind: product\nmajor: V1\nstatus: planned\n'
            "target_tag: v1.0.0\nga: true\n"
        )
        write_issue(self.path, self.original_frontmatter_text, "DoD.\n")
        self.before_raw = self.path.read_text(encoding="utf-8")

    def _frontmatter_keys_in_file(self) -> list:
        raw = self.path.read_text(encoding="utf-8")
        inner = raw.split("---\n", 2)[1]
        return [line.split(":", 1)[0] for line in inner.splitlines() if ":" in line]

    def test_field_order_is_unchanged_after_a_patch(self):
        cairn.apply_patch(self.path, {"status": "in-progress"})
        keys = self._frontmatter_keys_in_file()
        self.assertEqual(keys, ["id", "name", "kind", "major", "status", "target_tag", "ga"])

    def test_no_updated_key_is_injected(self):
        cairn.apply_patch(self.path, {"status": "in-progress"})
        frontmatter, _ = cairn.parse_frontmatter(self.path.read_text(encoding="utf-8"))
        self.assertNotIn(
            "updated", frontmatter,
            "apply_patch injected an issue-only 'updated' key into a milestone-shaped file",
        )

    def test_round_trip_diff_only_touches_the_patched_line(self):
        cairn.apply_patch(self.path, {"status": "in-progress"})
        before_lines = self.before_raw.splitlines()
        after_lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(before_lines), len(after_lines), "line count changed -- a key was added or dropped")
        differing = [(b, a) for b, a in zip(before_lines, after_lines) if b != a]
        self.assertEqual(differing, [("status: planned", "status: in-progress")])

    def test_issue_field_order_and_updated_bump_are_unaffected(self):
        # Regression guard -- PT-13 must not touch the issue-file path.
        issue_path = self.tmp / "PT-1.md"
        write_issue(
            issue_path,
            "id: PT-1\ntitle: Thing\nstatus: todo\nmilestone: null\nparent: null\n"
            "blocked_by: []\nassignee: null\nlabels: []\npriority: null\npr: null\n"
            "created: 2026-08-01\nupdated: 2026-08-01\n",
            "Body.\n",
        )
        cairn.apply_patch(issue_path, {"status": "in-review"})
        raw = issue_path.read_text(encoding="utf-8")
        inner = raw.split("---\n", 2)[1]
        keys = [line.split(":", 1)[0] for line in inner.splitlines() if ":" in line]
        self.assertEqual(keys, cairn.ISSUE_FIELD_ORDER)
        frontmatter, _ = cairn.parse_frontmatter(raw)
        self.assertEqual(frontmatter["updated"], datetime.date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
