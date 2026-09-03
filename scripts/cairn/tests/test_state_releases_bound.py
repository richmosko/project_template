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

Two defects fixed post-review (architect, PT-75, 2026-09-03), both
reproduced against the real code before the fix:

1. The GitHub Releases URL used to be hardcoded to this repo
   (`richmosko/project_template`). Every downstream template instance
   would inherit this file verbatim and fail `/finish-feature`'s hard
   gate on day one, pointing at ITS OWN releases page -- the exact PT-45
   defect class this file's own docstring cites as the model to follow.
   Fixed by deriving `<owner>/<repo>` from whatever GitHub Releases URL
   the lead-in prose actually links to, then cross-checking the data
   row's release link uses that SAME owner/repo -- template-generic, and
   strictly stronger than the pinned assert (it also catches a lead-in
   pointing at a different repo than the row).
2. The data-row filter keyed on the literal leading `v` (`^\\|\\s*v...`),
   so a row whose version cell was blank, malformed, or simply missing
   the `v` prefix was invisible to BOTH the row-count check and the
   200-char check -- reproduced with a 320-char non-`v`-prefixed row
   appended below v0.9.0: the full suite still reported `OK`. Fixed by
   extracting data rows STRUCTURALLY (every table line that is neither
   the header nor the `|---|...` separator, by position, not content),
   with the `v`-prefix now checked as a separate, explicit shape
   assertion on each extracted row -- so a malformed row is COUNTED and
   then fails loudly on shape, instead of never being seen at all.
"""
from __future__ import annotations

import re
import unittest

import helpers  # noqa: F401

STATE_MD = helpers.CAIRN_DIR.parent.parent / "process" / "STATE.md"

# Anchored on the STRUCTURAL shape: a `## Releases` heading, running until
# the next `## `-level heading or EOF. Not a bare "grep for '| v'" search,
# so a row that drifts outside the Releases section (e.g. an example row
# quoted inside `## Decisions` prose) can never be silently counted.
SECTION_RE = re.compile(r"^## Releases\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)

# A markdown table separator row: `|---|---|...`, optionally with alignment
# colons (`|:---|---:|`) and internal whitespace. Used to find where the
# header row ends and the data rows begin, STRUCTURALLY -- position in the
# table, not row content.
SEPARATOR_ROW_RE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")

# The SHAPE a valid release data row's first cell must have -- checked as a
# property of an already-extracted row, never as the filter that decides
# whether a row gets extracted in the first place (that was defect 2).
VERSION_CELL_RE = re.compile(r"^\|\s*v\S*")

# A GitHub Releases page URL, `https://github.com/<owner>/<repo>/releases`,
# with owner/repo captured so the template stays generic across every repo
# it's instantiated into -- never pinned to this repo's own org/name (that
# was defect 1).
GITHUB_RELEASES_URL_RE = re.compile(r"https://github\.com/([^/\s)]+)/([^/\s)]+)/releases\b")


class ExtractionError(AssertionError):
    """Raised when the Releases section, its table, or its GitHub Releases
    link can't be located in STATE.md's text.

    A plain AssertionError subclass (not a bare `return None`/`[]`),
    mirroring PT-45's (test_skill_id_literals.py) and PT-36's
    (test_column_parity.py) contract: a caller that forgets to check for
    an empty result still sees a loud, NAMED failure -- there is no code
    path in which "the heading/table/link wasn't found" silently becomes
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


def extract_table_lines(section: str) -> list[str]:
    """Every contiguous line starting with `|` in the section, from the
    first such line onward -- the whole markdown table as written (header,
    separator, and data rows together). Raises ExtractionError if no line
    starts with `|` at all."""
    lines = section.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().startswith("|")), None)
    if start is None:
        raise ExtractionError(
            "found a '## Releases' section but no markdown table (no line starting "
            "with '|') inside it -- if the table was removed or restructured, this "
            "guard needs to be updated, not silenced."
        )
    table_lines = []
    for line in lines[start:]:
        if not line.strip().startswith("|"):
            break
        table_lines.append(line)
    return table_lines


def extract_data_rows(section: str) -> list[str]:
    """Every table row that is neither the header nor the separator --
    excluded STRUCTURALLY by position (row 1 is the header, row 2 must be
    the `|---|---|` separator), never by content. A data row whose version
    cell is blank, malformed, or missing its `v` prefix is still counted
    here; VERSION_CELL_RE / the shape test below is what catches that,
    not silent exclusion from the count (defect 2, architect review
    2026-09-03: a 320-char non-`v`-prefixed row previously passed every
    check invisibly). Raises ExtractionError if the second table line
    isn't a separator row, or if zero rows remain after it -- 'exactly
    one row' must never silently mean 'zero'."""
    table_lines = extract_table_lines(section)
    if len(table_lines) < 2 or not SEPARATOR_ROW_RE.match(table_lines[1].strip()):
        second_line = table_lines[1] if len(table_lines) > 1 else "<missing>"
        raise ExtractionError(
            f"found a table in the '## Releases' section but its second line doesn't "
            f"look like a markdown separator row ('|---|---|...') -- if the table's "
            f"shape changed, this guard needs to be updated, not silenced. Second "
            f"line was: {second_line!r}"
        )
    rows = table_lines[2:]
    if not rows:
        raise ExtractionError(
            "found a '## Releases' table but zero data rows (lines after the header "
            "and separator) inside it -- the section must retain exactly one pointer "
            "row (PT-75 acceptance criteria); zero rows is not the target state either."
        )
    return rows


def extract_github_owner_repo(lead_in: str) -> tuple[str, str]:
    """The `(owner, repo)` a `https://github.com/<owner>/<repo>/releases`
    link in the lead-in prose points at. Raises ExtractionError if no such
    link is present -- deliberately NOT hardcoded to this repo's own
    owner/repo (defect 1, architect review 2026-09-03), so this guard
    stays correct verbatim in every repo instantiated from the template,
    each pointing at its own Releases page."""
    match = GITHUB_RELEASES_URL_RE.search(lead_in)
    if not match:
        raise ExtractionError(
            "the Releases section's lead-in prose has no "
            "'https://github.com/<owner>/<repo>/releases' link -- the section must "
            "link to the GitHub Releases page as the full history (PT-75 acceptance "
            f"criteria); got lead-in: {lead_in!r}"
        )
    return match.group(1), match.group(2)


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

    def test_data_row_extraction_is_structural_not_content_based(self):
        """Defect 2 regression fixture: a data row whose version cell is
        NOT `v`-prefixed must still be extracted (and therefore still
        counted, still length-checked) -- it was previously invisible to
        `DATA_ROW_RE`, letting an over-limit, miscounted row through the
        gate undetected."""
        section = "\nLead-in.\n\n| Version | Date |\n|---|---|\n| 0.10.0 | 2026-09-03 |\n"
        rows = extract_data_rows(section)
        self.assertEqual(rows, ["| 0.10.0 | 2026-09-03 |"])

    def test_version_shape_check_catches_a_row_missing_the_v_prefix(self):
        """The `v`-prefix is validated as an explicit, separate shape
        property of an already-extracted row -- never as the extraction
        filter itself (that coupling was defect 2)."""
        self.assertIsNone(VERSION_CELL_RE.match("| 0.10.0 | 2026-09-03 |"))
        self.assertIsNotNone(VERSION_CELL_RE.match("| v0.10.0 | 2026-09-03 |"))

    def test_github_owner_repo_extraction_finds_a_releases_link(self):
        lead_in = "Full history lives at https://github.com/acme-corp/widget-api/releases -- see it."
        owner, repo = extract_github_owner_repo(lead_in)
        self.assertEqual((owner, repo), ("acme-corp", "widget-api"))

    def test_github_owner_repo_extraction_raises_loudly_when_no_link_exists(self):
        with self.assertRaises(ExtractionError) as ctx:
            extract_github_owner_repo("No GitHub link here at all.")
        self.assertIn("github.com", str(ctx.exception))

    def test_github_owner_repo_extraction_is_not_pinned_to_this_repo(self):
        """Defect 1 regression fixture: the extractor must work for ANY
        owner/repo, not just this template's own -- proving it wasn't
        silently re-hardcoded during the fix."""
        owner, repo = extract_github_owner_repo(
            "See https://github.com/someone-else/some-other-project/releases for history."
        )
        self.assertEqual((owner, repo), ("someone-else", "some-other-project"))

    def test_synthetic_full_section_with_matching_owner_repo_passes_end_to_end(self):
        """A full synthetic Releases section for a downstream fork
        (acme-corp/widget-api -- deliberately NOT richmosko/project_template)
        run through every extractor in sequence (section -> lead-in ->
        owner/repo -> rows -> repo cross-check) and found consistent --
        proves the template-generic fix works as a WHOLE pipeline, not
        just at the level of each extractor tested in isolation above."""
        source = (
            "## Releases\n\n"
            "Full history at https://github.com/acme-corp/widget-api/releases.\n\n"
            "| Version | Date | Notes |\n|---|---|---|\n"
            "| v1.0.0 | 2026-01-01 | [release](https://github.com/acme-corp/widget-api/releases/tag/v1.0.0) |\n"
            "\n## Decisions\n"
        )
        section = extract_releases_section(source)
        lead_in = extract_lead_in(section)
        owner, repo = extract_github_owner_repo(lead_in)
        rows = extract_data_rows(section)
        expected_prefix = f"https://github.com/{owner}/{repo}/releases/tag/"
        mismatched = [row for row in rows if expected_prefix not in row]
        self.assertEqual(mismatched, [], "sanity: this fixture is deliberately consistent and must pass")

    def test_synthetic_mismatched_row_and_lead_in_repo_is_caught(self):
        """Same fixture shape as the passing test above, except the row's
        release link points at a DIFFERENT repo (other-org) than the
        lead-in claims (acme-corp) -- proves the cross-check can actually
        fail, not just always report agreement."""
        source = (
            "## Releases\n\n"
            "Full history at https://github.com/acme-corp/widget-api/releases.\n\n"
            "| Version | Date | Notes |\n|---|---|---|\n"
            "| v1.0.0 | 2026-01-01 | [release](https://github.com/other-org/widget-api/releases/tag/v1.0.0) |\n"
            "\n## Decisions\n"
        )
        section = extract_releases_section(source)
        lead_in = extract_lead_in(section)
        owner, repo = extract_github_owner_repo(lead_in)
        rows = extract_data_rows(section)
        expected_prefix = f"https://github.com/{owner}/{repo}/releases/tag/"
        mismatched = [row for row in rows if expected_prefix not in row]
        self.assertNotEqual(mismatched, [], "sanity: this fixture is deliberately mismatched and must be caught")


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

    def test_every_data_row_starts_with_a_version_literal(self):
        rows = extract_data_rows(self.section)  # raises loudly if extraction itself breaks
        bad = [row for row in rows if not VERSION_CELL_RE.match(row)]
        self.assertEqual(
            bad, [],
            f"every Releases data row's first cell must be a version literal like "
            f"'| vX.Y.Z |' -- found row(s) without one: {bad}",
        )

    def test_lead_in_links_to_the_github_releases_page(self):
        lead_in = extract_lead_in(self.section)  # raises loudly if extraction itself breaks
        owner, repo = extract_github_owner_repo(lead_in)  # raises loudly if the link is missing
        self.assertTrue(
            owner and repo,
            f"extracted an empty owner/repo from the Releases lead-in link: {lead_in!r}",
        )

    def test_data_row_release_link_matches_the_lead_ins_repo(self):
        """Not just 'links somewhere on GitHub' -- the data row's own
        release link must point at the SAME owner/repo the lead-in
        advertises as the full history, so the two can never silently
        disagree (a check the old hardcoded-URL assert couldn't make,
        since it only ever compared against a literal)."""
        lead_in = extract_lead_in(self.section)
        owner, repo = extract_github_owner_repo(lead_in)
        rows = extract_data_rows(self.section)
        expected_prefix = f"https://github.com/{owner}/{repo}/releases/tag/"
        mismatched = [row for row in rows if expected_prefix not in row]
        self.assertEqual(
            mismatched, [],
            f"every Releases data row must link to a release tag under the lead-in's "
            f"own repo ({expected_prefix}...) -- found row(s) that don't: {mismatched}",
        )


if __name__ == "__main__":
    unittest.main()
