---
id: DAS-1444
title: Wave-checkpoint writer + per-ticket pending-writes completion record (P1)
status: todo
assignee: backend-eng-1
author: ceo
dept: engineering
priority: p1
parent: DAS-1440
goal: organism-ws1-pulse
depends_on: [DAS-1443]
zone: scripts/pulse-checkpoint
created: 2026-07-03
updated: 2026-07-03
---

## Description

**AADL stage: GATE-3 Development.**

This ticket implements the **wave-checkpoint writer** for the ORGANISM Pulse
workstream (WS1). The goal is crash-safe wave execution: if the orchestrator
dies mid-wave, a resume must (a) restart from the last committed wave boundary
and (b) **never re-run a ticket that already finished** in the interrupted wave.

### Why (embedded context)

DasLab runs work in *waves* — each `/daslab-cycle` wave dispatches a batch of
actionable tickets in parallel, then the next wave begins. Today there is an
append-only event store (`board/.events.jsonl`, see `scripts/dgox/events.py`)
and a replay-QA harness (`scripts/replay_qa.py`) that verifies routing
transition chains, but there is **no durable wave-boundary checkpoint** and **no
per-ticket completion record**. Consequently a crash mid-wave loses the
knowledge of which tickets already completed, forcing re-runs (wasted model
spend, possible double-side-effects) and risking a corrupted resume.

This ticket adds two durable artifacts:

1. **Wave-boundary checkpoint** — at each wave boundary, write
   `board/runs/<run_id>/wave-NNN.checkpoint.json` capturing:
   - board snapshot hash (a stable hash over ticket file states),
   - event-store offset (byte offset / line count into `board/.events.jsonl`
     at the moment of the checkpoint),
   - per-ticket states (id → status at the boundary),
   - pending interrupts (any queued/unhandled interrupts at the boundary),
   - ledger hashes (hashes chaining prior checkpoints for tamper-evidence).
   Storage is **DELTA** per **ADR-0023** — each checkpoint after the first
   records only the change from the previous checkpoint, NOT a full snapshot.

2. **Per-ticket completion record (pending-writes analogue)** — as each ticket
   *completes* mid-wave, immediately append a durable completion record so a
   crash after N of M tickets leaves exactly those N marked complete. This is the
   "pending-writes" analogue: durable-on-finish, replay-safe, idempotent on
   resume.

### Extend-vs-new posture

- **EXTEND the existing event/replay machinery, do not fork it.** Reuse the
  append-only JSONL discipline (durable `O_APPEND` + `flock` + `fsync`) already
  proven in `scripts/dgox/events.py::EventStore.append`. Do not invent a second
  incompatible append primitive.
- **Emit all events via the DAS-1443 typed builders** (typed-run-events). This
  ticket must NOT hand-roll raw event dicts; it consumes the typed builders that
  DAS-1443 produces. Add the new event shapes there if they are missing, and
  route completion records through them.
- **NEW code** lives under the declared zone `scripts/pulse-checkpoint/`
  (new module, e.g. `scripts/pulse_checkpoint.py` or a `scripts/pulse_checkpoint/`
  package) plus its tests. Wave-boundary checkpoint files are runtime artifacts
  under `board/runs/<run_id>/` (gitignored runtime state, exactly like
  `board/.events.jsonl`).

### Key existing files this touches / reuses

- `scripts/dgox/events.py` — append-only JSONL store; **reuse** the durable-append
  pattern (`EventStore.append`, `O_APPEND`+`flock`+`fsync`) and `iter_events` for
  reading the offset. Self-locating root via `_resolve_root()` / `DASLAB_ROOT`.
- `scripts/wave_kpi.py` — `read_events()` / `busy_fraction_from_events()` pair
  `run_start`/`run_end` by `run_id`; the checkpoint's event-store offset and
  `run_id` scoping must stay compatible with how this reader walks the store.
- `scripts/replay_qa.py` — replay/recovery-drill harness; the resume path this
  ticket enables must keep `replay_qa` green (zero corrupted resumes), and the
  crash-recovery test should demonstrate a clean resume consistent with its
  transition-chain model (`VALID_STATUSES`).
- **ADR-0023** — delta-checkpoint storage format (binding for the on-disk shape).
- **DAS-1443** (depends_on) — typed run-event builders; the emit path.

## Acceptance criteria

- [ ] A checkpoint file `board/runs/<run_id>/wave-NNN.checkpoint.json` is written
      at **each wave boundary** (NNN is the zero-padded wave index within the run).
- [ ] Each checkpoint records: board snapshot hash, event-store offset (into
      `board/.events.jsonl`), per-ticket states, pending interrupts, and ledger
      hashes (chained to the previous checkpoint).
- [ ] Storage is **DELTA** per ADR-0023 — checkpoints after the first store only
      the diff from the prior checkpoint, not a full snapshot (verified by a test
      asserting the serialized delta omits unchanged ticket states).
- [ ] As each ticket **completes** mid-wave, a durable per-ticket completion
      record is **appended** (pending-writes analogue), using the same durable
      append discipline as `EventStore.append` (`O_APPEND` + `flock` + `fsync`).
- [ ] All emitted events go through the **DAS-1443 typed builders**; no raw event
      dicts are hand-constructed in this module.
- [ ] **Simulated-crash test:** after N of M tickets complete, a simulated crash
      leaves exactly those N recorded complete; a resume re-runs only the
      remaining M−N and re-runs **none** of the N already-complete tickets
      (idempotent resume).
- [ ] Resume path keeps `scripts/replay_qa.py` green (0 corrupted resumes) on the
      produced records.
- [ ] Checkpoint writer is self-locating (honors `DASLAB_ROOT`, no hardcoded
      paths), pure/deterministic where timestamps are injected as arguments
      (matching the `events.py` convention — `created_at` is passed in, not
      generated inside helpers).
- [ ] Unit tests cover: boundary-write, delta encoding, per-ticket completion
      append, ledger-hash chaining, and the simulated-crash/resume scenario; all
      tests pass and are runnable from the repo root.

## Log

### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.

Consumes: typed-run-events (DAS-1443), adr-0023. Produces: wave-checkpoints (consumed by DAS-1445 / DAS-1451).
