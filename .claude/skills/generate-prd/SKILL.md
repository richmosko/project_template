---
name: generate-prd
description: Interview-driven generation of `docs/PRD.html`. Use during the Research phase, or whenever the user asks to "write the PRD", "generate the product spec", or "interview me about the product". Follows the chatprd.ai lightweight PRD template — Problem, Goals/Metrics, User Stories, Functional/Non-Functional Requirements, Design Considerations, Technical Considerations, Timeline, Open Questions, Appendix.
---

# generate-prd

You are running an interview to populate `docs/PRD.html`. This is the Research-phase driver activity. The `product-manager` teammate should run this skill (or the team-lead if no PM is active).

## Operating mode

- **One section at a time.** Don't ask all questions in a wall of text. Walk the user through Problem → Goals → Stories → Requirements, asking a small batch per section.
- **Open Questions are first-class.** It's fine — expected — for the user to say "I don't know yet." Capture the gap in the Open Questions section explicitly; don't invent an answer.
- **Treat the PRD as living.** First pass aims for ~70% confidence on Problem/Goals/Stories. Other sections can be sparse on v1.
- **Use AskUserQuestion liberally** — give the user clear options when possible, and free-form where their thinking matters more than a multiple choice.

## Step-by-step

### 1. Pre-flight

- Read `docs/PRD.html` if it exists. If sections already have content, treat this as a refinement pass, not a fresh start.
- Read `CLAUDE.md` and `MILESTONES.md` to confirm we're in the Research phase.

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

Fill **Non-Functional Requirements**. Flag the SecOps consult here.

### 7. Design Considerations

If a UX designer is active, hand off to them via `SendMessage`. Otherwise leave the section as a stub with `_TBD — UX designer engagement pending_`.

### 8. Technical Considerations

Lightweight — what integrations or constraints do we already know about? (e.g. "must use the company's existing auth", "ships on Vercel"). Detail goes in ARCH.html during Plan.

Fill **Technical Considerations**.

### 9. Timeline & Milestones

If milestones aren't decided yet, fill with a placeholder and note "to be finalized in Plan phase with architect."

### 10. Open Questions & Risks

Re-read everything you wrote. List every unresolved question and every assumption that could be wrong. This is the most important section — the team-lead uses it to drive the next conversation.

### 11. Appendix

Stub: "Research notes, competitive analysis, links."

## Writing to HTML

Update `docs/PRD.html` in place. Preserve the `<head>`, the `_assets/doc.css` link, and the Mermaid loader. Only edit the section bodies. Each section is a `<section data-section="<name>">` block.

If the user gives you raw Mermaid (e.g. for a user flow), wrap it as:
```html
<pre class="mermaid">
flowchart TD
  ...
</pre>
```

## When you finish

1. Show the user a summary of what's filled vs. still stubbed.
2. Open the doc with `/open-doc docs/PRD.html` so they can review.
3. Ask: "Approve PRD v1 to move to Plan phase?" If yes, add an entry to `MILESTONES.md` → Decision Log and update `## Current Phase` to "Plan".
