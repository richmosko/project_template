---
name: generate-designdoc
description: Generates or refines `docs/DESIGN/index.html` — the Design System & UX document — plus its deliverables (`tokens.css`, `screen.css`, `design-system-spec.md`, flows, wireframes, styled-screens). Use from late Research (flows + wireframes, once user stories stabilize) through Plan/Implement (the design system matures as screens get built), or whenever the user asks for the design system, UX flows, wireframes, or tokens. Driven by the `ux-designer` agent. Interview-driven; pairs with Figma for high-fidelity work.
---

# generate-designdoc

You are populating `docs/DESIGN/` — the in-repo, code-level home for the design system and UX deliverables. Owned by the `ux-designer` agent. This is **cross-phase**: wireframes and flows start in late Research (after user stories stabilize); the design system (`tokens.css` / `screen.css`) matures through Plan and Implement.

Figma stays the high-fidelity design tool (via the `ux-designer`'s `figma:*` skills). `docs/DESIGN/` is the in-repo contract that ships with the project and that `frontend-lead` consumes directly — keep the two in sync (export tokens/specs here; pull frames via Code Connect there).

## Pre-flight

- Read `docs/PRD/index.html` — especially **User Stories** (flows follow the highest-traffic stories) and **Non-Functional Requirements → Accessibility**.
- Read `CLAUDE.md` + `MILESTONES.md` to confirm the phase. Late Research onward is fine; you don't need ARCH first (unlike `/generate-secdoc`).
- Read the current `docs/DESIGN/index.html`, `tokens.css`, `screen.css`, and `design-system-spec.md` — this skill **refines in place**, it doesn't overwrite hand edits.
- If the user passed an existing design artifact (Figma export, a style guide, a legacy CSS), treat it as import source: map it to the sections below and interview only for gaps (mirror the import behavior of `/generate-prd`).

## Interview, then write

Work section by section. Use `AskUserQuestion` for converged decisions (palette direction, type system, density); keep it conversational while still exploring. Don't invent a brand — surface options and let the user choose.

### Sections (match `docs/DESIGN/index.html`)

1. **Overview & Design Principles** (`#overview`) — what the product should feel like; 3–5 principles that resolve disputes (e.g. mobile-first, accessible by default, no decorative loading states).
2. **Design System** (`#design-system`) — orient the reader to the spec + the two CSS files; keep the Figma↔repo relationship explicit.
3. **Design Tokens** (`#tokens`) — write real values into `tokens.css`: color (semantic roles + contrast pairings), typography (families/scale/weights/leading), spacing scale, radius, shadow, motion, layout/breakpoints. The swatch preview in `index.html` reads these live.
4. **Components & Screen Styles** (`#components`) — the component inventory; for each, document **all states** (default/hover/focus-visible/active/disabled/loading/error) in `design-system-spec.md` and implement token-backed styles in `screen.css`. Never hardcode a value — reference a `--token`.
5. **User Flows** (`#flows`) — Mermaid `flowchart` for the top 3–8 PRD stories. First-pass inline in `index.html`; promote complex flows to files in `flows/`.
6. **Wireframes** (`#wireframes`) — low-fi layout per key screen; assets in `wireframes/`. Promote to Figma for anything shipping.
7. **Styled Screens** (`#styled-screens`) — hi-fi HTML mockups in `styled-screens/` that link `tokens.css` + `screen.css`. These double as a visual-regression reference and a head-start for `frontend-lead`.
8. **Accessibility** (`#accessibility`) — target standard (default WCAG AA) + deliberate exceptions with rationale. Mirror into `design-system-spec.md`.
9. **Open Questions** (`#open-questions`) — unresolved design decisions; drives the next conversation.

## Writing to the files

- **`docs/DESIGN/index.html`** — update each `<section data-section="<name>">` in place. Preserve the `<head>` + `_assets` links and the `tokens.css` link.
- **`tokens.css` / `screen.css`** — write real, token-referencing CSS. Keep `screen.css` built strictly on `tokens.css`.
- **`design-system-spec.md`** — the written *why* + per-component state tables + usage rules + accessibility policy.
- Keep section `id`s unchanged so the `comments.md` / `/refine-doc DESIGN` review loop keeps working.

## When you finish

1. Update the PRD's **Design Considerations** (`#design`) section with a link to `docs/DESIGN/` and a one-line rationale for each major interaction choice — `SendMessage` the `product-manager` if they own that edit.
2. `SendMessage` to `frontend-lead`: "Design system v1 in `docs/DESIGN/` — `tokens.css` + `screen.css` are the contract; flag anything missing for the screens you're about to build."
3. `/open-doc docs/DESIGN/index.html` for user review (or `/serve-docs DESIGN` to review with the inline comment widget, then `/refine-doc DESIGN`).
4. Promote shipping wireframes/screens to Figma via the `figma:*` skills; keep the exported stills + token specs in `docs/DESIGN/` as the in-repo record.
