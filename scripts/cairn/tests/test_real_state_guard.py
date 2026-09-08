"""PT-100 gate-1 ruling, RE-ISSUED WHOLE (architect, process/cairn/issues/
PT-100.md @ 0487f33, superseding @d0de5e3; addendum 1 @c2d868f): failing
acceptance tests for the shared real-file guard helper the ruling adds
to `scripts/cairn/tests/helpers.py` -- `snapshot_real_state`,
`diagnose_real_state`, `assert_real_state_untouched`. Six real-file guard
modules (test_milestone_overhead, test_otel_receiver, test_otel_receiver_
self_stop, test_receiver_flush_drop, test_run_tests, test_test_run_hooks)
are ported onto this helper by implementation-lead; this file tests the
helper ITSELF, in isolation, against synthetic fixtures under a
throwaway tmp dir -- NEVER the real committed process/cairn/metrics/
files.

**The retraction that drives this file's shape.** The first ruling
(@d0de5e3, discarded here -- its counter-monotonicity tests are gone,
never a subject of any commit past this file's first, superseded one)
keyed rows by `(issue, role, model, source)` into a dict. That key is
NOT unique (558 real lines, 401 distinct keys, one key 32 times), so
last-occurrence-wins silently invented an "in-place update" and three
"decreased counters" that were never real. The corrected tolerance is
**raw-line multiset containment**: every pre-existing LINE (not key)
must still be present verbatim; only its position may move (the
daemon's `_append_lines` re-sorts the whole file). A duplicate-key pair
(two lines, same identity key, different `generated`) is the fixture
that proves a helper isn't secretly keying by identity again -- removing
one copy must still raise even though the KEY still appears via the
other copy.

Assumed signature (the ruling fixes the CONTRACT, not the exact
parameter list -- flag to the architect if implementation-lead's shape
diverges):

    snapshot_real_state(token_usage_path: Path, pidfile_path: Path,
        sessions_dir: Path, data_dir: Path) -> <opaque snapshot>
        Records token-usage LINES as a multiset (never parsed into an
        identity-keyed dict) plus raw bytes, `.receiver.pid` bytes, and
        the `.sessions/` listing. `data_dir` (a `process/cairn`-shaped
        root, `helpers.make_tmp_data_dir`'s own shape) resolves whether
        a NEW line's `issue` is backed by a real issue file.

    diagnose_real_state(snapshot) -> List[str]
        Re-reads current state from the paths in `snapshot`; `[]` when
        nothing changed or the change classifies as a daemon flush
        (every pre-existing line contained verbatim, every new line's
        issue backed). Every non-empty diagnosis names four facts:
        line-count delta, whether containment holds, how many
        pre-existing lines went missing plus the first one verbatim
        (classified, when any are missing, as "looks like a backfill
        re-run" when every missing line carries
        `source: transcript-backfill`, else a suspected test write),
        and the first differing line index.

    assert_real_state_untouched(snapshot) -> None
        Raises `AssertionError` joining `diagnose_real_state`'s
        findings when non-empty; never a bare `assert` (PT-91 Amendment
        1 -- `-O` strips it silently).

Row/field shapes mirror test_tokens_endpoint.py's own `token_line()`
fixture. Issue-id backing: `helpers.make_tmp_data_dir` copies the real
checked-in fixture tree, which carries `PT-1`, `PT-3`, `PT-4` as real
issue files -- `PT-2` is a deliberate gap, the "no issue file backs
this id" case.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401


def usage_row(
    issue: str, role: str = "team-lead", model: str = "claude-sonnet-5", source: str = "otel",
    input: int = 10, cache_write: int = 0, cache_read: int = 0, output: int = 0,
    generated: str = "2026-09-08T00:00:00Z",
) -> dict:
    return {
        "source": source, "generated": generated,
        "window_start": "2026-09-08", "window_end": "2026-09-08",
        "issue": issue, "role": role, "model": model,
        "input": input, "cache_write": cache_write, "cache_read": cache_read, "output": output,
        "records": 1,
    }


def line_for(row: dict) -> str:
    """The exact raw line text a row serializes to -- deterministic given
    identical field values, so reusing the same string across "before"
    and "after" fixture writes is a genuine verbatim-survival test, not
    an accidental re-serialization that happens to match."""
    return json.dumps(row, separators=(",", ":"))


def write_lines(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def make_fixture(testcase):
    """(token_usage_path, pidfile_path, sessions_dir, data_dir) -- fresh,
    isolated, never the real committed files."""
    data_dir = helpers.make_tmp_data_dir(testcase)
    tmp = data_dir.parent
    token_usage_path = tmp / "token-usage.jsonl"
    pidfile_path = tmp / ".receiver.pid"
    sessions_dir = tmp / ".sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return token_usage_path, pidfile_path, sessions_dir, data_dir


def _snapshot(*args):
    assert hasattr(helpers, "snapshot_real_state"), (
        "helpers.snapshot_real_state does not exist yet -- PT-100's ruled shared real-file "
        "guard helper (process/cairn/issues/PT-100.md @ 0487f33) is unimplemented"
    )
    return helpers.snapshot_real_state(*args)


def _diagnose(snap):
    assert hasattr(helpers, "diagnose_real_state"), (
        "helpers.diagnose_real_state does not exist yet -- PT-100's ruled shared real-file "
        "guard helper is unimplemented"
    )
    return helpers.diagnose_real_state(snap)


def _assert_untouched(snap):
    assert hasattr(helpers, "assert_real_state_untouched"), (
        "helpers.assert_real_state_untouched does not exist yet -- PT-100's ruled shared "
        "real-file guard helper is unimplemented"
    )
    helpers.assert_real_state_untouched(snap)


class DaemonShapedFlushTests(unittest.TestCase):
    """Ruling (d)1: a daemon-shaped flush -- every old LINE present,
    re-sorted (order changes), new lines for real issue ids -- produces
    NO finding. Mutation: compare bytes for equality (which a re-sort
    always fails, even legitimately).

    Carries the addendum's duplicate-key pair (two lines sharing one
    identity key, differing only in `generated`) among the "old" lines --
    proves containment doesn't need identity keys to be unique."""

    def test_a_daemon_shaped_resort_with_a_duplicate_key_pair_produces_no_finding(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        dup_a = line_for(usage_row("PT-1", generated="2026-09-08T00:00:00Z"))
        dup_b = line_for(usage_row("PT-1", generated="2026-09-08T00:05:00Z"))  # SAME identity key, different generated
        other = line_for(usage_row("PT-3", generated="2026-09-08T00:00:00Z"))
        write_lines(token_usage_path, [dup_a, dup_b, other])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        new_line = line_for(usage_row("PT-4", generated="2026-09-08T00:10:00Z"))  # real, backed
        # RE-SORTED order, every old line still present VERBATIM, one new line.
        write_lines(token_usage_path, [other, new_line, dup_b, dup_a])
        findings = _diagnose(snap)
        self.assertEqual(
            findings, [],
            f"a daemon-shaped re-sort (every old line verbatim, just reordered, one new "
            f"backed-issue line) must produce NO finding -- got {findings!r}",
        )


class DroppedLineSurvivesLineCountTests(unittest.TestCase):
    """Ruling (d)2: a re-sort with ONE old line dropped raises, naming the
    missing line -- even when TWO new lines are also added, so the total
    line count grows and a count-only comparison would wrongly pass.
    Mutation: compare line counts only."""

    def test_a_dropped_line_plus_two_additions_still_raises_naming_the_missing_line(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        keep_1 = line_for(usage_row("PT-1", generated="2026-09-08T00:00:00Z"))
        dropped = line_for(usage_row("PT-3", generated="2026-09-08T00:00:00Z"))
        write_lines(token_usage_path, [keep_1, dropped])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        new_a = line_for(usage_row("PT-4", generated="2026-09-08T00:10:00Z"))
        new_b = line_for(usage_row("PT-1", role="qa-engineer", generated="2026-09-08T00:10:00Z"))
        # 2 lines before -> 3 after: `dropped` is GONE, two new lines added.
        # A naive "count only" check sees 2 -> 3 (grew) and would wrongly
        # call this a legitimate flush.
        write_lines(token_usage_path, [keep_1, new_a, new_b])
        with self.assertRaises(AssertionError) as ctx:
            _assert_untouched(snap)
        self.assertIn(
            "PT-3", str(ctx.exception),
            f"the raised message must NAME the missing line (PT-3's row) -- got {ctx.exception}",
        )


class UnbackedIssueIdTests(unittest.TestCase):
    """Ruling (d)3: a new line whose `issue` no issue file backs raises,
    even though containment otherwise holds. Mutation: skip the issue-id
    resolution."""

    def test_a_new_line_for_an_issue_no_file_backs_raises(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        kept = line_for(usage_row("PT-1", generated="2026-09-08T00:00:00Z"))
        write_lines(token_usage_path, [kept])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        # PT-2 has no issue file in this fixture (PT-1/PT-3/PT-4 exist,
        # PT-2 is a deliberate gap) -- containment otherwise holds, one
        # new line appended.
        unbacked = line_for(usage_row("PT-2", generated="2026-09-08T00:10:00Z"))
        write_lines(token_usage_path, [kept, unbacked])
        with self.assertRaises(AssertionError):
            _assert_untouched(snap)


class TruncationTests(unittest.TestCase):
    """Ruling (d)4: truncation to empty raises. Mutation: treat an empty
    snapshot (the CURRENT, post-truncation file) as "nothing to compare"
    and skip the check."""

    def test_truncation_to_empty_raises(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        write_lines(token_usage_path, [
            line_for(usage_row("PT-1")), line_for(usage_row("PT-3")), line_for(usage_row("PT-4")),
        ])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_lines(token_usage_path, [])  # truncated to empty
        with self.assertRaises(AssertionError):
            _assert_untouched(snap)


class DiagnosisFactsAndBackfillClassificationTests(unittest.TestCase):
    """Ruling (d)5 + addendum 1: every diagnosis names four facts --
    line-count delta, whether containment holds, the first missing line
    verbatim, and the first differing line index -- and, when lines ARE
    missing, classifies the cause: "looks like a backfill re-run" when
    EVERY missing line carries `source: transcript-backfill`, else a
    suspected test write. Mutation: drop the missing-line excerpt.
    Exact phrasing isn't ruled, so this checks each concept's keyword
    rather than a verbatim string."""

    def test_the_finding_names_all_four_facts(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        keep = line_for(usage_row("PT-1"))
        dropped = line_for(usage_row("PT-3", generated="2026-09-08T00:00:00Z"))
        write_lines(token_usage_path, [keep, dropped])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_lines(token_usage_path, [keep])  # `dropped` removed
        findings = _diagnose(snap)
        joined = " ".join(findings).lower()
        self.assertRegex(joined, r"\bline", f"expected the line-count delta to be named -- got {findings!r}")
        self.assertRegex(joined, r"\bcontain", f"expected containment status to be named -- got {findings!r}")
        self.assertIn(
            '"issue":"pt-3"', joined.replace(" ", ""),
            f"expected the first missing line's VERBATIM text (PT-3's row) to be quoted -- got {findings!r}",
        )
        self.assertRegex(joined, r"\bdiffer", f"expected the first differing line index to be named -- got {findings!r}")

    def test_missing_lines_all_backfill_sourced_are_classified_as_a_backfill_re_run(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        backfill_line = line_for(usage_row("PT-1", source="transcript-backfill"))
        write_lines(token_usage_path, [backfill_line])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_lines(token_usage_path, [])  # the ONLY line, backfill-sourced, vanished
        findings = _diagnose(snap)
        joined = " ".join(findings).lower()
        self.assertIn(
            "backfill", joined,
            f"every missing line carries source: transcript-backfill -- expected the "
            f"'looks like a backfill re-run' classification -- got {findings!r}",
        )

    def test_missing_lines_not_all_backfill_sourced_are_classified_as_a_suspected_test_write(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        otel_line = line_for(usage_row("PT-1", source="otel"))
        write_lines(token_usage_path, [otel_line])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_lines(token_usage_path, [])  # the ONLY line, otel-sourced (not backfill), vanished
        findings = _diagnose(snap)
        joined = " ".join(findings).lower()
        self.assertNotIn(
            "backfill", joined,
            f"the missing line is otel-sourced, not transcript-backfill -- must NOT get the "
            f"backfill-re-run classification -- got {findings!r}",
        )
        self.assertIn(
            "test", joined,
            f"expected a suspected-test-write classification -- got {findings!r}",
        )


class DuplicateIdentityKeyNotCollapsedTests(unittest.TestCase):
    """Ruling (d)6, the retraction's own lesson: a fixture carrying the
    SAME identity key twice (differing only in `generated`) must still
    raise when only ONE copy is removed, even though the key itself
    still appears via the surviving copy. Mutation: build the comparison
    via a dict keyed by identity -- the exact defect @0487f33 retracts."""

    def test_removing_one_copy_of_a_duplicate_key_still_raises(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        copy_a = line_for(usage_row("PT-1", generated="2026-09-08T00:00:00Z"))
        copy_b = line_for(usage_row("PT-1", generated="2026-09-08T00:05:00Z"))  # same key as copy_a
        write_lines(token_usage_path, [copy_a, copy_b])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_lines(token_usage_path, [copy_a])  # copy_b's line vanished; the KEY still "appears" via copy_a
        with self.assertRaises(
            AssertionError,
            msg="removing one of two lines sharing an identity key must still raise -- a "
            "dict-keyed-by-identity comparison would see the key present (via the surviving "
            "copy) and wrongly tolerate this",
        ):
            _assert_untouched(snap)


class SessionsRegistryTests(unittest.TestCase):
    """Ruling siblings section: `.sessions/` tolerates ADDITIONS only -- a
    removal or a content change raises. Mutation: tolerate removals too."""

    def test_an_added_session_file_is_tolerated(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        (sessions_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        (sessions_dir / "sess-b.json").write_text("{}", encoding="utf-8")  # ADDED
        findings = _diagnose(snap)
        self.assertEqual(findings, [], f"an ADDED session registry entry must be tolerated -- got {findings!r}")

    def test_a_removed_session_file_raises(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        (sessions_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        (sessions_dir / "sess-b.json").write_text("{}", encoding="utf-8")
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        (sessions_dir / "sess-a.json").unlink()  # REMOVED
        with self.assertRaises(AssertionError):
            _assert_untouched(snap)

    def test_a_content_changed_session_file_raises(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        (sessions_dir / "sess-a.json").write_text('{"a": 1}', encoding="utf-8")
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        (sessions_dir / "sess-a.json").write_text('{"a": 2}', encoding="utf-8")  # CONTENT CHANGED
        with self.assertRaises(AssertionError):
            _assert_untouched(snap)


# --------------------------------------------------------------------------
# Ruling (d)8 / (c): PT-91 Amendment 1's lesson, re-pinned for the new
# shared helper -- a bare `assert` is stripped entirely under `python -O`
# (measured on PT-91). Mutation: revert to a bare `assert`. Real
# subprocess, real -O flag -- never mocked, mirroring test_milestone_
# overhead.py's ExplicitRaiseDifferentialTests pattern. The mismatch here
# is a full truncation (test 4's shape) -- any correct implementation
# must flag it, so this test is agnostic to exactly how containment is
# implemented.
# --------------------------------------------------------------------------

_DASH_O_GUARD_PROBE_TEMPLATE = '''
import json
import sys
from pathlib import Path

TESTS_DIR = Path(sys.argv[1])
FIXTURE_ROOT = Path(sys.argv[2])
sys.path.insert(0, str(TESTS_DIR))
import helpers  # noqa: E402

data_dir = helpers.copy_fixture_data_dir(FIXTURE_ROOT)
token_usage_path = FIXTURE_ROOT / "token-usage.jsonl"
pidfile_path = FIXTURE_ROOT / ".receiver.pid"
sessions_dir = FIXTURE_ROOT / ".sessions"
sessions_dir.mkdir(parents=True, exist_ok=True)

line = json.dumps({
    "source": "otel", "generated": "2026-09-08T00:00:00Z",
    "window_start": "2026-09-08", "window_end": "2026-09-08",
    "issue": "PT-1", "role": "team-lead", "model": "claude-sonnet-5",
    "input": 10, "cache_write": 0, "cache_read": 0, "output": 0, "records": 1,
}, separators=(",", ":"))

token_usage_path.write_text(line + "\\n", encoding="utf-8")
snap = helpers.snapshot_real_state(token_usage_path, pidfile_path, sessions_dir, data_dir)

token_usage_path.write_text("", encoding="utf-8")  # truncated to empty
helpers.assert_real_state_untouched(snap)
'''


class GuardFiresUnderDashOTests(unittest.TestCase):
    def _run(self, use_dash_o: bool) -> subprocess.CompletedProcess:
        fixture_root = helpers.make_empty_tmp_dir(self)
        script = fixture_root / "dash_o_probe.py"
        script.write_text(_DASH_O_GUARD_PROBE_TEMPLATE, encoding="utf-8")
        args = [sys.executable]
        if use_dash_o:
            args.append("-O")
        args += [str(script), str(helpers.TESTS_DIR), str(fixture_root)]
        return subprocess.run(args, capture_output=True, text=True)

    def test_the_guard_fires_without_dash_o(self):
        result = self._run(use_dash_o=False)
        self.assertNotEqual(
            result.returncode, 0,
            f"the guard must catch a truncation without -O -- got rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_the_guard_still_fires_under_dash_o(self):
        result = self._run(use_dash_o=True)
        self.assertNotEqual(
            result.returncode, 0,
            f"the guard must still catch a truncation under -O (a bare `assert` would be "
            f"silently stripped) -- got rc={result.returncode} stdout={result.stdout!r} "
            f"stderr={result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
