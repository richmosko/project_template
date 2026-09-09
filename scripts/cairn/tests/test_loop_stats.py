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


FULL = "cd scripts/cairn && python3 -m unittest discover -s tests 2>&1 | tail -3"
MODULE = 'python3 -m unittest discover -s tests -p "test_x.py"'


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


if __name__ == "__main__":
    unittest.main()
