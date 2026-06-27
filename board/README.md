# DasLab Board — file-based ticket store

> A file-based ticket store. One markdown file in
> `tickets/` = one ticket. The orchestrator (`/daslab-cycle`) and role subagents
> read and edit these files directly — there is no API.

## Scope — platform tickets only

`board/tickets/` is reserved **exclusively for DasLab-platform (org-engine)
tickets**: work on the engine, generators, validators, skills, agent overlays,
policies, and governance themselves. A **project's** tickets (any product /
client / app / website / agent / SaaS / campaign work) live ONLY in that
project's own board, `projects/<slug>/board-tickets/` — each project keeps its
tickets on its own board — and are dispatched in the project's own context, never
from the org `board/tickets/` (QONUN — Project Placement Law). Consequently a
`board/tickets/` ticket **must not** declare a `project:` field;
`scripts/board_lint.py` fails any that does.

## Ticket file

Name: `tickets/DAS-<n>-<slug>.md` (n strictly increasing; next id = max existing + 1).

```markdown
---
id: DAS-1001
title: Short imperative title
status: todo            # backlog | todo | in_progress | blocked | in_review | done
assignee: backend-eng-1 # role key = .claude/agents/<key>.md; empty = needs routing
author: senior-pm       # role that created it (never reviews its own work)
dept: engineering
priority: p1            # p0 | p1 | p2
parent: DAS-1000        # epic id, or empty
goal: ship-v1
created: 2026-06-10
updated: 2026-06-10
---

## Description
What and why. Enough context to work without asking.

## Acceptance criteria
- [ ] verifiable outcome 1
- [ ] verifiable outcome 2

## Log
### 2026-06-10 — Senior PM
Created from goal decomposition (/daslab-plan).
```

## Optional governance fields (risk taxonomy / never-auto-approve)

These OPTIONAL frontmatter fields let `scripts/check_never_auto_approve.py`
classify a ticket against `config/risk_taxonomy.yaml` (QONUN-5). They are additive
— tickets without them lint exactly as before. Editing them is governance-relevant.

| Field | Example | Meaning |
|---|---|---|
| `approval` | `auto` / `review:cxo` / `human:founder` | how the change was approved; `auto*` = auto-approved |
| `ticket_type` | `goal` / `epic-root` / `feature` | gates `new_goal` (only the Founder authorizes new goals) |
| `stage` | `GATE-5` | AADL stage; gates `gate5_deployment` |
| `labels` | `[security, migration]` | category labels (security/auth/secrets, migration/schema, …) |
| `paths` | `["src/auth/login.py"]` | declared changed paths, matched against never-auto-approve path globs |
| `project` | `acme-app` | **FORBIDDEN in `board/tickets/`** — this folder is platform-only (see Scope); `scripts/board_lint.py` fails any org-board ticket that declares it. The field belongs on tickets in a **project's own board** (`projects/<slug>/board-tickets/`), binding them to `projects/<slug>/`; there a past-backlog project ticket requires a Founder-approved `projects/<slug>/APPROVED-GOAL-QUEUE.md` (QONUN-3, enforced at `/daslab-plan` time). |
| `spec` / `implements` | `001-onboarding` / `[FR-001, SC-002]` | bind a child ticket to its per-epic `SPEC.md` and the `FR-NNN`/`SC-NNN` it implements; `scripts/check_spec_consistency.py` rejects dangling refs (ADR-0015). Optional, size-gated. |
| `depends_on` | `[DAS-1376]` | ticket ids that must be `done` before this is actionable; `scripts/check_dependency_graph.py` enforces acyclic + no-dangling (ADR-0016). |
| `zone` | `apps/web` | the repo area this ticket mutates; two same-`zone` tickets must not run in one wave — the `/daslab-cycle` correctness guard reads this instead of inferring (ADR-0016). |

A ticket in a never-auto-approve category (`new_goal`, `security_sensitive`,
`schema_migration`, `gate5_deployment`, `governance_or_policy`, `permission_change`,
`secret_change`) MUST NOT carry `approval: auto*` — CI fails (QONUN-5), regardless
of how any risk classifier scored it.

## Rules (lifted from AGENTS.md §6, adapted)

- **WIP = 1**: a subagent works only the ticket named in its prompt.
- Every state change appends a `## Log` entry — who, what, why. Never a silent edit.
- `status: in_review` requires `assignee` switched to the reviewer from
  [`ROUTING.md`](ROUTING.md) (author's manager; never the author).
- `done` for engineering tickets = merged PR with green CI, per the git rules in
  `engineering/AGENTS.md` §2 (one issue = one branch = one PR, worktree per issue,
  never commit to `main`).
- `blocked` requires a precise reason in the log; external-dependency blocks
  (RAHMAT / UZINFOCOM / tax / legal entity) are never auto-dispatched.
- Subtasks carry `parent:` + `goal:` — no orphan tickets.
- For new projects, tickets may be created only from
  `projects/<project>/APPROVED-GOAL-QUEUE.md` items that have explicit Founder
  approval (`status: founder_approved` or later). No approved queue, no tickets.
  Those project tickets are written to the **project's own board**
  (`projects/<project>/board-tickets/`), not here — `board/tickets/` only ever
  holds DasLab-platform (org-engine) tickets (see Scope).
- Ticket references in prose are written `DAS-12` and resolve to `tickets/DAS-12-*.md`.

## Concurrency

The board is plain files in one git repo. Only the orchestrator session mutates
routing fields (`assignee`, dispatch order); a role subagent edits only its own
ticket file plus the artifacts of its work. There is no checkout/lock API; git and worktree isolation prevent conflicts.
