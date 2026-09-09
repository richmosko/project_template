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

PT-113 gate-1 ruling: `_is_python_token` also recognises versioned
basenames (`python3.14`, `/opt/homebrew/bin/python3.14`, the
free-threaded `python3.14t`), not just literal `python`/`python3`, so a
teammate typing a versioned interpreter can't slip past either hook.

PT-115 gate-1 ruling (PT-115.md @c7b84c0), measured over 2110 real
transcript commands: `find_runner_invocation`'s adjacency anchor was too
strict in one direction (an interpreter flag or a launcher prefix
between the python token and its target -- zero real instances, but
cheap to add) and too loose in three others that DID happen live --
`-m unittest <dotted target>` (3 real refusals; naming a module IS
narrowing, only `discover`/bare `-m unittest` is a full run),
`run_tests.py --help`/`-h`/`--list` (1 real refusal; these exit without
running anything), and a heredoc body that merely QUOTES a run (8 real
commands, several refused -- `_strip_heredocs` moves IN HERE from
`loop_stats.py`, reversing that issue's "hooks stay literal" reasoning,
because this is measurement: `loop_stats.classify_bash` and both hooks
now share the one implementation via `tokenize`).
"""
from __future__ import annotations

import re
import shlex
from typing import List, Optional, Tuple

# The shell prefilter in settings.json globs on these same tokens
# (`*<token>*`) before ever spawning python -- keep the two in lockstep
# (SettingsAnchoringTests / ShellPrefilterCouplingTests).
TEST_CMD_TOKENS = ("unittest", "run_tests")

_NARROW_FLAGS = ("-p", "--pattern", "-k")
_CHAIN_BREAKS = ("&&", "||", ";", "|")
_HELP_LIST_FLAGS = ("--help", "-h", "--list")

# PT-113 gate-1 ruling (PT-113.md @ e5b1106): accept `python`, `python3`,
# any `python3.<N>` version suffix, and the free-threaded `python3.14t`
# forward-cover form; reject `python2`, `py`, `pypy3`, and any dashed
# neighbour (`python3-config`, `python3.14-config`) -- anchored both ends,
# no `startswith`.
_PY_RE = re.compile(r"^python(3(\.\d+)?t?)?$")

# PT-115 gate-1 ruling item (v): only these two launchers count -- `pipx
# run` runs a PACKAGE, not a script, and is deliberately excluded.
_LAUNCHER_PAIRS = (("uv", "run"), ("poetry", "run"))

# PT-115 gate-1 ruling item (iv): a CLOSED allow-list of interpreter
# flags, never "any dash token" -- measured live against the real
# interpreter in all four forms (separated, attached, combined-short,
# and the -X/-W pair). `-c` and `-` are deliberately absent: 30 and 75
# real calls respectively, and both MUST stay non-runs (the code/stdin
# that follows is not a filename).
_FLAG_CLUSTER_RE = re.compile(r"^-[uBOIEsqvd]+$")
_FLAG_WITH_SEPARATE_ARG = ("-X", "-W")

# PT-111 gate-1 ruling, guard 6 (moved here whole by PT-115 item (iii)):
# strip heredoc BODIES (the text between a `<<DELIM`/`<<'DELIM'`/
# `<<-DELIM` marker and its closing delimiter line) before tokenising --
# a `cat > f <<'EOF' ... EOF` that merely QUOTES a full-run command
# (writing a verdict/ruling comment, say) must never be classified as an
# attempt at all, in the hooks OR in loop_stats. Measured on the real
# archive: 8 such commands, several actually refused.
_HEREDOC_START_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


def _strip_heredocs(cmd: str) -> str:
    out: List[str] = []
    delim: Optional[str] = None
    for line in cmd.split("\n"):
        if delim is None:
            out.append(line)
            m = _HEREDOC_START_RE.search(line)
            if m:
                delim = m.group(2)
        elif line.strip() == delim:
            delim = None
    return "\n".join(out)


def tokenize(command: str) -> List[str]:
    command = _strip_heredocs(command)
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        # Unbalanced quotes etc. -- fall back to a plain whitespace split
        # rather than raising; a hook must never crash the tool call it's
        # attached to.
        return command.split()


def _is_python_token(tok: str) -> bool:
    name = tok.rsplit("/", 1)[-1]
    return bool(_PY_RE.match(name))


def _skip_interpreter_flags(tokens: List[str], i: int) -> Optional[int]:
    """From `i` (the token right after a python invocation), skip a
    CLOSED allow-list of interpreter flags -- PT-115 gate-1 ruling item
    (iv). Returns the index of the first token that isn't one of those
    flags (which may be `-m`, handed off to the caller's own "-m
    unittest" check), or `None` if `-c`/`-`/an unrecognised dash token is
    hit first -- those STOP the scan rather than being guessed past:
    this particular python invocation cannot reach run_tests.py or `-m
    unittest` at all."""
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if not tok.startswith("-"):
            return i
        if tok == "-m":
            return i
        if tok in ("-c", "-"):
            return None
        if _FLAG_CLUSTER_RE.match(tok):
            i += 1
            continue
        if tok in _FLAG_WITH_SEPARATE_ARG:
            i += 2  # separated form: the flag plus its own argument (`-X dev`)
            continue
        if tok.startswith(_FLAG_WITH_SEPARATE_ARG):
            i += 1  # attached form: `-Xdev`, `-Werror::DeprecationWarning`
            continue
        return None  # unrecognised dash token -- stop, don't guess past
    return None


def _match_target(tokens: List[str], j: int) -> Optional[Tuple[str, int]]:
    """Does position `j` begin `run_tests.py` or `-m unittest`? Same
    (runner, args_start) contract as `find_runner_invocation`.

    PT-115 gate-1 ruling item (ii): `run_tests.py` carrying `--help`,
    `-h`, or `--list` (anywhere in its own args, before a chain break)
    exits without running anything -- not a match at all, not merely a
    narrowed one."""
    if j >= len(tokens):
        return None
    tok = tokens[j]
    if tok == "run_tests.py" or tok.endswith("/run_tests.py"):
        k = j + 1
        for t in tokens[k:]:
            if t in _CHAIN_BREAKS:
                break
            if t in _HELP_LIST_FLAGS:
                return None
        return "run_tests", k
    if tok == "-m" and j + 1 < len(tokens) and tokens[j + 1] == "unittest":
        return "unittest", j + 2
    return None


def find_runner_invocation(tokens: List[str]) -> Optional[Tuple[str, int]]:
    """Returns (runner, index) where `index` is the first token AFTER the
    runner's own invocation point (i.e. where its own args begin), or
    None if no token stream invokes `run_tests.py` or `-m unittest`.
    `runner` is `"run_tests"` or `"unittest"`.

    Requires the target to be reachable from a python invocation (through
    a CLOSED allow-list of interpreter flags, PT-115 item (iv)) or from a
    recognised launcher prefix (`uv run` / `poetry run`, PT-115 item
    (v)) -- not merely present anywhere on the line. Two false positives
    hit live while building the original version: a `git log -- .../
    test_run_tests.py` (a path that merely ENDS in "run_tests.py") and a
    plain `grep -n ... run_tests.py` (a real reference to the file that
    never runs it). Neither has a python token directly before the
    filename, so anchoring on that excludes both without needing a
    special case for either."""
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        if i + 1 < n and (tok, tokens[i + 1]) in _LAUNCHER_PAIRS:
            after = i + 2
            if after < n and _is_python_token(tokens[after]):
                j = _skip_interpreter_flags(tokens, after + 1)
                if j is not None:
                    m = _match_target(tokens, j)
                    if m is not None:
                        return m
            else:
                m = _match_target(tokens, after)
                if m is not None:
                    return m
            i += 1
            continue
        if _is_python_token(tok):
            j = _skip_interpreter_flags(tokens, i + 1)
            if j is not None:
                m = _match_target(tokens, j)
                if m is not None:
                    return m
        i += 1
    return None


def is_test_invocation(command: str) -> bool:
    """Whether `command` actually invokes the runner or `-m unittest` --
    not merely mentions one of TEST_CMD_TOKENS as a substring somewhere
    (a grep pattern, a quoted filename, a diff line)."""
    return find_runner_invocation(tokenize(command)) is not None


def is_full_suite_run(command: str) -> bool:
    """True iff `command` invokes the runner with no narrowing flag
    (`-p`/`--pattern`/`-k`) *of its own* -- a `-p` belonging to some other
    program earlier on the line (`/usr/bin/time -p ...`) doesn't count,
    and the scan for the runner's own flags stops at the next shell
    chain break (`&&`, `|`, `;`) so a later command's flags don't leak
    in either.

    PT-115 gate-1 ruling item (i): for `-m unittest`, naming a dotted
    test target explicitly IS narrowing -- only `discover` (or a bare
    `-m unittest` with nothing after it) is a full-suite shape. Aligns
    with `loop_stats._FULL_RE`, which has only ever treated `unittest
    discover` as full, since PT-93."""
    tokens = tokenize(command)
    found = find_runner_invocation(tokens)
    if found is None:
        return False
    runner, args_start = found
    args: List[str] = []
    for tok in tokens[args_start:]:
        if tok in _CHAIN_BREAKS:
            break
        args.append(tok)
    if any(tok in _NARROW_FLAGS for tok in args):
        return False
    if runner == "unittest":
        first_positional = next((tok for tok in args if not tok.startswith("-")), None)
        if first_positional is not None and first_positional != "discover":
            return False
    return True


def gate_of(command: str) -> Optional[str]:
    tokens = tokenize(command)
    for i, tok in enumerate(tokens):
        if tok == "--gate" and i + 1 < len(tokens) and tokens[i + 1] in ("red", "green", "verdict", "finish"):
            return tokens[i + 1]
    return None
