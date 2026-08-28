"""PT-63 failing acceptance tests: self-hosted board fonts, per the
PT-57 ruling (4785853) + its location-superseding addendum (781e000) --
fully pre-decided, no architect ruling gate on THIS issue (architect
reviews the landed diff only):

- Three spec faces self-hosted under `scripts/cairn/board/vendor/`
  (the existing checked-in-binary precedent from marked.js/purify.min.js,
  NOT a new `board/fonts/` directory), with NOTICE.md provenance rows
  (library/version/license/upstream) -- the three faces are SIL OFL.
- latin + latin-ext subsets only, six `.woff2` files, ~245KB target (the
  ruling's measured budget).
- `@font-face` declarations naming the spec's exact family strings
  ('Merriweather Variable', 'Space Grotesk Variable', 'Geist Mono
  Variable'), and board.css's font-family declarations switched to the
  spec's stacks by ROLE (heading vs body vs mono), not by selector size.
- Cross-mounting `/dashboard/assets/*.woff2` is PERMANENTLY REJECTED --
  the board's fonts must be its own files, never a dependency on the
  dashboard's build artifact (the exact spin-off-boundary reasoning
  PT-54's git-state read and PT-56's roster reader module already
  established).
- The dashboard's Board-panel seam note ("typography still differs until
  the fonts follow-up (PT-63)") must be retired in the SAME PR, in BOTH
  the Svelte source and the built dist bundle -- its condition becomes
  false the moment this lands. Checked whitespace-normalized (architect's
  own near-miss on PT-57: a wrapped sentence's embedded newline/indent
  survives into the built bundle verbatim, so a raw substring grep can
  false-fail on a sentence that wrapped differently, or false-pass on a
  literal check that never actually matched either file).
- No CDN at runtime, zero network font requests.

Nothing under test exists yet: no font files in vendor/, no NOTICE.md
font rows, no `@font-face` in board.css/board's tokens.css, board.css's
font-family declarations are still the old system-UI/ui-monospace stacks.
Every test below is expected to fail for one of those concrete reasons --
missing file (404 or FileNotFoundError), an empty extracted set, or a
substring genuinely absent -- never an import error.
"""
from __future__ import annotations

import re
import threading
import time
import unittest
import urllib.error
import urllib.request

import helpers  # noqa: F401

import cairn

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
VENDOR_DIR = helpers.CAIRN_DIR / "board" / "vendor"
NOTICE_MD = VENDOR_DIR / "NOTICE.md"
BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"
BOARD_TOKENS_CSS = helpers.CAIRN_DIR / "board" / "tokens.css"
DASHBOARD_APP_SVELTE = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "src" / "App.svelte"
DASHBOARD_DIST_INDEX_JS = REPO_ROOT / "scripts" / "cairn" / "dashboard" / "dist" / "assets" / "index.js"

SPEC_FONT_FAMILIES = {
    "Merriweather Variable",  # --font-sans (body/UI, per role not size)
    "Space Grotesk Variable",  # --font-heading
    "Geist Mono Variable",  # --font-mono
}

TARGET_BUDGET_BYTES = 245_000  # the ruling's own measured target
BUDGET_TOLERANCE = 120_000  # generous sanity band, not a strict byte-for-byte pin


def _strip_css_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _read_board_and_tokens_css() -> str:
    """The two files font-related CSS could legitimately live in --
    concatenated, since neither the ruling nor this test needs to
    prescribe which one carries @font-face specifically."""
    parts = []
    if BOARD_TOKENS_CSS.is_file():
        parts.append(BOARD_TOKENS_CSS.read_text(encoding="utf-8"))
    if BOARD_CSS.is_file():
        parts.append(BOARD_CSS.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _extract_font_face_blocks(css_source: str) -> list:
    """The declaration-body text of every `@font-face { ... }` rule."""
    stripped = _strip_css_comments(css_source)
    return re.findall(r"@font-face\s*\{([^{}]*)\}", stripped)


def _extract_font_families(font_face_blocks: list) -> set:
    families = set()
    for block in font_face_blocks:
        m = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)['\"]?\s*;", block)
        if m:
            families.add(m.group(1).strip())
    return families


class NoticeFontProvenanceTests(unittest.TestCase):
    def test_notice_md_names_all_three_font_families(self):
        self.assertTrue(NOTICE_MD.is_file(), f"{NOTICE_MD} missing")
        text = NOTICE_MD.read_text(encoding="utf-8")
        for family in ("Merriweather", "Space Grotesk", "Geist Mono"):
            self.assertIn(family, text, f"NOTICE.md does not mention {family!r}")

    def test_notice_md_records_the_sil_ofl_license(self):
        text = NOTICE_MD.read_text(encoding="utf-8")
        self.assertIn("OFL", text, "NOTICE.md must record the SIL OFL license for the font entries")

    def test_notice_md_still_documents_the_pre_existing_marked_and_dompurify_entries(self):
        # Regression guard: adding font rows must not clobber the existing
        # PT-4 vendor table.
        text = NOTICE_MD.read_text(encoding="utf-8")
        self.assertIn("marked", text.lower())
        self.assertIn("dompurify", text.lower())


class VendorFontFilesTests(unittest.TestCase):
    def test_exactly_six_woff2_files_are_committed(self):
        found = sorted(VENDOR_DIR.glob("**/*.woff2"))
        self.assertEqual(
            len(found), 6,
            f"expected exactly 6 .woff2 files (3 faces x latin/latin-ext) in {VENDOR_DIR}, "
            f"found {len(found)}: {[p.name for p in found]}",
        )

    def test_woff2_filenames_indicate_the_latin_subsets(self):
        found = sorted(VENDOR_DIR.glob("**/*.woff2"))
        for p in found:
            self.assertIn(
                "latin", p.name.lower(),
                f"{p.name} does not look like a latin/latin-ext-subset file -- "
                f"PT-63 scope is latin + latin-ext only, not the full unicode-range set",
            )

    def test_total_woff2_size_is_within_the_ruled_budget(self):
        found = list(VENDOR_DIR.glob("**/*.woff2"))
        total = sum(p.stat().st_size for p in found)
        self.assertTrue(
            0 < total <= TARGET_BUDGET_BYTES + BUDGET_TOLERANCE,
            f"total woff2 size {total} bytes is outside the sane range around the ruling's "
            f"~{TARGET_BUDGET_BYTES}-byte target (+{BUDGET_TOLERANCE} tolerance) -- if this is "
            f"legitimately larger (e.g. a face gained a subset), update the budget deliberately",
        )


class VendorFontFilesHTTPTests(unittest.TestCase):
    """Every committed woff2 must actually be reachable through the
    board's existing static route (`/board/<rel>`, already guarded/MIME-
    mapped by _send_static since PT-54's font-adjacent MIME additions) --
    a file sitting on disk that the server can't serve is as useless as
    one that doesn't exist."""

    def setUp(self):
        self.data_dir = helpers.make_tmp_data_dir(self)
        self.server = cairn.make_server(self.data_dir, port=0)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        self._wait_until_up()

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _wait_until_up(self):
        last_exc = None
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{self.base_url}/api/board", timeout=5).close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise AssertionError(f"server never came up: {last_exc}")

    def test_every_committed_woff2_is_served_200_with_the_right_mime_type(self):
        found = sorted(VENDOR_DIR.glob("**/*.woff2"))
        self.assertTrue(found, "no woff2 files found to test -- see VendorFontFilesTests")
        for p in found:
            rel = p.relative_to(VENDOR_DIR.parent)  # e.g. vendor/fonts/merriweather-....woff2
            resp = urllib.request.urlopen(f"{self.base_url}/board/{rel.as_posix()}", timeout=5)
            self.assertEqual(resp.status, 200, f"{rel} did not serve 200")
            self.assertIn(
                "font/woff2", resp.headers.get("Content-Type", ""),
                f"{rel} did not serve with a font/woff2 Content-Type",
            )


class FontFaceDeclarationTests(unittest.TestCase):
    def test_exactly_the_three_spec_font_families_are_declared(self):
        blocks = _extract_font_face_blocks(_read_board_and_tokens_css())
        families = _extract_font_families(blocks)
        self.assertEqual(
            families, SPEC_FONT_FAMILIES,
            f"expected @font-face to declare exactly {SPEC_FONT_FAMILIES}, found {families}",
        )

    def test_every_font_face_src_points_at_the_local_vendor_path_not_a_cdn_or_the_dashboard(self):
        blocks = _extract_font_face_blocks(_read_board_and_tokens_css())
        self.assertTrue(blocks, "no @font-face blocks found at all")
        for block in blocks:
            self.assertRegex(block, r"url\(\s*['\"]?/board/vendor/", f"@font-face src is not a local /board/vendor/ path: {block}")
            self.assertNotRegex(block, r"https?://", f"@font-face src references a network URL -- CDN fonts are forbidden: {block}")
            self.assertNotIn("/dashboard/assets", block, f"@font-face src cross-mounts the dashboard's build output -- permanently rejected: {block}")

    def test_no_cdn_font_service_is_referenced_anywhere_in_board_css_or_tokens(self):
        combined = _read_board_and_tokens_css()
        for forbidden in ("fonts.googleapis.com", "fonts.gstatic.com"):
            self.assertNotIn(forbidden, combined, f"board CSS references a font CDN ({forbidden}) -- self-hosted only")


class BoardCssFontRoleSwitchTests(unittest.TestCase):
    """Face-by-role, not size-tiered: body/UI text uses --font-sans, the
    wordmark/headings use --font-heading, code/mono contexts use
    --font-mono -- and the OLD hardcoded system stacks must be gone,
    replaced by the token references, not left alongside them."""

    def test_old_system_ui_stack_no_longer_hardcoded(self):
        css = _strip_css_comments(BOARD_CSS.read_text(encoding="utf-8"))
        self.assertNotIn(
            "-apple-system, BlinkMacSystemFont", css,
            "the old hardcoded system-UI font stack is still present -- should be var(--font-sans) "
            "or var(--font-heading) now",
        )

    def test_old_mono_stack_no_longer_hardcoded(self):
        css = _strip_css_comments(BOARD_CSS.read_text(encoding="utf-8"))
        self.assertNotIn(
            "ui-monospace, SFMono-Regular, Menlo, monospace", css,
            "the old hardcoded monospace stack is still present -- should be var(--font-mono) now",
        )

    def test_font_sans_and_font_mono_vars_are_actually_referenced_in_board_css(self):
        css = _strip_css_comments(BOARD_CSS.read_text(encoding="utf-8"))
        self.assertIn("var(--font-sans)", css)
        self.assertIn("var(--font-mono)", css)


class RosterEmbedSeamNoteRetiredTests(unittest.TestCase):
    """The dashboard Board-panel seam note's condition becomes false the
    moment PT-63 lands -- retired in the SAME PR, both sides, whitespace-
    normalized (see this file's module docstring for why raw substring
    matching is unsafe here)."""

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text)

    def test_pt63_fonts_followup_caveat_is_gone_from_source_and_dist(self):
        src = self._normalize(DASHBOARD_APP_SVELTE.read_text(encoding="utf-8"))
        self.assertTrue(DASHBOARD_DIST_INDEX_JS.is_file(), f"{DASHBOARD_DIST_INDEX_JS} missing -- dist not built")
        dist = self._normalize(DASHBOARD_DIST_INDEX_JS.read_text(encoding="utf-8"))
        caveat = "typography still differs until the fonts follow-up (PT-63)"
        self.assertNotIn(caveat, src, "the fonts-follow-up caveat is still in App.svelte's source")
        self.assertNotIn(caveat, dist, "the fonts-follow-up caveat is still in the committed dist bundle")


if __name__ == "__main__":
    unittest.main()
