---
name: generate-secdoc
description: Generates or refines `docs/SECURITY/index.html` — the Security Requirements document. Use during the Plan phase (after ARCH v1 exists) or whenever the user asks for the security doc, threat model, or compliance mapping. Driven by the `seceng` agent. Produces a STRIDE-based threat model, trust-boundary map, controls catalog, compliance mapping, and incident-response runbook.
---

# generate-secdoc

You are populating `docs/SECURITY/index.html`. This is owned by the `seceng` agent and produced jointly with the `architect`.

## Pre-flight

- Read `docs/PRD/index.html` (especially the Non-Functional Requirements → regulatory regime).
- Read `docs/ARCH` — the threat model is structured around its components and trust boundaries. Do **not** start this skill before ARCH v1 exists.
- Read `CLAUDE.md` and `MILESTONES.md` to confirm Plan phase.

## Sections

### 1. Compliance Posture

A short table:

| Regime | In scope? | Why |
|---|---|---|
| HIPAA | _yes/no_ | _e.g. we handle PHI in patient records_ |
| PCI-DSS | _no_ | _no card data; payments via Stripe Elements_ |
| GDPR | _yes_ | _EU users in scope_ |
| SOC 2 | _planned for Q4_ | _enterprise sales requirement_ |

The PRD's Non-Functional Requirements section is the source. Push the user if they're vague.

### 2. Trust Boundaries

Refer to ARCH components. List each boundary explicitly:

| From | To | Boundary type | Notes |
|---|---|---|---|
| Public internet | Edge / CDN | Network | TLS termination here |
| Edge | API service | Network + Auth | JWT validation |
| API service | Database | Network + IAM | Service account, least privilege |

Embed a Mermaid `flowchart` showing the boundaries visually.

### 3. Threat Model (STRIDE)

For each component in ARCH, walk through STRIDE:

- **S**poofing — can the attacker pretend to be someone else?
- **T**ampering — can they modify data in transit or at rest?
- **R**epudiation — can they deny doing something they did?
- **I**nformation disclosure — can they read what they shouldn't?
- **D**enial of service — can they make us unavailable?
- **E**levation of privilege — can they gain more access than authorized?

One table per component:

| Threat | STRIDE | Likelihood | Impact | Control(s) |
|---|---|---|---|---|
| Stolen JWT replayed | S | medium | high | short TTL + refresh rotation + revocation list |

Don't try to be exhaustive — focus on threats with non-trivial likelihood × impact.

### 4. Authn / Authz Design

- How users authenticate (provider, MFA policy, session model).
- How services authenticate to each other.
- How authorization decisions are made (RBAC? ABAC? policy engine?). Where is the policy enforced (gateway? service? both)?

### 5. Data Classification & Handling

A table:

| Data type | Classification | At rest | In transit | Retention |
|---|---|---|---|---|
| PII (email, name) | Confidential | encrypted (KMS) | TLS 1.3 | 5y after account close |
| Session tokens | Restricted | hashed | TLS | TTL 1h |

### 6. Secret Management

- Where secrets live (vault product).
- How they're injected at runtime.
- Rotation policy and cadence.
- Who can read them (least privilege).
- Forbidden practices: secrets in env files in git, secrets in logs, secrets in error messages.

### 7. Controls Catalog

For each threat in section 3, the specific control(s) implemented. Each control has:
- Description ("schema-validate request body against zod schema X")
- Where it lives (file path or service)
- How it's tested (unit, integration, security-regression)
- Status (implemented / planned / not yet)

### 8. CI/CD Security

- Signed commits / signed tags.
- Dependency scanning (Renovate / Dependabot + audit).
- Container image scanning.
- SAST/DAST (if applicable).
- SBOM generation and storage.

### 9. Logging, Monitoring & Detection

- What we log (request ID, user ID, action, outcome — never raw secrets).
- Where logs go and retention.
- Alerts on anomalies (auth failure spikes, authz denials, unusual data egress).
- Audit log for sensitive operations.

### 10. Incident Response

- Who's on call.
- How an incident is declared (severity criteria).
- Containment, eradication, recovery steps.
- Post-incident: blameless postmortem within 5 business days; entry in [`DECISIONS.md`](../../../DECISIONS.md).

### 11. Open Risks (Accepted)

Risks we've decided to live with for now. Each entry:
- The risk
- Why it's acceptable (cost-benefit)
- Compensating controls
- Re-evaluation date
- Approved by (the user)

## Writing to HTML

Update `docs/SECURITY/index.html` in place. Each section is a `<section data-section="<name>">` block. Preserve head + assets links.

## When you finish

1. Run `/security-review` on the current branch as a baseline (it should find nothing yet — no code).
2. `SendMessage` to architect: "SECURITY v1 done; flag any new trust boundaries we should add to ARCH."
3. `/open-doc docs/SECURITY/index.html` for user review.
4. Once ARCH and SECURITY are both approved, the Plan→Implement gate is open. Log in `MILESTONES.md`.
