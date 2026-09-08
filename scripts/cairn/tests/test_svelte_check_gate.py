"""PT-104 (architect's gate-1 ruling, process/cairn/issues/PT-104.md @
da9de2d): `dashboard-api.ts` and `token-chart-logic.ts` each declared
the `/api/tokens` wire payload type and had drifted -- 5 pre-existing
svelte-check errors that survived three prior loops (PT-88, PT-101,
PT-102) undetected because svelte-check was never in a gate. Ruled:
`dashboard-api.ts` (the wire boundary) owns `TokensPayload`,
`TokenIssueTotal`, and `TokenKind`; `token-chart-logic.ts` imports them
instead of redeclaring. `TokenCounters` is explicitly excluded from the
move -- the ruling: "the two copies already agree" -- and stays
duplicated in both files.

Three guards:

(a) `SvelteCheckExitsCleanOnTheDashboardTests` -- the real invocation
    the ruling measured (`node node_modules/svelte-check/bin/svelte-
    check --tsconfig ./tsconfig.app.json`, cwd `scripts/cairn/
    dashboard`) must exit 0 with zero errors once the drift is fixed.
    Skipped with a NAMED reason when the dashboard's node_modules (or
    svelte-check within it) is absent from this checkout/worktree -- a
    missing local install must not fail the suite. Measured before
    writing this test (real subprocess, piped to a file, never through
    `tail` -- a pipe swallows the real exit code): 5 errors, exit 1,
    today.

(b) `SkillMdPinsTheSvelteCheckGateTests` -- the finish-feature SKILL.md
    scan pinning the ruled shape (PT-83 pattern): the svelte-check
    invocation itself, the `-d .../node_modules` presence guard, and a
    NOTE-style skip line for the absent case, all inside the pre-flight
    fenced bash block. Mutation: delete any one of the three -> red.

(c) `TokenChartLogicImportsTheOwnedTypesTests` -- `token-chart-logic.ts`
    declares no `TokensPayload`/`TokenIssueTotal`/`TokenKind` of its own
    and imports all three from `./dashboard-api`.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent  # scripts/cairn -> scripts -> repo root
DASHBOARD_DIR = REPO_ROOT / "scripts" / "cairn" / "dashboard"
DASHBOARD_NODE_MODULES = DASHBOARD_DIR / "node_modules"
SVELTE_CHECK_BIN = DASHBOARD_NODE_MODULES / "svelte-check" / "bin" / "svelte-check"
SKILL_MD = REPO_ROOT / ".claude" / "skills" / "finish-feature" / "SKILL.md"
DASHBOARD_API_TS = DASHBOARD_DIR / "src" / "lib" / "dashboard-api.ts"
TOKEN_CHART_LOGIC_TS = DASHBOARD_DIR / "src" / "lib" / "token-chart-logic.ts"


# --------------------------------------------------------------------------
# (a) svelte-check itself, real subprocess.
# --------------------------------------------------------------------------

_SUMMARY_RE = re.compile(r"COMPLETED\s+\d+\s+FILES\s+(\d+)\s+ERRORS?\s+(\d+)\s+WARNINGS?")


class SvelteCheckExitsCleanOnTheDashboardTests(unittest.TestCase):
    def test_svelte_check_exits_0_with_zero_errors(self):
        if not DASHBOARD_NODE_MODULES.is_dir():
            self.skipTest(f"{DASHBOARD_NODE_MODULES} absent -- dashboard dependencies not installed in this checkout")
        if not SVELTE_CHECK_BIN.is_file():
            self.skipTest(f"{SVELTE_CHECK_BIN} absent -- svelte-check not installed under dashboard node_modules")

        result = subprocess.run(
            ["node", str(SVELTE_CHECK_BIN), "--tsconfig", "./tsconfig.app.json"],
            cwd=str(DASHBOARD_DIR), capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        # Exit code is the primary signal (measured directly, never piped
        # through `tail` -- a pipe reports the LAST command's exit code,
        # not svelte-check's, the same class of bug this suite's own
        # memory warns against for git chains).
        self.assertEqual(
            result.returncode, 0,
            f"svelte-check must exit 0 on the dashboard (PT-104: the TokensPayload/TokenIssueTotal/"
            f"TokenKind duplicate-type drift + the L552 Snippet-type mismatch) -- {output}",
        )
        summary = _SUMMARY_RE.search(output)
        self.assertIsNotNone(summary, f"svelte-check's own COMPLETED summary line was not found -- {output}")
        errors = int(summary.group(1))
        self.assertEqual(errors, 0, f"svelte-check's own summary reports non-zero errors -- {output}")


# --------------------------------------------------------------------------
# (b) SKILL.md scan -- PT-83 pattern (pin the ratified command + its
# guard branches so a future edit can't silently drop the gate).
# --------------------------------------------------------------------------

_BASH_BLOCK_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _preflight_bash_block() -> str:
    source = SKILL_MD.read_text(encoding="utf-8")
    blocks = _BASH_BLOCK_RE.findall(source)
    assert blocks, f"expected at least one ```bash fenced block in {SKILL_MD}"
    return blocks[0]


class SkillMdPinsTheSvelteCheckGateTests(unittest.TestCase):
    """Mutation, each case independently: delete the named line/branch
    from SKILL.md's pre-flight block -> red."""

    def test_the_svelte_check_invocation_is_present(self):
        block = _preflight_bash_block()
        self.assertRegex(
            block, r"svelte-check[^\n]*--tsconfig",
            "SKILL.md's pre-flight must invoke svelte-check with --tsconfig -- PT-104 gate-1 ruling",
        )

    def test_the_node_modules_presence_guard_is_present(self):
        block = _preflight_bash_block()
        self.assertRegex(
            block, r"-d\s+scripts/cairn/dashboard/node_modules",
            "SKILL.md's svelte-check step must guard on dashboard node_modules presence, per the ruling",
        )

    def test_a_named_skip_note_covers_the_node_modules_absent_case(self):
        block = _preflight_bash_block()
        self.assertRegex(
            block, r"NOTE:[^\n]*svelte-check[^\n]*",
            "SKILL.md must print a named NOTE when svelte-check is skipped (node_modules absent) -- "
            "a missing local install must not fail the gate, but must say so out loud",
        )


# --------------------------------------------------------------------------
# (c) token-chart-logic.ts imports the owned types, redeclares none.
# --------------------------------------------------------------------------

_OWNED_TYPES = ("TokensPayload", "TokenIssueTotal", "TokenKind")
# `export type X = ` or `type X = ` -- a declaration, not a usage.
_DECL_RE = {name: re.compile(rf"(?:^|\n)\s*(?:export\s+)?type\s+{name}\b\s*=") for name in _OWNED_TYPES}
_IMPORT_FROM_DASHBOARD_API_RE = re.compile(r"import\s+type\s*\{([^}]*)\}\s*from\s*['\"]\./dashboard-api['\"]")


class TokenChartLogicImportsTheOwnedTypesTests(unittest.TestCase):
    def _source(self) -> str:
        self.assertTrue(TOKEN_CHART_LOGIC_TS.is_file(), f"expected {TOKEN_CHART_LOGIC_TS}")
        return TOKEN_CHART_LOGIC_TS.read_text(encoding="utf-8")

    def test_declares_none_of_the_owned_types(self):
        source = self._source()
        offenders = [name for name, rx in _DECL_RE.items() if rx.search(source)]
        self.assertEqual(
            offenders, [],
            f"token-chart-logic.ts must not redeclare types dashboard-api.ts now owns (PT-104) -- "
            f"still declared: {offenders}",
        )

    def test_imports_all_three_owned_types_from_dashboard_api(self):
        source = self._source()
        m = _IMPORT_FROM_DASHBOARD_API_RE.search(source)
        self.assertIsNotNone(
            m, "token-chart-logic.ts must import the wire payload types from './dashboard-api' -- no import found",
        )
        imported = {n.strip() for n in m.group(1).split(",") if n.strip()}
        missing = [name for name in _OWNED_TYPES if name not in imported]
        self.assertEqual(
            missing, [],
            f"token-chart-logic.ts's import from './dashboard-api' is missing: {missing} -- got {imported!r}",
        )

    def test_dashboard_api_declares_all_three_owned_types(self):
        self.assertTrue(DASHBOARD_API_TS.is_file(), f"expected {DASHBOARD_API_TS}")
        source = DASHBOARD_API_TS.read_text(encoding="utf-8")
        missing = [name for name, rx in _DECL_RE.items() if not rx.search(source)]
        self.assertEqual(
            missing, [],
            f"dashboard-api.ts (the ruled owner) must declare every wire payload type -- missing: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
