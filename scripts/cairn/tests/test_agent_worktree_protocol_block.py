"""PT-82 gate-1 ruling (architect, process/cairn/issues/PT-82.md @
6316a9b, AC2/AC4): every teammate's spawn brief carries the worktree
protocol as IDENTITY, not a per-spawn instruction -- "`.claude/agents/
*.md` carry one shared block: `EnterWorktree` first, pull-rebase before
a step, push fast-forward on completion, commit by pathspec, report a
sha. Deduped." AC4: a test asserts the shared block is present and
IDENTICAL across all ten agent files.

Assumed delimiter (the ruling fixes the block's CONTENT, not its exact
markup -- flag to the architect/implementation-lead if the real
delimiter diverges): an HTML-comment-bounded region,
`<!-- WORKTREE PROTOCOL (shared, do not edit per-file) -->` ...
`<!-- END WORKTREE PROTOCOL -->`, matching the convention this repo
already uses for scanning ratified/structural text (extraction, never a
hand-maintained copy comparison) -- see test_ratified_text_scanners.py.

Extraction raises a NAMED ExtractionError (never a silent None/empty
result) when a file carries no marker at all, so a future agent file
added without the block fails loudly here rather than silently sitting
outside the guard's coverage."""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

AGENTS_DIR = helpers.CAIRN_DIR.parent.parent / ".claude" / "agents"

# The ten agent definitions this repo ships -- every one of them, no
# exceptions named in the ruling (mcp-broker included: it is a spawned
# teammate like any other, per CLAUDE.md).
AGENT_FILES = sorted(AGENTS_DIR.glob("*.md"))

BLOCK_START = "<!-- WORKTREE PROTOCOL (shared, do not edit per-file) -->"
BLOCK_END = "<!-- END WORKTREE PROTOCOL -->"
BLOCK_RE = re.compile(re.escape(BLOCK_START) + r"(.*?)" + re.escape(BLOCK_END), re.DOTALL)

# The five elements the ruling names for the block's content (AC2,
# verbatim): EnterWorktree first, pull-rebase before a step, push
# fast-forward on completion, commit by pathspec, report a sha.
REQUIRED_ELEMENT_PATTERNS = {
    "EnterWorktree first": re.compile(r"EnterWorktree", re.IGNORECASE),
    "pull-rebase before a step": re.compile(r"pull\s+--rebase|pull-rebase", re.IGNORECASE),
    "push fast-forward on completion": re.compile(r"push\b.*fast.forward|fast.forward\b.*push", re.IGNORECASE | re.DOTALL),
    "commit by pathspec": re.compile(r"commit\s+by\s+pathspec", re.IGNORECASE),
    "report a sha": re.compile(r"report\s+(?:the|a)\s+sha", re.IGNORECASE),
}


class ExtractionError(AssertionError):
    """Raised when an agent file carries no `WORKTREE PROTOCOL` marker
    pair at all -- never a silent None, mirroring this suite's standing
    contract (test_ratified_text_scanners.py, test_skill_id_literals.py)
    for a guard that must fail loudly, not go vacuously green, the
    moment its anchor text stops matching."""


def extract_worktree_protocol_block(source: str, label: str = "<source>") -> str:
    match = BLOCK_RE.search(source)
    if not match:
        raise ExtractionError(
            f"found no `{BLOCK_START}` ... `{BLOCK_END}` marker pair in {label} -- every agent "
            "definition must carry the shared worktree protocol block (PT-82 AC2/AC4). If the "
            "real marker syntax differs from this test's assumption, update the assumption, "
            "don't silence the guard."
        )
    return match.group(1)


class SharedWorktreeProtocolBlockIsIdenticalTests(unittest.TestCase):
    """AC4: the shared block is present in EVERY agent file, and every
    one of those blocks is byte-for-byte identical to the others --
    'deduped', not ten independently-maintained copies that can drift."""

    def test_every_agent_file_carries_the_block(self):
        self.assertTrue(AGENT_FILES, f"expected agent definitions under {AGENTS_DIR}")
        missing = []
        for path in AGENT_FILES:
            source = path.read_text(encoding="utf-8")
            try:
                extract_worktree_protocol_block(source, label=str(path))
            except ExtractionError:
                missing.append(str(path))
        self.assertEqual(
            missing, [],
            f"every one of the {len(AGENT_FILES)} agent files must carry the shared worktree "
            f"protocol block -- missing from: {missing}",
        )

    def test_every_agent_files_block_is_byte_identical(self):
        blocks = {}
        for path in AGENT_FILES:
            source = path.read_text(encoding="utf-8")
            blocks[str(path)] = extract_worktree_protocol_block(source, label=str(path))
        distinct = set(blocks.values())
        self.assertEqual(
            len(distinct), 1,
            f"every agent file's worktree protocol block must be byte-for-byte identical "
            f"(deduped, not per-file copies that can drift) -- found {len(distinct)} distinct "
            f"version(s) across {len(blocks)} files: {blocks}",
        )

    def test_the_shared_block_names_all_five_required_elements(self):
        # Any ONE file's block suffices once identity is proven above --
        # this checks the block actually SAYS the five things AC2 names,
        # not just that it's identical everywhere (identical-but-wrong
        # would otherwise pass the test above).
        self.assertTrue(AGENT_FILES, f"expected agent definitions under {AGENTS_DIR}")
        source = AGENT_FILES[0].read_text(encoding="utf-8")
        block = extract_worktree_protocol_block(source, label=str(AGENT_FILES[0]))
        missing_elements = [
            name for name, pattern in REQUIRED_ELEMENT_PATTERNS.items() if not pattern.search(block)
        ]
        self.assertEqual(
            missing_elements, [],
            f"the shared worktree protocol block is missing required element(s): "
            f"{missing_elements} -- got block text: {block!r}",
        )


FRONTMATTER_TOOLS_LINE_RE = re.compile(r"^tools:\s*(.+)$", re.MULTILINE)


def extract_tools_list(source: str, label: str = "<source>") -> list:
    """The comma-separated `tools:` frontmatter line, split into
    individual tool names (whitespace-trimmed). Raises ExtractionError
    if the file carries no `tools:` line at all -- every agent
    definition has one; a file that doesn't is a structural break, not
    a legitimate "no tools" state."""
    match = FRONTMATTER_TOOLS_LINE_RE.search(source)
    if not match:
        raise ExtractionError(f"found no frontmatter `tools:` line in {label}")
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


class EveryAgentGrantsEnterWorktreeTests(unittest.TestCase):
    """Pre-spike defect, found at PT-82.md @ 98d6cdb: the shared block's
    own first instruction is `EnterWorktree`, but tool grants bind at
    spawn (agent-teams.md) -- a teammate whose frontmatter `tools:`
    allowlist omits `EnterWorktree` cannot call it at all, no matter what
    the prose block says to do first. Every agent file carrying the
    worktree protocol block must list `EnterWorktree` in its own
    `tools:` line. Mutation: remove it from one file's `tools:` line."""

    def test_every_agent_files_tools_line_grants_enterworktree(self):
        self.assertTrue(AGENT_FILES, f"expected agent definitions under {AGENTS_DIR}")
        missing = []
        for path in AGENT_FILES:
            source = path.read_text(encoding="utf-8")
            tools = extract_tools_list(source, label=str(path))
            if "EnterWorktree" not in tools:
                missing.append(str(path))
        self.assertEqual(
            missing, [],
            f"every agent file carrying the worktree protocol block must grant `EnterWorktree` "
            f"in its own frontmatter `tools:` line (grants bind at spawn -- a prose instruction "
            f"to call a tool the allowlist doesn't grant is a dead instruction) -- missing from: "
            f"{missing}",
        )


class ExtractionRaisesWhenTheMarkerIsAbsentTests(unittest.TestCase):
    def test_extraction_raises_on_a_source_with_no_marker(self):
        with self.assertRaises(ExtractionError):
            extract_worktree_protocol_block("Just some ordinary agent prose, no marker here.", label="<markerless>")


if __name__ == "__main__":
    unittest.main()
