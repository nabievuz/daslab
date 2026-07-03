---
id: DAS-1451
title: Kill-drill in check_recovery + fork-drill (T5 gate)
status: todo
assignee: qa-lead
author: ceo
dept: engineering
priority: p1
parent: DAS-1440
goal: organism-ws1-pulse
depends_on: [DAS-1444, DAS-1445]
zone: scripts/recovery
created: 2026-07-03
updated: 2026-07-03
---

## Description

**AADL stage: GATE-4 Testing.**

The ORGANISM program needs the T5 recovery-reliability gate to be scored by a
**real** kill/resume drill, not just by passively replaying whatever routing
transitions already happen to be in the event store. Today `scripts/check_recovery.py`
computes T5 = `successful_replays / recovery_drills` (target ≥ 0.99, guardrail:
zero corrupted resumes) and is **inert** (exit 0) until `recovery_drill` events
exist. `scripts/replay_qa.py` can emit those events, but only from pre-existing
`routing_decision` chains — nothing exercises a genuine mid-wave crash and
`--resume`. This ticket makes the gate meaningful by driving actual kill and
fork drills that produce the `recovery_drill` events the existing gate scores.

**What & why.** Add a real drill harness that (a) starts a synthetic 3-wave run,
(b) `kill -9`s it mid-wave-2, (c) resumes via `--resume`, and (d) asserts the
resumed run lost **zero** tickets and duplicated **zero** tickets. Then add a
**fork-drill**: fork from a wave-1 checkpoint, run it forward to a divergent
outcome, and confirm the original run is left intact. Both drills emit
`recovery_drill` events so the existing T5 computation in
`metrics_lib.recovery_reliability()` (and thus `check_recovery.py`) scores them.
This turns T5 from a shipped-but-inert lever into a gate backed by live evidence,
per the ORGANISM WS1 pulse plan.

**Extend-vs-new posture: EXTEND, do not replace.**
- Keep `metrics_lib.recovery_reliability()` and `check_recovery.py`'s scoring/exit
  contract exactly as-is — they already read `recovery_drill` events, honor the
  zero-corrupted guardrail, and stay inert when unmeasured. Do not fork the T5
  math.
- Reuse the `recovery_drill` event shape emitted by `replay_qa.py`
  (`event_type: "recovery_drill"`, `outcome: "success"|"fail"`, `corrupted: bool`,
  plus `run_id`, `ticket_id`, `created_at`). New drills MUST emit this same shape
  (via `replay_qa --emit` or an equivalent writer) so no gate change is needed to
  score them.
- Add the drill driver as a new, self-contained module/entrypoint under the
  `scripts/recovery` zone. Wiring it *through* `check_recovery.py` (e.g. a
  `--drill`/`--run-drills` flag that generates events then scores) is acceptable
  as long as the default no-arg behavior of `check_recovery.py` is unchanged.

**Key existing files this touches (paths):**
- `scripts/check_recovery.py` — the T5 gate CLI. Currently: reads
  `board/.events.jsonl`, calls `metrics_lib.recovery_reliability(...)`, prints
  inert message + exit 0 when `None`, else OK/FAIL on `ratio >= target and
  corrupted == 0`. Extend to drive/consume the new drills without breaking the
  existing default path.
- `scripts/replay_qa.py` — recovery-drill harness. `drill()` groups
  `routing_decision` events by `run_id`/`ticket_id`, `replay_run()` detects a
  broken transition chain (corrupted resume), and `--emit` appends
  `recovery_drill` events. `VALID_STATUSES = {backlog, todo, in_progress,
  blocked, in_review, done}`. Reuse `--emit` as the event writer.
- `scripts/metrics_lib.py` — `recovery_reliability(events)` (lines ~181-192):
  filters `event_type == "recovery_drill"`, counts `corrupted`, counts `ok`
  (`outcome == "success"` AND not `corrupted`), returns
  `{ratio, successful, drills, corrupted}` or `None`. Do NOT change this shape.
- Event store: `board/.events.jsonl` (default `--events`); drill events should be
  emittable into a throwaway store for CI and/or the live store for scheduled runs.
- CI/drills wiring: add the cheap drill to the existing CI workflow and the
  expensive (≥20-iteration) drill to a scheduled workflow under `.github/`.

**Cost tiering.** The kill/resume drill and the ≥20-iteration T5 accumulation are
expensive; the fast smoke variant is cheap. Put the **cheap** smoke drill into CI
(runs on every PR) and the **expensive** ≥20-iteration + fork drill into a
**scheduled** workflow, so PR latency stays low while T5 still accrues real data.

## Acceptance criteria

- [ ] **Kill-mid-wave-2 drill exists and passes:** a new drill starts a synthetic
      3-wave run, `kill -9`s it during wave 2, `--resume`s it, and asserts **zero
      lost tickets** and **zero duplicated tickets** across the resume boundary.
- [ ] **T5 ≥ 0.99 over ≥ 20 iterations:** running the drill ≥ 20 times emits ≥ 20
      `recovery_drill` events such that `check_recovery.py` reports T5 `ratio ≥
      0.99` with `corrupted == 0` (gate exit 0).
- [ ] **Fork-drill:** forking from a wave-1 checkpoint produces a divergent run
      whose outcome differs from the original, while the original run remains
      intact (unmodified checkpoint/state, still independently replayable).
- [ ] **Events emitted + scored:** both drills emit `recovery_drill` events in the
      shape consumed by `metrics_lib.recovery_reliability()` (via `replay_qa
      --emit` or equivalent), and `check_recovery.py` scores them (a corrupted
      resume yields `corrupted > 0` → FAIL exit 1, honoring the guardrail).
- [ ] **CI/scheduled wiring:** the cheap smoke drill runs in CI on every PR; the
      expensive ≥20-iteration + fork drill runs on a scheduled workflow. Both are
      green.
- [ ] `check_recovery.py`'s existing default (no-arg) behavior and its scoring/exit
      contract are unchanged; `metrics_lib.recovery_reliability()` return shape is
      unchanged.
- [ ] Consumes the outputs of DAS-1444 (wave-checkpoints) and DAS-1445
      (resume-fork); no re-implementation of checkpointing or fork mechanics here.

## Log

### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
