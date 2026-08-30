"""PT-69 architect ruling §3 + ux-designer's dropdown-anatomy proposal,
source-text guards (no browser available to this teammate -- team-lead's
own browser leg covers the rendered/visual claims per this project's
browser-visibility precedent; these guards pin the STRUCTURAL prerequisites
a rendered check needs something to find).

Four things gated here:

1. Inline theme-bootstrap `<script>` in BOTH heads, appearing before the
   render-blocking resource it must beat (stylesheet links on the board,
   the module script on the dashboard) -- architect: "It must be inline:
   an external file is a second blocking request on the board and a Vite
   asset on the dashboard." Byte-identical content across both heads
   ("that snippet is a fourth accepted copy... generate it from the same
   variants.json and assert both heads contain it verbatim").
2. `variants.css` wired into each surface's existing stylesheet chain at
   the ruled position (board: after tokens.css, before board.css;
   dashboard: `@import` immediately after app.css's existing three
   imports, still Tailwind-v4-import-order-legal).
3. A settings/theme dropdown trigger + the four ruled rows (Mode / Base
   Color / Theme / Chart Color) actually present in source, on BOTH
   surfaces -- ux-designer's anatomy proposal.
4. Mode is wired as a real mechanism on the board -- architect's own
   flagged risk: "Nothing in either surface ever adds the `.dark` class
   today... Mode is therefore a new mechanism on both surfaces, not a
   toggle of an existing one." This is the structural half of that gate;
   team-lead's rendered/computed-style browser pass is the other half
   (dark mode on the board has never been rendered, per the issue's own
   scope-fence risk note) and is NOT substituted by anything in this file.
5. Mode's `system` state (team-lead's 3-state ruling, ux-designer's Mode
   addendum, architect's addendum item 2-3): the inline bootstrap must
   synchronously resolve `matchMedia('(prefers-color-scheme: dark)')` for
   `system` rather than falling back to a light default (a dark-OS user
   would otherwise get a white flash on every cold load), AND a separate
   `change` listener must keep `.dark` tracking the OS live while the page
   stays open and mode resolves to system -- distinct from architect's
   cross-tab `storage` listener, both needed. Plus lightweight source pins
   for the ruled 3-state (system/light/dark) shape and the submenu-radio-
   group selection idiom (no cycle-on-click anywhere in the dropdown).
6. **Bootstrap VALID_* lists actually match variants.json's real option
   sets** (team-lead's browser-leg finding, 2026-08-29): the bootstrap
   snippet's `VALID_BASE`/`VALID_THEME`/`VALID_CHART` arrays are the
   per-dimension allow-list its own validation logic rejects an unknown
   stored value against, falling back to that dimension's default. The
   byte-identity test above (item 1) only proves board.html's copy and
   dashboard/index.html's copy AGREE WITH EACH OTHER -- it says nothing
   about whether either one agrees with variants.json, the actual source
   of truth. Two IDENTICALLY STALE copies pass that check while silently
   rejecting every newly-added option and resetting to default on next
   load -- exactly what team-lead's browser pass found. This class of
   guard (VariantsJsonValidListParityTests) checks each VALID_* array
   against variants.json's own dimension set + default, independently of
   the cross-head byte-identity check.

Every source-text extractor in this suite is scoped to an explicit region
(the `<head>...</head>` slice, a specific attribute value) rather than a
whole-file substring search, per this suite's own established discipline
(test_css_parse_sanity.py's docstring on exactly this class of gap).

Nothing under test exists yet when this file is written -- board.html has
no inline bootstrap script and no theme trigger; dashboard/index.html is a
13-line Vite shell with none of this either. Every failure below is a
genuinely-absent construct.
"""
from __future__ import annotations

import json
import re
import unittest

import helpers  # noqa: F401

REPO_ROOT = helpers.CAIRN_DIR.parent.parent
BOARD_HTML = helpers.CAIRN_DIR / "board" / "board.html"
DASHBOARD_INDEX_HTML = helpers.CAIRN_DIR / "dashboard" / "index.html"
VARIANTS_JSON = helpers.CAIRN_DIR / "design" / "variants.json"
APP_CSS = helpers.CAIRN_DIR / "dashboard" / "src" / "app.css"
BOARD_JS = helpers.CAIRN_DIR / "board" / "board.js"
BOARD_CSS = helpers.CAIRN_DIR / "board" / "board.css"
DASHBOARD_SRC = helpers.CAIRN_DIR / "dashboard" / "src"

# The exact id architect's ruling implies a single shared generated snippet
# needs SOME stable handle to locate/compare -- this is the contract this
# file assumes (spec-by-test, same role as PT-69's other not-yet-built
# contracts): both heads carry `<script id="cairn-theme-bootstrap">`.
BOOTSTRAP_SCRIPT_ID = "cairn-theme-bootstrap"

FOUR_ROW_LABELS = ("Mode", "Base Color", "Theme", "Chart Color")
STORAGE_KEY = "cairn.theme"


def _head(html: str) -> str:
    match = re.search(r"<head[^>]*>(.*?)</head>", html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _extract_script_by_id(html: str, script_id: str):
    pattern = re.compile(
        r'<script\b[^>]*\bid=["\']' + re.escape(script_id) + r'["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    return match.group(1) if match else None


def _strip_js_comments(source: str) -> str:
    """`//` line comments and `/* */` block comments removed, single/
    double/template-literal string contents left untouched (so a `//` or
    `/*` sitting inside a string isn't mistaken for a comment opener) --
    the exact discipline this file's own `HeadTimeEmbedClassAssignmentTests`
    needed after an explanatory comment containing the literal searched-for
    code string fooled a plain `re.search` on raw source. Not a full JS
    tokenizer (no regex-literal `/.../ ` handling, no escape-sequence
    awareness inside strings) -- this bootstrap snippet is small,
    generated, stdlib-simple JS; a real tokenizer is overkill for it."""
    out = []
    i, n = 0, len(source)
    in_string = None  # None, or the quote character currently open
    in_line_comment = False
    in_block_comment = False
    while i < n:
        two = source[i : i + 2]
        ch = source[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue
        if in_block_comment:
            if two == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            out.append(ch)
            if ch == "\\":
                # Preserve the escaped character verbatim too, so an
                # escaped quote (`\"`) doesn't end the string early.
                if i + 1 < n:
                    out.append(source[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if two == "//":
            in_line_comment = True
            i += 2
            continue
        if two == "/*":
            in_block_comment = True
            i += 2
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tag_offset(html: str, needle_pattern: str):
    match = re.search(needle_pattern, html, flags=re.IGNORECASE | re.DOTALL)
    return match.start() if match else None


class BoardBootstrapInlineScriptTests(unittest.TestCase):
    def setUp(self):
        self.html = BOARD_HTML.read_text(encoding="utf-8") if BOARD_HTML.is_file() else ""
        self.head = _head(self.html)

    def test_board_html_head_contains_the_bootstrap_script(self):
        self.assertTrue(BOARD_HTML.is_file(), f"{BOARD_HTML} does not exist")
        snippet = _extract_script_by_id(self.head, BOOTSTRAP_SCRIPT_ID)
        self.assertIsNotNone(
            snippet,
            f'{BOARD_HTML}: no <script id="{BOOTSTRAP_SCRIPT_ID}"> found in <head> -- '
            f"architect's ruling requires an inline (not external) bootstrap script that reads "
            f"the {STORAGE_KEY} key and applies theme attributes before first paint.",
        )

    def test_bootstrap_script_reads_the_storage_key(self):
        snippet = _extract_script_by_id(self.head, BOOTSTRAP_SCRIPT_ID)
        if snippet is None:
            self.skipTest("bootstrap script not found -- see test_board_html_head_contains_the_bootstrap_script")
        self.assertIn("localStorage", snippet)
        self.assertIn(STORAGE_KEY, snippet)

    def test_bootstrap_script_applies_data_cairn_attributes_and_dark_class(self):
        snippet = _extract_script_by_id(self.head, BOOTSTRAP_SCRIPT_ID)
        if snippet is None:
            self.skipTest("bootstrap script not found -- see test_board_html_head_contains_the_bootstrap_script")
        for marker in ("cairn-base", "cairn-theme", "cairn-chart", "cairnBase", "cairnTheme", "cairnChart"):
            if marker in snippet:
                break
        else:
            self.fail(
                f"{BOARD_HTML}: bootstrap script doesn't appear to set any of the "
                f"data-cairn-base/theme/chart attributes (checked for setAttribute-style "
                f"'cairn-base' or dataset-style 'cairnBase' spellings, per dimension)"
            )
        self.assertIn(
            "dark", snippet,
            f"{BOARD_HTML}: bootstrap script never mentions 'dark' -- architect: mode keeps "
            f"the .dark class, applied via this same inline script before first paint.",
        )

    def test_bootstrap_script_appears_before_the_stylesheet_links(self):
        # Architect: "before the stylesheet links in board.html".
        script_offset = _tag_offset(self.head, r'<script\b[^>]*\bid=["\']' + re.escape(BOOTSTRAP_SCRIPT_ID) + r'["\']')
        first_link_offset = _tag_offset(self.head, r'<link\b[^>]*\brel=["\']stylesheet["\']')
        if script_offset is None:
            self.skipTest("bootstrap script not found -- see test_board_html_head_contains_the_bootstrap_script")
        self.assertIsNotNone(first_link_offset, f"{BOARD_HTML}: no stylesheet <link> found in <head> at all")
        self.assertLess(
            script_offset, first_link_offset,
            f"{BOARD_HTML}: bootstrap script must appear BEFORE the stylesheet links, to avoid "
            f"a flash of default theme before the correct variant CSS is even relevant.",
        )


class DashboardBootstrapInlineScriptTests(unittest.TestCase):
    def setUp(self):
        self.html = DASHBOARD_INDEX_HTML.read_text(encoding="utf-8") if DASHBOARD_INDEX_HTML.is_file() else ""
        self.head = _head(self.html)

    def test_dashboard_index_html_head_contains_the_bootstrap_script(self):
        self.assertTrue(DASHBOARD_INDEX_HTML.is_file(), f"{DASHBOARD_INDEX_HTML} does not exist")
        snippet = _extract_script_by_id(self.head, BOOTSTRAP_SCRIPT_ID)
        self.assertIsNotNone(
            snippet,
            f'{DASHBOARD_INDEX_HTML}: no <script id="{BOOTSTRAP_SCRIPT_ID}"> found in <head>.',
        )

    def test_bootstrap_script_appears_before_the_module_script(self):
        # Architect: "before the module script in dashboard/index.html".
        script_offset = _tag_offset(self.head, r'<script\b[^>]*\bid=["\']' + re.escape(BOOTSTRAP_SCRIPT_ID) + r'["\']')
        module_offset = _tag_offset(self.html, r'<script\b[^>]*\btype=["\']module["\']')
        if script_offset is None:
            self.skipTest("bootstrap script not found -- see test_dashboard_index_html_head_contains_the_bootstrap_script")
        self.assertIsNotNone(module_offset, f"{DASHBOARD_INDEX_HTML}: no <script type=\"module\"> found at all")
        self.assertLess(
            script_offset, module_offset,
            f"{DASHBOARD_INDEX_HTML}: bootstrap script must appear BEFORE the module script.",
        )


class BootstrapScriptsAreByteIdenticalTests(unittest.TestCase):
    """Architect: 'that snippet is a fourth accepted copy... assert both
    heads contain it verbatim.' Byte-identity, not just presence."""

    def test_board_and_dashboard_bootstrap_scripts_match_verbatim(self):
        board_html = BOARD_HTML.read_text(encoding="utf-8") if BOARD_HTML.is_file() else ""
        dashboard_html = DASHBOARD_INDEX_HTML.read_text(encoding="utf-8") if DASHBOARD_INDEX_HTML.is_file() else ""
        board_snippet = _extract_script_by_id(_head(board_html), BOOTSTRAP_SCRIPT_ID)
        dashboard_snippet = _extract_script_by_id(_head(dashboard_html), BOOTSTRAP_SCRIPT_ID)
        if board_snippet is None or dashboard_snippet is None:
            self.skipTest("one or both bootstrap scripts not found yet -- see the per-surface test classes above")
        self.assertEqual(
            board_snippet, dashboard_snippet,
            "board.html's and dashboard/index.html's inline bootstrap scripts have diverged -- "
            "architect requires them to be the SAME generated snippet, verbatim, on both surfaces.",
        )


class SystemModeSynchronousResolutionTests(unittest.TestCase):
    """architect's addendum + design-system-spec.md's Mode section: 'the
    inline FOUC-avoidance bootstrap script must evaluate matchMedia(
    (prefers-color-scheme: dark)).matches synchronously on first paint for
    system, not fall through to the light default' -- a dark-OS user on
    mode=system (the default) must never get a light flash. Checked on
    BOTH surfaces' bootstrap scripts independently (not just via the byte-
    identity test above), so a partial implementation that wires it into
    only one surface's copy is still caught by name."""

    def _snippet(self, html_path):
        html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
        return _extract_script_by_id(_head(html), BOOTSTRAP_SCRIPT_ID)

    def _assert_resolves_system_synchronously(self, snippet, surface_label):
        self.assertIn(
            "matchMedia", snippet,
            f"{surface_label}: bootstrap script never calls matchMedia -- mode=system (the "
            f"default) needs a synchronous prefers-color-scheme check before first paint, "
            f"per architect's addendum correcting the original 'fall back to light' proposal.",
        )
        self.assertIn(
            "prefers-color-scheme", snippet,
            f"{surface_label}: bootstrap script calls matchMedia but doesn't appear to query "
            f"'prefers-color-scheme' specifically.",
        )
        self.assertIn(
            "dark", snippet,
            f"{surface_label}: bootstrap script doesn't reference 'dark' anywhere near its "
            f"matchMedia check.",
        )

    def test_board_bootstrap_resolves_system_synchronously(self):
        snippet = self._snippet(BOARD_HTML)
        if snippet is None:
            self.skipTest("board bootstrap script not found yet")
        self._assert_resolves_system_synchronously(snippet, "board.html")

    def test_dashboard_bootstrap_resolves_system_synchronously(self):
        snippet = self._snippet(DASHBOARD_INDEX_HTML)
        if snippet is None:
            self.skipTest("dashboard bootstrap script not found yet")
        self._assert_resolves_system_synchronously(snippet, "dashboard/index.html")


class SystemModeLiveFollowListenerTests(unittest.TestCase):
    """architect's addendum, item 3 + ux-designer's Mode addendum: 'a
    matchMedia change listener... If stored mode is system (or absent),
    the OS flipping light<->dark MID-SESSION must re-resolve .dark live.'
    Distinct from architect's cross-tab `storage` event listener (§3 of
    the main ruling) -- two different triggers for the same requirement,
    both needed; this class checks specifically for the media-query
    listener, not the storage one.

    Searched across each surface's full combined source (not scoped to
    the inline bootstrap snippet) since a live-updating listener is more
    likely to live in board.js / a dashboard module than in the tiny
    inline FOUC script -- same 'don't pin a file this feature hasn't
    settled yet' reasoning as the dropdown-presence tests below."""

    def test_board_wires_a_prefers_color_scheme_change_listener(self):
        html = BOARD_HTML.read_text(encoding="utf-8") if BOARD_HTML.is_file() else ""
        js = BOARD_JS.read_text(encoding="utf-8") if BOARD_JS.is_file() else ""
        haystack = html + "\n" + js
        if not (BOARD_HTML.is_file() and BOARD_JS.is_file()):
            self.skipTest("board.html or board.js does not exist")
        match = re.search(
            r"matchMedia\([^)]*prefers-color-scheme[^)]*\)[\s\S]{0,200}?addEventListener\(\s*['\"]change['\"]",
            haystack,
        )
        self.assertIsNotNone(
            match,
            "no `matchMedia('(prefers-color-scheme: dark)').addEventListener('change', ...)` "
            "found in board.html/board.js -- mode=system needs to keep tracking the OS live, "
            "not just resolve once at load.",
        )

    def test_dashboard_wires_a_prefers_color_scheme_change_listener(self):
        if not DASHBOARD_SRC.is_dir():
            self.skipTest("dashboard/src does not exist")
        parts = [
            p.read_text(encoding="utf-8")
            for p in DASHBOARD_SRC.rglob("*")
            if p.is_file() and p.suffix in (".svelte", ".ts")
        ]
        haystack = "\n".join(parts)
        if not parts:
            self.skipTest("no .svelte/.ts source found under dashboard/src")
        match = re.search(
            r"matchMedia\([^)]*prefers-color-scheme[^)]*\)[\s\S]{0,200}?addEventListener\(\s*['\"]change['\"]",
            haystack,
        )
        self.assertIsNotNone(
            match,
            "no `matchMedia('(prefers-color-scheme: dark)').addEventListener('change', ...)` "
            "found anywhere under dashboard/src.",
        )


class ModeThreeStateShapeTests(unittest.TestCase):
    """team-lead's ruling (Mode is 3-state, system|light|dark, default
    system) + ux-designer's Mode-row addendum (submenu radio group,
    System/Light/Dark in that order, native checkmark idiom identical to
    the other three rows). Lightweight source-text pins only -- the
    rendered submenu behavior itself is team-lead's browser leg."""

    def setUp(self):
        board_html = BOARD_HTML.read_text(encoding="utf-8") if BOARD_HTML.is_file() else ""
        board_js = BOARD_JS.read_text(encoding="utf-8") if BOARD_JS.is_file() else ""
        dashboard_parts = []
        if DASHBOARD_SRC.is_dir():
            dashboard_parts = [
                p.read_text(encoding="utf-8")
                for p in DASHBOARD_SRC.rglob("*")
                if p.is_file() and p.suffix in (".svelte", ".ts")
            ]
        self.board_haystack = board_html + "\n" + board_js
        self.dashboard_haystack = "\n".join(dashboard_parts)
        self.board_exists = BOARD_HTML.is_file() and BOARD_JS.is_file()
        self.dashboard_exists = bool(dashboard_parts)

    def test_board_names_all_three_mode_states(self):
        self.assertTrue(self.board_exists, "board.html or board.js does not exist")
        missing = [s for s in ("system", "light", "dark") if s not in self.board_haystack.lower()]
        self.assertEqual(
            missing, [],
            f"board source is missing mode state string(s) {missing} (case-insensitive) -- "
            f"Mode is ruled 3-state (system|light|dark), not a 2-state toggle.",
        )

    def test_dashboard_names_all_three_mode_states(self):
        self.assertTrue(self.dashboard_exists, "no .svelte/.ts source found under dashboard/src")
        missing = [s for s in ("system", "light", "dark") if s not in self.dashboard_haystack.lower()]
        self.assertEqual(
            missing, [],
            f"dashboard source is missing mode state string(s) {missing} (case-insensitive) -- "
            f"Mode is ruled 3-state (system|light|dark), not a 2-state toggle.",
        )

    def test_dashboard_uses_the_radio_group_submenu_idiom(self):
        # ux-designer: "DropdownMenu.Sub + DropdownMenu.RadioGroup... identical
        # selection idiom to the other three submenus" -- explicitly NOT
        # cycle-on-click anywhere in the dropdown.
        self.assertTrue(self.dashboard_exists, "no .svelte/.ts source found under dashboard/src")
        self.assertIn(
            "RadioGroup", self.dashboard_haystack,
            "no 'RadioGroup' reference found under dashboard/src -- ux-designer's ruled "
            "submenu idiom is DropdownMenu.Sub + DropdownMenu.RadioGroup for every row, "
            "Mode included, not a cycle-on-click interaction.",
        )


class HeadTimeEmbedClassAssignmentTests(unittest.TestCase):
    """PT-70 scope addition (architect's flash-window residue, folded in
    by team-lead): `wireThemeSettings()` removes the embedded trigger from
    the DOM, but that removal runs from `init()` -- AFTER the page has
    already parsed and (briefly) painted the trigger. In an embedded
    context that's a real flash: visible trigger, then gone a moment
    later. Fix: the inline bootstrap script (already synchronous, head-
    time, before first paint -- the same mechanism PT-69 uses for theme)
    ALSO sets a `:root`-level embed class the instant `window.self !==
    window.top` is true, and board.css keys a rule off `:root.embed` to
    hide the trigger before board.js ever runs -- no flash window,
    because the hide happens before the browser paints anything at all.

    Also covers, implicitly: byte-identity across both heads' bootstrap
    scripts is ALREADY asserted by `BootstrapScriptsAreByteIdenticalTests`
    above -- this class doesn't re-test that, only that the embed-class
    assignment specifically is present in each snippet (which, combined
    with the existing byte-identity test, is equivalent to "present and
    identical on both").
    """

    def _snippet_for(self, html_path):
        html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
        return _extract_script_by_id(_head(html), BOOTSTRAP_SCRIPT_ID)

    def _assert_sets_embed_class_at_head_time(self, surface_label: str, snippet):
        # Search the COMMENT-STRIPPED code, not the raw snippet: this
        # exact class of test bit implementation-lead for real once
        # already -- an explanatory comment ABOVE the real code contained
        # the literal string "window.self !== window.top" in backticks,
        # which a naive `re.search` on the raw text matches FIRST (it
        # appears earlier in source than the real code), landing the real
        # `classList.add("embed")` call just past a short lookahead
        # window. Same self-sabotage shape as an earlier comment
        # collision this feature hit (test_css_parse_sanity.py's PT-57
        # `--chart-*/--radius` finding). Stripping comments first means
        # this guard can no longer be fooled by its own documentation.
        self.assertIsNotNone(snippet, f"{surface_label}: bootstrap script not found")
        code = _strip_js_comments(snippet)
        self_top_match = re.search(r"self\s*!==\s*window\.top", code)
        self.assertIsNotNone(
            self_top_match,
            f"{surface_label}: bootstrap script's actual CODE (comments stripped) never checks "
            f"`window.self !== window.top` -- the head-time embed-class assignment has nothing "
            f"to key off.",
        )
        neighborhood = code[max(0, self_top_match.start() - 50):self_top_match.end() + 250]
        self.assertTrue(
            "classList.add" in neighborhood and "embed" in neighborhood,
            f"{surface_label}: no classList.add(...'embed'...) found near the `window.self !== "
            f"window.top` check in the bootstrap script's actual code -- the embed class must be "
            f"assigned at head time, synchronously, before board.js/main.ts ever runs, or the "
            f"trigger still flashes visible for a moment in the embedded context.",
        )

    def test_board_bootstrap_sets_an_embed_class_at_head_time(self):
        self._assert_sets_embed_class_at_head_time("board.html", self._snippet_for(BOARD_HTML))

    def test_dashboard_bootstrap_sets_an_embed_class_at_head_time(self):
        self._assert_sets_embed_class_at_head_time("dashboard/index.html", self._snippet_for(DASHBOARD_INDEX_HTML))

    def test_board_css_hides_the_trigger_via_a_root_embed_selector(self):
        self.assertTrue(BOARD_CSS.is_file(), f"{BOARD_CSS} does not exist")
        source = BOARD_CSS.read_text(encoding="utf-8")
        stripped = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        match = re.search(r":root\.embed\b[^{]*\{([^}]*)\}", stripped)
        self.assertIsNotNone(
            match,
            f"{BOARD_CSS}: no `:root.embed {{ ... }}` (or a selector compounding on it, e.g. "
            f"`:root.embed .theme-settings`) found -- the head-time embed class needs a CSS "
            f"rule to actually hide the trigger before board.js runs.",
        )
        rule_body = match.group(1)
        self.assertTrue(
            re.search(r"display\s*:\s*none", rule_body) is not None,
            f"{BOARD_CSS}: found a `:root.embed`-keyed rule but it doesn't set `display: none` "
            f"-- that's the actual hiding mechanism this pre-JS fix needs.",
        )


FIXED_VALID_MODE = frozenset({"system", "light", "dark"})  # 3-state ruling; not derived from variants.json


def _extract_valid_list(snippet: str, name: str):
    """The array literal assigned to `var VALID_<name> = [...]` inside the
    bootstrap snippet, parsed as JSON (double-quoted string array, no
    trailing commas -- the shape gen_variants.py itself emits). Returns
    None if the variable isn't found at all (a genuinely-absent construct,
    distinct from an empty list)."""
    match = re.search(r"var\s+VALID_" + re.escape(name) + r"\s*=\s*(\[[^\]]*\])\s*;", snippet)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


class VariantsJsonValidListParityTests(unittest.TestCase):
    """team-lead's browser-leg finding (2026-08-29): both heads' bootstrap
    scripts can be BYTE-IDENTICAL to each other (BootstrapScriptsAreByte
    IdenticalTests, above) while both being STALE against variants.json --
    a newly-added option applies and stores fine, then gets silently
    rejected and reset to that dimension's default on the very next
    load's first paint, because VALID_THEME/VALID_CHART never learned
    about it. Byte-identity checks COPIES-MATCH; this checks LISTS-MATCH-
    DATA -- two different claims, and the first one cannot stand in for
    the second (identically-stale is still identically wrong)."""

    def setUp(self):
        self.assertTrue(VARIANTS_JSON.is_file(), f"{VARIANTS_JSON} does not exist")
        self.variants_data = json.loads(VARIANTS_JSON.read_text(encoding="utf-8"))

    def _expected_set(self, dim: str) -> set:
        dimension = self.variants_data["dimensions"][dim]
        return set(dimension["variants"].keys()) | {dimension["default"]}

    def _snippet_for(self, html_path):
        html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
        return _extract_script_by_id(_head(html), BOOTSTRAP_SCRIPT_ID)

    def _assert_valid_lists_match(self, surface_label: str, snippet):
        self.assertIsNotNone(snippet, f"{surface_label}: bootstrap script not found")
        mode_list = _extract_valid_list(snippet, "MODE")
        self.assertIsNotNone(mode_list, f"{surface_label}: VALID_MODE not found in bootstrap script")
        self.assertEqual(
            set(mode_list), set(FIXED_VALID_MODE),
            f"{surface_label}: VALID_MODE is {sorted(mode_list)}, expected exactly "
            f"{sorted(FIXED_VALID_MODE)} (the ruled 3-state set -- Mode isn't a variants.json "
            f"token dimension, so this one's fixed, not derived).",
        )
        for dim_key, var_name in (("base", "BASE"), ("theme", "THEME"), ("chart", "CHART")):
            found_list = _extract_valid_list(snippet, var_name)
            self.assertIsNotNone(found_list, f"{surface_label}: VALID_{var_name} not found in bootstrap script")
            expected = self._expected_set(dim_key)
            found = set(found_list)
            missing = sorted(expected - found)
            extra = sorted(found - expected)
            self.assertEqual(
                (missing, extra), ([], []),
                f"{surface_label}: VALID_{var_name} disagrees with variants.json's '{dim_key}' "
                f"dimension (variants + default) -- missing from bootstrap: {missing}, present "
                f"in bootstrap but not in variants.json: {extra}. A newly-added option that's "
                f"missing here applies+stores fine, then gets silently rejected and reset to "
                f"'{self.variants_data['dimensions'][dim_key]['default']}' on the very next "
                f"load's first paint -- exactly team-lead's browser-leg finding.",
            )

    def test_board_bootstrap_valid_lists_match_variants_json(self):
        self._assert_valid_lists_match("board.html", self._snippet_for(BOARD_HTML))

    def test_dashboard_bootstrap_valid_lists_match_variants_json(self):
        self._assert_valid_lists_match("dashboard/index.html", self._snippet_for(DASHBOARD_INDEX_HTML))


class ValidListExtractorSelfTests(unittest.TestCase):
    """Proves `_extract_valid_list` finds the real thing and that the
    parity check above CAN fail on a genuine mismatch, not just that real
    files currently agree."""

    def test_extracts_a_simple_valid_list(self):
        snippet = 'var VALID_BASE = ["stone", "zinc"];'
        self.assertEqual(_extract_valid_list(snippet, "BASE"), ["stone", "zinc"])

    def test_returns_none_when_the_variable_is_absent(self):
        self.assertIsNone(_extract_valid_list("var VALID_BASE = [];\n", "THEME"))

    def test_stale_list_is_caught_as_a_real_mismatch(self):
        # Mirrors the exact shape team-lead's browser leg found: a
        # variants.json with a newly-added option the bootstrap's
        # VALID_THEME array doesn't know about yet.
        variants_theme_set = {"sky", "blue", "violet", "lime"}
        stale_bootstrap_list = ["sky", "blue", "violet"]  # "lime" missing
        missing = variants_theme_set - set(stale_bootstrap_list)
        self.assertEqual(missing, {"lime"})


class VariantsCssWiringTests(unittest.TestCase):
    def test_board_html_links_variants_css_after_tokens_before_board_css(self):
        self.assertTrue(BOARD_HTML.is_file(), f"{BOARD_HTML} does not exist")
        html = BOARD_HTML.read_text(encoding="utf-8")
        tokens_offset = _tag_offset(html, r'<link\b[^>]*href=["\']/board/tokens\.css["\']')
        variants_offset = _tag_offset(html, r'<link\b[^>]*href=["\']/board/variants\.css["\']')
        board_css_offset = _tag_offset(html, r'<link\b[^>]*href=["\']/board/board\.css["\']')
        self.assertIsNotNone(tokens_offset, f"{BOARD_HTML}: no <link> to /board/tokens.css found")
        self.assertIsNotNone(board_css_offset, f"{BOARD_HTML}: no <link> to /board/board.css found")
        self.assertIsNotNone(
            variants_offset,
            f"{BOARD_HTML}: no <link> to /board/variants.css found -- architect: linked "
            f"AFTER tokens.css, BEFORE board.css.",
        )
        if variants_offset is not None:
            self.assertLess(tokens_offset, variants_offset, f"{BOARD_HTML}: variants.css must come after tokens.css")
            self.assertLess(variants_offset, board_css_offset, f"{BOARD_HTML}: variants.css must come before board.css")

    def test_app_css_imports_variants_css_immediately_after_the_existing_three_imports(self):
        self.assertTrue(APP_CSS.is_file(), f"{APP_CSS} does not exist")
        source = APP_CSS.read_text(encoding="utf-8")
        import_lines = re.findall(r"^@import\s+['\"][^'\"]+['\"];\s*$", source, flags=re.MULTILINE)
        self.assertGreaterEqual(
            len(import_lines), 3,
            f"{APP_CSS}: expected at least the existing 3 @import lines (tailwindcss, "
            f"tw-animate-css, shadcn-svelte/tailwind.css), found {len(import_lines)}",
        )
        variants_imports = [ln for ln in import_lines if "variants.css" in ln]
        self.assertTrue(
            variants_imports,
            f"{APP_CSS}: no `@import './variants.css';` found -- architect: must sit immediately "
            f"after app.css's existing three imports, still ahead of any rule (Tailwind v4's "
            f"import-ordering rule).",
        )
        if variants_imports:
            variants_line_index = import_lines.index(variants_imports[0])
            self.assertEqual(
                variants_line_index, 3,
                f"{APP_CSS}: variants.css import is at import-position {variants_line_index} "
                f"(0-indexed among consecutive @import lines), expected position 3 (immediately "
                f"after the existing 3 imports).",
            )


class DropdownPresenceOnBoardTests(unittest.TestCase):
    """The board is vanilla HTML/CSS/JS with no Svelte component tree, so
    the four rows are more likely assembled by board.js than static HTML --
    this searches the combined board.html + board.js source rather than
    pinning an exact DOM shape neither this test nor implementation-lead
    has settled on yet."""

    def setUp(self):
        html = BOARD_HTML.read_text(encoding="utf-8") if BOARD_HTML.is_file() else ""
        js = BOARD_JS.read_text(encoding="utf-8") if BOARD_JS.is_file() else ""
        self.haystack = html + "\n" + js
        self.files_exist = BOARD_HTML.is_file() and BOARD_JS.is_file()

    def test_board_has_a_theme_settings_trigger(self):
        # re.search + assertIsNotNone rather than assertRegex: on a failure,
        # assertRegex dumps the WHOLE haystack (board.html + board.js, a
        # couple thousand lines) into the test output -- unreadable and
        # slow to scroll past for no benefit over a plain pass/fail here.
        self.assertTrue(self.files_exist, "board.html or board.js does not exist")
        match = re.search(r'id=["\'][\w-]*theme[\w-]*["\']', self.haystack)
        self.assertIsNotNone(
            match,
            "no element with an id containing 'theme' found in board.html/board.js -- "
            "ux-designer's proposal: a small trigger pinned to the board's own top-right header.",
        )

    def test_board_source_names_all_four_rows(self):
        self.assertTrue(self.files_exist, "board.html or board.js does not exist")
        missing = [label for label in FOUR_ROW_LABELS if label not in self.haystack]
        self.assertEqual(
            missing, [],
            f"board.html/board.js is missing row label(s) {missing} -- ux-designer's ruled "
            f"anatomy is Mode / Base Color / Theme / Chart Color, all four, both surfaces.",
        )

    def test_board_source_references_the_storage_key(self):
        self.assertTrue(self.files_exist, "board.html or board.js does not exist")
        self.assertIn(
            STORAGE_KEY, self.haystack,
            f"board.html/board.js never references the {STORAGE_KEY} localStorage key.",
        )

    def test_board_wires_the_dark_class_as_a_real_mechanism(self):
        # Architect's flagged risk: "Nothing in either surface ever adds
        # the .dark class today... Mode is therefore a new mechanism."
        # This is a structural pin only -- team-lead's rendered browser
        # pass is the actual "does it render" check, not this.
        self.assertTrue(self.files_exist, "board.html or board.js does not exist")
        match = re.search(r'classList\s*\.\s*(add|toggle|remove)\s*\(\s*[\'"]dark[\'"]', self.haystack)
        self.assertIsNotNone(
            match,
            "no `classList.add/toggle/remove('dark')` found in board.html/board.js -- Mode "
            "needs to be a genuinely new mechanism on the board, not just declared dead CSS.",
        )

    def test_board_places_the_trigger_inside_the_top_header(self):
        # Mosko's live-test finding #1 + ux's ruling (issue thread,
        # 2026-08-29): the trigger must live in the top-right HEADER area
        # on both surfaces, same position. Board's own header is
        # `<header class="app-header">` -- pin the trigger inside it,
        # not just present somewhere on the page.
        self.assertTrue(BOARD_HTML.is_file(), f"{BOARD_HTML} does not exist")
        html = BOARD_HTML.read_text(encoding="utf-8")
        match = re.search(r'<header\b[^>]*class="app-header"[^>]*>(.*?)</header>', html, re.DOTALL)
        self.assertIsNotNone(match, f'{BOARD_HTML}: no <header class="app-header"> block found')
        header_block = match.group(1) if match else ""
        self.assertTrue(
            'id="theme-settings-trigger"' in header_block,
            f'{BOARD_HTML}: the theme-settings trigger is not inside <header class="app-header">'
            f" -- ux's placement ruling requires the top-right header area on both surfaces.",
        )


class DropdownPresenceOnDashboardTests(unittest.TestCase):
    """Searches all dashboard/src source (svelte/ts) rather than a single
    named file -- implementation-lead hasn't built the composing component
    yet (no app-sidebar.svelte or similar exists when this is written), so
    this doesn't pin a file name, only that the required pieces exist
    SOMEWHERE under dashboard/src."""

    def setUp(self):
        if not DASHBOARD_SRC.is_dir():
            self.haystack = ""
            self.files_exist = False
            return
        parts = []
        for p in DASHBOARD_SRC.rglob("*"):
            if p.is_file() and p.suffix in (".svelte", ".ts"):
                parts.append(p.read_text(encoding="utf-8"))
        self.haystack = "\n".join(parts)
        self.files_exist = bool(parts)

    def test_dashboard_places_the_trigger_inside_the_top_right_header(self):
        # RETARGETED (was test_dashboard_uses_sidebar_footer): ux-designer's
        # original Sidebar.Footer placement was superseded by Mosko's
        # live-test finding #1 ("the Sidebar.Footer trigger wasn't
        # discovered") -- ruled placement is now the top-right HEADER,
        # same position as the board's. The old test would have kept
        # passing vacuously forever: "Sidebar.Footer" still appears in
        # App.svelte, but only in a COMMENT explaining the retired plan,
        # not in any real component usage -- checked the actual file
        # before writing this, this is not a hypothetical risk.
        dashboard_app_svelte = DASHBOARD_SRC / "App.svelte"
        self.assertTrue(dashboard_app_svelte.is_file(), f"{dashboard_app_svelte} does not exist")
        source = dashboard_app_svelte.read_text(encoding="utf-8")
        match = re.search(r"<header\b[^>]*>(.*?)</header>", source, re.DOTALL)
        self.assertIsNotNone(match, f"{dashboard_app_svelte}: no <header> block found")
        header_block = match.group(1) if match else ""
        self.assertTrue(
            "<ThemeSettings" in header_block,
            f"{dashboard_app_svelte}: <ThemeSettings ...> is not rendered inside the page's "
            f"<header> -- ux's placement ruling: top-right header, same position as the board.",
        )

    def test_dashboard_theme_settings_has_exactly_one_render_site(self):
        # Regression pin against the RETIRED Sidebar.Footer plan silently
        # coming back as a second render site (a real dedup/placement
        # regression) -- distinct from the comment mentioning it, which
        # is fine and expected to stay as historical explanation.
        self.assertTrue(self.files_exist, "no .svelte/.ts source found under dashboard/src")
        occurrences = re.findall(r"<ThemeSettings\b", self.haystack)
        self.assertEqual(
            len(occurrences), 1,
            f"expected exactly one <ThemeSettings ...> render site under dashboard/src, found "
            f"{len(occurrences)} -- a second site would mean the retired Sidebar.Footer "
            f"placement (or some other duplicate) came back, not just a comment mentioning it.",
        )

    def test_dashboard_uses_the_settings2_icon(self):
        self.assertTrue(self.files_exist, "no .svelte/.ts source found under dashboard/src")
        self.assertIn(
            "Settings2", self.haystack,
            "no 'Settings2' (lucide icon) reference found under dashboard/src -- ux-designer's "
            "ruled trigger icon.",
        )

    def test_dashboard_source_names_all_four_rows(self):
        self.assertTrue(self.files_exist, "no .svelte/.ts source found under dashboard/src")
        missing = [label for label in FOUR_ROW_LABELS if label not in self.haystack]
        self.assertEqual(
            missing, [],
            f"dashboard/src is missing row label(s) {missing} -- ux-designer's ruled anatomy "
            f"is Mode / Base Color / Theme / Chart Color, all four, both surfaces.",
        )

    def test_dashboard_source_references_the_storage_key(self):
        self.assertTrue(self.files_exist, "no .svelte/.ts source found under dashboard/src")
        self.assertIn(
            STORAGE_KEY, self.haystack,
            f"dashboard/src never references the {STORAGE_KEY} localStorage key.",
        )


class SourceTextExtractorSelfTests(unittest.TestCase):
    """Proves the head/script/offset helpers CAN detect what they claim to,
    against synthetic input -- not just that real files currently pass."""

    def test_head_extraction_scoped_correctly(self):
        html = "<html><head><title>x</title></head><body>ignored theme mode stuff</body></html>"
        self.assertNotIn("ignored", _head(html))

    def test_extract_script_by_id_finds_the_right_script(self):
        html = '<head><script id="other">nope</script><script id="cairn-theme-bootstrap">yes</script></head>'
        self.assertEqual(_extract_script_by_id(html, "cairn-theme-bootstrap"), "yes")

    def test_extract_script_by_id_returns_none_when_absent(self):
        html = "<head><script>no id here</script></head>"
        self.assertIsNone(_extract_script_by_id(html, "cairn-theme-bootstrap"))

    def test_strip_js_comments_removes_line_and_block_comments(self):
        source = "// a line comment\nvar x = 1; /* a block\ncomment */ var y = 2;"
        stripped = _strip_js_comments(source)
        self.assertNotIn("a line comment", stripped)
        self.assertNotIn("a block", stripped)
        self.assertIn("var x = 1;", stripped)
        self.assertIn("var y = 2;", stripped)

    def test_strip_js_comments_leaves_string_contents_with_comment_like_text_alone(self):
        source = 'var url = "http://example.com"; // trailing comment'
        stripped = _strip_js_comments(source)
        self.assertIn('"http://example.com"', stripped)
        self.assertNotIn("trailing comment", stripped)

    def test_strip_js_comments_reproduces_the_real_self_sabotage_bug(self):
        # The EXACT shape implementation-lead hit: an explanatory comment
        # containing the literal searched-for code string, positioned
        # BEFORE the real code, so a naive re.search on raw source finds
        # the comment's occurrence first and a short lookahead window
        # never reaches the real classList.add call.
        source = (
            "// head-time embed detection: `window.self !== window.top` is the same check\n"
            "// board.js's isEmbedMode already uses, so we don't invent a second signal here.\n"
            "// This whole explanatory aside is deliberately long enough that a naive fixed-\n"
            "// width lookahead window from the FIRST raw-text match (this comment) would\n"
            "// land short of the real code below, exactly like the bug that motivated this.\n"
            "if (window.self !== window.top) root.classList.add(\"embed\");\n"
        )
        raw_match = re.search(r"self\s*!==\s*window\.top", source)
        raw_neighborhood = source[raw_match.start():raw_match.end() + 250]
        # Reproduces the bug: the raw-text search, unstripped, does NOT
        # find classList.add within the short window (it's stuck inside
        # the long comment).
        self.assertNotIn("classList.add", raw_neighborhood)
        # The stripped version fixes it: the comment is gone, so the
        # FIRST (and only) match is the real code, immediately followed
        # by classList.add.
        stripped = _strip_js_comments(source)
        stripped_match = re.search(r"self\s*!==\s*window\.top", stripped)
        self.assertIsNotNone(stripped_match)
        stripped_neighborhood = stripped[stripped_match.start():stripped_match.end() + 250]
        self.assertIn("classList.add", stripped_neighborhood)

    def test_tag_offset_orders_two_tags_correctly(self):
        html = '<a id="first"></a><b id="second"></b>'
        first = _tag_offset(html, r'<a\b')
        second = _tag_offset(html, r'<b\b')
        self.assertLess(first, second)


if __name__ == "__main__":
    unittest.main()
