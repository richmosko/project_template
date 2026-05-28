# Template Decisions

> Append-only log of decisions about the `project_template` repo itself — its workflow, conventions, structure, tooling, and shape. Audience: the template maintainer and any Claude session working on the template.
>
> **⚠️ Delete this file when you bootstrap a new project from the template.** Your project's own decision log is [`DECISIONS.md`](DECISIONS.md). This file documents the template, not your project.

## Format

```
### YYYY-MM-DD — <short decision title> (#<pr>)
**Decision:** <one sentence>
**Why:** <one or two sentences>
**Alternatives considered:** <bullets, if relevant>
**Approved by:** <name>
**Supersedes:** <ref to prior decision, if any>
```

Same format as the seed `DECISIONS.md`. The log is **append-only**. Don't edit historical entries; supersede them.

---

### 2026-05-28 — Shared / reusable components model + `/spin-off-component` (#15)
**Decision:** Add a "Shared / reusable components" model to the workflow. A substantial, reusable component graduates to its own repo as a fresh template instance with its own Linear Initiative, released on its own cadence via semver git tags, and consumed by parent projects as a tag-pinned dependency. Ship `/spin-off-component` to mechanize the history-preserving extraction + repo creation + initial `v0.1.0` release + linkage recording; **borrow** stays a documented procedure (no skill).
**Why:** For a solo dev the recurring driver is reuse — a component used by ≥2 projects, needing its own release clock, or already built elsewhere. The shared-team / multi-Initiative model already supports this with no new infra; the only gaps were a graduation rubric, a linkage convention, and mechanizing the error-prone git extraction.
**Alternatives considered:**
- *Submodules / subtree as the default coupling:* sharp edges (detached HEAD, fiddly merge-back). Kept as opt-in for "borrow"; not the default.
- *Monorepo workspaces only (never split):* the right answer when the driver is size/context — documented as the "don't split" path — but doesn't serve genuine reuse / independent release.
- *Give "borrow" its own skill too:* deferred — pinning a dependency + recording linkage is light enough to stay convention-only until it proves repetitive.
- *Require a package registry:* unnecessary for solo dev; git tags are consumed natively by every major ecosystem.

**Approved by:** Mosko

---

### 2026-05-28 — `/drive` goal-driven loop + delivery-autonomy methodologies (#14)
**Decision:** Add the `/drive` skill, which prepares a native `/goal` loop to run an Implement→Validate cycle hands-off and **surfaces the `/goal` line for the user to paste** (a skill cannot self-issue `/goal`). Two delivery-autonomy methodologies, chosen per project at `/setup-linear-team`: `stop-at-merge` (default) and `self-merge-within-milestone`.
**Why:** Lets a large project be driven deliverable-by-deliverable with less turn-by-turn prompting, while keeping a human checkpoint at goal-set time. `stop-at-merge` preserves the per-feature human gate; `self-merge` trades it for unattended speed within a milestone (needs auto mode). Phase-gate transitions stay human under both.
**Alternatives considered:**
- *A skill that self-issues `/goal`:* impossible — no model-callable goal tool, no `SlashCommand` tool (verified against Claude Code docs). Construct-and-paste is the supported pattern.
- *Stop hook or nested `claude -p "/goal"` subprocess to fake self-issue:* unsupported (no mid-session hook hot-reload; nested sessions contend over state). Rejected.
- *Convention-only (no skill):* rejected — assembling a ~4,000-char condition from live state each loop is error-prone.

**Approved by:** Mosko

---

### 2026-05-25 — Template gets its own semver tags + GitHub Releases
**Decision:** The `project_template` repo will tag its own semver versions (`vX.Y.Z`) and publish GitHub Releases, using the same `/merge-pr`-prompted process the template defines for downstream projects. Only meaningful template-shape changes get a tag — not every PR.
**Why:** Downstream projects need a way to say *"this project was bootstrapped from project_template vX.Y.Z"* for recovery and debugging. Without tags, every workflow bug becomes "which commit of the template were you on?" guesswork. The template should eat its own dog food on this convention.
**Alternatives considered:**
- *Always-current template (no tags):* simpler, but loses the pin-point affordance. Rejected.
- *Date-based versioning (YYYY.MM.DD):* clearer ordering, but breaks the convention the template defines for downstream. Rejected for consistency.
- *Tag every merged PR:* too noisy; defeats the "release = milestone" intent. Rejected.

**Mechanics:**
- First tag: **v0.1.0**, cut from `main` immediately after this PR merges. Covers everything in `#1`–`#13`, including the versioning system itself.
- Bootstrap step in `CLAUDE.md` writes the template version into the new project's `DECISIONS.md` bootstrap entry: *"Bootstrapped from project_template vX.Y.Z."*
- No `CHANGELOG.md` (per existing template convention). GitHub Releases auto-draft from PR titles, curated and published manually.

**Approved by:** Mosko

---

### 2026-05-25 — `TEMPLATE_DECISIONS.md` separated from seed `DECISIONS.md`
**Decision:** Decisions about the template itself live in `TEMPLATE_DECISIONS.md` (root, deleted on bootstrap). The seed `DECISIONS.md` only contains format scaffolding + a bootstrap example, with no template-meta entries.
**Why:** Without separation, template-meta decisions accumulate in `DECISIONS.md` and travel into every downstream project as irrelevant baggage. The two logs have different audiences and lifecycles.
**Alternatives considered:**
- *Single `DECISIONS.md` with a "template" section:* downstream projects would have to remember to strip it. Brittle. Rejected.
- *Hidden directory `.template-meta/`:* cleaner namespace but easy to forget; harder to discover in GitHub's file tree. Rejected.

**Approved by:** Mosko

---

### 2026-05-25 — Team-agents requirement made explicit in `CLAUDE.md` (#12)
**Decision:** `CLAUDE.md` (auto-loaded every session) states explicitly that the template requires Claude Code's experimental team-agents feature, names the two settings, and warns that disabling them breaks `SendMessage` / shared task list / anchor-task coordination.
**Why:** Prior wording said *"verify teammate mode"*, which could be read as *"pick a mode"* rather than *"team-agents must be on."* The README + WORKFLOW.md already enforced it; CLAUDE.md was the gap.

**Approved by:** Mosko

---

### 2026-05-23 — `/serve-docs` skill: background docs server under Claude session (#11)
**Decision:** Add a `/serve-docs` skill that runs `scripts/serve-docs.sh` as a background process owned by the Claude harness, with `start | status | stop | <DOC>` subcommands. Server lifecycle is bound to the Claude session — dies on `/exit`.
**Why:** Without it, the user had to keep a separate terminal open to run the comments-sidecar server. The skill collapses that into a single in-session command.
**Trade-off:** Server logs go to the harness's background-shell buffer, not the user's terminal. For debugging the server itself, the standalone `./scripts/serve-docs.sh` invocation still works.

**Approved by:** Mosko

---

### 2026-05-23 — PRD `§appendix` numbering + comments-FAQ default (#10)
**Decision:** Number the PRD's `§appendix` consistently with prior sections (`11.` H2 / `11.1` H3) and replace the placeholder FAQ Q/A with a real default Q&A about the comments-sidecar workflow. Also added a `section h3` rule to `doc.css` so H3 subsections render distinctly from their parent H2.
**Why:** Surfaced during the first real `/refine-doc` dogfood pass. The PRD's TOC numbered the appendix but the body didn't; H3s under H2 sections inherited browser defaults and read indistinct.

**Approved by:** Mosko

---

### 2026-05-23 — Comments-sidecar Pass 2: inline widget + local server (#9)
**Decision:** Layer an inline comment-authoring UX (`docs/_assets/comments.js` + `comments.css`, served by `scripts/serve-docs.py` / `.sh`) on top of Pass 1's `comments.md` convention. Widget detects doc from URL, shows a status badge, injects `+ Comment` and `💬 N` buttons next to every `<section>` heading.
**Why:** Hand-editing `comments.md` works but is friction-heavy. Inline authoring removes the friction without changing the on-disk format — widget-authored and hand-edited comments use the same `## §<section-id>` shape and feed `/refine-doc` identically.
**Security shape:** Server binds `127.0.0.1` only (no LAN exposure); two API endpoints; `doc` whitelist-validated; `section` regex-validated; no auth (localhost only).
**Graceful degradation:** Opened via `file://` (no server) → widget shows offline badge; doc remains readable; hand-editing still works.

**Approved by:** Mosko

---

### 2026-05-23 — Comments-sidecar Pass 1: convention + `/refine-doc` skill (#8)
**Decision:** Establish `docs/<DOC>/comments.md` as the per-doc review sidecar (gitignored), with `## §<section-id>` blocks anchored to existing `<section id="...">` IDs in the HTML doc. New skill `/refine-doc <PRD|ARCH|SECURITY>` walks the sidecar, addresses each comment in the matching HTML section, and removes addressed comments as it goes.
**Why:** The doc-review feedback loop needed a structured-but-low-overhead surface. Sidecar files keep working notes out of the committed doc; the resolution (the doc edit) is what gets committed.
**Decisions baked in:**
- Per-section granularity (reuses existing `<section id="...">` anchors).
- Addressed comments are removed (not struck through or archived).
- Single-user assumed; multi-user attribution deferred.
- Commit shape: one batch commit per `/refine-doc` run, listing addressed sections in the body.
- Sidecar files gitignored at the template level (in-process working notes only).

**Approved by:** Mosko

---

### 2026-05-23 — `/open-doc` invokes browser explicitly, bypassing `.html` LaunchServices default (#7)
**Decision:** `/open-doc` Step 2 on macOS uses `open -a "Google Chrome" <path> 2>/dev/null || open -a "Safari" <path>` instead of the bare `open <path>`. Linux/Windows guidance unchanged.
**Why:** macOS LaunchServices `.html` defaults drift to whatever editor was installed last (MacVim, VS Code, Sublime) — a common side-effect of editor installs. The explicit `-a` bypass routes the doc to an actual browser regardless of LS state.
**README "Customizing doc preview"** documents how to swap the preferred browser by editing a single string.

**Approved by:** Mosko

---

### 2026-05-23 — HTML docs live in per-doc subdirectories (#6)
**Decision:** Each top-level HTML doc gets its own subdirectory with `index.html` as the entry point. `docs/PRD.html` → `docs/PRD/index.html`; same for `ARCH` and `SECURITY`. Path-style references use the new form; bare prose references shorten to `PRD` / `ARCH` / `SECURITY`.
**Why:** Forward-plans for growth. When a doc accumulates supporting assets (mockup images, threat-model graphics, sub-pages), they sit alongside the index without crowding template-shared `docs/_assets/`. The `index.html` filename stays stable as the entry point even if a doc later splits into multiple files.

**Approved by:** Mosko

---

### 2026-05-23 — Mermaid: CDN by default, vendoring script for offline/regulated projects (#5)
**Decision:** HTML docs load Mermaid via `docs/_assets/mermaid-init.js` from `cdn.jsdelivr.net` by default. Projects with CDN-access restrictions (fintech, healthcare, air-gapped) run `scripts/vendor-mermaid.sh` to download the UMD bundle to `docs/_assets/vendor/` and rewrite the init script to load from local file.
**Why:** Most projects work fine with the CDN — zero setup, always-current Mermaid version. Regulated projects can't. A one-command vendor script covers both audiences without forcing the template to pick a default that's wrong for half its users.
**Implementation choices:**
- UMD (not ESM) so `file://` URLs continue to work for doc preview.
- Vendor directory gitignored at the template level so the template itself isn't bloated by the ~3MB bundle. Downstream projects choose commit-or-not.
- Version overridable: `MERMAID_VERSION=11.4.0 ./scripts/vendor-mermaid.sh`.
- Idempotent; revert via `git checkout`.

**Approved by:** Mosko

---

### 2026-05-23 — Doc additions from mosko-fintech feedback (#4)
**Decision:** Several documentation additions surfaced from adoption notes on a derived project:
- README: new "Common project-specific extensions" section (Visual Designer / Compliance Officer / Data-pipeline Lead as documented optional add-on roles) + new "Customizing doc preview" section.
- WORKFLOW.md: Decision logging "What goes where" table separating DECISIONS / git+MILESTONES / GitHub Releases. New "Release process" subsection formalizing `gh release create --generate-notes --draft → curate → publish`. Explicitly states the template does NOT ship `CHANGELOG.md`.
- `/merge-pr` skill: Step 6 prompts for both the tag and the GitHub Release draft, with curation handoff to the Principal.
- MILESTONES.md: Roadmap table gains an explicit **Gate** column.

**Why:** Adopting projects surfaced gaps the template hadn't anticipated. Bundled as one PR because individually they're each too small to justify the full I→V loop.

**Approved by:** Mosko

---

### 2026-05-22 — Seed M0 + M1 process milestones at bootstrap (#3)
**Decision:** `/setup-linear-team` creates **M0 (Bootstrap & Research)** and **M1 (Plan)** as Linear projects and back-fills the MILESTONES.md Roadmap with both rows at project Day 0. Each phase can be subdivided if complexity warrants (`M0a`, `M0b`...); the two seeded rows are a floor, not a cap.
**Why:** Without seeded process milestones, the Roadmap is empty until the architect populates product milestones during M1 — which makes Research and Plan phases invisible in Linear's Roadmap view. Seeding M0/M1 makes the heavyweight phases first-class trackable units from session one.

**Approved by:** Mosko

---

### 2026-05-22 — SessionStart hook robustness + Resume runbook (#2)
**Decision:**
- `SessionStart` hook uses `awk '/^## Roadmap/{exit} {print}'` to capture MILESTONES.md head through (but not including) the Roadmap section, instead of `head -40`. Robust to row drift.
- `CLAUDE.md` → Session management gains a 6-step **Resume runbook** for fresh "let's continue" sessions: read full MILESTONES → inspect git → match branch to context → check open PRs → read WORKFLOW only if needed → confirm pickup point before acting. Plus a mid-feature gotcha callout.

**Why:** Hard-coded `head -40` silently broke when MILESTONES tables grew past 40 lines. Cold-start resumes were over-relying on the auto-injected head and missing important context (Active Feature row drift, branch-state mismatches).

**Approved by:** Mosko

---

### 2026-05-22 — PRD aligned with "Aligned" template elements (#1)
**Decision:** Cross-reference the template's PRD against chatprd.ai's template and the internal "Aligned" PRD Google Doc; pull in selected elements that fit a team-of-agents workflow:
- Added §1.1 **High-Level Approach** (subsection of Overview).
- Reframed §3 **Non-Goals** to require the *why*.
- Added an **FAQs** subsection under Appendix.
- Normalized §2 **Goals & Success Metrics** from a table to an ordered list for consistency with Non-Goals.

**Skipped** (deliberately): phase sign-off gates (too formal for solo + agents), operational checklist (out of scope), in-doc changelog (lives in `DECISIONS.md`).

**Approved by:** Mosko

---

<!--
Add new template-meta decisions ABOVE this comment, newest first.
-->
