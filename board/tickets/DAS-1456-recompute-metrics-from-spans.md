---
id: DAS-1456
title: wave_kpi + T-validators recompute from spans (single read_events source)
status: todo
assignee: backend-eng-1
author: ceo
dept: engineering
priority: p1
parent: DAS-1441
goal: organism-ws3-bridge
depends_on: [DAS-1454, DAS-1455]
zone: scripts/metrics
created: 2026-07-03
updated: 2026-07-03
---

## Description

**What & why.** DasLab's throughput KPIs (`wave_kpi.py`) and the T1–T7
validators (`scripts/metrics_lib.py` + the busy-fraction/gate readers) each
reconstruct their own view of "what ran" — some parse the human-readable
`board/.wave-log`, some read the DGO-X JSONL event store
(`board/.events.jsonl`). DAS-1455 introduces a **span/run event model** written
by the dispatch emitter (the `span-builder` + `dispatch-emitter` this ticket
consumes). This ticket makes **every** metric reader derive from that ONE
source: the shared `read_events` reader over the span/run events. No reader may
keep a private, divergent notion of a run. This is the "single source of truth"
seam that lets slice-2's cost ledger reconcile against the same spans without a
second parse path.

**AADL stage.** GATE-3 Development (spec-of-record:
`docs/research/ORGANISM-PROGRAM-PLAN.md`).

**Embedded context — the existing code you are extending (EXTEND, do not
rewrite):**

- `scripts/wave_kpi.py` — already owns the canonical event reader
  `read_events(path=EVENTS_LOG)` (JSONL → `list[dict]`, `[]` when the file is
  absent) and `busy_fraction_from_events(events)` (T1). It pairs
  `run_start`/`run_end` events by `run_id` and returns `None` when there are no
  paired runs (inert-by-design). Constants: `EVENTS_LOG =
  "board/.events.jsonl"`, `LIVE_LOG = "board/.wave-log"`. Make this module's
  `read_events` the ONE reader; T1 must derive from spans emitted by DAS-1455.
- `scripts/metrics_lib.py` — T2–T6 + anti-gaming (R-9) + T1b. It already
  `import wave_kpi` and calls `wave_kpi.parse` / consumes the event store. Every
  function here returns `None` when there is no live data (`idle_wave_rates`,
  `concurrency_stats`, `model_mix`, `recovery_reliability`,
  `review_efficiency`, `gaming_violations`, `t1b_high_impact`). Point its
  event-derived functions (`run_intervals`, `concurrency_stats`, `model_mix`,
  `recovery_reliability`, `review_efficiency`, `gaming_violations`,
  `t1b_high_impact`) at `wave_kpi.read_events` so there is a single reader; keep
  every inert-when-empty guard intact.
- `scripts/check_spans.py` — **does not exist yet; this ticket creates it.** A
  new validator that reads the same event store via `wave_kpi.read_events` and
  asserts that **100% of dispatches in a run produce a well-formed span**: every
  dispatched ticket has a matching `run_start` **and** `run_end` paired by
  `run_id`, each carrying the required fields (`run_id`, `ticket_id`, `model`,
  `created_at` ISO-8601). It must be inert (exit 0, "no events") when the store
  is absent/empty, and fail (non-zero) only when live events exist and a
  dispatch is missing/malformed.

**Extend-vs-new posture.** EXTEND `wave_kpi.py` and `metrics_lib.py` in place —
route all readers through the existing `wave_kpi.read_events`; do NOT add a
second parser or duplicate the `run_id` pairing logic. CREATE exactly one new
file, `scripts/check_spans.py`. Do not touch `board/.events.jsonl` schema owned
by DAS-1455 beyond consuming it.

**Cost/token reconciliation seam.** The cost-ledger lands in slice 2, so
cost/token sum fields may be absent today. Leave the seam: where a span carries
token/cost fields, `check_spans.py` (or a helper) must reconcile the per-run
token sums against the span-level sums and pass trivially (inert) when the
fields are absent — never fabricate a number.

**Consumes:** `span-builder`, `dispatch-emitter` (DAS-1455).

## Acceptance criteria

- [ ] `wave_kpi.py` (T1) and the `metrics_lib.py` T2–T7 validators all derive
      from spans via the single shared `wave_kpi.read_events` source — no reader
      keeps a private/divergent run reconstruction.
- [ ] New `scripts/check_spans.py` asserts 100% of dispatches in a run produce
      well-formed spans (matching paired `run_start`/`run_end` by `run_id` with
      required fields); exits non-zero on any missing/malformed dispatch when
      live events exist.
- [ ] Token sums (once present) reconcile with span sums; the reconciliation
      passes inertly when token/cost fields are absent (cost-ledger is slice-2).
- [ ] `python3 scripts/diagnostics.py` stays 100/100.
- [ ] All validators (`wave_kpi`, `metrics_lib`, `check_spans`) remain
      inert-by-design — return `None`/exit 0 with a clear "no events" message —
      when the event store is absent or empty.

## Log

### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
