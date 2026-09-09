"""Tests for loop_stats (PT-94 E16): the per-loop scorecard and the
step-by-step transcript audit behind `cairn loop-stats`.

Transcripts are synthesised here in the harness's jsonl shape (header
record, assistant tool_use / text records, user inbound records) so the
suite never depends on a real ~/.claude transcript.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

import loop_stats

T0 = datetime.datetime(2026, 9, 5, 19, 20, tzinfo=datetime.timezone.utc)


def ts(minutes: float) -> str:
    return (T0 + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def header(role: str, sid: str) -> dict:
    return {"type": "agent-setting", "agentSetting": role, "sessionId": sid}


def tool(minutes: float, name: str, **inp) -> dict:
    return {"type": "assistant", "timestamp": ts(minutes),
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def text(minutes: float, body: str) -> dict:
    return {"type": "assistant", "timestamp": ts(minutes), "message": {"content": [{"type": "text", "text": body}]}}


def inbound(minutes: float, who: str, body: str) -> dict:
    return {"type": "user", "timestamp": ts(minutes),
            "message": {"content": f'Another Claude session sent a message:\n<teammate-message teammate_id="{who}">\n{body}\n</teammate-message>'}}


def idle(minutes: float, who: str, result: str) -> dict:
    payload = json.dumps({"type": "idle_notification", "from": who, "result": result})
    return inbound(minutes, who, payload)


def tool_result(minutes: float) -> dict:
    return {"type": "user", "timestamp": ts(minutes),
            "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def tool_use_with_id(minutes: float, tool_id: str, name: str, **inp) -> dict:
    """PT-111: a tool_use block carrying the real harness's `id` field, so
    a later tool_result can be linked to it via `tool_use_id` -- `tool()`
    above has no id and cannot be resolved against a result at all."""
    return {"type": "assistant", "timestamp": ts(minutes),
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}}


def result_for(minutes: float, tool_id: str, content: str, is_error: bool = False,
               denial_kind: str | None = None) -> dict:
    """PT-111: the real harness shape for an id-linked tool_result --
    measured against real transcripts (PT-111.md's gate-1 ruling):
    `is_error` and `tool_use_id` sit on the content block, `toolDenialKind`
    is a TOP-LEVEL sibling of `message` (only present for a hook/permission
    denial, never for an ordinary command failure)."""
    rec = {"type": "user", "timestamp": ts(minutes),
           "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}]}}
    if denial_kind is not None:
        rec["toolDenialKind"] = denial_kind
    return rec


def tool_use_with_id_at(iso_ts: str, tool_id: str, name: str, command: str) -> dict:
    """Same shape as tool_use_with_id, but for fixtures built on an
    already-formatted (e.g. `now()`-relative) ISO timestamp rather than
    the fixed-T0 `ts(minutes)` helper -- ScorecardTests' fixtures use
    `now()` since scorecard() defaults `until` to it."""
    return {"type": "assistant", "timestamp": iso_ts,
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {"command": command}}]}}


def result_for_at(iso_ts: str, tool_id: str, content: str, is_error: bool = False,
                   denial_kind: str | None = None) -> dict:
    rec = {"type": "user", "timestamp": iso_ts,
           "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}]}}
    if denial_kind is not None:
        rec["toolDenialKind"] = denial_kind
    return rec


def ledger_record(ts_iso: str, who, seconds: float = 25.0, jobs: int = 8) -> dict:
    return {"ts": ts_iso, "who": who, "gate": "green", "full": True, "runner": "run_tests",
            "sha": "abc123", "branch": "feature/x", "seconds": seconds, "harness_ms": int(seconds * 1000) + 60,
            "jobs": jobs, "files": 1, "tests": 10, "skipped": 0, "ok": True, "session": "s1",
            "cmd": "python3 run_tests.py --gate green"}


FULL = "cd scripts/cairn && python3 -m unittest discover -s tests 2>&1 | tail -3"
MODULE = 'python3 -m unittest discover -s tests -p "test_x.py"'

# PT-111 gate-1 ruling (PT-111.md @ ec75732), guard 6: classify_bash
# tokenises heredoc BODIES too, so a command that merely QUOTES a full
# run inside a `cat > f <<'EOF' ... EOF` counts as one. Reproduced live:
# classify_bash(HEREDOC_CMD) == "FULL_SUITE" today.
HEREDOC_CMD = "cat > verdict.md <<'EOF'\nRun this at a gate: python3 run_tests.py --gate verdict\nEOF"

GUARD_REFUSAL_CONTENT = (
    "PreToolUse:Bash hook error: [in=$(cat); case \"$in\" in *unittest*|*run_tests*) printf %s \"$in\" | "
    "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/test_run_guard.py\";; *) exit 0;; esac]: "
    "test_run_guard: refusing an un-tiered full-suite run. Mid-loop, narrow it: "
    'python3 run_tests.py -p "test_<area>*.py" (WORKFLOW -> Implement -> Inner loop). '
    "At a gate, declare it: python3 run_tests.py --gate <red|green|verdict|finish> (PT-94 C9).\n"
)
NO_RUN_ERROR_CONTENT = "python3: can't open file '/x/scripts/cairn/tests/run_tests.py': [Errno 2] No such file or directory"


def write_jsonl(path: Path, records: list) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class ClassifyTests(unittest.TestCase):
    """Mutation that turns each test red: drop the named branch of
    loop_stats.classify_bash."""

    def test_full_suite_is_a_discover_without_a_pattern(self):
        self.assertEqual(loop_stats.classify_bash(FULL), "FULL_SUITE")

    def test_a_pattern_run_is_a_module_test(self):
        self.assertEqual(loop_stats.classify_bash(MODULE), "module_test")
        self.assertEqual(loop_stats.classify_bash("python3 -m unittest tests.test_x -v"), "module_test")

    def test_git_reads_and_commits_are_told_apart(self):
        self.assertEqual(loop_stats.classify_bash("git status --short"), "git_read")
        self.assertEqual(loop_stats.classify_bash("git commit -m x -- a.md"), "git_commit")

    def test_a_bare_run_tests_py_call_is_full_suite(self):
        # PT-97 AC2: on PT-96, classify_bash scored 0 full_suite_runs even
        # though the runner ran the full suite at every gate -- it only
        # matched `unittest discover`, never `run_tests.py`.
        self.assertEqual(loop_stats.classify_bash("cd scripts/cairn && python3 run_tests.py"), "FULL_SUITE")
        self.assertEqual(loop_stats.classify_bash("python3 run_tests.py --gate green"), "FULL_SUITE")

    def test_a_narrowed_run_tests_py_call_is_a_module_test(self):
        self.assertEqual(loop_stats.classify_bash('python3 run_tests.py -p "test_x*.py"'), "module_test")

    def test_narrowing_is_flag_aware_not_a_substring_scan(self):
        # PT-97 gate-4 delta 8 (PT-97.md @ f66fe09, non-blocking): the
        # very substring bug delta 1 fixed in the hooks (" -p " matches
        # inside `time -p`; `--pattern` doesn't match " -p " at all) is
        # still live in classify_bash -- confirmed live: `time -p
        # python3 run_tests.py` -> "module_test" (wrong, should be
        # FULL_SUITE) and `--pattern "test_x*.py"` -> "FULL_SUITE" (wrong,
        # should be module_test).
        self.assertEqual(
            loop_stats.classify_bash("/usr/bin/time -p python3 run_tests.py"), "FULL_SUITE",
            "time's own -p flag must not be mistaken for run_tests.py's narrowing flag",
        )
        self.assertEqual(
            loop_stats.classify_bash('python3 run_tests.py --pattern "test_x*.py"'), "module_test",
            "--pattern is run_tests.py's own long form of -p and must be recognised as narrowing",
        )

    def test_a_versioned_bare_run_tests_py_call_is_full_suite(self):
        # PT-113 gate-1 ruling (PT-113.md @ e5b1106): loop_stats.classify_bash
        # shares _is_python_token via find_runner_invocation/is_full_suite_run
        # -- a versioned interpreter (python3.14) must classify the same as
        # literal python3, or a versioned full run is invisible to the
        # full_suite_runs cap. Control: the narrowed -p form stays
        # module_test.
        self.assertEqual(
            loop_stats.classify_bash("python3.14 scripts/cairn/run_tests.py"), "FULL_SUITE",
        )
        self.assertEqual(
            loop_stats.classify_bash('python3.14 scripts/cairn/run_tests.py -p "test_x*.py"'), "module_test",
        )

    def test_heredoc_quoted_full_run_text_is_not_classified_as_a_run(self):
        # PT-111 guard 6: a heredoc BODY that merely quotes a full-run
        # command (writing a verdict/ruling comment, say) must not be
        # classified as an attempt at all -- not FULL_SUITE, not
        # full_run_blocked. Strip heredoc bodies in loop_stats.py only;
        # the hooks' own tokeniser (_test_run_shared) is untouched (control
        # below).
        self.assertNotIn(loop_stats.classify_bash(HEREDOC_CMD), ("FULL_SUITE", "full_run_blocked"))

    def test_the_same_command_without_the_heredoc_wrapper_is_still_full_suite(self):
        self.assertEqual(loop_stats.classify_bash("python3 run_tests.py --gate verdict"), "FULL_SUITE")

    def test_is_full_suite_run_on_that_string_is_unchanged_in_the_hooks(self):
        # Control: _test_run_shared.is_full_suite_run (the hooks' own
        # guard surface) must still refuse this shape for real -- this
        # feature touches loop_stats.py's classification only.
        self.assertTrue(loop_stats.is_full_suite_run("python3 run_tests.py --gate verdict"))


class AuditAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)

    def _audit(self, records):
        p = self.tmp / "s1.jsonl"
        write_jsonl(p, [header("implementation-lead", "s1")] + records)
        return loop_stats.audit_agent(p, T0, T0 + datetime.timedelta(hours=2))

    def test_full_rerun_with_no_code_change_is_flagged(self):
        """Mutation: stop clearing edited_since_full -> the second run is
        never flagged."""
        steps, summary = self._audit([
            tool(1, "Edit", file_path="/r/scripts/cairn/cairn.py"),
            tool(2, "Bash", command=FULL),
            tool(3, "Edit", file_path="/r/process/TRACKER.md"),
            tool(4, "Bash", command=FULL),
        ])
        self.assertEqual(summary["full_suite_runs"], 2)
        self.assertEqual(summary["waste"]["FULL_RERUN_NO_CODE_CHANGE"], 1)

    def test_full_run_after_test_only_edits_is_flagged(self):
        """Mutation: treat tests/ paths as source -> no flag."""
        _, summary = self._audit([
            tool(1, "Edit", file_path="/r/scripts/cairn/tests/test_x.py"),
            tool(2, "Bash", command=FULL),
        ])
        self.assertEqual(summary["waste"]["FULL_RUN_AFTER_TEST_ONLY_EDITS"], 1)
        self.assertNotIn("FULL_RERUN_NO_CODE_CHANGE", summary["waste"])

    def test_same_turn_reread_is_flagged_but_a_new_turn_resets(self):
        """Mutation: never reset reads_this_turn on an inbound message ->
        the third read is flagged too."""
        _, summary = self._audit([
            tool(1, "Read", file_path="/r/a.py"),
            tool(2, "Read", file_path="/r/a.py"),
            inbound(3, "team-lead", "go"),
            tool(4, "Read", file_path="/r/a.py"),
        ])
        self.assertEqual(summary["waste"]["REREAD_SAME_TURN"], 1)

    def test_messages_are_split_by_recipient_and_ask_and_wait_is_flagged(self):
        """Mutation: drop 'please confirm' from CONFIRM_RE -> no round trip."""
        _, summary = self._audit([
            tool(1, "SendMessage", to="architect", message="Shape proposed — please confirm before I build."),
            tool(2, "SendMessage", to="team-lead", message="Built at abc123.\nsuite green"),
        ])
        self.assertEqual(summary["msgs_to_lead"], 1)
        self.assertEqual(summary["msgs_to_peers"], 1)
        self.assertEqual(summary["waste"]["CONFIRM_ROUNDTRIP"], 1)

    def test_protocol_dict_body_with_summary_is_skipped_not_crashed(self):
        """PT-108. A shutdown/plan-approval SendMessage carries a JSON
        object, not prose. Mutation: drop the skip -> CONFIRM_ROUNDTRIP/long
        flags and msgs_to_lead return (json.dumps coercion still appends to
        msgs); this must count as message_protocol with nothing counted."""
        _, summary = self._audit([
            tool(1, "SendMessage", to="team-lead",
                 message={"type": "shutdown_response", "request_id": "r1", "approve": True},
                 summary="teardown ack"),
        ])
        self.assertEqual(summary["messages"], 0)
        self.assertEqual(summary["msgs_to_lead"], 0)
        self.assertEqual(summary["msg_lines_total"], 0)
        self.assertEqual(summary["by_class"]["message_protocol"], 1)

    def test_protocol_dict_body_without_summary_does_not_crash(self):
        """PT-108. `detail = (inp.get("summary") or body)[:90]` crashes at
        loop_stats.py:343 before the regex line whenever `summary` is
        absent -- the guard must sit above `detail`, not just at the
        regex."""
        _, summary = self._audit([
            tool(1, "SendMessage", to="architect",
                 message={"type": "shutdown_request", "reason": "idle"}),
        ])
        self.assertEqual(summary["messages"], 0)
        self.assertEqual(summary["by_class"]["message_protocol"], 1)

    def test_non_protocol_dict_body_is_coerced_and_counted(self):
        """PT-108. Mutation: skip every dict body regardless of `type` ->
        messages == 0. A dict without a protocol `type` is a real message
        and must be counted, not dropped."""
        _, summary = self._audit([
            tool(1, "SendMessage", to="architect", message={"note": "custom payload", "id": 7}),
        ])
        self.assertEqual(summary["messages"], 1)
        self.assertNotIn("message_protocol", summary["by_class"])

    def test_standing_by_text_turn_is_idle_waste(self):
        _, summary = self._audit([text(1, "Standing by for the architect's ruling.")])
        self.assertEqual(summary["waste"]["IDLE_STANDBY"], 1)

    def test_lead_text_turns_are_never_idle_waste(self):
        """Mutation: ignore the `lead` flag -> IDLE_STANDBY == 1."""
        p = self.tmp / "lead.jsonl"
        write_jsonl(p, [{"type": "last-prompt", "sessionId": "lead"}, text(1, "qa standing by. Waiting on implementation-lead's commits.")])
        _, summary = loop_stats.audit_agent(p, T0, T0 + datetime.timedelta(hours=1), lead=True)
        self.assertNotIn("IDLE_STANDBY", summary["waste"])

    def test_window_excludes_records_outside_it(self):
        """Mutation: drop the `since <= t <= until` filter -> 2 runs."""
        p = self.tmp / "s2.jsonl"
        write_jsonl(p, [header("qa-engineer", "s2"), tool(-30, "Bash", command=FULL), tool(5, "Bash", command=FULL)])
        _, summary = loop_stats.audit_agent(p, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(summary["full_suite_runs"], 1)


class AuditAgentBlockedRunTests(unittest.TestCase):
    """PT-111 gate-1 ruling (PT-111.md @ ec75732): a FULL_SUITE-shaped Bash
    step is resolved against its id-linked tool_result, in this
    precedence -- (1) a ledger match promotes to executed; (2) `Ran N
    tests` in the result -> executed, exit status is not the
    discriminator; (3) an error result carrying `toolDenialKind` + the
    guard's own marker text -> full_run_blocked; (4) any other error
    result with no run summary -> full_run_blocked; (5) otherwise
    (redirected stdout, absence of evidence) -> executed.

    `audit_agent` gains an optional `ledger_path` kwarg (default None) so
    the per-agent count can corroborate a step against
    process/cairn/metrics/test-runs.jsonl the same way `full_run_stats`
    already does for the top-of-card count; every pre-existing call site
    in this file omits it and is unaffected. `who` for the ledger's
    who-keyed match comes from the transcript's own header (agentSetting),
    the same source `transcript_roles` already reads -- no new parameter
    needed to convey it."""

    def setUp(self):
        self.tmp = helpers.make_empty_tmp_dir(self)

    def _audit(self, records, ledger=None):
        p = self.tmp / "s1.jsonl"
        write_jsonl(p, [header("architect", "s1")] + records)
        ledger_path = None
        if ledger is not None:
            ledger_path = self.tmp / "test-runs.jsonl"
            write_jsonl(ledger_path, ledger)
        return loop_stats.audit_agent(p, T0, T0 + datetime.timedelta(hours=2), ledger_path=ledger_path)

    def test_guard_refused_step_is_blocked_not_counted(self):
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="python3 run_tests.py"),
            result_for(1.02, "t1", GUARD_REFUSAL_CONTENT, is_error=True, denial_kind="permission-rule"),
        ])
        self.assertEqual(summary["full_suite_runs"], 0)
        self.assertEqual(summary.get("full_run_blocked"), 1)

    def test_wrong_path_step_is_blocked_not_counted(self):
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="cd scripts/cairn/tests && python3 run_tests.py --gate green"),
            result_for(1.02, "t1", NO_RUN_ERROR_CONTENT, is_error=True),
        ])
        self.assertEqual(summary["full_suite_runs"], 0)
        self.assertEqual(summary.get("full_run_blocked"), 1)

    def test_guard_1_fixture_one_executed_two_blocked(self):
        # The ruling's own fixture shape: one executed+gated step (no
        # linked result at all -- absence of evidence, rule 5), one
        # guard-refused, one wrong-path.
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="python3 run_tests.py --gate green"),
            tool_use_with_id(2, "t2", "Bash", command="python3 run_tests.py"),
            result_for(2.02, "t2", GUARD_REFUSAL_CONTENT, is_error=True, denial_kind="permission-rule"),
            tool_use_with_id(3, "t3", "Bash", command="cd scripts/cairn/tests && python3 run_tests.py --gate green"),
            result_for(3.02, "t3", NO_RUN_ERROR_CONTENT, is_error=True),
        ])
        self.assertEqual(summary["full_suite_runs"], 1)
        self.assertEqual(summary.get("full_run_blocked"), 2)

    def test_a_result_quoting_the_guards_own_source_is_not_a_denial(self):
        # False-positive control (a): is_error False and no toolDenialKind
        # -- a free-text match on the refusal phrase (e.g. a Read of
        # test_run_guard.py's own docstring) must not block this step.
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="python3 run_tests.py --gate green"),
            result_for(1.02, "t1", "...\n" + GUARD_REFUSAL_CONTENT + "\n...", is_error=False),
        ])
        self.assertEqual(summary["full_suite_runs"], 1)
        self.assertEqual(summary.get("full_run_blocked", 0), 0)

    def test_a_denial_linked_to_a_different_step_does_not_mark_this_one(self):
        # False-positive control (b): t1's own result is absent -- t2's
        # denial must not leak onto t1 via a free-text scan.
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="python3 run_tests.py --gate green"),
            tool_use_with_id(2, "t2", "Bash", command="python3 run_tests.py"),
            result_for(2.02, "t2", GUARD_REFUSAL_CONTENT, is_error=True, denial_kind="permission-rule"),
        ])
        self.assertEqual(summary["full_suite_runs"], 1)
        self.assertEqual(summary.get("full_run_blocked"), 1)

    def test_exit_1_but_ran_is_full_suite_not_blocked(self):
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="python3 run_tests.py --gate green"),
            result_for(1.02, "t1", "Ran 1577 tests in 25.4s (95 files, 8 workers)\nFAILED (failures=3)\n", is_error=True),
        ])
        self.assertEqual(summary["full_suite_runs"], 1)
        self.assertEqual(summary.get("full_run_blocked", 0), 0)

    def test_redirected_stdout_run_with_no_ledger_is_still_full_suite(self):
        _, summary = self._audit([
            tool_use_with_id(1, "t1", "Bash", command="nohup python3 -m unittest discover -s tests > /tmp/x 2>&1"),
            result_for(1.02, "t1", "", is_error=False),
        ])
        self.assertEqual(summary["full_suite_runs"], 1)
        self.assertEqual(summary.get("full_run_blocked", 0), 0)

    def test_ledger_match_promotes_an_error_result_to_executed(self):
        # Guard 5, positive: the step's own timestamp lines up with a
        # ledger record's computed start (ts - seconds), same who.
        step_minutes = 10.0
        record_ts = ts(step_minutes + 25.0 / 60.0)  # end = start (step time) + 25s
        _, summary = self._audit(
            [
                tool_use_with_id(step_minutes, "t1", "Bash", command="cd /wrong && python3 run_tests.py --gate green"),
                result_for(step_minutes + 0.02, "t1", NO_RUN_ERROR_CONTENT, is_error=True),
            ],
            ledger=[ledger_record(record_ts, who="architect")],
        )
        self.assertEqual(summary["full_suite_runs"], 1)
        self.assertEqual(summary.get("full_run_blocked", 0), 0)

    def test_ledger_record_twenty_minutes_away_does_not_match(self):
        # Guard 5, negative control: identical step, record moved 20
        # minutes away -- must NOT promote.
        step_minutes = 10.0
        record_ts = ts(step_minutes + 20.0 + 25.0 / 60.0)
        _, summary = self._audit(
            [
                tool_use_with_id(step_minutes, "t1", "Bash", command="cd /wrong && python3 run_tests.py --gate green"),
                result_for(step_minutes + 0.02, "t1", NO_RUN_ERROR_CONTENT, is_error=True),
            ],
            ledger=[ledger_record(record_ts, who="architect")],
        )
        self.assertEqual(summary["full_suite_runs"], 0)
        self.assertEqual(summary.get("full_run_blocked"), 1)


class LeadInboundTests(unittest.TestCase):
    def test_idle_duplicating_the_direct_message_is_counted(self):
        """Mutation: raise the overlap threshold above 1.0 -> dup == 0."""
        tmp = helpers.make_empty_tmp_dir(self)
        p = tmp / "lead.jsonl"
        body = "PT-1 backend committed at abc123, eighteen tests green, canonicalisation matches the ruling"
        write_jsonl(p, [
            {"type": "last-prompt", "sessionId": "lead"},
            inbound(1, "implementation-lead", body),
            idle(2, "implementation-lead", "Sent: " + body),
            idle(3, "qa-engineer", "Standing by for the verdict."),
        ])
        rows, dup = loop_stats.lead_inbound(p, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(len(rows), 3)
        self.assertEqual(dup, 1)
        self.assertEqual(sum(1 for r in rows if r[2] == "idle"), 2)


class TranscriptRoleTests(unittest.TestCase):
    def test_role_comes_from_agent_setting_and_defaults_to_team_lead(self):
        tmp = helpers.make_empty_tmp_dir(self)
        write_jsonl(tmp / "a.jsonl", [header("qa-engineer", "a")])
        write_jsonl(tmp / "b.jsonl", [{"type": "last-prompt", "sessionId": "b"}])
        roles = loop_stats.transcript_roles(tmp)
        self.assertEqual(roles[tmp / "a.jsonl"], "qa-engineer")
        self.assertEqual(roles[tmp / "b.jsonl"], "team-lead")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class ScorecardTests(unittest.TestCase):
    """A tmp repo with a feature branch: three commits (one chore), one new
    test, one issue-file comment; a transcript dir with one full run and
    two messages to the lead."""

    def setUp(self):
        self.root = helpers.make_empty_tmp_dir(self)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        self.data_dir = helpers.copy_fixture_data_dir(self.root / "process")
        # copy_fixture_data_dir puts the tree at <dest>/cairn -> process/cairn
        issue = self.data_dir / "issues" / "PT-1.md"
        issue.write_text(
            "---\nid: PT-1\ntitle: Thing\nstatus: in-progress\nmilestone: null\nparent: null\n"
            "assignee: null\nlabels: []\npriority: null\npr: null\ncreated: 2026-09-01\nupdated: 2026-09-01\n---\n\nBody.\n",
            encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_a.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed")
        git(self.root, "checkout", "-q", "-b", "feature/pt-1-thing")
        (self.root / "tests" / "test_a.py").write_text("def test_one():\n    pass\n\ndef test_two():\n    pass\n", encoding="utf-8")
        git(self.root, "commit", "-q", "-am", "test(PT-1): second test")
        issue.write_text(issue.read_text() + "\n## Comments\n\n### @architect — 2026-09-05\n\nGating ruling: build it.\n", encoding="utf-8")
        git(self.root, "commit", "-q", "-am", "chore(PT-1): architect gating ruling")
        (self.root / "app.py").write_text("x = 1\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat(PT-1): app")
        self.transcripts = self.root / "transcripts"
        self.transcripts.mkdir()
        now = datetime.datetime.now(datetime.timezone.utc)
        recent = lambda m: (now + datetime.timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # The window defaults to [first branch commit, now]; the synthetic
        # transcript predates the commits, so every call passes `since`.
        self.since = now - datetime.timedelta(minutes=10)
        self.since_arg = recent(-10)
        write_jsonl(self.transcripts / "q.jsonl", [
            header("qa-engineer", "q"),
            {"type": "assistant", "timestamp": recent(-3), "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": FULL}}]}},
            {"type": "assistant", "timestamp": recent(-2), "message": {"content": [{"type": "tool_use", "name": "SendMessage", "input": {"to": "team-lead", "message": "red at abc"}}]}},
            {"type": "assistant", "timestamp": recent(-1), "message": {"content": [{"type": "tool_use", "name": "SendMessage", "input": {"to": "team-lead", "message": "green at def"}}]}},
        ])

    def test_scorecard_counts_commits_comments_tests_and_transcript_signals(self):
        """Mutations: count all commits as chores (chore_commits 3);
        count `def test_` in removed lines too; read transcripts without
        the window (runs still 1 here -- covered by AuditAgentTests)."""
        card = loop_stats.scorecard(self.root, self.data_dir, "PT-1", base="main", since=self.since, transcripts_dir=self.transcripts)
        self.assertEqual(card["commits"], 3)
        self.assertEqual(card["chore_commits"], 1)
        self.assertEqual(card["comments"], 1)
        self.assertEqual(card["ruling_sections"], 1)
        self.assertEqual(card["tests_added"], 1)
        self.assertGreater(card["issue_kb_added"], 0)
        self.assertEqual(card["full_suite_runs"], 1)
        self.assertEqual(card["msgs_to_lead"], 2)
        self.assertEqual(card["suite_seconds_added"], None)

    def test_the_per_agent_cross_check_agrees_with_the_authoritative_count_on_a_consistent_fixture(self):
        # PT-97 gate-4 delta 8 (PT-97.md @ f66fe09, non-blocking): on a
        # fixture built so the two sources SHOULD agree -- one full-suite
        # Bash call in the transcript, one matching full record in
        # test-runs.jsonl -- they must actually agree, proving the
        # cross-check math is sound (not just its labelling on the
        # disagreeing case above). Depends on classify_bash's flag-aware
        # narrowing fix landing correctly for the `run_tests.py` shape
        # too, not just the plain `unittest discover` shape this
        # particular fixture happens to use.
        metrics_dir = self.data_dir / "metrics"
        metrics_dir.mkdir()
        now = datetime.datetime.now(datetime.timezone.utc)
        record = {
            "ts": (now + datetime.timedelta(minutes=-3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "who": "qa-engineer", "gate": "red", "full": True, "runner": "unittest",
            "sha": "abc123", "branch": "feature/pt-1-thing", "seconds": 20.0,
            "harness_ms": 20029, "jobs": 8, "files": 84, "tests": 1408, "skipped": 1,
            "ok": True, "session": "q", "cmd": FULL,
        }
        write_jsonl(metrics_dir / "test-runs.jsonl", [record])
        card = loop_stats.scorecard(self.root, self.data_dir, "PT-1", base="main", since=self.since, transcripts_dir=self.transcripts)
        self.assertEqual(card["full_suite_runs"], 1)
        per_agent_sum = sum(s["full_suite_runs"] for s in card["per_agent"].values())
        self.assertEqual(
            per_agent_sum, 1,
            f"the transcript-derived per-agent sum must agree with the authoritative "
            f"records count on this fixture -- got {per_agent_sum!r} vs {card['full_suite_runs']!r}",
        )

    def test_guard_refused_and_wrong_path_runs_do_not_count_against_the_cap(self):
        # PT-111 gate-1 ruling's own fixture, end to end through
        # scorecard(): one executed+gated run (ledger-matched), one
        # guard-refused step, one wrong-path step -> full_suite_runs 1,
        # full_run_blocked 2, cap evaluated against 1 (not 3).
        transcripts = self.root / "transcripts_blocked"
        transcripts.mkdir()
        now = datetime.datetime.now(datetime.timezone.utc)
        recent = lambda m: (now + datetime.timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        write_jsonl(transcripts / "a.jsonl", [
            header("architect", "a1"),
            tool_use_with_id_at(recent(-9), "t1", "Bash", "python3 run_tests.py --gate green"),
            result_for_at(recent(-8.98), "t1", "Ran 10 tests in 25.000s (1 files, 8 workers)\nOK\n", is_error=False),
            tool_use_with_id_at(recent(-7), "t2", "Bash", "python3 run_tests.py"),
            result_for_at(recent(-6.99), "t2", GUARD_REFUSAL_CONTENT, is_error=True, denial_kind="permission-rule"),
            tool_use_with_id_at(recent(-5), "t3", "Bash", "cd scripts/cairn/tests && python3 run_tests.py --gate green"),
            result_for_at(recent(-4.99), "t3", NO_RUN_ERROR_CONTENT, is_error=True),
        ])
        metrics_dir = self.data_dir / "metrics"
        metrics_dir.mkdir(exist_ok=True)
        write_jsonl(metrics_dir / "test-runs.jsonl", [{
            "ts": recent(-9 + 25 / 60), "who": "architect", "gate": "green", "full": True, "runner": "run_tests",
            "sha": "abc123", "branch": "feature/pt-1-thing", "seconds": 25.0, "harness_ms": 25080, "jobs": 8,
            "files": 1, "tests": 10, "skipped": 0, "ok": True, "session": "a1", "cmd": "python3 run_tests.py --gate green",
        }])
        card = loop_stats.scorecard(self.root, self.data_dir, "PT-1", base="main", since=self.since, transcripts_dir=transcripts)
        self.assertEqual(card["full_suite_runs"], 1)
        self.assertEqual(card.get("full_run_blocked"), 2, f"got card={card!r}")
        self.assertFalse(card["caps"]["full_suite_runs"]["over"])
        per_agent = card["per_agent"]["architect"]
        self.assertEqual(per_agent["full_suite_runs"], 1)
        self.assertEqual(per_agent.get("blocked"), 2)

    def test_caps_are_reported_and_exceeding_one_is_marked(self):
        """Mutation: compare with `>=` instead of `>` -> commits (3) vs a
        cap of 3 reads OVER."""
        card = loop_stats.scorecard(self.root, self.data_dir, "PT-1", base="main", since=self.since, transcripts_dir=self.transcripts,
                                    caps={"commits": 3, "msgs_to_lead": 1})
        over = {k for k, v in card["caps"].items() if v["over"]}
        self.assertEqual(over, {"msgs_to_lead"})
        md = loop_stats.format_scorecard(card)
        self.assertIn("| msgs_to_lead | 2 | 1 | OVER |", md)
        self.assertIn("| commits | 3 | 3 | ok |", md)

    def test_cli_prints_the_markdown_scorecard(self):
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "loop-stats", "PT-1", "--data-dir", str(self.data_dir), "--base", "main",
             "--transcripts-dir", str(self.transcripts), "--since", self.since_arg],
            capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## Loop scorecard — PT-1", result.stdout)
        self.assertIn("| full_suite_runs | 1 |", result.stdout)

    def test_cli_steps_writes_one_table_per_transcript(self):
        out = self.root / "steps"
        result = subprocess.run(
            [str(helpers.CAIRN_BIN), "loop-stats", "PT-1", "--data-dir", str(self.data_dir), "--base", "main",
             "--transcripts-dir", str(self.transcripts), "--since", self.since_arg, "--steps", str(out)],
            capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((out / "steps-qa-engineer.md").exists())
        self.assertIn("FULL_SUITE", (out / "steps-qa-engineer.md").read_text())


class FullRunStatsFromRecordsTests(unittest.TestCase):
    """PT-97 guard 9: loop_stats derives full_suite_runs/suite_seconds_added
    from process/cairn/metrics/test-runs.jsonl records -- never
    (unmeasured). Mutation: return None -> both fields lose their real
    numbers."""

    def _write(self, tmp, records):
        p = tmp / "test-runs.jsonl"
        write_jsonl(p, records)
        return p

    def _record(self, minutes, seconds, full=True, who="architect", gate="red", jobs=8):
        return {
            "ts": ts(minutes), "who": who, "gate": gate, "full": full,
            "runner": "run_tests", "sha": "abc123", "branch": "feature/pt-97",
            "seconds": seconds, "harness_ms": int(seconds * 1000) + 29, "jobs": jobs,
            "files": 84, "tests": 1408, "skipped": 1, "ok": True,
            "session": "s1", "cmd": "python3 run_tests.py",
        }

    def test_two_or_more_full_records_in_window_give_numeric_stats(self):
        tmp = helpers.make_empty_tmp_dir(self)
        path = self._write(tmp, [self._record(2, 26.4), self._record(5, 19.5)])
        stats = loop_stats.full_run_stats(path, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(stats["full_suite_runs"], 2)
        self.assertAlmostEqual(stats["suite_seconds_added"], 19.5 - 26.4, places=2)

    def test_fewer_than_two_full_records_gives_no_seconds_but_still_counts(self):
        tmp = helpers.make_empty_tmp_dir(self)
        path = self._write(tmp, [self._record(2, 26.4)])
        stats = loop_stats.full_run_stats(path, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(stats["full_suite_runs"], 1)
        self.assertIsNone(stats["suite_seconds_added"])

    def test_non_full_records_and_records_outside_the_window_are_excluded(self):
        tmp = helpers.make_empty_tmp_dir(self)
        records = [
            self._record(2, 26.4, full=False),
            self._record(-30, 99.0),
            self._record(3, 20.1),
            self._record(6, 19.5),
        ]
        path = self._write(tmp, records)
        stats = loop_stats.full_run_stats(path, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(stats["full_suite_runs"], 2)
        self.assertAlmostEqual(stats["suite_seconds_added"], 19.5 - 20.1, places=2)

    def test_missing_records_file_gives_zero_not_a_crash(self):
        tmp = helpers.make_empty_tmp_dir(self)
        stats = loop_stats.full_run_stats(tmp / "nonexistent.jsonl", T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(stats["full_suite_runs"], 0)
        self.assertIsNone(stats["suite_seconds_added"])

    def test_seconds_added_is_computed_within_the_largest_jobs_group_only(self):
        # Gate-4 verdict delta 4 (PT-97.md @ d896d8d, blocking): mixing
        # configurations gave 86.55799999999999 -- the serial run (106.5s)
        # minus the parallel run (19.9s) of IDENTICAL code, a config
        # difference reported as a feature-caused change. Three records
        # at jobs=8 (an unambiguous majority group) and one at jobs=1
        # (a --serial control run) -- only the jobs=8 group may be used.
        tmp = helpers.make_empty_tmp_dir(self)
        records = [
            self._record(1, 26.386, jobs=8),
            self._record(2, 999.0, jobs=1),
            self._record(3, 22.111, jobs=8),
            self._record(4, 19.978, jobs=8),
        ]
        path = self._write(tmp, records)
        stats = loop_stats.full_run_stats(path, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(stats["full_suite_runs"], 4, "the total full-record count is independent of jobs grouping")
        self.assertEqual(
            stats["suite_seconds_added"], round(19.978 - 26.386, 3),
            f"the jobs=1 control run must not enter the delta -- got {stats['suite_seconds_added']!r}",
        )

    def test_suite_seconds_added_is_rounded_to_three_places(self):
        tmp = helpers.make_empty_tmp_dir(self)
        path = self._write(tmp, [self._record(1, 106.536, jobs=1), self._record(2, 19.978, jobs=1)])
        stats = loop_stats.full_run_stats(path, T0, T0 + datetime.timedelta(hours=1))
        self.assertEqual(stats["suite_seconds_added"], round(19.978 - 106.536, 3))
        # Exact float-noise reproduction from the verdict: unrounded this
        # is 86.55799999999999 (sign flipped here since first > last).
        self.assertNotIn("99999", repr(stats["suite_seconds_added"]))


class ScorecardRenderingNeverPrintsUnmeasuredTests(unittest.TestCase):
    """PT-97 AC2: format_scorecard prints numbers or '(no full-run
    records in window)' -- never the old '(unmeasured — PT-93)' tag."""

    def _min_card(self, **overrides):
        card = {
            "issue": "PT-1", "base": "main",
            "since": "2026-09-06T00:00:00+00:00", "until": "2026-09-06T01:00:00+00:00",
            "commits": 1, "chore_commits": 0, "comments": 0, "ruling_sections": 0,
            "issue_kb_added": 0.0, "tests_added": 0,
            "suite_seconds_added": None, "full_suite_runs": 0, "msgs_to_lead": 0,
            "idle_notifications": 0, "idle_dup_of_direct": 0, "cost_usd": None,
            "per_agent": {},
        }
        card.update(overrides)
        card["caps"] = {k: {"cap": v, "value": card.get(k), "over": False} for k, v in loop_stats.DEFAULT_CAPS.items()}
        return card

    def test_no_full_run_records_renders_the_new_tag_not_unmeasured(self):
        rendered = loop_stats.format_scorecard(self._min_card(full_suite_runs=1, suite_seconds_added=None))
        self.assertNotIn("unmeasured", rendered)
        self.assertIn("no full-run records in window", rendered)

    def test_a_real_measurement_renders_the_number(self):
        rendered = loop_stats.format_scorecard(self._min_card(full_suite_runs=2, suite_seconds_added=-6.9))
        self.assertNotIn("unmeasured", rendered)
        self.assertIn("-6.9", rendered)

    def test_per_agent_table_is_labelled_when_it_disagrees_with_the_authoritative_count(self):
        # Gate-4 verdict delta 4: the real output printed "full_suite_runs
        # 2" in the metric table and a per-agent table beneath it summing
        # to 12, in the SAME output, with no indication they come from
        # different sources (records vs. transcript heuristic). Records
        # are authoritative (card["full_suite_runs"]); the per-agent
        # breakdown must say so when it disagrees, not sit there silently
        # implying it should add up to the same number.
        card = self._min_card(full_suite_runs=2, suite_seconds_added=-6.9)
        card["per_agent"] = {
            "architect": {"tool_calls": 10, "full_suite_runs": 4, "msgs_to_lead": 1, "waste": {}},
            "implementation-lead": {"tool_calls": 20, "full_suite_runs": 8, "msgs_to_lead": 2, "waste": {}},
        }
        rendered = loop_stats.format_scorecard(card)
        self.assertIn("transcript", rendered.lower(), "a disagreeing per-agent breakdown must be labelled as transcript-derived, not left unlabelled")

    def test_blocked_runs_get_their_own_row_and_the_executed_label(self):
        # PT-111 gate-1 ruling: rename the full_suite_runs row's display
        # text to "full_suite_runs (executed)" and add a full_run_blocked
        # row -- shown, but with no cap of its own (never in DEFAULT_CAPS).
        card = self._min_card(full_suite_runs=1, full_run_blocked=2, suite_seconds_added=-6.9)
        card["per_agent"] = {"architect": {"tool_calls": 5, "full_suite_runs": 1, "blocked": 2, "msgs_to_lead": 0, "waste": {}}}
        rendered = loop_stats.format_scorecard(card)
        self.assertIn("full_suite_runs (executed)", rendered)
        self.assertIn("full_run_blocked", rendered)
        self.assertIn("2", rendered.split("full_run_blocked", 1)[1].split("\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
