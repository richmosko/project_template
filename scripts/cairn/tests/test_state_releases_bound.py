"""PT-75 gate: `process/STATE.md`'s `## Releases` section must stay a
ONE-ROW POINTER, not the append-only log it grew into (ruling, team-lead
2026-09-02). Measured pre-fix on `5b93de9`: 11 data rows, 7768 bytes,
shortest row 223 chars -- already over the 200-char hard limit before
even accounting for the other ten.

Same loud-failure contract as test_skill_id_literals.py (PT-45) and
test_column_parity.py (PT-36): a named `ExtractionError` (never a bare
`return None`/`[]`) whenever the section or its table can't be located,
so a future restructure of STATE.md's headings fails HERE with a legible
message, not as a silently-vacuous green pass or a bare stack trace two
frames down. `STATE_MD.exists()` is asserted explicitly in `setUp` (PT-45's
own precondition shape) so a `git subtree split` or spun-off repo that
drags this file out without `process/STATE.md` fails legibly too.

Reads `process/STATE.md` AS TEXT (`helpers.CAIRN_DIR.parent.parent`),
never parsed as structured markdown -- there is no markdown-table parser
in this codebase's dependency tree (same reasoning as PT-36/PT-45 reading
their targets as text), so every extractor below is a regex anchored on
STATE.md's own heading/table conventions.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

STATE_MD = helpers.CAIRN_DIR.parent.parent / "process" / "STATE.md"

RELEASES_URL = "https://github.com/richmosko/project_template/releases"

# Anchored on the STRUCTURAL shape: a `## Releases` heading, running until
# the next `## `-level heading or EOF. Not a bare "grep for '| v'" search,
# so a row that drifts outside the Releases section (e.g. an example row
# quoted inside `## Decisions` prose) can never be silently counted.
SECTION_RE = re.compile(r"^## Releases\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)

# A release data row: a markdown table row beginning `| v` (a version
# literal like `| v0.9.0 |`) -- excludes the header row (`| Version | ...`)
# and the separator row (`|---|---|...`) by construction, since neither
# starts with `| v`.
DATA_ROW_RE = re.compile(r"^\|\s*v\S*.*$", re.MULTILINE)


class ExtractionError(AssertionError):
    """Raised when the Releases section or its table can't be located in
    STATE.md's text.

    A plain AssertionError subclass (not a bare `return None`/`[]`),
    mirroring PT-45's (test_skill_id_literals.py) and PT-36's
    (test_column_parity.py) contract: a caller that forgets to check for
    an empty result still sees a loud, NAMED failure -- there is no code
    path in which "the heading/table wasn't found" silently becomes
    "compare zero rows to zero expectations and pass".
    """


def extract_releases_section(source: str) -> str:
    """The text between the `## Releases` heading and the next `## `
    heading (or EOF). Raises ExtractionError if the heading is missing."""
    match = SECTION_RE.search(source)
    if not match:
        raise ExtractionError(
            "could not find a '## Releases' heading in the given source -- if this "
            "heading was renamed or restructured, this guard needs to be updated, "
            "not silenced."
        )
    return match.group(1)


def extract_lead_in(section: str) -> str:
    """The prose between the heading and the first table row (any line
    starting with `|`). Raises ExtractionError if no table row is found
    (the lead-in has nothing to precede) or if the lead-in itself is
    empty (heading immediately followed by the table, no prose at all)."""
    lines = section.splitlines()
    table_start = next((i for i, line in enumerate(lines) if line.strip().startswith("|")), None)
    if table_start is None:
        raise ExtractionError(
            "found a '## Releases' section but no markdown table (no line starting "
            "with '|') inside it -- if the table was removed or restructured, this "
            "guard needs to be updated, not silenced."
        )
    lead_in = "\n".join(lines[:table_start]).strip()
    if not lead_in:
        raise ExtractionError(
            "the '## Releases' section's table has no lead-in prose before it -- "
            "the section must keep a one-sentence lead-in linking to the GitHub "
            "Releases page (PT-75 acceptance criteria)."
        )
    return lead_in


def extract_data_rows(section: str) -> list[str]:
    """Every table row that looks like a release data row (`| v...`),
    excluding the header and separator rows. Raises ExtractionError if
    none are found -- a table with zero data rows and this returning []
    silently would let 'exactly one row' collapse into 'zero rows',
    which is a different (and unintended) success mode."""
    rows = DATA_ROW_RE.findall(section)
    if not rows:
        raise ExtractionError(
            "found a '## Releases' table but zero data rows (lines starting with "
            "'| v') inside it -- the section must retain exactly one pointer row "
            "(PT-75 acceptance criteria); zero rows is not the target state either."
        )
    return rows


class ExtractorSelfTests(unittest.TestCase):
    """Reds independent of the real file -- prove the extraction mechanism
    itself can match, fail to match (raising loudly, naming what it was
    looking for), against synthetic source. Same non-vacuity discipline as
    PT-45/PT-36's own ExtractorSelfTests classes."""

    def test_section_extraction_finds_real_content_between_headings(self):
        source = "# State\n\n## Active Feature\nsomething\n\n## Releases\nLead-in.\n\n| v1 |\n\n## Decisions\nother\n"
        section = extract_releases_section(source)
        self.assertIn("Lead-in.", section)
        self.assertIn("| v1 |", section)
        self.assertNotIn("## Decisions", section)
        self.assertNotIn("other", section)

    def test_section_extraction_runs_to_eof_when_no_trailing_heading(self):
        source = "## Releases\nLead-in.\n\n| v1 |\n"
        section = extract_releases_section(source)
        self.assertIn("| v1 |", section)

    def test_section_extraction_raises_loudly_when_heading_is_missing(self):
        with self.assertRaises(ExtractionError) as ctx:
            extract_releases_section("# State\n\n## Active Feature\nno releases heading here\n")
        self.assertIn("Releases", str(ctx.exception))

    def test_lead_in_extraction_finds_prose_before_the_table(self):
        section = "\nSee our history at https://example.com/releases for more.\n\n| Version |\n|---|\n| v1 |\n"
        lead_in = extract_lead_in(section)
        self.assertIn("history at https://example.com/releases", lead_in)

    def test_lead_in_extraction_raises_loudly_when_no_table_row_exists(self):
        with self.assertRaises(ExtractionError) as ctx:
            extract_lead_in("\nJust prose, no table at all.\n")
        self.assertIn("table", str(ctx.exception))

    def test_lead_in_extraction_raises_loudly_when_lead_in_is_empty(self):
        with self.assertRaises(ExtractionError) as ctx:
            extract_lead_in("\n| Version |\n|---|\n| v1 |\n")
        self.assertIn("lead-in", str(ctx.exception))

    def test_data_row_extraction_excludes_header_and_separator_rows(self):
        section = "\nLead-in.\n\n| Version | Date |\n|---|---|\n| v1.0.0 | 2026-01-01 |\n"
        rows = extract_data_rows(section)
        self.assertEqual(rows, ["| v1.0.0 | 2026-01-01 |"])

    def test_data_row_extraction_raises_loudly_when_table_has_zero_data_rows(self):
        with self.assertRaises(ExtractionError) as ctx:
            extract_data_rows("\nLead-in.\n\n| Version | Date |\n|---|---|\n")
        self.assertIn("data rows", str(ctx.exception))

    def test_negative_control_two_data_rows_is_distinguishable_from_one(self):
        section = "\nLead-in.\n\n| Version |\n|---|\n| v1.0.0 |\n| v0.9.0 |\n"
        rows = extract_data_rows(section)
        self.assertNotEqual(len(rows), 1, "sanity: this fixture is deliberately two rows")
        self.assertEqual(len(rows), 2)


class StateReleasesBoundTests(unittest.TestCase):
    """The real guard, against the actual `process/STATE.md`."""

    def setUp(self):
        self.assertTrue(
            STATE_MD.exists(),
            f"expected STATE.md at {STATE_MD} -- if this file was moved or a repo was "
            f"spun off without it, this guard needs an explicit skip/update, not a "
            f"stack trace two frames down.",
        )
        self.source = STATE_MD.read_text(encoding="utf-8")
        self.section = extract_releases_section(self.source)  # raises loudly if missing

    def test_exactly_one_data_row(self):
        rows = extract_data_rows(self.section)  # raises loudly if extraction itself breaks
        self.assertEqual(
            len(rows), 1,
            f"'## Releases' must hold exactly one data row (a pointer to the latest "
            f"tagged release, not an append-only log) -- found {len(rows)}: {rows}",
        )

    def test_every_data_row_is_at_most_200_characters(self):
        rows = extract_data_rows(self.section)  # raises loudly if extraction itself breaks
        too_long = [(len(row), row) for row in rows if len(row) > 200]
        self.assertEqual(
            too_long, [],
            f"every Releases data row (outer pipes + full link URL, counted as the "
            f"literal markdown line) must be <= 200 characters -- found row(s) over "
            f"the limit: {too_long}",
        )

    def test_lead_in_links_to_the_github_releases_page(self):
        lead_in = extract_lead_in(self.section)  # raises loudly if extraction itself breaks
        self.assertIn(
            RELEASES_URL, lead_in,
            f"the Releases section's lead-in prose must link to {RELEASES_URL} as "
            f"the full history -- got lead-in: {lead_in!r}",
        )


if __name__ == "__main__":
    unittest.main()
