"""PT-87 failing acceptance tests: role attribution prefers the
transcript's `agentSetting` (roster role, harness-supplied) over
`agentName` (spawn nickname), in the receiver and the backfill alike.

Pinned to the architect's gating ruling (245b9fa) + addendum (0aa49be)
on process/cairn/issues/PT-87.md, and team-lead's acceptance (f063954).
Written strictly AFTER the ruling landed in the tracked issue file --
the PT-86 lesson this loop was explicitly told to apply.

## The fixture trap the addendum specifically warns about

`agentSetting` lives ONLY on a record of `type: "agent-setting"`, never
alongside `agentName` or a usage block; `agentName` lives on
user/attachment/assistant/system records; the two fields NEVER share a
record (measured across 69 real transcripts, addendum §A). A fixture
that placed both fields on one `assistant` record -- this file's own
first draft, before the addendum was read -- "would pass a resolver
that can never work on real data" (the addendum's own words). Every
fixture below carries that exact type separation.

Flagged honestly, per the addendum's own instruction ("diff a fixture's
head against a real transcript's head"): this sandbox has no access to
a real transcript file to literally diff against. The record shapes
below are built from the architect's own MEASURED description (type
name, field placement, line-1/2 position, "session-constant" values),
not from a byte-for-byte real sample. If that description and a real
transcript ever disagree, the fixtures are wrong in exactly the
direction the addendum warns about -- that is a review finding to raise
with the architect, not a hunch to silently work around.

## Two scan sites, restructured per the addendum

- Receiver (`otel_receiver._resolve_role_from_session`): already scans
  every record regardless of `type` -- never filtered on `type` at all.
  Only needs widening to ALSO collect `agentSetting`, and must not
  early-return on either field before the 50-record window closes.
- Backfill (`backfill_tokens.py`): currently resolves role PER RECORD,
  gated on `type == "assistant"` -- structurally cannot reach an
  `agent-setting` record (addendum §A). Must move to a per-FILE header
  scan (same shape the receiver already uses, first 50 records, any
  type), resolved ONCE per file and applied to every usage-bearing
  record in that file (addendum §B: both fields are session-constant,
  measured 0/69 and 0/53 files varying). The `type == "assistant"`
  filter stays exactly where it is for USAGE accumulation -- two
  different questions, two different filters (addendum's own
  instruction; do not widen the usage filter).

## Shared precedence function (unchanged by the addendum)

`backfill_tokens.resolve_role_from_header(agent_setting, agent_name,
roster) -> str` (architect §3): `agentSetting` present and non-empty ->
that value VERBATIM, no `-<digits>` strip (§2: "it is a type name,
never a spawn name"); else `agentName` -> the existing, untouched
`_normalize_role`; else -> `"team-lead"`. `PureResolverMatrixTests`
below pins this directly, pure, no I/O. The two integration suites
after it prove each CONSUMER calls it correctly against its OWN
differently-shaped scan -- not that the precedence logic is right
twice.

## What this file does not cover

- AC 3 (live check, custom spawn name): team-lead's to trigger, same
  division of labor as PT-86 §9 -- the assertion gets written once
  that happens, not before.
- AC 5 (backfill re-run replacing the committed snapshot): an
  operational end-of-loop step over `merge_and_write`'s EXISTING,
  already-tested replace-own-source semantics (architect §5: "confirmed
  against the write path, not assumed") -- not new logic this file
  needs to re-prove.
- AC 4's TRACKER prose: not something a red test meaningfully gates.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Optional

import helpers  # noqa: F401

import backfill_tokens

RECEIVER_SCRIPT = helpers.CAIRN_DIR / "otel_receiver.py"
BACKFILL_SCRIPT = helpers.CAIRN_DIR / "backfill_tokens.py"
OTLP_FIXTURES = helpers.FIXTURES_DIR / "otlp"
RECEIVER_TRANSCRIPTS = OTLP_FIXTURES / "transcripts"
BACKFILL_FIXTURES = helpers.FIXTURES_DIR / "transcripts" / "agent_setting"

# The real roster this repo actually has -- read once, used both as the
# pure-function tests' explicit roster and to sanity-check the
# fixtures' own premise (claude-code-guide must NOT be in it, or the
# non-roster-kept-verbatim case is testing nothing).
REAL_ROSTER = {p.stem for p in (helpers.CAIRN_DIR.parent.parent / ".claude" / "agents").glob("*.md")}


def read_jsonl(path: Path) -> list[dict]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))
    return lines


def run_receiver(args: list[str], env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RECEIVER_SCRIPT), *args], capture_output=True, text=True, env=env)


def ingest_receiver(payload_fixture: str, out_path: Path, transcripts_dir: Path) -> subprocess.CompletedProcess:
    return run_receiver([
        "--ingest", str(OTLP_FIXTURES / payload_fixture),
        "--out-file", str(out_path),
        "--transcripts-dir", str(transcripts_dir),
    ])


def run_backfill(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BACKFILL_SCRIPT), *args], capture_output=True, text=True)


class FixturePremiseGuardTests(unittest.TestCase):
    """Not a PT-87 acceptance case -- a guard on THIS file's own fixture
    premise, since a wrong premise here would make every other test in
    the file pass for the wrong reason (exactly PT-86's crossed-wire
    lesson, applied to fixtures instead of seams)."""

    def test_claude_code_guide_is_genuinely_not_in_the_real_roster(self):
        self.assertNotIn(
            "claude-code-guide", REAL_ROSTER,
            "the non-roster-agentSetting-kept-verbatim fixtures assume claude-code-guide has no "
            "roster file -- if this ever changes, those fixtures test the wrong thing",
        )

    def test_the_roster_fixtures_reference_are_genuinely_in_the_real_roster(self):
        for name in ("qa-engineer", "implementation-lead", "architect"):
            self.assertIn(name, REAL_ROSTER, f"{name} must be a real roster member for its fixture case to mean anything")


class PureResolverMatrixTests(unittest.TestCase):
    """Architect §2/§3: `resolve_role_from_header(agent_setting,
    agent_name, roster)`, pure, no I/O. An explicit literal roster (not
    the real one) so this class stays independent of what's actually in
    `.claude/agents/` -- only the two integration suites below need the
    real roster."""

    ROSTER = {"qa-engineer", "implementation-lead", "architect", "backend-lead"}

    def _resolve(self, agent_setting, agent_name):
        self.assertTrue(
            hasattr(backfill_tokens, "resolve_role_from_header"),
            "backfill_tokens.resolve_role_from_header does not exist yet -- PT-87's shared resolver seam is unimplemented",
        )
        return backfill_tokens.resolve_role_from_header(agent_setting, agent_name, self.ROSTER)

    def test_roster_agent_setting_wins_over_a_non_roster_agent_name(self):
        self.assertEqual(self._resolve("qa-engineer", "qa-telemetry-probe"), "qa-engineer")

    def test_non_roster_agent_setting_is_kept_verbatim_not_falling_through(self):
        # The ruling's explicit deviation from the issue's original AC 1
        # wording -- claude-code-guide is a real harness type with no
        # roster file, and must NOT be discarded in favour of a spawn
        # nickname.
        self.assertEqual(self._resolve("claude-code-guide", "guide-pt18"), "claude-code-guide")

    def test_agent_setting_present_agent_name_absent_resolves_to_the_roster_role_not_team_lead(self):
        # §7's named case -- the live mis-attribution in today's real
        # data: absent agentName must NOT collapse this to team-lead.
        self.assertEqual(self._resolve("implementation-lead", None), "implementation-lead")

    def test_agent_setting_absent_roster_suffixed_agent_name_still_normalises(self):
        # Existing _normalize_role behaviour, untouched, exercised via
        # the new shared entry point.
        self.assertEqual(self._resolve(None, "qa-engineer-76"), "qa-engineer")

    def test_agent_setting_absent_adhoc_agent_name_stays_verbatim(self):
        self.assertEqual(self._resolve(None, "impl2"), "impl2")

    def test_neither_field_resolves_to_team_lead(self):
        self.assertEqual(self._resolve(None, None), "team-lead")

    def test_empty_string_agent_setting_is_treated_as_absent(self):
        # §2: "present AND non-empty" -- an empty string must fall
        # through to the agentName path, not be kept as "".
        self.assertEqual(self._resolve("", "qa-engineer-76"), "qa-engineer")

    def test_agent_setting_never_gets_the_digit_suffix_strip(self):
        # §2: "No -<digits> strip -- it is a type name, never a spawn
        # name." A value that LOOKS like a normalize_role candidate
        # (stem "architect" IS in the roster) must survive verbatim if
        # it arrived via agentSetting -- proving the implementation
        # doesn't accidentally reuse _normalize_role's stripping here.
        self.assertEqual(self._resolve("architect-2", "irrelevant"), "architect-2")


class ReceiverRoleMatrixTests(unittest.TestCase):
    """AC 1: the receiver's header scan, fixture-driven, against the
    REAL roster (--transcripts-dir points at synthetic, correctly-typed
    transcripts; no real transcript, no network). One ingest of
    agent_setting_role_matrix.json resolves seven sessions at once, each
    on its own model so every case lands in its own output line even
    where two cases legitimately share a role."""

    def _run(self) -> dict:
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = ingest_receiver("agent_setting_role_matrix.json", out_path, RECEIVER_TRANSCRIPTS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        return {line["model"]: line["role"] for line in lines}

    def test_roster_agent_setting_wins_over_a_non_roster_agent_name(self):
        roles = self._run()
        self.assertEqual(roles.get("claude-model-1"), "qa-engineer", roles)

    def test_non_roster_agent_setting_is_kept_verbatim(self):
        roles = self._run()
        self.assertEqual(roles.get("claude-model-2"), "claude-code-guide", roles)

    def test_agent_setting_present_agent_name_absent_is_not_team_lead(self):
        roles = self._run()
        self.assertEqual(roles.get("claude-model-3"), "implementation-lead", roles)

    def test_agent_setting_absent_roster_suffixed_agent_name_still_normalises(self):
        roles = self._run()
        self.assertEqual(roles.get("claude-model-4"), "qa-engineer", roles)

    def test_agent_setting_absent_adhoc_agent_name_stays_verbatim(self):
        roles = self._run()
        self.assertEqual(roles.get("claude-model-5"), "impl2", roles)

    def test_neither_field_resolves_to_team_lead(self):
        roles = self._run()
        self.assertEqual(roles.get("claude-model-6"), "team-lead", roles)

    def test_scan_does_not_early_return_on_agent_name_before_seeing_a_later_agent_setting(self):
        # Adversarial ordering, robustness-only (kept explicitly
        # separate from the realistic matrix above, per the addendum's
        # fixture-trap warning): agentName at line 1, agentSetting at
        # line 2. A scan that stopped at the first agentName would
        # resolve "early-name" instead of "architect".
        roles = self._run()
        self.assertEqual(roles.get("claude-model-7"), "architect", roles)


class BackfillRoleMatrixTests(unittest.TestCase):
    """AC 2: the SAME matrix through the backfill's real scan -- proving
    the two consumers bucket identically, not just that the shared
    pure function is correct in isolation. Six separate transcript
    FILES (role resolved once per file, addendum §B), one branch each so
    every case lands in its own (issue, role, model) bucket."""

    def _run(self) -> tuple[dict, str]:
        out_dir = helpers.make_empty_tmp_dir(self)
        out_path = out_dir / "token-usage.jsonl"
        result = run_backfill(["--transcripts-dir", str(BACKFILL_FIXTURES), "--out-file", str(out_path)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = read_jsonl(out_path)
        by_issue = {line["issue"]: line["role"] for line in lines}
        return by_issue, result.stderr

    def test_roster_agent_setting_wins_over_a_non_roster_agent_name(self):
        by_issue, _ = self._run()
        self.assertEqual(by_issue.get("PT-301"), "qa-engineer", by_issue)

    def test_non_roster_agent_setting_is_kept_verbatim_and_stays_on_the_unmapped_trail(self):
        by_issue, stderr = self._run()
        self.assertEqual(by_issue.get("PT-302"), "claude-code-guide", by_issue)
        self.assertIn(
            "claude-code-guide", stderr,
            f"a non-roster agentSetting must still be reported on the unmapped-names paper trail -- got stderr: {stderr!r}",
        )

    def test_agent_setting_present_agent_name_absent_is_not_team_lead(self):
        # The exact live mis-attribution the whole ticket exists to fix.
        by_issue, _ = self._run()
        self.assertEqual(by_issue.get("PT-303"), "implementation-lead", by_issue)
        self.assertNotEqual(by_issue.get("PT-303"), "team-lead", "must not collapse to team-lead just because agentName is absent")

    def test_agent_setting_absent_roster_suffixed_agent_name_still_normalises(self):
        by_issue, _ = self._run()
        self.assertEqual(by_issue.get("PT-304"), "qa-engineer", by_issue)

    def test_agent_setting_absent_adhoc_agent_name_stays_verbatim_and_unmapped(self):
        by_issue, stderr = self._run()
        self.assertEqual(by_issue.get("PT-305"), "impl2", by_issue)
        self.assertIn("impl2", stderr, f"impl2 must still appear on the unmapped-names trail -- got stderr: {stderr!r}")

    def test_neither_field_resolves_to_team_lead(self):
        by_issue, _ = self._run()
        self.assertEqual(by_issue.get("PT-306"), "team-lead", by_issue)

    def test_superseded_spawn_names_never_appear_as_roles(self):
        # qa-telemetry-probe and guide-pt18 are the agentName values PT-303/2
        # would have wrongly resolved to before this ticket -- must never
        # surface anywhere once agentSetting is consulted.
        by_issue, stderr = self._run()
        roles = set(by_issue.values())
        self.assertNotIn("qa-telemetry-probe", roles, by_issue)
        self.assertNotIn("guide-pt18", roles, by_issue)
        self.assertNotIn("qa-telemetry-probe", stderr)
        self.assertNotIn("guide-pt18", stderr)


if __name__ == "__main__":
    unittest.main()
