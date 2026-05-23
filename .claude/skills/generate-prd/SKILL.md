---
name: generate-prd
description: Interview-driven generation of `docs/PRD/index.html`. Use during the Research phase, or whenever the user asks to "write the PRD", "generate the product spec", or "interview me about the product". Follows the chatprd.ai lightweight PRD template — Problem, Goals/Metrics, User Stories, Functional/Non-Functional Requirements, Design Considerations, Technical Considerations, Timeline, Open Questions, Appendix. **Supports import mode**: pass an optional path to an existing PRD artifact (markdown, HTML, PDF, Google Doc) and the skill analyzes the legacy content, maps it to the AGILE framework, and runs the interview only for gaps.
---

# generate-prd

You are running an interview to populate `docs/PRD/index.html`. This is the Research-phase driver activity. The `product-manager` teammate should run this skill (or the team-lead if no PM is active).

## Two modes

- **Greenfield mode** (no argument): interview from a blank slate. Walk all sections.
- **Import mode** (argument is a path or URL to an existing PRD artifact): analyze the source, classify content by the rubric in `WORKFLOW.md` → Importing existing artifacts, port what fits, flag what doesn't, then run the interview only for gaps.

## Operating mode

- **One section at a time.** Don't ask all questions in a wall of text. Walk the user through Problem → Goals → Stories → Requirements, asking a small batch per section.
- **Open Questions are first-class.** It's fine — expected — for the user to say "I don't know yet." Capture the gap in the Open Questions section explicitly; don't invent an answer.
- **Treat the PRD as living.** First pass aims for ~70% confidence on Problem/Goals/Stories. Other sections can be sparse on v1.
- **Use AskUserQuestion liberally** — give the user clear options when possible, and free-form where their thinking matters more than a multiple choice.

## Step-by-step

### 1. Pre-flight

- Read `docs/PRD/index.html` if it exists. If sections already have content, treat this as a refinement pass, not a fresh start.
- Read `CLAUDE.md` and `MILESTONES.md` to confirm we're in the Research phase.
- **If `$ARGUMENTS` is a path or URL to an existing PRD artifact:** run **Section 1a. Import mode** below before continuing. Otherwise, skip directly to Section 2.

### 1a. Import mode (only when `$ARGUMENTS` is a source path/URL)

When a legacy PRD exists, your job shifts from "interview from scratch" to "analyze + map + fill gaps". Run this flow once, then return to Section 2 for any remaining gaps.

**a. Read the source.** Pick the right tool for the format:

- `.md` / `.markdown` / `.txt` / `.html` — Read tool directly
- `.pdf` — Read tool with `pages` parameter (max 20 per request; chunk if larger)
- Google Doc URL — `mcp__claude_ai_Google_Drive__download_file_content`
- Other formats — ask the user to convert first

**b. Parse and classify.** Split the source into sections (markdown headers, HTML `<section>`, etc.). Classify each section per the rubric in `WORKFLOW.md` → Importing existing artifacts → "Classification rubric — PRD content". Tag each section with one of:

- **Port directly** — content fits the framework as-is
- **Port with refinement** — fits but needs adjustment (e.g. quantify a qualitative goal)
- **Decompose** — too coarse; needs breaking down (e.g. mega-feature → multiple user stories)
- **Relocate** — belongs in ARCH, MILESTONES.md, or Linear instead of PRD
- **Archive** — historical context; goes to Appendix or `docs/archive/`

**c. Surface the mapping for confirmation.** Show the user a table summarizing what you found and how you'd handle each section:

| Source section | Content type | Proposed action |
|---|---|---|
| §1 "Overview" | Problem statement | Port directly → PRD §1 |
| §3 "Features" | Feature list (high-level) | Decompose → 6 user stories |
| §5 "Implementation Approach" | Implementation detail | **Relocate** → ARCH |
| ... | ... | ... |

Ask: "Any overrides before I refactor?" Honor the user's preferences (e.g. they may want to keep something marked "relocate" in the PRD as a special case).

**d. Stash the original.** Move the source file to `docs/archive/<YYYY-MM-DD>__<original-filename>` (today's absolute date). If it's an external URL (e.g. Google Doc), download a snapshot to that path; don't try to "move" the live doc.

**e. Apply the ports.** Fill the relevant `<section>` blocks in `docs/PRD/index.html` with the classified+refined content. Add a reference at the bottom of PRD's Appendix: "Source documents: [docs/archive/...]"

**f. Queue the spillover.** For content marked "Relocate":
- → ARCH: queue as draft content for a later `/generate-archdoc` run (or feed directly if architect agent is active)
- → `DECISIONS.md`: queue as a Decision Log entry; or → `MILESTONES.md`: queue as a Milestone row
- → Linear: queue as backlog issues (PM agent can call `save_issue` via MCP)

Present each queued item to the user for one-shot batch confirmation before writing.

**g. Identify gaps.** Compare what got ported to what the framework needs:
- Are user stories in "As a X, I want Y so that Z" form? (List which need rephrasing.)
- Are goals measurable? (List unmeasured ones.)
- Is there a Non-Goals section? (Most legacy PRDs lack this — usually a gap.)
- Are stories small enough for one I→V loop (~1–3 days)? (Flag oversize for decomposition.)
- Are dates tied to milestones (OK) or features (suspect)?

Each gap becomes an interview question handled in Section 2 onward — **but skip any section the import already filled satisfactorily.**

### 2. Problem & Audience (always start here)

Ask:
- What user problem are we solving, in one sentence?
- Who feels this problem? (specific persona, not "users")
- How are they solving it today? Why is that inadequate?
- What's the business outcome if we solve it well?

Fill the **Overview / Problem Statement** section. If the answer is vague, push: "who *specifically* — a job title, a team, a behavior pattern?"

### 3. Goals & Success Metrics

Ask:
- What does success look like 30 days after launch? 90 days?
- What's a quantitative metric that would prove it?
- What's a counter-metric we'd watch to make sure we didn't break something else?
- What are we **not** trying to do? (Non-goals — critical for scope discipline.)

Fill **Goals & Success Metrics** and a `## Non-Goals` subsection.

### 4. User Stories

Walk through the primary persona's journey. For each meaningful step, capture a story in the form: `As a <persona>, I want to <action> so that <outcome>`.

Push for 3–8 stories. More than 8 and we're scoping a quarter, not a single milestone — break it down further with the user.

Fill **User Stories & Use Cases**.

### 5. Functional Requirements

For each user story, surface the "the system shall" statements. Keep them implementation-agnostic — *what* the system does, not *how*.

Fill **Functional Requirements**.

### 6. Non-Functional Requirements

Ask quick-fire:
- Performance: any latency targets? Scale targets?
- Availability: 99%? 99.9%? 99.99%? (Each nine is a different architecture.)
- Security: any regulatory regime (HIPAA, PCI, GDPR, SOC2)?
- Accessibility: WCAG level?
- Browser/device support?

Fill **Non-Functional Requirements**. Flag the SecEng consult here.

### 7. Design Considerations

If a UX designer is active, hand off to them via `SendMessage`. Otherwise leave the section as a stub with `_TBD — UX designer engagement pending_`.

### 8. Technical Considerations

Lightweight — what integrations or constraints do we already know about? (e.g. "must use the company's existing auth", "ships on Vercel"). Detail goes in ARCH during Plan.

Fill **Technical Considerations**.

### 9. Timeline & Milestones

If milestones aren't decided yet, fill with a placeholder and note "to be finalized in Plan phase with architect."

### 10. Open Questions & Risks

Re-read everything you wrote. List every unresolved question and every assumption that could be wrong. This is the most important section — the team-lead uses it to drive the next conversation.

### 11. Appendix

Stub: "Research notes, competitive analysis, links."

## Writing to HTML

Update `docs/PRD/index.html` in place. Preserve the `<head>`, the `_assets/doc.css` link, and the Mermaid loader. Only edit the section bodies. Each section is a `<section data-section="<name>">` block.

If the user gives you raw Mermaid (e.g. for a user flow), wrap it as:
```html
<pre class="mermaid">
flowchart TD
  ...
</pre>
```

## When you finish

1. Show the user a summary of what's filled vs. still stubbed.
2. Open the doc with `/open-doc docs/PRD/index.html` so they can review.
3. Ask: "Approve PRD v1 to move to Plan phase?" If yes, add an entry to [`DECISIONS.md`](../../../DECISIONS.md) and update `MILESTONES.md` → `## Current Phase` to "Plan".
