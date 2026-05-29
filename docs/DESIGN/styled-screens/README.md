# Styled Screens

High-fidelity screens that apply the design system to the wireframes.

- **Format:** self-contained HTML that links the design system:
  ```html
  <link rel="stylesheet" href="../tokens.css">
  <link rel="stylesheet" href="../screen.css">
  ```
  Use the token-backed component classes (`.btn`, `.input`, `.card`, …) — never hardcode values.
- **Naming:** `<screen>.html` (e.g. `dashboard.html`, `settings.html`).
- **Why HTML, not just images:** these double as a visual-regression reference and a head-start for `frontend-lead` during Implement — the markup + token usage is the contract.
- **Reference** them from `../index.html` § Styled Screens.
