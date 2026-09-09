"""PT-97 gate 2 (qa-engineer): failing tests for the two new hooks,
pinned to the architect's gate-1 ruling (process/cairn/issues/PT-97.md @
a23e832 -- "Seam" and "Guard thresholds").

Two hooks, neither built yet at this sha:
    .claude/hooks/test_run_guard.py   (PreToolUse, matcher Bash) -- refuses
        a teammate's un-tiered full-suite run, naming both `-p` and
        `--gate` in its exit-2 message. Every unknown case (malformed
        stdin, non-Bash, unrecognised agent_type) exits 0 -- that is what
        keeps it off a human's shell and off the lead's finish gate.
    .claude/hooks/test_run_record.py  (PostToolUse, matcher Bash) --
        appends one record per test run to
        process/cairn/metrics/test-runs.jsonl under $CLAUDE_PROJECT_DIR;
        writes nothing for a non-test Bash call.

Every hook invocation here is a real subprocess given a synthetic (or,
for the recorder, the ruling's REAL captured) PreToolUse/PostToolUse
JSON payload on stdin -- never through an actual Bash tool call, and
never against the real repo's metrics file: the recorder tests always
point $CLAUDE_PROJECT_DIR at a throwaway tmp dir.

Writer boundary (ruling): implementation-lead owns both hook files,
.claude/settings.json, run_tests.py, loop_stats.py. qa-engineer owns this
file (new), tests/test_loop_stats.py, and the settings-anchoring guard
(also here, guard 10). Nothing here edits an implementation-lead file.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"
HOOK_PAYLOADS_PATH = REPO_ROOT / "process" / "reviews" / "PT-97" / "hook-payloads.json"
REAL_METRICS_DIR = REPO_ROOT / "process" / "cairn" / "metrics"
REAL_TEST_RUNS_PATH = REAL_METRICS_DIR / "test-runs.jsonl"
REAL_RECEIVER_PIDFILE = REAL_METRICS_DIR / ".receiver.pid"
REAL_SESSIONS_DIR = REAL_METRICS_DIR / ".sessions"
# PT-97 delta 7 seam -- see test_run_tests.py's identical constant.
CAIRN_TEST_RUNS_ENV = "CAIRN_TEST_RUNS_FILE"


def _pre_payload(command: str, agent_type="qa-engineer", **overrides) -> dict:
    payload = {
        "session_id": "test-session-pt97",
        "transcript_path": "/tmp/pt97-fake-transcript.jsonl",
        "cwd": str(REPO_ROOT / "scripts" / "cairn"),
        "scratchpad_dir": "/tmp/pt97-fake-scratchpad",
        "permission_mode": "auto",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "PT-97 guard test"},
        "tool_use_id": "toolu_pt97_test",
    }
    if agent_type is not None:
        payload["agent_type"] = agent_type
    payload.update(overrides)
    return payload


def _load_post_sample() -> dict:
    # The ruling's own real capture -- a hand-written payload proves only
    # self-consistency (ruling, "Writers").
    data = json.loads(HOOK_PAYLOADS_PATH.read_text(encoding="utf-8"))
    return data["post_sample"]


def _run_hook(script: str, stdin_text: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env.setdefault("CLAUDE_PROJECT_DIR", str(REPO_ROOT))
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script)],
        input=stdin_text, capture_output=True, text=True, env=full_env,
    )


class GuardRefusesUntieredFullRunsTests(unittest.TestCase):
    """Guard thresholds 1 and 6: a teammate's bare full-suite run --
    run_tests.py or unittest discover -s tests, either one, no -p/-k --
    is refused with exit 2, message naming both -p and --gate."""

    def test_bare_run_tests_py_is_refused_naming_both_forms(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("cd scripts/cairn && python3 run_tests.py")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)

    def test_bare_unittest_discover_is_also_refused(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("cd scripts/cairn && python3 -m unittest discover -s tests")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)


class GuardAllowsTieredAndGateRunsTests(unittest.TestCase):
    """Guard thresholds 2 and 3: a --gate run and a -p run both pass."""

    def test_a_gate_run_passes(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("python3 run_tests.py --gate green")))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_narrowed_pattern_run_passes(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload('python3 run_tests.py -p "test_x*.py"')))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class GuardFailsOpenTests(unittest.TestCase):
    """Guard thresholds 4 and 5: an unknown/absent agent_type (the human/
    lead lane) and malformed stdin both pass -- every unrecognised case
    exits 0, never 2."""

    def test_unrecognised_agent_type_passes(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("python3 run_tests.py", agent_type="not-a-real-agent-stem")))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_absent_agent_type_passes(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("python3 run_tests.py", agent_type=None)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_malformed_stdin_passes(self):
        result = _run_hook("test_run_guard.py", "not valid json {{{")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_non_bash_tool_passes(self):
        payload = _pre_payload("python3 run_tests.py")
        payload["tool_name"] = "Read"
        result = _run_hook("test_run_guard.py", json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RecorderTests(unittest.TestCase):
    """Guard thresholds 7 and 8: the recorder writes one record matching
    the ruling's real captured payload, and writes nothing for a
    non-test Bash call. $CLAUDE_PROJECT_DIR always points at a throwaway
    tmp dir here -- the real repo's metrics file is never touched."""

    def _env(self, tmp: Path) -> dict:
        return {"CLAUDE_PROJECT_DIR": str(tmp)}

    def _records_path(self, tmp: Path) -> Path:
        return tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"

    def test_recorder_writes_one_record_matching_the_captured_payload(self):
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        result = _run_hook("test_run_record.py", json.dumps(_load_post_sample()), env=self._env(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records_path = self._records_path(tmp)
        self.assertTrue(records_path.exists(), "must write process/cairn/metrics/test-runs.jsonl under $CLAUDE_PROJECT_DIR")
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"expected exactly one record, got {len(lines)}: {lines!r}")
        record = lines[0]
        self.assertEqual(record.get("tests"), 29)
        self.assertEqual(record.get("files"), 1)
        # Mutation guard: seconds must come from the PARSED "Ran 29 tests
        # in 0.079s" summary, never duration_ms/1000 (157/1000 = 0.157,
        # the gap IS shell overhead, per the ruling -- substituting one
        # for the other is exactly the mutation this pins).
        self.assertAlmostEqual(record.get("seconds"), 0.079, places=3)
        self.assertEqual(record.get("runner"), "run_tests")
        self.assertEqual(record.get("who"), "architect")

    def test_recorder_leaves_the_file_unchanged_for_a_non_test_bash_call(self):
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        records_path = self._records_path(tmp)
        records_path.write_text("", encoding="utf-8")
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
            "duration_ms": 42, "tool_use_id": "x",
        }
        result = _run_hook("test_run_record.py", json.dumps(payload), env=self._env(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(records_path.read_text(encoding="utf-8"), "", "a non-test Bash call must never append a record")


class VersionedPythonInterpreterGuardTests(unittest.TestCase):
    """PT-113 gate-1 ruling (PT-113.md @ e5b1106): `_is_python_token` must
    recognise `python3.14`-style basenames as a python invocation, not
    just literal `python`/`python3` -- today a real run typed that way
    passes the PreToolUse guard untouched. Widening the predicate widens
    the guard too: a teammate's un-tiered `python3.14 -m unittest
    discover -s tests` must now be refused (guard threshold 1)."""

    def test_guard_refuses_a_versioned_bare_run_tests_py(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("python3.14 scripts/cairn/run_tests.py")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)

    def test_guard_refuses_a_versioned_bare_unittest_discover(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("python3.14 -m unittest discover -s tests")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)

    def test_guard_allows_the_same_two_versioned_commands_when_gated(self):
        for cmd in (
            "python3.14 scripts/cairn/run_tests.py --gate green",
            "python3.14 -m unittest discover -s tests --gate green",
        ):
            with self.subTest(cmd=cmd):
                result = _run_hook("test_run_guard.py", json.dumps(_pre_payload(cmd)))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class VersionedPythonInterpreterRecordHookTests(unittest.TestCase):
    """Guard threshold 2: a versioned command must patch a trailing
    `who: null` record in place, same shape as
    test_worktree_metrics_path_resolution.py's
    test_the_post_hook_patches_who_in_place... -- and the literal-`python3`
    case must still patch (no second record) once the predicate widens."""

    def _seed(self, tmp: Path, cmd: str) -> Path:
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        records_path.parent.mkdir(parents=True, exist_ok=True)
        seed = {
            "ts": "2026-09-09T00:00:00.000Z", "who": None, "gate": "red", "full": True,
            "runner": "run_tests", "sha": "deadbeef", "branch": "feature/pt-113",
            "seconds": 1.0, "harness_ms": 1000, "jobs": 1, "files": 1, "tests": 1,
            "skipped": 0, "ok": True, "session": "s", "cmd": cmd,
        }
        records_path.write_text(json.dumps(seed) + "\n", encoding="utf-8")
        return records_path

    def _patch_and_check(self, cmd: str):
        tmp = helpers.make_empty_tmp_dir(self)
        records_path = self._seed(tmp, cmd)
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": cmd},
            "tool_response": {"stdout": "", "stderr": ""},
            "duration_ms": 1000, "tool_use_id": "x",
        }
        result = _run_hook("test_run_record.py", json.dumps(payload), env={"CLAUDE_PROJECT_DIR": str(tmp)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"must patch the trailing null-who record in place, not append -- got {lines!r}")
        self.assertEqual(lines[0]["who"], "architect")

    def test_a_versioned_command_patches_the_trailing_null_who_record(self):
        self._patch_and_check("python3.14 scripts/cairn/run_tests.py --gate red")

    def test_the_literal_python3_case_still_patches_after_widening(self):
        self._patch_and_check("python3 scripts/cairn/run_tests.py --gate red")


class IsPythonTokenTruthTableTests(unittest.TestCase):
    """Guard threshold 3: enumerated truth table over
    `_test_run_shared._is_python_token` (PT-113.md @ e5b1106, gate-1
    ruling) -- both directions, not sampled. `python3-config` and
    `python3.14-config` are the reject side the ruling calls out as a
    live evasion risk (both binaries exist on this box); `python2`,
    `py`, and `pypy3` are the brief's out-of-scope interpreters."""

    ACCEPT = (
        "python", "python3", "python3.14",
        "/opt/homebrew/bin/python3.14", "python3.14t",
    )
    REJECT = (
        "python3-config", "python3.14-config", "pypy3", "py", "python2", "python3.x",
    )

    def test_accepted_basenames(self):
        module = _load_hook_module("_test_run_shared.py")
        for tok in self.ACCEPT:
            with self.subTest(tok=tok):
                self.assertTrue(module._is_python_token(tok), f"{tok!r} must be recognised as a python invocation")

    def test_rejected_basenames(self):
        module = _load_hook_module("_test_run_shared.py")
        for tok in self.REJECT:
            with self.subTest(tok=tok):
                self.assertFalse(module._is_python_token(tok), f"{tok!r} must NOT be recognised as a python invocation")


class FlagAwareNarrowingTests(unittest.TestCase):
    """Gate-4 verdict delta 1 (PT-97.md @ d896d8d, blocking): narrowing
    must be detected from the runner's own tokenised arguments, not a
    substring scan of the whole command line -- the substring approach
    breaks in both directions:
    - `--pattern` (run_tests.py's own long form of `-p`) doesn't contain
      the literal substring ` -p `, so it was wrongly treated as NOT
      narrowed and refused.
    - `/usr/bin/time -p ...` DOES contain the literal substring ` -p `
      (time's own flag), so a bare full run was wrongly treated as
      narrowed and let through.
    Reproduced live against e86f163 before writing these (see the
    conversation record, not restated here)."""

    def test_long_form_pattern_flag_passes_the_guard(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload('python3 run_tests.py --pattern "test_x*.py"')))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_time_wrapped_bare_full_run_is_still_refused(self):
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("/usr/bin/time -p python3 -m unittest discover -s tests")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)

    def test_control_the_same_command_without_the_time_prefix_is_also_refused(self):
        # Proves the PREFIX is what changes the (wrong) answer above, not
        # the underlying command -- this one must already pass today.
        result = _run_hook("test_run_guard.py", json.dumps(
            _pre_payload("python3 -m unittest discover -s tests")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_long_form_pattern_flag_is_recorded_as_narrowed_not_full(self):
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": 'python3 run_tests.py --pattern "test_x*.py"'},
            "tool_response": {"stdout": "Ran 5 tests in 0.05s (1 files, 8 workers)\nOK\n", "stderr": ""},
            "duration_ms": 60, "tool_use_id": "x",
        }
        env = {"CLAUDE_PROJECT_DIR": str(tmp)}
        result = _run_hook("test_run_record.py", json.dumps(payload), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines[0].get("full"), f"a --pattern run must record full=false, got: {lines[0]!r}")

    def test_a_narrowed_run_with_a_gate_shaped_command_records_gate_null(self):
        # Verdict delta 5, defence in depth (PT-97.md @ bfb1d92): the
        # runner itself now refuses --gate + -p together (see
        # test_run_tests.py's GateRequiresFullRunTests), but the recorder
        # must never trust a non-null gate on a full=false record either
        # -- belt and suspenders against any command that reaches it with
        # both. Reproduced live against e86f163: currently records
        # gate="green", full=false in the same line.
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": 'python3 run_tests.py --gate green -p "test_x*.py"'},
            "tool_response": {"stdout": "Ran 5 tests in 0.05s (1 files, 8 workers)\nOK\n", "stderr": ""},
            "duration_ms": 60, "tool_use_id": "x",
        }
        env = {"CLAUDE_PROJECT_DIR": str(tmp)}
        result = _run_hook("test_run_record.py", json.dumps(payload), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        record = lines[0]
        self.assertFalse(record.get("full"), f"a -p run must record full=false, got: {record!r}")
        self.assertIsNone(record.get("gate"), f"a full=false record must never carry a non-null gate, got: {record!r}")


class RunnerSelfRecordsTests(unittest.TestCase):
    """Gate-4 verdict delta 2 (blocking): run_tests.py writes its own
    record -- counts, seconds, jobs, gate are all in-process there, so
    scraping them back out of a possibly-piped stdout (every gate owner
    reads a 100-line result through `| tail`, per the verdict's own three
    reproduction runs) cannot be made reliable. The hook's only remaining
    job is filling in `who` (the one field the CLI cannot know).

    Uses the established fake-engine-root technique (PT-77/PT-80,
    test_milestone_overhead.py's with_engine_copy): copies run_tests.py
    into a throwaway root with a tiny, fast, synthetic tests/ dir -- so
    this drives the REAL CLI path end to end without paying for (or
    touching) the real 84-file suite."""

    def _fake_engine_root(self):
        tmp = helpers.make_empty_tmp_dir(self)
        engine_dir = tmp / "scripts" / "cairn"
        engine_dir.mkdir(parents=True)
        engine_dir.joinpath("run_tests.py").write_bytes((helpers.CAIRN_DIR / "run_tests.py").read_bytes())
        tests_dir = engine_dir / "tests"
        tests_dir.mkdir()
        tests_dir.joinpath("test_fake_ok.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        return tmp, engine_dir

    def test_a_run_with_stdout_fully_discarded_still_yields_a_complete_record(self):
        tmp, engine_dir = self._fake_engine_root()
        # Piped through `> /dev/null` -- exactly the shape every gate
        # owner's `| tail` reduces to for this purpose: nothing of the
        # runner's own stdout survives to be scraped afterward.
        result = subprocess.run(
            f'cd "{engine_dir}" && {sys.executable} run_tests.py --gate red > /dev/null',
            shell=True, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        self.assertTrue(records_path.exists(), "run_tests.py itself must write the record -- no hook was involved in this test at all")
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        record = lines[0]
        self.assertEqual(record.get("tests"), 1)
        self.assertIsNotNone(record.get("seconds"))
        self.assertIsNotNone(record.get("jobs"))
        self.assertEqual(record.get("gate"), "red")
        self.assertTrue(record.get("full"))


class SelfRecordSessionTests(unittest.TestCase):
    """PT-112 gate-1 ruling (PT-112.md @8b60a8b), guard threshold 5:
    `run_tests.py::_self_record` writes `session` from
    `$CLAUDE_CODE_SESSION_ID` -- both directions, env set and absent.
    Measured live by the architect: the hook's stdin `session_id` and the
    runner's own `CLAUDE_CODE_SESSION_ID` are the identical string, so
    this is the deterministic matching key the hook uses (no new
    channel, no run id printed in the summary)."""

    def _fake_engine_root(self):
        tmp = helpers.make_empty_tmp_dir(self)
        engine_dir = tmp / "scripts" / "cairn"
        engine_dir.mkdir(parents=True)
        engine_dir.joinpath("run_tests.py").write_bytes((helpers.CAIRN_DIR / "run_tests.py").read_bytes())
        tests_dir = engine_dir / "tests"
        tests_dir.mkdir()
        tests_dir.joinpath("test_fake_ok.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        return tmp, engine_dir

    def _run_and_get_record(self, env: dict) -> dict:
        tmp, engine_dir = self._fake_engine_root()
        result = subprocess.run(
            [sys.executable, str(engine_dir / "run_tests.py"), "--gate", "red"],
            cwd=str(engine_dir), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_session_is_written_from_the_env_var_when_set(self):
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        env["CLAUDE_CODE_SESSION_ID"] = "S-real-session-123"
        record = self._run_and_get_record(env)
        self.assertEqual(record.get("session"), "S-real-session-123")

    def test_session_is_null_when_the_env_var_is_absent(self):
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CAIRN_TEST_RUNS_FILE", None)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        record = self._run_and_get_record(env)
        self.assertIsNone(record.get("session"))


class SessionScopedPatchTests(unittest.TestCase):
    """PT-112 gate-1 ruling (PT-112.md @8b60a8b), guard thresholds 1-4:
    the hook scans the last 200 ledger lines for the NEWEST record with
    `who is null` and `session` non-null and equal to the payload's
    `session_id`, and patches only that line -- replacing the old
    last-line-only rule that cross-attributes concurrent worktree runs."""

    def _env(self, tmp: Path) -> dict:
        return {"CLAUDE_PROJECT_DIR": str(tmp)}

    def _records_path(self, tmp: Path) -> Path:
        return tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"

    def _seed(self, tmp: Path, records: list) -> Path:
        path = self._records_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        return path

    def _record(self, session, who=None, cmd="python3 run_tests.py --gate red") -> dict:
        return {
            "ts": "2026-09-09T00:00:00.000Z", "who": who, "session": session, "gate": "red", "full": True,
            "runner": "run_tests", "sha": None, "branch": None, "seconds": 1.0, "harness_ms": 1000,
            "jobs": 1, "files": 1, "tests": 1, "skipped": 0, "ok": True, "cmd": cmd,
        }

    def _payload(self, session_id, agent_type, command="python3 run_tests.py --gate red", **overrides) -> dict:
        payload = {
            "session_id": session_id, "cwd": "/x", "agent_type": agent_type,
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "", "stderr": ""}, "duration_ms": 1000, "tool_use_id": "x",
        }
        payload.update(overrides)
        return payload

    def test_two_interleaved_sessions_are_each_patched_to_their_own_record(self):
        # Guard 1: S1 first, S2 second, both who:null. Today's last-line
        # rule patches the SECOND (S2) record for the S1 payload -- wrong.
        tmp = helpers.make_empty_tmp_dir(self)
        records_path = self._seed(tmp, [self._record("S1"), self._record("S2")])

        result = _run_hook("test_run_record.py", json.dumps(self._payload("S1", "architect")), env=self._env(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, f"must patch in place, never append -- got {lines!r}")
        self.assertEqual(lines[0]["who"], "architect", f"S1's own record must be patched -- got {lines!r}")
        self.assertIsNone(lines[1]["who"], f"S2's record must stay untouched by S1's payload -- got {lines!r}")

        result2 = _run_hook("test_run_record.py", json.dumps(self._payload("S2", "implementation-lead")), env=self._env(tmp))
        self.assertEqual(result2.returncode, 0, result2.stdout + result2.stderr)
        lines2 = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines2), 2)
        self.assertEqual(lines2[0]["who"], "architect")
        self.assertEqual(lines2[1]["who"], "implementation-lead", f"S2's own record must now be patched -- got {lines2!r}")

    def test_a_stale_null_session_line_is_never_patched(self):
        # Guard 2: a null-session record (every pre-PT-112 record) stays
        # who:null permanently, by design -- no payload may adopt it.
        tmp = helpers.make_empty_tmp_dir(self)
        records_path = self._seed(tmp, [self._record(None)])
        result = _run_hook("test_run_record.py", json.dumps(self._payload("S-anything", "architect")), env=self._env(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"a run_tests command with no match must write nothing -- got {lines!r}")
        self.assertIsNone(lines[0]["who"], f"a null-session line must never be adopted -- got {lines!r}")

    def test_cross_attribution_control_no_match_writes_nothing_for_run_tests(self):
        # Guard 3: neither S1 nor S2 matches the payload's session -- for
        # a run_tests command, write nothing (unattributed beats
        # misattributed), and never append a second record either.
        tmp = helpers.make_empty_tmp_dir(self)
        records_path = self._seed(tmp, [self._record("S1"), self._record("S2")])
        result = _run_hook("test_run_record.py", json.dumps(self._payload("S-unmatched", "architect")), env=self._env(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, f"no match must neither patch nor append -- got {lines!r}")
        self.assertIsNone(lines[0]["who"])
        self.assertIsNone(lines[1]["who"])

    def test_unittest_runner_with_no_match_still_appends_a_self_attributing_record(self):
        # Guard 4: bare `unittest` never self-records, so a miss falls
        # back to scrape-and-append exactly as today -- `session` comes
        # from the payload, so the appended record is self-attributing.
        tmp = helpers.make_empty_tmp_dir(self)
        records_path = self._records_path(tmp)
        records_path.parent.mkdir(parents=True, exist_ok=True)
        records_path.write_text("", encoding="utf-8")
        payload = self._payload(
            "S-new", "qa-engineer", command="python3 -m unittest discover -s tests",
            tool_response={"stdout": "Ran 5 tests in 0.050s\nOK\n", "stderr": ""},
        )
        result = _run_hook("test_run_record.py", json.dumps(payload), env=self._env(tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"expected exactly one appended record -- got {lines!r}")
        self.assertEqual(lines[0]["who"], "qa-engineer")
        self.assertEqual(lines[0]["session"], "S-new")


class ConcurrentPatchAndAppendTests(unittest.TestCase):
    """PT-112 gate-1 ruling (PT-112.md @8b60a8b), guard threshold 6 (the
    in-scope concurrency fix): the hook's read-modify-write must hold an
    exclusive lock across the WHOLE critical section, or a real runner's
    concurrent append -- landing while the hook is mid-patch -- is
    silently discarded when the hook's read-then-overwrite replays only
    its own stale snapshot. Orchestrated deterministically: this test
    itself holds `fcntl.flock(LOCK_EX)` on the ledger BEFORE starting
    both real subprocesses (the runner, via the established
    fake-engine-root technique, and the hook), so both are guaranteed to
    still be at (or blocked on) their own file access when the lock is
    released -- no wall-clock racing, no repeat-run battery."""

    def _fake_engine_root(self):
        tmp = helpers.make_empty_tmp_dir(self)
        engine_dir = tmp / "scripts" / "cairn"
        engine_dir.mkdir(parents=True)
        engine_dir.joinpath("run_tests.py").write_bytes((helpers.CAIRN_DIR / "run_tests.py").read_bytes())
        tests_dir = engine_dir / "tests"
        tests_dir.mkdir()
        tests_dir.joinpath("test_fake_ok.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        return tmp, engine_dir

    def test_a_concurrent_append_survives_the_hooks_locked_patch(self):
        import fcntl

        tmp, engine_dir = self._fake_engine_root()
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        records_path.parent.mkdir(parents=True, exist_ok=True)
        target = {
            "ts": "2026-09-09T00:00:00.000Z", "who": None, "session": "S-target", "gate": "red", "full": True,
            "runner": "run_tests", "sha": None, "branch": None, "seconds": 1.0, "harness_ms": 1000,
            "jobs": 1, "files": 1, "tests": 1, "skipped": 0, "ok": True, "cmd": "python3 run_tests.py --gate red",
        }
        records_path.write_text(json.dumps(target) + "\n", encoding="utf-8")

        runner_env = dict(os.environ)
        runner_env.pop("CLAUDE_PROJECT_DIR", None)
        runner_env.pop("CAIRN_TEST_RUNS_FILE", None)
        runner_env["CLAUDE_CODE_SESSION_ID"] = "S-concurrent-runner"

        hook_payload = {
            "session_id": "S-target", "cwd": str(engine_dir), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 run_tests.py --gate red"},
            "tool_response": {"stdout": "", "stderr": ""}, "duration_ms": 1000, "tool_use_id": "x",
        }
        hook_env = dict(os.environ)
        hook_env["CLAUDE_PROJECT_DIR"] = str(tmp)

        lock_fd = open(records_path, "r+", encoding="utf-8")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            runner_proc = subprocess.Popen(
                [sys.executable, str(engine_dir / "run_tests.py"), "--gate", "red"],
                cwd=str(engine_dir), env=runner_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            hook_proc = subprocess.Popen(
                [sys.executable, str(HOOKS_DIR / "test_run_record.py")],
                env=hook_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            hook_proc.stdin.write(json.dumps(hook_payload))
            hook_proc.stdin.close()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

        runner_out, runner_err = runner_proc.communicate(timeout=15)
        hook_out, hook_err = hook_proc.communicate(timeout=15)
        self.assertEqual(runner_proc.returncode, 0, runner_out + runner_err)
        self.assertEqual(hook_proc.returncode, 0, hook_out + hook_err)

        lines = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, f"the concurrent runner's own append must survive the hook's patch -- got {lines!r}")
        by_session = {l.get("session"): l for l in lines}
        self.assertIn("S-concurrent-runner", by_session, f"the concurrently-appended record must not be lost -- got {lines!r}")
        self.assertEqual(by_session["S-target"]["who"], "architect", f"the hook's own patch must still land correctly -- got {lines!r}")


class RecorderIgnoresNonRunNoiseTests(unittest.TestCase):
    """Gate-4 verdict delta 3 (blocking): record only a run. No parseable
    result and no runner exit => write nothing; `gate` never comes from a
    substring match against arbitrary command text. Reproduced live
    against e86f163 (see the conversation record): both payloads below
    currently produce a noise record with tests=None or a hallucinated
    gate/count scraped out of unrelated git output."""

    def test_a_git_add_whose_path_text_mentions_gate_green_writes_nothing(self):
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": 'git add -- "notes/python3 run_tests.py --gate green.md"'},
            "tool_response": {"stdout": "", "stderr": ""},
            "duration_ms": 12, "tool_use_id": "x1",
        }
        result = _run_hook("test_run_record.py", json.dumps(payload), env={"CLAUDE_PROJECT_DIR": str(tmp)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(records_path.exists() and records_path.read_text(encoding="utf-8").strip(),
                          "a git add is not a run -- it must never write a record, gate=green or otherwise")

    def test_a_git_log_whose_diff_text_mentions_a_fake_summary_writes_nothing(self):
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline | grep run_tests && python3 --version && git show HEAD"},
            "tool_response": {
                "stdout": "commit abc123\n+    # measured: Ran 39 tests in 1.163s (was previously logged)\n",
                "stderr": "",
            },
            "duration_ms": 12, "tool_use_id": "x2",
        }
        result = _run_hook("test_run_record.py", json.dumps(payload), env={"CLAUDE_PROJECT_DIR": str(tmp)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(records_path.exists() and records_path.read_text(encoding="utf-8").strip(),
                          "a git log/show is not a run -- a diff line that merely LOOKS like a summary must never be recorded")

    def test_a_test_shaped_command_with_unparseable_stdout_writes_nothing(self):
        # implementation-lead's re-read: delta 3's "record only a run"
        # left a gap -- a command that DOES look like a real run
        # (python3 + run_tests token, so _is_test_run passes) but whose
        # captured stdout has no parseable "Ran N tests" summary at all
        # currently still writes a record, with tests/seconds left null
        # instead of writing nothing. Reproduced live against f66fe09.
        tmp = helpers.make_empty_tmp_dir(self)
        (tmp / "process" / "cairn" / "metrics").mkdir(parents=True)
        records_path = tmp / "process" / "cairn" / "metrics" / "test-runs.jsonl"
        payload = {
            "session_id": "s", "cwd": str(tmp), "agent_type": "architect",
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": 'python3 run_tests.py -p "test_x*.py"'},
            "tool_response": {"stdout": "some garbage output with no summary line at all\n", "stderr": ""},
            "duration_ms": 60, "tool_use_id": "x3",
        }
        result = _run_hook("test_run_record.py", json.dumps(payload), env={"CLAUDE_PROJECT_DIR": str(tmp)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(records_path.exists() and records_path.read_text(encoding="utf-8").strip(),
                          "unparseable stdout from a test-shaped command must write nothing, not a null-filled record")


class RealRunTestsRecordsUnderOverrideTests(unittest.TestCase):
    """Gate-4 verdict delta 7 (blocking, PT-97.md @ f66fe09): _self_record
    derives repo_root from the SCRIPT'S OWN __file__ location, so a
    subprocess spawn of the REAL run_tests.py (as several tests here and
    in test_run_tests.py do) writes into the REAL
    process/cairn/metrics/test-runs.jsonl -- reproduced live twice at
    f7d1eba. The fix is an explicit override (CAIRN_TEST_RUNS_FILE) the
    real script must honour when set. This snapshots the real file BEFORE
    spawning and restores it in cleanup regardless of outcome (belt and
    suspenders alongside the module-wide guard below) -- while red, the
    unfixed script writes into the real file exactly once."""

    def test_a_real_spawn_with_the_override_set_writes_under_tmp_not_the_real_file(self):
        before = REAL_TEST_RUNS_PATH.read_bytes() if REAL_TEST_RUNS_PATH.exists() else None

        def _restore():
            if before is None:
                REAL_TEST_RUNS_PATH.unlink(missing_ok=True)
            else:
                REAL_TEST_RUNS_PATH.write_bytes(before)
        self.addCleanup(_restore)

        tmp = helpers.make_empty_tmp_dir(self)
        override_path = tmp / "test-runs.jsonl"
        env = dict(os.environ)
        env[CAIRN_TEST_RUNS_ENV] = str(override_path)
        result = subprocess.run(
            [sys.executable, str(helpers.CAIRN_DIR / "run_tests.py"), "-p", "test_id_sort.py"],
            cwd=helpers.CAIRN_DIR, capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = REAL_TEST_RUNS_PATH.read_bytes() if REAL_TEST_RUNS_PATH.exists() else None
        self.assertEqual(
            before, after,
            "the real records file must be byte-identical before and after a spawn with "
            f"{CAIRN_TEST_RUNS_ENV} set",
        )
        self.assertTrue(
            override_path.exists(),
            f"with {CAIRN_TEST_RUNS_ENV} set, the real run_tests.py must write there instead",
        )


def _load_hook_module(script: str):
    # .claude/hooks/ is outside the normal package path -- load by file
    # location rather than adding it to sys.path. Safe against triggering
    # the hook's own main(): spec_from_file_location gives it a module
    # name other than "__main__", so `if __name__ == "__main__":` at the
    # bottom of the hook never fires.
    spec = importlib.util.spec_from_file_location(f"pt97_{script[:-3]}", HOOKS_DIR / script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _find_hook_command(settings: dict, event: str, name_substring: str) -> str | None:
    for entry in settings.get("hooks", {}).get(event, []):
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            if name_substring in cmd:
                return cmd
    return None


class ShellPrefilterCouplingTests(unittest.TestCase):
    """Ruling addendum 1 (PT-97.md @ d691d19): the real guard lives behind
    a shell `case` prefilter in settings.json (measured: ~6ms on a glob
    miss vs 29ms unconditional), matched on
    `test_run_guard.TEST_CMD_TOKENS`. Two coupling risks the prior tests
    (which call test_run_guard.py directly, bypassing the prefilter
    entirely) cannot catch: the glob and the token tuple drifting apart,
    and a narrowed glob silently never spawning python at all. Named
    mutation (addendum 1): narrow the glob to `*unittest*` only, feed the
    real prefilter a bare `python3 run_tests.py` command -- python is
    not spawned, the run is not blocked, and this must go red on exactly
    that."""

    def test_test_cmd_tokens_each_have_a_glob_alternative_in_settings_json(self):
        module = _load_hook_module("test_run_guard.py")
        tokens = module.TEST_CMD_TOKENS
        settings_text = SETTINGS_PATH.read_text(encoding="utf-8")
        missing = [t for t in tokens if f"*{t}*" not in settings_text]
        self.assertEqual(
            missing, [],
            f"settings.json's shell prefilter glob is missing a *<token>* alternative for: "
            f"{missing!r} -- it and TEST_CMD_TOKENS must never drift apart",
        )

    def test_a_bare_run_tests_py_command_is_blocked_through_the_real_prefilter(self):
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        cmd = _find_hook_command(settings, "PreToolUse", "test_run_guard.py")
        self.assertIsNotNone(cmd, "no PreToolUse hook command in settings.json references test_run_guard.py yet")
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
        result = subprocess.run(
            ["sh", "-c", cmd], input=json.dumps(_pre_payload("cd scripts/cairn && python3 run_tests.py")),
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("-p", result.stderr)
        self.assertIn("--gate", result.stderr)

    def test_a_narrowed_pattern_command_passes_through_the_real_prefilter(self):
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        cmd = _find_hook_command(settings, "PreToolUse", "test_run_guard.py")
        self.assertIsNotNone(cmd, "no PreToolUse hook command in settings.json references test_run_guard.py yet")
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
        result = subprocess.run(
            ["sh", "-c", cmd], input=json.dumps(_pre_payload('python3 run_tests.py -p "test_x*.py"')),
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def _hook_commands(settings: dict) -> list[str]:
    cmds = []
    for _event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                if ".claude/hooks/" in cmd:
                    cmds.append(cmd)
    return cmds


class SettingsAnchoringTests(unittest.TestCase):
    """Guard threshold 10: every .claude/hooks/ command in
    .claude/settings.json is $CLAUDE_PROJECT_DIR-anchored, message_cap.py
    included. Control (ruling: '1 command, 1 unanchored' at 09a0843):
    the scan must find at least one real .claude/hooks/ command, so an
    empty offenders list can't come from a broken pattern or path."""

    def test_every_hooks_command_is_project_dir_anchored(self):
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        cmds = _hook_commands(settings)
        offenders = [c for c in cmds if "$CLAUDE_PROJECT_DIR" not in c]
        self.assertEqual(offenders, [], f"unanchored .claude/hooks/ command(s): {offenders!r}")

    def test_the_scan_finds_at_least_one_real_hook_command(self):
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        cmds = _hook_commands(settings)
        self.assertGreaterEqual(len(cmds), 1, "scan found zero .claude/hooks/ commands -- pattern or path is broken")


# --------------------------------------------------------------------------
# PT-97 delta 7 (blocking, PT-97.md @ f66fe09): module-wide backstop, same
# construction as test_run_tests.py's identical guard -- see that file's
# comment for the full rationale. setUpModule/tearDownModule are
# unittest's own guaranteed whole-module brackets; a bare `assert` is
# stripped under `python -O` (PT-91/PT-95) -- raise explicitly instead.
# --------------------------------------------------------------------------

_REAL_STATE_SNAPSHOT = None


def setUpModule():
    # PT-100 (architect's re-issued ruling, PT-100.md @ 0487f33): ported
    # onto the shared, self-diagnosing snapshot -- see test_run_tests.py's
    # identical guard for the full rationale (raw-line multiset
    # containment; this file's records carry no `issue` field so any
    # added line is treated as unbacked, preserving the original
    # byte-exact-on-any-write intent).
    global _REAL_STATE_SNAPSHOT
    _REAL_STATE_SNAPSHOT = helpers.snapshot_real_state(
        REAL_TEST_RUNS_PATH, REAL_RECEIVER_PIDFILE, REAL_SESSIONS_DIR, REAL_METRICS_DIR.parent,
    )


def tearDownModule():
    helpers.assert_real_state_untouched(_REAL_STATE_SNAPSHOT)


if __name__ == "__main__":
    unittest.main()
