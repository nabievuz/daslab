# DasLab — Agent Roster & Org Structure

> **Audience: AI agents and operators.** This document is the authoritative, human- and machine-readable description of the DasLab agent organization — how many agents exist, each agent's job, how they are structured (reporting lines, model), and what each is accountable for.
>
> **Source of truth.** This roster mirrors three SSOT artifacts; if they disagree, *they* win and this file is stale:
> 1. [`governance/policies/model-allocation.md`](../governance/policies/model-allocation.md) — the canonical `role → model` table (binding board policy).
> 2. The role overlays (`<dept>/agents/<role>/AGENTS.md`) — each role's charter and accountability.
> 3. The generated subagent files [`.claude/agents/*.md`](../.claude/agents/) — written by [`scripts/gen_subagents.py`](../scripts/gen_subagents.py) from (1) + (2). The `model:` frontmatter in those files is authoritative for dispatch.

---

## 1. Summary

| Property | Value |
|---|---|
| Organization | **DasLab** (Dasturlash Laboratoriyasi) · ticket prefix `DAS` |
| Runtime | Claude Code subagent sessions over a file-based board (`board/tickets/DAS-*.md`); operator-invoked waves, no HTTP API |
| **Core agents** | **32** (4 levels: Board → CEO → Dept Manager → IC) |
| Active product | none currently |

### Model tiers (SSOT: [`model-allocation.md`](../governance/policies/model-allocation.md))

| Tier | Alias | Count | Who |
|---|---|---|---|
| Opus | `opus` (Opus 4.8) | 10 | 8 AADL gate-owners (CEO, Chairman, CPO, Senior PM, Backend EM, Frontend EM, QA Lead, SRE Lead) + CTO + Security Lead |
| Sonnet | `sonnet` (Sonnet 4.6) | 19 | Execution core — ICs, analysts, Design Lead, plus CDO / CMO / COO / Board Member (checklist-driven coordination) |
| Haiku | `haiku` (Haiku 4.5) | 3 | High-frequency, low-ambiguity, downstream-gated: SEO Specialist, Support Lead, Technical Writer |

Models are referenced by **alias** (`opus`/`sonnet`/`haiku`), not pinned ids, so they auto-track the newest model of each tier. The model follows **task complexity, not title**. Fable 5 / Tier F is decommissioned — `cto` and `security-lead` run on `opus` permanently with no restore path.

---

## 2. Org hierarchy

The 32 core agents form 4 levels: **Board → CEO → Dept Manager → IC.**

```
Chairman of the Board ── Board Member        (governance, opus / sonnet)
  │
  └── CEO                                     (whole company, opus)
        ├── CPO  (Product)
        │     ├── Senior Product Manager
        │     ├── Product Analyst
        │     └── Technical Writer
        ├── COO  (Operations)
        │     ├── Legal / Compliance Analyst
        │     ├── Finance / Billing Analyst        (role: cfo)
        │     └── Support Lead
        ├── CTO  (Engineering)
        │     ├── Backend EM
        │     │     ├── Backend Engineer 1
        │     │     └── Backend Engineer 2
        │     ├── Frontend EM
        │     │     ├── Frontend Engineer 1
        │     │     └── Frontend Engineer 2
        │     ├── Security Engineer
        │     ├── SRE / DevOps Lead
        │     │     └── SRE Engineer
        │     └── QA Lead
        │           └── QA Engineer
        ├── CMO  (Marketing)
        │     ├── SEO Specialist
        │     ├── Growth Marketer
        │     └── Content Lead
        └── CDO  (Design)
              └── Design Lead
                    ├── UX Researcher
                    └── Product Designer
```

---

## 3. Governance layer (Board)

| Agent | Role | Model | Accountable for |
|---|---|---|---|
| **Chairman of the Board** | `chairman` | opus | Final approval authority; charter/governance rulings, new-hire & strategic sign-off; arbitrates org-wide. Top of chain. |
| **Board Member** | `board-member` | sonnet | Charter-guided governance review and votes; second board voice on hires, budget changes, CEO strategy. |

Board agents are not wave-dispatched on a cadence — they are engaged when a governance decision (hire, budget change, CEO strategy, cross-org conflict) is routed to them per [`board/ROUTING.md`](../board/ROUTING.md). The Chairman stays on `opus` for binding rulings; the Board Member runs on `sonnet` (charter-guided votes are checklist-driven).

---

## 4. C-suite (reports to CEO unless noted)

| Agent | Role | Reports to | Model | Department & accountability |
|---|---|---|---|---|
| **CEO** | `ceo` | Chairman | opus | Whole company. Strategy, goal decomposition, Board liaison, arbitrates C-suite conflicts, owns the active goal. |
| **CTO** | `cto` | CEO | opus | Engineering. Architecture/ADR sign-off, AADL GATE-2/3 accountable, **security gate enforcement**, all technical choices (opus permanent). |
| **CPO** | `cpo` | CEO | opus | Product. GATE-1 accountable — roadmap, product scope, KPI definitions, discovery. |
| **CMO** | `cmo` | CEO | sonnet | Marketing. Launch sign-off, brand voice, campaign approval (checklist-driven coordination). |
| **CDO** | `cdo` | CEO | sonnet | Design. Design-system stewardship, brand consistency (checklist-driven coordination). |
| **COO** | `coo` | CEO | sonnet | Operations. GATE-6 accountable — compliance gates, finance review, support SLA (checklist-driven cadence). |

C-suite decomposes goals → epics → tickets, routes work (RACI §6 below), enforces quality gates, and escalates governance-grade decisions to the Board. C-suite **never** does IC labor — they delegate. The model follows task complexity: CEO/CTO/CPO carry program-wide judgment (opus); CMO/CDO/COO run checklist-driven coordination (sonnet).

---

## 5. Engineering (CTO's org) — 10 core agents

| Agent | Role | Reports to | Model | Accountable for |
|---|---|---|---|---|
| **Backend EM** | `backend-em` | CTO | opus | Backend team delivery; decomposes backend tickets; code review, merge decisions, GATE-3 responsible. |
| Backend Engineer 1 | `backend-eng-1` | Backend EM | sonnet | Backend tickets: APIs, DB queries, server actions, jobs. |
| Backend Engineer 2 | `backend-eng-2` | Backend EM | sonnet | Backend tickets (parallel capacity). |
| **Frontend EM** | `frontend-em` | CTO | opus | Frontend team delivery; decomposes UI tickets; code review, merge decisions, GATE-3 responsible. |
| Frontend Engineer 1 | `frontend-eng-1` | Frontend EM | sonnet | UI/React/Next pages, forms, components, i18n. |
| Frontend Engineer 2 | `frontend-eng-2` | Frontend EM | sonnet | UI tickets (parallel capacity). |
| **Security Engineer** | `security-eng` | CTO | sonnet | Red-team execution, scans; the opus control is the Security Lead review gate, not the IC tier. |
| **SRE / DevOps Lead** | `sre-lead` | CTO | opus | GATE-5 accountable — production launch, deploy, CI, observability, VPS/Dokploy, on-call sign-off. |
| SRE Engineer | `sre-eng` | SRE/DevOps Lead | sonnet | Infra tickets, runbooks, deploy automation, monitoring wiring. |
| **QA Lead** | `qa-lead` | CTO | opus | GATE-4 accountable — QA bar owner, eval thresholds, release-blocking judgment; reviews-and-closes in-review work. |
| QA Engineer | `qa-eng` | QA Lead | sonnet | Test suites: unit, integration, E2E (Playwright); eval runs. |

Security Lead (`security-lead`, opus) — the OWASP/guardrails sign-off owner (GATE-2/4/5) — is enumerated with the gate owners; the IC Security Engineer above executes under that opus review gate.

---

## 6. Product (CPO's org) — 3 core agents

| Agent | Role | Reports to | Model | Accountable for |
|---|---|---|---|---|
| **Senior Product Manager** | `senior-pm` | CPO | opus | GATE-1 responsible — PRD authoring, ticket decomposition, acceptance criteria, sprint shaping (ambiguity here multiplies downstream). |
| **Product Analyst** | `product-analyst` | CPO | sonnet | GATE-6 responsible — metrics, KPI/goal-drift reports, analytics definitions, data-driven product insight. |
| **Technical Writer** | `tech-writer` | CPO | haiku | Documentation, changelogs, doc-sync, API docs, runbooks — mechanical, high-frequency; wrong output caught by the reviewing manager's gate (W3 re-tier, ADR 0007). |

---

## 7. Operations (COO's org) — 3 agents

| Agent | Role | Reports to | Model | Accountable for |
|---|---|---|---|---|
| **Legal / Compliance Analyst** | `legal-analyst` | COO | sonnet | TOS, privacy, GDPR/PD-operator, UZINFOCOM, contracts; **blocking review** on privacy/legal changes; escalates novel calls via ticket. |
| **Finance / Billing Analyst** | `finance-analyst` | COO | sonnet | Pricing, invoices, forecasts, token/infra budget checks, burn reports, IKPU/tax matters. |
| **Support Lead** | `support-lead` | COO | haiku | Support flows, ticket triage, SLA tracking, templated responses (high-frequency, low-ambiguity). |

---

## 8. Marketing (CMO's org) — 3 agents

| Agent | Role | Reports to | Model | Accountable for |
|---|---|---|---|---|
| **SEO Specialist** | `seo-specialist` | CMO | haiku | SEO, keywords, sitemap, meta/structured routine output (high-frequency, low-ambiguity). |
| **Growth Marketer** | `growth-marketer` | CMO | sonnet | Ads, funnels, activation, acquisition, growth experiments. |
| **Content Lead** | `content-lead` | CMO | sonnet | Blog, launch copy, brand voice — content drafting/editing (CMO signs off public copy). |

---

## 9. Design (CDO's org) — 3 agents

| Agent | Role | Reports to | Model | Accountable for |
|---|---|---|---|---|
| **Design Lead** | `design-lead` | CDO | sonnet | Design system, wireframes, mockups, tokens, **design-spec review** for UI-without-design. |
| UX Researcher | `ux-researcher` | Design Lead | sonnet | User testing, personas, interviews, UX test synthesis. |
| Product Designer | `product-designer` | Design Lead | sonnet | Product mockups, component design, design tokens. |

---

## 10. How they are structured & operate

**Runtime lifecycle.** DasLab dispatches role subagents from an operator-invoked
`/daslab-cycle` wave. Each subagent works one selected ticket, updates the ticket
log/status, reports back, and exits. There is no autonomous driver, timer chain,
or night loop in the active runtime.

**Orchestration.** Work is driven by operator-invoked waves, not a timer: `/daslab-plan` decomposes a goal into board tickets (goal → epic → ticket); `/daslab-cycle` runs one wave (dispatch every actionable role subagent in parallel); `/daslab-run` drains the Founder-approved goal queue. Dispatch passes `model` explicitly on every Agent call (the role's `model:` frontmatter) — frontmatter alone is not trusted at runtime ([claude-code#44385](https://github.com/anthropics/claude-code/issues/44385)).

**Delegation / RACI (task → role).** Backend/DB → Backend EM→Engineer; UI → Frontend EM→Engineer; tests → QA Lead→Engineer; deploy/CI → SRE Lead→Engineer; auth/security → Security Engineer (reports to CTO); roadmap/PRD → CPO→Senior PM; analytics → Product Analyst; docs → Technical Writer; design → CDO→Design Lead→Designer; copy/SEO/ads → CMO→Content/SEO/Growth; finance/legal/support → COO→Finance/Legal/Support; hire/strategy → Chairman + Board.

**Quality gates (who must review).** Code → EM + QA Lead (in-review). Security-touching → Security Engineer execution under the Security Lead review gate (blocking). Schema/migration → Backend EM + SRE Lead (RFC/ADR). UI-without-design → Design Lead. Public copy → CMO. Privacy/legal → Legal Analyst (blocking). New hire / agent-config → Board. Strategy → Board (Chairman + Board Member).

**Governance gates.** Hiring, budget changes, CEO strategy, and cross-org conflicts escalate to the Board per [`board/ROUTING.md`](../board/ROUTING.md). An agent never upgrades its own model — too hard for your tier → log escalation and reassign to your manager.

**Correctness guard (binding).** No per-wave parallel cap and no opus wave-mix cap; the only dispatch bound is that two tickets touching the same repo area never run in one wave (parallel edits → merge conflicts → rework), plus the AADL gate order.

---

## 11. Quick reference — all 32 core agents

| # | Agent | Role | Reports to | Model |
|---|---|---|---|---|
| 1 | Chairman of the Board | `chairman` | — | opus |
| 2 | Board Member | `board-member` | — | sonnet |
| 3 | CEO | `ceo` | Chairman | opus |
| 4 | CTO | `cto` | CEO | opus |
| 5 | CPO | `cpo` | CEO | opus |
| 6 | CMO | `cmo` | CEO | sonnet |
| 7 | CDO | `cdo` | CEO | sonnet |
| 8 | COO | `coo` | CEO | sonnet |
| 9 | Backend EM | `backend-em` | CTO | opus |
| 10 | Backend Engineer 1 | `backend-eng-1` | Backend EM | sonnet |
| 11 | Backend Engineer 2 | `backend-eng-2` | Backend EM | sonnet |
| 12 | Frontend EM | `frontend-em` | CTO | opus |
| 13 | Frontend Engineer 1 | `frontend-eng-1` | Frontend EM | sonnet |
| 14 | Frontend Engineer 2 | `frontend-eng-2` | Frontend EM | sonnet |
| 15 | Security Engineer | `security-eng` | CTO | sonnet |
| 16 | Security Lead | `security-lead` | CTO | opus |
| 17 | SRE / DevOps Lead | `sre-lead` | CTO | opus |
| 18 | SRE Engineer | `sre-eng` | SRE/DevOps Lead | sonnet |
| 19 | QA Lead | `qa-lead` | CTO | opus |
| 20 | QA Engineer | `qa-eng` | QA Lead | sonnet |
| 21 | Senior Product Manager | `senior-pm` | CPO | opus |
| 22 | Product Analyst | `product-analyst` | CPO | sonnet |
| 23 | Technical Writer | `tech-writer` | CPO | haiku |
| 24 | Legal / Compliance Analyst | `legal-analyst` | COO | sonnet |
| 25 | Finance / Billing Analyst | `finance-analyst` | COO | sonnet |
| 26 | Support Lead | `support-lead` | COO | haiku |
| 27 | SEO Specialist | `seo-specialist` | CMO | haiku |
| 28 | Growth Marketer | `growth-marketer` | CMO | sonnet |
| 29 | Content Lead | `content-lead` | CMO | sonnet |
| 30 | Design Lead | `design-lead` | CDO | sonnet |
| 31 | UX Researcher | `ux-researcher` | Design Lead | sonnet |
| 32 | Product Designer | `product-designer` | Design Lead | sonnet |

**Tally:** opus ×10 · sonnet ×19 · haiku ×3 = 32 core agents.

> **Source of truth (re-derive, don't assume this snapshot is current):** the `role → model` rows in [`governance/policies/model-allocation.md`](../governance/policies/model-allocation.md), the role overlays (`<dept>/agents/<role>/AGENTS.md`), and the generated [`.claude/agents/*.md`](../.claude/agents/) (`model:` frontmatter, written by [`scripts/gen_subagents.py`](../scripts/gen_subagents.py)). If the policy table changes, re-run `python3 scripts/gen_subagents.py` and re-mirror this roster. Names/roles/reporting lines evolve.
