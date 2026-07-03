---
id: DAS-1459
title: Cost-ledger — per ticket agent tier run token and cost aggregation (P12)
status: todo
assignee: backend-eng-2
author: ceo
dept: engineering
priority: p1
parent: DAS-1457
goal: organism-ws3-slice2
zone: scripts/cost
created: 2026-07-03
updated: 2026-07-03
---

## Description

DasLab's DGO-X span events (`event_type: "span"`, ADR 0024) now carry OpenTelemetry
GenAI token-usage attributes — `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.usage.cached_input_tokens` — emitted per unit
of agent work by the producer wired in DAS-1454/1455 (`scripts/dispatch_emitter.py` →
`scripts/dgox/events.py::build_span`). Those tokens are **recorded but never
totalled**: nothing rolls them up into a per-ticket / per-agent / per-tier / per-run
cost view. This ticket builds that rollup — a **cost ledger** — so the org can see
where its Claude token spend actually goes.

**AADL stage: GATE-3 (Development).** Predecessor gates GATE-0/1/2 for this slice are
closed by DAS-1457's decomposition; this is buildable code behind an already-open gate.

**Why INFORMATIONAL-first.** Per the approved ORGANISM §9 default #6, a brand-new
metric ships as an *informational* reader first (like T6 review-efficiency — a shipped
lever that reads live data and reports, but is **not** a hard gate). We do NOT add a
blocking cost gate now: pricing drifts, and the loop stays off until real waves read
clean. The reader must be **inert-by-design** — return `None` / exit 0 when there are
no span events yet (mirroring the exact pattern in `scripts/metrics_lib.py` and
`scripts/wave_kpi.py`, where every function returns `None` until live data exists).

**Extend, do not fork.** This is a NEW reader in a NEW zone (`scripts/cost/`). It
**imports** the existing span reader (`scripts/dgox/events.py::iter_events`) and reuses
its field names verbatim — it never re-implements event parsing, and it never modifies
`events.py`, `dispatch_emitter.py`, `metrics_lib.py`, or `wave_kpi.py`. The token
field names are a hard contract owned by `events.py` (`SPAN_OTEL_ATTRS`); read them,
do not rename them.

### Key existing files (paths)

- `scripts/dgox/events.py` — span builder + `iter_events(path, ticket_id=, run_id=,
  event_type=)` reader. Span JSON fields to read: `event_type == "span"`, `trace_id`
  (== `ticket_id`), `ticket_id`, `run_id`, `gen_ai.agent.name`, `gen_ai.request.model`
  (the tier: `opus`/`sonnet`/`haiku`, or a full model id), `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, `gen_ai.usage.cached_input_tokens`, `cached`. Default
  store path is `DEFAULT_STORE_PATH` = `board/.events.jsonl` (gitignored runtime).
- `scripts/dispatch_emitter.py` — the producer of those spans (context only; do not edit).
- `scripts/metrics_lib.py` — the inert-reader pattern to copy: `_parse_iso`,
  `read_waves`, and every T-gate returning `None` on no data. `LOW_COST_MODELS = {"haiku"}`.
- `scripts/wave_kpi.py` — `read_events()` (tolerant JSONL reader; `[]` if the store is
  absent) and `EVENTS_LOG = "board/.events.jsonl"`. Reuse this read discipline (skip
  unparseable lines; empty when the file is missing).
- `metrics/registry.yaml` — the T1–T7 metric contract registry (SSOT). Each entry has
  `definition / formula / source / window / target / guardrail / owner / validator`.
  Note the existing `owner: cost` on `T4_cost_model_mix` — this ticket's owner is also
  `cost`. Add a NEW entry alongside (do not touch T1–T7).
- `config/alert_thresholds.yaml` — alert SSOT (context for where a future cost alert
  would live; this ticket does NOT add a blocking threshold — informational-first).

### Pricing (verified via the claude-api skill, cached table dated 2026-06-04)

Per-1M-token USD list prices for the DasLab model tiers (Model Allocation Law:
opus/sonnet/haiku). `cached_input` = cache-read ≈ 0.1× base input (per
`shared/prompt-caching.md`):

| tier   | model id (canonical) | input $/1M | cached_input $/1M | output $/1M |
|--------|----------------------|-----------:|------------------:|------------:|
| opus   | claude-opus-4-8      |       5.00 |              0.50 |       25.00 |
| sonnet | claude-sonnet-4-6    |       3.00 |              0.30 |       15.00 |
| haiku  | claude-haiku-4-5     |       1.00 |              0.10 |        5.00 |

`config/budgets.yaml` MUST cite this source inline (a comment: claude-api skill,
Current Models table cached 2026-06-04) so a future agent knows where the numbers came
from and that they need re-verification when models change.

### Cost model

For each span: `cost = (input_tokens · input_price + cached_input_tokens ·
cached_input_price + output_tokens · output_price) / 1_000_000`, priced by the span's
tier (`gen_ai.request.model`, lower-cased and mapped to one of opus/sonnet/haiku; an
unknown/unpriced tier contributes tokens but `0.0` estimated cost and is surfaced, not
silently dropped). Aggregate the same spans four ways: per **ticket** (`ticket_id` /
`trace_id`), per **agent** (`gen_ai.agent.name`), per **tier** (`gen_ai.request.model`),
per **run** (`run_id`). Reconciliation invariant: the sum of every group's token totals
(along each axis independently) MUST equal the raw span token sums — the ledger only
re-buckets, it never adds or drops tokens.

## Acceptance criteria

- [ ] `scripts/cost/cost_ledger.py` exists and aggregates token counts **and** estimated
      USD cost per **ticket**, per **agent**, per **tier**, and per **run**, reading only
      `span` events via `scripts/dgox/events.py::iter_events` (no re-implemented parsing).
- [ ] Cost is computed from `config/budgets.yaml` unit prices (input / cached_input /
      output per tier); an unknown tier contributes tokens with `0.0` cost and is reported.
- [ ] `config/budgets.yaml` exists with: per-tier unit prices (opus/sonnet/haiku, the
      cited table above), per-run and per-day token + cost caps, and an inline citation of
      the pricing source (claude-api skill, Current Models table cached 2026-06-04).
- [ ] `metrics/registry.yaml` gains ONE new entry for the cost metric with all eight
      fields (`definition / formula / source / window / target / guardrail / owner:cost /
      validator: scripts/check_cost.py`), marked **INFORMATIONAL** (not a hard gate; like
      T6, per ORGANISM §9 default #6). T1–T7 entries are unchanged.
- [ ] `scripts/check_cost.py` exists as an informational reader: **exit 0** when there are
      no events (inert-by-design) and in the normal informational path; it only exits
      non-zero when an explicit `--max` flag is passed AND a live cap in `budgets.yaml`
      is exceeded. Prints a human-readable per-axis cost summary.
- [ ] A reconciliation test asserts that per-ticket, per-agent, per-tier, and per-run
      token totals each sum back to the raw span token sums (ledger re-buckets, never
      changes totals), plus an inert test (empty store → `None`/exit 0, no crash).
- [ ] `python3 scripts/diagnostics.py` reports 100/100; `ruff check scripts/cost/
      scripts/check_cost.py` is clean.
- [ ] No `project:` field anywhere in this ticket or the added files (org-engine work;
      board_lint R9).

## Log

### 2026-07-03 — CEO
Created from ORGANISM WS3 slice-2 decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
