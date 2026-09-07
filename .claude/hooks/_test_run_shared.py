"""PT-97 gate-4 verdict delta 1 (shared, flag-aware): both test_run_guard.py
and test_run_record.py import this so the "is this command actually
invoking the test runner, and is it narrowed" decision lives in exactly
one place. Before this split the two hooks each carried their own
substring check and drifted apart in both directions: `--pattern`
(run_tests.py's own long form of `-p`) was refused as un-tiered because a
naive ` -p ` scan never sees it, and `/usr/bin/time -p ...` passed a bare
full run because `time`'s own `-p` flag matched the same scan.

The fix is real tokenisation (`shlex.split`, quote-aware) plus locating
the runner's own invocation point in the token stream, so a `-p`
belonging to some OTHER program on the command line (`time`, `grep`, a
quoted filename that merely mentions "run_tests.py") is never mistaken
for the runner's own narrowing flag -- and, symmetrically, a command that
never actually invokes the runner (a `git log`, a `git add` whose path
text happens to contain "run_tests.py --gate green") is never mistaken
for a run at all.
"""
from __future__ import annotations

import shlex
from typing import List, Optional, Tuple

# The shell prefilter in settings.json globs on these same tokens
# (`*<token>*`) before ever spawning python -- keep the two in lockstep
# (SettingsAnchoringTests / ShellPrefilterCouplingTests).
TEST_CMD_TOKENS = ("unittest", "run_tests")

_NARROW_FLAGS = ("-p", "--pattern", "-k")
_CHAIN_BREAKS = ("&&", "||", ";", "|")


def _tokenize(command: str) -> List[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        # Unbalanced quotes etc. -- fall back to a plain whitespace split
        # rather than raising; a hook must never crash the tool call it's
        # attached to.
        return command.split()


def _is_python_token(tok: str) -> bool:
    name = tok.rsplit("/", 1)[-1]
    return name in ("python", "python3")


def find_runner_invocation(tokens: List[str]) -> Optional[Tuple[str, int]]:
    """Returns (runner, index) where `index` is the first token AFTER the
    runner's own invocation point (i.e. where its own args begin), or
    None if no token stream invokes `run_tests.py` or `-m unittest`.
    `runner` is `"run_tests"` or `"unittest"`.

    Requires the target to be the token immediately following a python
    invocation, not merely present anywhere on the line -- two false
    positives hit live while building this: a `git log -- .../
    test_run_tests.py` (a path that merely ENDS in "run_tests.py") and a
    plain `grep -n ... run_tests.py` (a real reference to the file that
    never runs it). Neither has a python token directly before the
    filename, so anchoring on that excludes both without needing a
    special case for either."""
    for i, tok in enumerate(tokens):
        if not _is_python_token(tok) or i + 1 >= len(tokens):
            continue
        nxt = tokens[i + 1]
        if nxt == "run_tests.py" or nxt.endswith("/run_tests.py"):
            return "run_tests", i + 2
        if nxt == "-m" and i + 2 < len(tokens) and tokens[i + 2] == "unittest":
            return "unittest", i + 3
    return None


def is_test_invocation(command: str) -> bool:
    """Whether `command` actually invokes the runner or `-m unittest` --
    not merely mentions one of TEST_CMD_TOKENS as a substring somewhere
    (a grep pattern, a quoted filename, a diff line)."""
    return find_runner_invocation(_tokenize(command)) is not None


def is_full_suite_run(command: str) -> bool:
    """True iff `command` invokes the runner with no narrowing flag
    (`-p`/`--pattern`/`-k`) *of its own* -- a `-p` belonging to some other
    program earlier on the line (`/usr/bin/time -p ...`) doesn't count,
    and the scan for the runner's own flags stops at the next shell
    chain break (`&&`, `|`, `;`) so a later command's flags don't leak
    in either."""
    tokens = _tokenize(command)
    found = find_runner_invocation(tokens)
    if found is None:
        return False
    _runner, args_start = found
    for tok in tokens[args_start:]:
        if tok in _CHAIN_BREAKS:
            break
        if tok in _NARROW_FLAGS:
            return False
    return True


def gate_of(command: str) -> Optional[str]:
    tokens = _tokenize(command)
    for i, tok in enumerate(tokens):
        if tok == "--gate" and i + 1 < len(tokens) and tokens[i + 1] in ("red", "green", "verdict", "finish"):
            return tokens[i + 1]
    return None
