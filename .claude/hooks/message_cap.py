#!/usr/bin/env python3
"""PreToolUse hook on SendMessage (PT-94 E20 / A1): a message is a pointer,
not a ruling. Over MAX_LINES lines or MAX_CHARS characters -> exit 2 with
the guidance on stderr (the harness blocks the call and shows the text to
the sender). Anything unexpected -> exit 0: a broken hook must never
silence the team."""
import json
import sys

MAX_LINES = 8
MAX_CHARS = 1200


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "SendMessage":
        return 0
    inp = data.get("tool_input")
    if not isinstance(inp, dict):
        return 0
    msg = inp.get("message") or ""
    if not isinstance(msg, str):
        return 0
    lines = msg.count("\n") + 1
    if lines <= MAX_LINES and len(msg) <= MAX_CHARS:
        return 0
    sys.stderr.write(
        f"SendMessage blocked: {lines} lines / {len(msg)} chars; the cap is {MAX_LINES} lines and {MAX_CHARS} chars (PT-94 A1/A2). "
        "A message carries a pointer, sha-first: put the ruling, verdict table, or construction in the issue file "
        "(cairn comment) or a review-log file, commit it, and send \"read <file> @ <sha>\" plus at most a few lines of what changed.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
