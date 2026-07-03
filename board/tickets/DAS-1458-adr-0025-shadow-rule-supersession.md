---
id: DAS-1458
title: Author ADR-0025 shadow-rule supersession and shadow-test refinement
status: todo
assignee: cto
author: ceo
dept: engineering
priority: p1
parent: DAS-1457
goal: organism-ws3-slice2
zone: docs/adr
created: 2026-07-03
updated: 2026-07-03
---

## Description

**What.** Author a new ADR — `docs/adr/0025-events-load-bearing.md` — that
canonicalizes what three ORGANISM tickets independently discovered while building
the durable-execution core: the DGO-X event store at `board/.events.jsonl` is now
**load-bearing**, not the "advisory-only shadow" the Phase-1 design (ADR 0010 C3 /
ADR 0011 §4) promised. This ticket also **refines** the shadow test
(`tests/test_dgox_phase1_shadow.py`) to encode a principled reader-vs-producer
distinction in place of the current per-file allowlist stopgap.

**Why (embedded context — the tension, verbatim from the code).** Three agents
flagged the same gap and left a paper trail:

1. **DAS-1455 — `scripts/dispatch_emitter.py`** is the DGO-X event *producer*. Its
   module docstring says the whole observability stack (T1–T7 gates, anti-gaming
   R-9, KPIs) *reads* `board/.events.jsonl`, and that until this producer existed
   "every event-based T-gate read 'inert'". So events are load-bearing **as
   PRODUCERS**: `run_start`/`run_end`/`span` writes are what light up the run-model
   and telemetry. It is write-only (uses `EventStore.append` exclusively, never
   reads to route) — so it is not a dispatch-decision reader.

2. **DAS-1445 — `scripts/resume_fork.py`** is the first genuine event *reader in a
   dispatch path*. Its `SHADOW-RULE CONTRACT` docstring states plainly: "This
   module READS `board/.events.jsonl` to decide which tickets to re-dispatch. This
   tensions the Phase-1 'dispatch-decision scripts don't import dgox' structural
   guarantee." It resolves the tension with three mitigations — (a) scoped ONLY to
   the explicit operator-invoked `--resume`/`--fork` recovery path (normal waves
   unchanged), (b) no `dgox.*` import (reads via `wave_kpi.read_events` +
   `replay_qa`, so the P1 import-scan gate is untripped), (c) failure-isolated
   (missing/corrupt store → empty set or `ValueError`, never silent wrong
   dispatch) — and **explicitly recommends a formal ADR supersession** (see its
   docstring lines 41-43 and the DAS-1445 log).

3. **Slice-1 / ADR-0023 (`docs/adr/0023-run-model.md`)** already adopts an
   EXTEND-not-fork posture and makes `run_start`/`run_end` the home of the metrics
   the T-gates read — implicitly relying on events being load-bearing.

The current `tests/test_dgox_phase1_shadow.py` P1 scan copes with this by
maintaining a hand-curated allowlist: `_EVENT_PRODUCERS = {"pulse_checkpoint.py",
"dispatch_emitter.py", "kill_drill.py"}` and `_SPAN_VALIDATORS = {"check_spans.py"}`
(around lines 495 & 507). The inline comments themselves call this "a stopgap" and
say "a principled refinement (flag only READERS: `iter_events`/`read_events`) is a
tracked follow-up, and ADR-0010 C3 / ADR-0011 Phase-1 shadow rule is being
superseded by ORGANISM … — that supersession needs its own ADR." **This ticket is
that ADR + that refinement.**

**AADL stage.** GATE-1 Planning. This is an ADR (a decision doc) plus a
targeted test refinement — a Planning/design deliverable that records the new
invariant precisely and removes the stopgap; it ships no runtime dispatch change.

**Extend-vs-new posture (binding).** EXTEND, do not fork. ADR-0025 does **not**
edit ADR-0010 or ADR-0011 in place (they are append-only, accepted records). It
**supersedes specific clauses** of them by reference and records the new
invariant. The shadow test is **refined**, not rewritten — it stays green and
keeps enforcing the real intent (normal dispatch flag-on == flag-off).

**Key existing files (read before writing).**
- `docs/adr/0010-adopt-dgox-graph-orchestrated-control-plane.md` — §5 C3 "Worker
  agents NEVER write routing fields" and the shadow framing ("Phase 1 runs in
  SHADOW mode … changes no dispatch behaviour").
- `docs/adr/0011-dgox-phase-1-data-contracts.md` — §4 "The SHADOW-mode rule":
  "The supervisor's `routing_decision` events are **advisory shadow records** —
  nothing dispatches off them"; and the Phase-1→Phase-2 exit criterion.
- `docs/adr/0023-run-model.md` — the EXTEND-not-fork run-model; §4 the
  hard field-name contract (`outcome`/`model`/`merged_pr`/`ci_status`/`t7_pass`/
  `t7_score`) the T-gates read.
- `docs/adr/README.md` — the ADR index (add the 0025 row + theme).
- `tests/test_dgox_phase1_shadow.py` — the P1 no-influence scan and the
  `_EVENT_PRODUCERS` / `_SPAN_VALIDATORS` allowlist to be replaced (lines ~440-555).
- `scripts/dispatch_emitter.py` — the write-only producer (uses only
  `EventStore.append`; no read).
- `scripts/resume_fork.py` — the operator-recovery reader (`get_unfinished_tickets`
  / `resume_run` / `fork_run`; reads via `wave_kpi.read_events` + `replay_qa`,
  scoped to `--resume`/`--fork`).

**The decision ADR-0025 must record precisely:**
- **(a) Events are LOAD-BEARING as PRODUCERS and as OPERATOR-RECOVERY READERS.**
  Producers (`dispatch_emitter` writing `run_start`/`run_end`/`span`;
  `pulse_checkpoint` writing checkpoint/span/completion records) are load-bearing
  because the run-model and T-gates depend on them. `resume_fork --resume/--fork`
  is a load-bearing READER — but ONLY in the explicit operator-invoked recovery
  path, where it reads events to decide re-dispatch.
- **(b) NORMAL wave dispatch stays flag-on == flag-off.** No shadow READ influences
  routing in the normal `/daslab-cycle` selection/dispatch path. The Phase-1
  guarantee is preserved *for normal waves* and only *narrowed* — it never claimed
  the recovery path.
- **(c) The determinism / anti-gaming guarantees the old shadow rule protected are
  now preserved DIFFERENTLY.** The old rule kept events from silently steering
  routing. That protection is now provided by: committed evidence (P13 / DAS-1460),
  the immutable T7 rubric, and anti-gaming R-9 (`merged_pr` + green `ci_status` +
  `t7_pass`). Re-dispatch off events is safe because it is operator-invoked,
  failure-isolated, and gated by the same committed-evidence T-gates — not by an
  advisory shadow record.

## Acceptance criteria

- [ ] `docs/adr/0025-events-load-bearing.md` created and merged, following the
      house ADR format (Status / Date / Context / Decision / Consequences / law
      check), Status `Accepted` with CTO as decider (GATE-1 Planning; RACI 3.1/3.6).
- [ ] ADR-0025 **explicitly supersedes** ADR-0010 §5 C3's advisory-shadow framing
      and ADR-0011 §4's "advisory shadow records — nothing dispatches off them"
      rule, by reference, and states the new invariant: events are load-bearing as
      producers and as the operator-invoked recovery reader.
- [ ] ADR-0010 and ADR-0011 are **NOT edited in place** (append-only records); the
      supersede relationship is expressed only from ADR-0025 (a "Supersedes/Amends"
      line pointing at 0010 C3 / 0011 §4).
- [ ] ADR-0025 records all three parts precisely: (a) producers +
      operator-recovery readers are load-bearing; (b) normal-dispatch invariant
      (flag-on == flag-off) preserved for normal `/daslab-cycle` waves; (c) how
      determinism/anti-gaming is now guaranteed differently — committed evidence
      (P13/DAS-1460) + immutable T7 rubric + R-9 (`merged_pr` + green ci + `t7_pass`).
- [ ] `docs/adr/README.md` gets the ADR-0025 index row and theme entry.
- [ ] `tests/test_dgox_phase1_shadow.py` refined: the per-file
      `_EVENT_PRODUCERS` / `_SPAN_VALIDATORS` allowlist is replaced by a
      **principled distinction** — a script is flagged ONLY when it READS the event
      store (`iter_events` / `read_events` / `resume_fork`-style replay) to make a
      routing decision in the NORMAL `/daslab-cycle` dispatch path; write-only
      producers and operator-recovery readers are NOT violations.
- [ ] The refined test still enforces the real intent (no normal-dispatch script
      reads events to route) and is **green** — full suite passes, no regression in
      the other Phase-1 shadow proofs (P2 no-writeback, P3 failure-isolation).
- [ ] `python3 scripts/diagnostics.py` (or the repo's diagnostics gate) reports
      100/100.

## Log

### 2026-07-03 — CEO
Created from ORGANISM WS3 slice-2 decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
