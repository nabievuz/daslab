---
id: DAS-1452
title: Wire run-model + dispatch emitter into daslab-cycle (preserve 4 guards)
status: todo
assignee: cto
author: ceo
dept: engineering
priority: p1
parent: DAS-1440
goal: organism-ws1-pulse
depends_on: [DAS-1444, DAS-1445, DAS-1455]
zone: daslab-cycle
created: 2026-07-03
updated: 2026-07-03
---

## Description

**What & why.** `/daslab-cycle` is the org's one-wave orchestrator (skill:
`.claude/skills/daslab-cycle/SKILL.md`). Today a wave selects, dispatches, and
reports, but it has no first-class notion of a **run** — there is no durable
`run_id`, no manifest of what a wave attempted, no checkpoint at wave
boundaries, and no lifecycle events a supervisor could observe. The ORGANISM
program (WS1 "pulse") introduces a run-model so the org can resume a crashed
wave, replay what happened, and expose run lifecycle to downstream consumers.
This ticket **wires that run-model into the real dispatch path** so that
invoking a wave actually creates a run, checkpoints at the natural boundaries,
and emits `run_start` / `run_end` / span events.

**AADL stage: GATE-5 Deployment — never auto-approve.** This ticket changes the
live dispatch wiring of the orchestrator that runs every other agent. A human
MUST review it before it lands (LAW / lifecycle: this is production wiring, not
a doc). Do not self-approve; route to the reviewer per `board/ROUTING.md`.

**Dependencies (what this ticket consumes).** This ticket is the *integration*
step — it does not build the primitives, it wires them in:
- **DAS-1444 — resume-fork / run-model** — supplies `run_id`, the run manifest,
  and the resume/fork API. This ticket calls it, does not define it.
- **DAS-1445 — wave-checkpoints** — supplies the checkpoint primitive written at
  wave boundaries. This ticket invokes it at step 0 (run open) and step 6/7
  (wave close).
- **DAS-1455 — dispatch-emitter** — supplies the `run_start` / `run_end` / span
  event emitter. This ticket calls the emitter from the cycle steps; it does NOT
  re-implement event plumbing. (Note the existing shadow `routing_decision`
  emission in step 5d via `scripts/dgox/events.py` is a SEPARATE, advisory-only
  channel — do not conflate the new run-lifecycle emitter with it, and do not
  disturb the `dgox_emit` feature gate.)

**Extend-vs-new posture: EXTEND, do not rewrite.** The cycle skill and its
guards are load-bearing and byte-sensitive (see cache-prefix note below). Add
the run-model wiring as **new steps/sub-steps** and new emitter calls at the
existing seams (step 0 = run open + first checkpoint; step 5 = per-dispatch
spans; step 6/7 = run close + final checkpoint). Do NOT restructure the existing
step numbering or reflow the selection logic. Every existing guard paragraph is
preserved verbatim.

**PRESERVE VERBATIM — the 4 selection guards.** These live in step 3 of
`.claude/skills/daslab-cycle/SKILL.md` and MUST survive this change unchanged
(same bytes, same meaning):
1. **Zone correctness guard** — "never two tickets touching the same repo area /
   file set in the same wave" via the `zone:` field (else `parent` + title
   overlap); the loser waits for the next wave.
2. **`depends_on` gate** — a ticket whose `depends_on:` names an id not yet
   `done` is NOT actionable → skipped, counted `dep-blocked`.
3. **AADL gate order** — a `Stage N` child is not actionable while the same
   project's `Stage N-1` epic is not `done` → skipped, counted gate-blocked.
4. **Clarify gate + circuit-breaker** — an unresolved `[NEEDS CLARIFICATION: …]`
   marker makes a ticket non-actionable (reassign to reviewer, never dispatch to
   a code subagent); if `clarify-blocked` ≥ half the actionable set, HALT the
   wave with a blocker report.

**PRESERVE VERBATIM — two more contracts:**
- The worktree path is a **pure function of the ticket id**:
  `.claude/worktrees/<TICKET-ID>/` (step 5b). The run-model must NOT inject
  `run_id`, timestamps, or any other component into the worktree path.
- The **"one operator invocation = one wave, no background timer"** contract
  (skill header + Boundaries). The run-model adds durable run state for
  resume/replay — it MUST NOT introduce a daemon, night driver, loop, or timer
  chain. A run is opened and closed within a single operator-invoked wave.

**Cache-prefix constraint (hard).** The stable-prefix region of
`.claude/skills/daslab-cycle/SKILL.md` is everything before the sentinel heading
`## Prompt-cache prefix layout (ADR 0006 — W4)` and is byte-checked by
`scripts/check_cache_prefix.py` (invariants a/b/c). Any edit that changes the
bytes of that region (i.e. any edit to steps 0–7 / system text / triage text)
will trip invariant (b) unless `CACHE_PREFIX_VERSION:` in the skill is bumped
(currently `v10-adr-renumber`, line ~424) AND the baseline is regenerated in the
SAME commit via `python3 scripts/check_cache_prefix.py --fix` (writes
`scripts/.cache_prefix_baseline`). Also respect invariant (a): do NOT place any
`run_id`, ISO timestamp, UUID, ticket-id, or `wave-N` counter literal inside the
stable-prefix region — those are volatile and belong only in the dynamic tail
(after the last `cache_control` breakpoint). The run-model wiring text must be
described generically in the prefix; concrete run ids/timestamps live at runtime
in the tail only.

**Key existing files this ticket touches:**
- `.claude/skills/daslab-cycle/SKILL.md` — the orchestrator skill; add run-open
  at step 0, span emission at step 5, run-close + final checkpoint at step 6/7;
  bump `CACHE_PREFIX_VERSION` if prefix bytes change.
- `scripts/check_cache_prefix.py` + `scripts/.cache_prefix_baseline` — the
  cache-prefix gate; re-baseline with `--fix` in the same commit if the prefix
  changed.
- Consumed APIs from DAS-1444 (run-model / resume-fork), DAS-1445
  (wave-checkpoints), DAS-1455 (dispatch-emitter) — call these; do not
  re-implement them here.

## Acceptance criteria

- [ ] Running a real (non-empty) `/daslab-cycle` wave creates a run (durable
      `run_id` + manifest via the DAS-1444 run-model), writes a checkpoint at the
      wave-open boundary and at the wave-close boundary (DAS-1445), and emits
      `run_start`, `run_end`, and per-dispatch span events (DAS-1455).
- [ ] All **4 selection guards** are preserved verbatim (zone correctness,
      `depends_on` gate, AADL gate order, clarify-gate + circuit-breaker) — the
      skill-token / guard tests pass unchanged.
- [ ] The worktree pure-id path `.claude/worktrees/<TICKET-ID>/` is intact — no
      `run_id`/timestamp/other component is injected into the worktree path.
- [ ] No background-timer / daemon / loop behavior is introduced — one operator
      invocation still equals exactly one wave; the run opens and closes within
      that single invocation.
- [ ] Cache-prefix baseline is handled: if the stable-prefix bytes changed,
      `CACHE_PREFIX_VERSION` is bumped AND `scripts/.cache_prefix_baseline` is
      regenerated via `python3 scripts/check_cache_prefix.py --fix` in the SAME
      commit; `python3 scripts/check_cache_prefix.py` exits 0.

## Log

### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
