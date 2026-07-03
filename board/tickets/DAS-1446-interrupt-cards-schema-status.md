---
id: DAS-1446
title: Interrupt-cards schema + interrupted status enum (P3)
status: todo
assignee: security-lead
author: ceo
dept: engineering
priority: p1
parent: DAS-1440
goal: organism-ws1-pulse
depends_on: [DAS-1442]
zone: scripts/board_lint
created: 2026-07-03
updated: 2026-07-03
---

## Description

**AADL stage: GATE-2 Design.** This is a **design + schema** ticket in the ORGANISM
"Pulse" workstream (WS1). It defines how a running agent can *pause itself* and ask
the Founder a question mid-flight — an **interrupt card** — and adds a new ticket
status, `interrupted`, so a ticket can legally sit in a "waiting on a human answer"
state without being mistaken for `blocked` (external dependency) or `in_review`.

**What & why.** Today an agent that hits an ambiguous decision has only two poor
options: guess, or mark the ticket `blocked` (which the board treats as an
external-dependency stall that is never auto-dispatched). Neither captures "I need
a quick human choice to keep going." The **interrupt card** is a small JSON object
that carries a question + the answer options to the Founder; the Founder answers by
writing `resume:<value>`, and the ticket flows back into the wave. This ticket
produces the **schema + enum + transition rules + a clean consumer sweep** so that a
later implementation ticket (DAS-1447) can wire the runtime behavior on top of a
board that already accepts the new status.

**Extend-vs-new posture.** EXTEND the existing board machinery; do not fork it.
- `interrupted` is added to the SAME `VALID_STATUSES` frozenset that already holds
  `backlog | todo | in_progress | blocked | in_review | done` — one enum, one source
  of truth mirrored in `board/README.md`.
- Interrupt cards get their OWN directory `board/interrupts/` (new), parallel to
  `board/tickets/`, so they never pollute the ticket glob (`board_lint` only reads
  `DAS-*.md`) and are trivially removable.
- Do NOT invent a parallel status system, a new lint script, or a second enum copy.

**Interrupt-card object (to be documented + specified here).**
Path: `board/interrupts/<id>.json` (one file per open question), shape:
```json
{
  "question": "free-text prompt shown to the Founder",
  "options": ["option-a", "option-b", "..."],
  "ticket": "DAS-####",
  "payload": { "arbitrary": "agent context needed to resume" },
  "created_by": "<role-key>"
}
```
The Founder answers by writing `resume:<value>` (where `<value>` is one of `options`)
— the exact write target/mechanism is specified by DAS-1447 (consumer), but the
answer contract (`resume:<value>`) is fixed HERE.

**Legal status transitions (recommended, to be documented as the design of record):**
- `in_progress` → `interrupted` — agent raises an interrupt card and yields.
- `interrupted` → `in_progress` — Founder supplies `resume:<value>`; the ticket
  re-enters the wave with the answer available to the agent.
- `interrupted` → `blocked` — the question is abandoned / cannot be answered; the
  ticket falls back to the normal blocked path (requires a log reason, per board rules).

**Key existing files this ticket touches (with paths):**
- `scripts/board_lint.py` — line ~46-48 `VALID_STATUSES` frozenset (add `interrupted`);
  R8 `in_review == author` check at lines ~181-186 (verify it does not touch, reject,
  or strand an `interrupted` ticket — R8 keys off `status == "in_review"`, so an
  `interrupted` ticket is out of its scope; confirm and record this).
- `board/README.md` — **line 27**, the status enum comment
  `# backlog | todo | in_progress | blocked | in_review | done` (add `interrupted`),
  plus the Rules section (~line 73+) if a transition note is warranted.
- `board/ROUTING.md` — the `in_review` reviewer-routing logic (verify `interrupted`
  does not get mis-routed to a reviewer; `interrupted` has no reviewer semantics).
- `/daslab-cycle` triage (the cycle skill / orchestrator) — verify triage neither
  auto-dispatches an `interrupted` ticket as actionable work nor strands it; an
  `interrupted` ticket is NOT actionable until it becomes `in_progress` again via
  `resume:<value>`. Document the intended triage handling.

**Consumer sweep (mandatory).** Enumerate every place that reads ticket `status` and
state, for each, exactly how it treats `interrupted`:
1. `board_lint.py` R2 status-enum check — now accepts `interrupted` (the add).
2. `board_lint.py` R8 in_review self-review check — untouched (scoped to `in_review`).
3. `/daslab-cycle` triage / actionability — `interrupted` is non-actionable (parked),
   not dispatched, not treated as `blocked`.
4. `board/ROUTING.md` in_review routing — `interrupted` is not routed to a reviewer.
No consumer may reject a validly-formed `interrupted` ticket or silently drop it.

**Spec-of-record:** `docs/research/ORGANISM-PROGRAM-PLAN.md`.
**Constraint:** this is org-engine (platform) work — the frontmatter carries NO
`project:` field (board_lint R9). **Produces:** `interrupt-schema` (consumed by DAS-1447).

## Acceptance criteria

- [ ] Interrupt-card JSON schema is documented (fields `question`, `options`,
      `ticket`, `payload`, `created_by`; path `board/interrupts/<id>.json`; the
      `resume:<value>` answer contract stated).
- [ ] `interrupted` is added to `scripts/board_lint.py` `VALID_STATUSES`.
- [ ] `interrupted` is added to the status enum on `board/README.md` **line 27**
      (and any other enum echo in that file kept in sync).
- [ ] Legal transitions are documented: `in_progress`→`interrupted`;
      `interrupted`→`in_progress` (via `resume:<value>`); `interrupted`→`blocked`
      (abandoned).
- [ ] Consumer sweep is complete and written down — each consumer listed with how it
      handles `interrupted`: (1) board_lint R2, (2) board_lint R8, (3) /daslab-cycle
      triage, (4) ROUTING in_review logic — none rejects or strands an `interrupted`
      ticket.
- [ ] `board_lint` accepts a well-formed `interrupted` ticket (a sample/fixture
      ticket with `status: interrupted` lints clean, exit 0).
- [ ] Tests cover the new status: a positive case (`interrupted` accepted) and a
      negative case (an unknown/invalid status still rejected) pass.

## Log
### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
