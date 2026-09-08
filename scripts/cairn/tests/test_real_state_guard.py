"""PT-100 gate-1 ruling (architect, process/cairn/issues/PT-100.md @
d0de5e3): failing acceptance tests for the shared real-file guard helper
the ruling adds to `scripts/cairn/tests/helpers.py` --
`snapshot_real_state`, `diagnose_real_state`, `assert_real_state_untouched`.
Six real-file guard modules (test_milestone_overhead, test_otel_receiver,
test_otel_receiver_self_stop, test_receiver_flush_drop, test_run_tests,
test_test_run_hooks) are ported onto this helper by implementation-lead;
this file tests the helper ITSELF, in isolation, against synthetic
fixtures under a throwaway tmp dir -- NEVER the real committed
process/cairn/metrics/ files.

Assumed signature (the ruling fixes the CONTRACT, not the exact
parameter list -- flag to the architect if implementation-lead's shape
diverges from this):

    snapshot_real_state(token_usage_path: Path, pidfile_path: Path,
        sessions_dir: Path, data_dir: Path) -> <opaque snapshot>
        `data_dir` is a `process/cairn`-shaped root (the same shape
        `helpers.make_tmp_data_dir` returns and every other data_dir-
        taking function in this codebase already takes) -- used to
        resolve whether a NEW identity key's `issue` is backed by a
        real issue file (or is `main` / a `milestone:` bucket, per the
        ruling's residual-risk paragraph -- not exercised here since
        this file never constructs a `main`/`milestone:` row).

    diagnose_real_state(snapshot) -> List[str]
        Re-reads the CURRENT state from the paths recorded in
        `snapshot` and returns human-readable findings; `[]` when
        nothing changed or the whole-file rewrite classifies as
        legitimate live-daemon activity (the ruling's semantic
        tolerance: every prior identity key survives, no counter
        decreased, `generated` not older, every new key backed by a
        real issue id).

    assert_real_state_untouched(snapshot) -> None
        Raises `AssertionError` joining `diagnose_real_state`'s
        findings when non-empty; never a bare `assert` (PT-91
        Amendment 1 -- `-O` strips it silently).

Identity key = (issue, role, model, source); counters = the four token
fields (input/cache_write/cache_read/output). Row/field shapes mirror
test_tokens_endpoint.py's own `token_line()` fixture, the one other
place in this suite that constructs token-usage.jsonl rows.

Issue-id backing fixture: `helpers.make_tmp_data_dir` copies the real
checked-in `tests/fixtures/process/cairn` tree, which carries `PT-1`,
`PT-3`, `PT-4` as real issue files -- `PT-2` is a deliberate gap, used
here as the "no issue file backs this id" case.
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


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


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
        "guard helper (process/cairn/issues/PT-100.md @ d0de5e3) is unimplemented"
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
    """Ruling (d)1: the discriminator is semantic, not positional -- a
    whole-file rewrite that classifies as legitimate live-daemon
    activity must produce NO finding, or the guard keeps tripping in
    tearDownModule for a false positive. Mutation: drop the monotone-
    counter check so it reports anyway."""

    def test_a_daemon_shaped_rewrite_produces_no_finding(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        write_jsonl(token_usage_path, [usage_row("PT-1", input=10, generated="2026-09-08T00:00:00Z")])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        # Whole-file rewrite (ruling measurement 1's real shape): PT-1's
        # counter GREW, `generated` advanced, and one NEW row lands for a
        # DIFFERENT real, backed issue id (PT-3) -- every prior identity
        # key survives, no counter decreased.
        write_jsonl(token_usage_path, [
            usage_row("PT-1", input=25, generated="2026-09-08T00:01:00Z"),
            usage_row("PT-3", input=5, generated="2026-09-08T00:01:00Z"),
        ])
        findings = _diagnose(snap)
        self.assertEqual(
            findings, [],
            f"a daemon-shaped whole-file rewrite (prior keys survive, counters only grew, "
            f"generated advanced, the new key backed by a real issue id) must produce NO "
            f"finding -- got {findings!r}",
        )


class KeyRemovedRewriteTests(unittest.TestCase):
    """Ruling (d)2: a rewrite that drops a prior identity key produces a
    finding NAMING it, visibly different from the daemon-shaped case
    above (which produces none). Mutation: compare only line counts."""

    def test_a_removed_identity_key_produces_a_finding_naming_it(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        write_jsonl(token_usage_path, [usage_row("PT-1", input=10), usage_row("PT-3", input=5)])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        # PT-1's row is gone entirely -- a test rewriting the file, not a
        # daemon flush; the exact shape the guard exists to catch.
        write_jsonl(token_usage_path, [usage_row("PT-3", input=5)])
        findings = _diagnose(snap)
        self.assertNotEqual(findings, [], "a removed identity key must produce at least one finding")
        joined = " ".join(findings)
        self.assertIn("PT-1", joined, f"the finding must NAME the missing key (PT-1) -- got {findings!r}")


class UnbackedIssueIdTests(unittest.TestCase):
    """Ruling (d)3: an appended row otherwise shaped exactly like a
    legitimate daemon flush (prior key survives unchanged, one new row)
    still raises if its `issue` resolves to no real issue file. This is
    the sharpness check that keeps the tolerance narrow (ruling's
    "residual risk" paragraph). Mutation: skip the issue-id resolution."""

    def test_a_new_row_for_an_issue_no_file_backs_raises(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        write_jsonl(token_usage_path, [usage_row("PT-1", input=10)])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        # PT-2 has no issue file in this fixture (PT-1/PT-3/PT-4 exist,
        # PT-2 is a deliberate gap) -- otherwise indistinguishable from a
        # legitimate flush: prior key unchanged, one new row appended.
        write_jsonl(token_usage_path, [usage_row("PT-1", input=10), usage_row("PT-2", input=1)])
        with self.assertRaises(AssertionError):
            _assert_untouched(snap)


class CounterDecreasedTests(unittest.TestCase):
    """Ruling (d)4: a decreased counter raises even though every identity
    key survives -- the second sharpness check. Mutation: compare key
    sets only."""

    def test_a_decreased_counter_raises_even_though_every_key_survives(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        write_jsonl(token_usage_path, [usage_row("PT-1", input=100)])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_jsonl(token_usage_path, [usage_row("PT-1", input=50)])  # same key, LOWER counter
        with self.assertRaises(AssertionError):
            _assert_untouched(snap)


class DiagnosisNamesAllFourFactsTests(unittest.TestCase):
    """Ruling (d)5 / AC1: every diagnosis names four facts -- line-count
    delta, whether prior identity keys survived, whether counters are
    monotone, and the first differing line index. Mutation: drop the
    first-differing-line index. Fixture trips on multiple axes at once
    (a removed key AND a decreased counter) so all four facts have real
    content to report; exact phrasing isn't ruled, so this checks for
    each concept's keyword rather than a verbatim string."""

    def test_the_finding_names_all_four_facts(self):
        token_usage_path, pidfile_path, sessions_dir, data_dir = make_fixture(self)
        write_jsonl(token_usage_path, [usage_row("PT-1", input=10), usage_row("PT-3", input=5)])
        snap = _snapshot(token_usage_path, pidfile_path, sessions_dir, data_dir)

        write_jsonl(token_usage_path, [usage_row("PT-3", input=1)])  # PT-1 removed, PT-3's counter fell
        findings = _diagnose(snap)
        joined = " ".join(findings).lower()
        self.assertRegex(joined, r"\bline", f"expected the line-count delta to be named -- got {findings!r}")
        self.assertRegex(joined, r"\bkey\b", f"expected identity-key survival to be named -- got {findings!r}")
        self.assertRegex(joined, r"\bcounter", f"expected counter monotonicity to be named -- got {findings!r}")
        self.assertRegex(joined, r"\bdiffer", f"expected the first differing line index to be named -- got {findings!r}")


class SessionsRegistryTests(unittest.TestCase):
    """Ruling (d)6 / AC4: `.sessions/` tolerates ADDITIONS only -- a
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
# Ruling (d)7 / (c): PT-91 Amendment 1's lesson, re-pinned for the new
# shared helper -- a bare `assert` is stripped entirely under `python -O`
# (measured on PT-91). Mutation: revert to a bare `assert`. Real
# subprocess, real -O flag -- never mocked, mirroring test_milestone_
# overhead.py's ExplicitRaiseDifferentialTests pattern.
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


def row(input_value):
    return json.dumps({
        "source": "otel", "generated": "2026-09-08T00:00:00Z",
        "window_start": "2026-09-08", "window_end": "2026-09-08",
        "issue": "PT-1", "role": "team-lead", "model": "claude-sonnet-5",
        "input": input_value, "cache_write": 0, "cache_read": 0, "output": 0,
        "records": 1,
    })


token_usage_path.write_text(row(100) + "\\n", encoding="utf-8")
snap = helpers.snapshot_real_state(token_usage_path, pidfile_path, sessions_dir, data_dir)

token_usage_path.write_text(row(50) + "\\n", encoding="utf-8")  # counter DECREASED
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
            f"the guard must catch a decreased counter without -O -- got rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_the_guard_still_fires_under_dash_o(self):
        result = self._run(use_dash_o=True)
        self.assertNotEqual(
            result.returncode, 0,
            f"the guard must still catch a decreased counter under -O (a bare `assert` would "
            f"be silently stripped) -- got rc={result.returncode} stdout={result.stdout!r} "
            f"stderr={result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
