---
id: DAS-1445
title: Resume + time-travel fork in daslab-cycle (P2)
status: todo
assignee: backend-eng-2
author: ceo
dept: engineering
priority: p1
parent: DAS-1440
goal: organism-ws1-pulse
depends_on: [DAS-1444]
zone: daslab-cycle
created: 2026-07-03
updated: 2026-07-03
---

## Description

**What & why.** `/daslab-cycle` runs one operator-invoked wave over the file
board and, on each dispatch, appends a `routing_decision` event per ticket to
the append-only event store `board/.events.jsonl` (SKILL.md step 5d). Today a
wave is fire-and-forget: if a run is interrupted mid-wave (crash, harness stop,
operator abort), there is no first-class way to pick it back up, and there is no
way to explore an *alternative* plan from a past point without corrupting the
original run's audit trail. This ticket adds two operator affordances to
`/daslab-cycle`:

1. **`--resume <run_id>`** — replay `board/.events.jsonl` for that `run_id` up to
   its last valid checkpoint, then re-dispatch **only the unfinished** tickets
   (those whose last recorded `to_status` is not a terminal `done`/`blocked`).
   Finished tickets are NOT re-dispatched (no duplicate work, no clobbering
   already-merged branches).
2. **`--fork <run_id>@wave-NNN`** — copy that run's checkpoint state as of
   `wave-NNN` into a **new** `run_id` and continue alternative planning from
   there. The original run's recorded events are left byte-for-byte untouched —
   fork writes only new-run events; it never rewrites, deletes, or re-parents the
   source run's history (time-travel without destroying the timeline).

**Embedded context — the replay contract (reuse, do NOT reinvent).**
`scripts/replay_qa.py` already defines the canonical replay model this ticket
must reuse verbatim as its contract:
- A **run** is keyed by `run_id` (falling back to `ticket_id`), via `_run_key()`
  / `group_runs()` — only `event_type == "routing_decision"` events participate.
- Replay is **ordered by `created_at`** (`replay_run()` sorts on
  `str(e.get("created_at",""))`), then walks the `from_status → to_status` chain.
- A checkpoint is **valid** only if the chain is intact: every `to_status` is in
  `VALID_STATUSES = {backlog, todo, in_progress, blocked, in_review, done}`, and
  each step's `from_status` equals the previous step's `to_status`. A break,
  or a missing/invalid `to_status`, is a **corrupted resume** — resume MUST
  refuse to re-dispatch off a corrupted chain (this is the T5 "zero corrupted
  resumes" guardrail enforced by `scripts/check_recovery.py`).

Resume/fork MUST call into this existing transition model (import/reuse
`group_runs` + `replay_run` from `replay_qa.py`) rather than re-deriving run
grouping or the ordered-transition walk. The "last checkpoint" for a run is the
`final_status`/`steps` that `replay_run()` reports for a clean chain.

**Extend-vs-new posture: EXTEND.** Add the two flags to the existing
`/daslab-cycle` command surface — do not fork a new command. The
`routing_decision` event store, the wave-log format, and the DGO-X emission path
are all already in place; resume/fork consume the SAME event store as their
source of truth. Only add: (a) argument parsing for `--resume` / `--fork`, (b) a
replay-to-checkpoint step that reuses `replay_qa.py`, (c) an unfinished-ticket
selector that feeds the existing selection/dispatch machinery, and (d) for fork,
a new-`run_id` minting + checkpoint-copy step that emits fresh events only.

**Key existing files this touches (paths):**
- `/Users/owner/DasLab/.claude/skills/daslab-cycle/SKILL.md` — the orchestrator
  spec; document the two new invocation modes. The selection step is §3 ("Select
  every actionable ticket") and its **4 selection guards** that MUST be preserved
  unchanged: (1) the zone/repo-area correctness guard (no two tickets touching
  the same `zone:`/repo area in one wave), (2) the `depends_on:` not-`done`
  dep-block skip, (3) the AADL predecessor-stage gate-order skip, and (4) the
  clarify gate `[NEEDS CLARIFICATION: …]` skip + at-least-half circuit-breaker.
  Dispatch is §5; the worktree path is a **pure function of ticket id** —
  `.claude/worktrees/<TICKET-ID>/` (§5b) — and MUST stay pure-id under resume
  (reuse an existing worktree at that path rather than re-creating).
- `/Users/owner/DasLab/scripts/replay_qa.py` — the replay/transition contract to
  reuse (`_run_key`, `group_runs`, `replay_run`, `VALID_STATUSES`, `drill`).
- `/Users/owner/DasLab/scripts/check_recovery.py` — the T5 gate
  (`successful_replays / recovery_drills >= 0.99`, zero corrupted); resume/fork
  round-trips should remain replayable so this gate stays green.
- `/Users/owner/DasLab/board/.events.jsonl` — the append-only event store that is
  both the resume source and the fork source (never rewritten in place).

**Cache-prefix caution (mechanical, do not skip).** SKILL.md carries the ADR-0006
byte-stable-prefix invariant with the sentinel `CACHE_PREFIX_VERSION:
v10-adr-renumber` (currently line ~424). If — and only if — an edit changes bytes
**before** that sentinel / inside the stable-prefix region, you MUST bump
`CACHE_PREFIX_VERSION` and run `python3 scripts/check_cache_prefix.py --fix` in
the **same commit** so the baseline is regenerated. Prefer to add the new
resume/fork documentation **after** the sentinel to avoid a prefix-byte change
entirely.

**Data-flow (program plan).** Consumes: `wave-checkpoints` (the recorded
`routing_decision` transitions per run). Produces: `resume-fork` — the resume/fork
capability consumed downstream by DAS-1451 and DAS-1452.

## Acceptance criteria

- [ ] `/daslab-cycle --resume <run_id>` replays `board/.events.jsonl` for that
      run to its last valid checkpoint and re-dispatches **only unfinished**
      tickets (last `to_status` not `done`/`blocked`); already-finished tickets
      are not re-dispatched.
- [ ] Resume refuses to re-dispatch off a **corrupted** chain (broken/invalid
      transition per `replay_run`), consistent with the T5 zero-corrupted
      guardrail (`scripts/check_recovery.py`).
- [ ] `/daslab-cycle --fork <run_id>@wave-NNN` produces a **divergent new run**
      (fresh `run_id`) seeded from that checkpoint, while the original run's
      recorded events in `board/.events.jsonl` remain byte-for-byte intact
      (append-only; no rewrite/delete/re-parent of source events).
- [ ] The replay path **reuses** `replay_qa.py`'s `run_id` grouping
      (`group_runs`) and ordered-`created_at` `routing_decision` transition walk
      (`replay_run`) as the replay contract — it does not re-implement run
      grouping or the transition model.
- [ ] A **round-trip test** exists: dispatch → interrupt → `--resume` reproduces
      the completed set with no duplicate dispatch; and `--fork` yields a
      divergent run whose replay is clean while the original replays unchanged.
- [ ] The **4 selection guards** (zone/repo-area, `depends_on` not-`done`, AADL
      gate-order, clarify `[NEEDS CLARIFICATION]` + circuit-breaker) and the
      pure-id `.claude/worktrees/<TICKET-ID>/` worktree-path invariant are
      preserved under both `--resume` and `--fork`.
- [ ] Cache-prefix baseline handled: if any edit changed stable-prefix bytes in
      SKILL.md (before the `CACHE_PREFIX_VERSION` sentinel), `CACHE_PREFIX_VERSION`
      is bumped and `python3 scripts/check_cache_prefix.py --fix` was run in the
      same commit; `python3 scripts/check_cache_prefix.py` passes. (If the doc was
      added after the sentinel, no prefix bytes changed — note that in the log.)

## Log

### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
