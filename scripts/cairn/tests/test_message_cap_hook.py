"""PreToolUse hook on SendMessage (PT-94 E20): a message over the cap is
blocked (exit 2, guidance on stderr); everything else passes, including
malformed hook input -- a broken hook must never silence the team."""
from __future__ import annotations

import json
import subprocess
import unittest

import helpers  # noqa: F401

HOOK = helpers.CAIRN_DIR.parent.parent / ".claude" / "hooks" / "message_cap.py"


def run_hook(payload) -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(["python3", str(HOOK)], input=data, capture_output=True, text=True)


class MessageCapHookTests(unittest.TestCase):
    def test_a_short_message_passes(self):
        r = run_hook({"tool_name": "SendMessage", "tool_input": {"to": "team-lead", "message": "Built at abc123.\nsuite green, 3 files."}})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_nine_lines_are_blocked_with_guidance(self):
        """Mutation: raise MAX_LINES to 9 -> passes."""
        r = run_hook({"tool_name": "SendMessage", "tool_input": {"to": "team-lead", "message": "\n".join(f"line {i}" for i in range(9))}})
        self.assertEqual(r.returncode, 2)
        self.assertIn("8 lines", r.stderr)
        self.assertIn("issue file", r.stderr)

    def test_a_long_single_line_is_blocked(self):
        """Mutation: drop the character cap -> passes."""
        r = run_hook({"tool_name": "SendMessage", "tool_input": {"to": "architect", "message": "x" * 1300}})
        self.assertEqual(r.returncode, 2)

    def test_other_tools_and_bad_input_pass(self):
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "\n" * 40}}).returncode, 0)
        self.assertEqual(run_hook("not json").returncode, 0)
        self.assertEqual(run_hook({"tool_name": "SendMessage"}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
