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


if __name__ == "__main__":
    unittest.main()
