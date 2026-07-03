---
id: DAS-1448
title: Merge-policies (append-only / owner-exclusive / aggregate) + reducers (P4)
status: todo
assignee: backend-em
author: ceo
dept: engineering
priority: p1
parent: DAS-1440
goal: organism-ws1-pulse
depends_on: [DAS-1446]
zone: scripts/board_lint
created: 2026-07-03
updated: 2026-07-03
---

## Description

**What & why.** Today the `/daslab-cycle` orchestrator enforces a hard
correctness guard: *never two tickets touching the same repo zone in one wave*
(`.claude/skills/daslab-cycle/SKILL.md`, step 3 — the "Correctness guard
(keep)" using the declared `zone:` field per ADR-0016). That guard trades
throughput for merge-conflict safety: the second same-zone ticket always waits
for the next wave. For zones whose parallel outputs are *mechanically
mergeable* (append-only logs, owner-partitioned files, aggregatable counters),
this is a needless brake — the ORGANISM program-plan (WS1 "pulse") calls for a
declarative escape hatch that lets two same-zone tickets run in one wave
**when, and only when, the zone opts in with a merge policy** and a reducer
that deterministically combines the parallel outputs.

This ticket adds that opt-in. It introduces an **optional** ticket frontmatter
field `merge_policy:` on a per-declared-zone basis, a small library of Python
**reducers** that merge parallel same-zone outputs, and extends
`board_lint.py` so the correctness guard is relaxed for a same-zone *pair*
**only** when the zone declares a permitting policy. With no policy declared,
the default behavior is unchanged: a same-zone pair is still forbidden
(fail-closed).

**Embedded context — the exact mechanics that already exist:**

- `scripts/board_lint.py` parses YAML frontmatter with a lightweight regex
  (`_FM_RE` / `_KV_RE`, no external YAML dep) into a flat `dict[str, str]`.
  Every value is a string; list-valued fields (like `depends_on: [DAS-1446]`)
  are captured as the raw string `"[DAS-1446]"`. `REQUIRED_FIELDS` lists the
  nine mandatory keys; rules R1–R9 are applied in `lint_tickets()`. **R9** is
  the platform-only guard: a ticket on `board/tickets/` must NOT carry a
  `project:` field — so this new field must NOT be `project:` and must not
  reintroduce a project concept. `board_lint` currently does **not** do any
  same-zone / same-wave reasoning at all — that logic lives only in the
  `/daslab-cycle` skill prose. This ticket is where the *lint layer* gains
  awareness of `merge_policy` and validates it.
- `scripts/check_dependency_graph.py` already reads the OPTIONAL `zone:` field
  (`_fm_field`, a separate tolerant line-based reader) and flags a
  present-but-empty `zone:` as a defect. It does NOT read `merge_policy`. The
  `zone:` field is the anchor that `merge_policy` attaches to.
- `.claude/skills/daslab-cycle/SKILL.md` step 3 is the runtime consumer of
  `zone:`. Its correctness guard is prose, enforced at dispatch time by the
  orchestrator, and (per the file's own note) guarded in CI "by a skill-token
  test, not here." This ticket does **not** rewrite the orchestrator's live
  dispatch behavior — it delivers the *validation + reducer library* that a
  later WS1 ticket wires into dispatch. Keep the SKILL prose truthful: if you
  reference the new policy, add it as an explicit opt-in that widens the guard,
  never as a change to the default.

**Extend-vs-new posture.** EXTEND the existing scripts; do not fork them.
- Extend `scripts/board_lint.py` in place: add `merge_policy` parsing +
  validation as a new rule (e.g. R10), keeping the existing regex parser
  working. The `depends_on: [DAS-1446]` style shows list values arrive as raw
  strings — if `merge_policy` ever needs multi-value or per-zone-map form,
  add a **tolerant reader** helper rather than swapping the whole parser.
- Add the reducers as a NEW, self-contained, dependency-free module under
  `scripts/` (e.g. `scripts/merge_reducers.py`) so it is unit-testable in
  isolation and importable by both the lint layer and a future dispatch hook.
- Add tests alongside the existing test suite (mirror where
  `board_lint` / `check_dependency_graph` are tested — search
  `tests/` for `board_lint` and place the new tests in the same location).

**Key existing files this touches:**
- `scripts/board_lint.py` — extend the frontmatter validation (new rule +
  optional tolerant reader).
- `scripts/merge_reducers.py` — NEW module: the three reducers.
- `scripts/check_dependency_graph.py` — READ-ONLY reference for the tolerant
  `_fm_field` reader pattern and the existing `zone:` handling; do not change
  its behavior unless a `merge_policy`-adjacent defect must be flagged there.
- `.claude/skills/daslab-cycle/SKILL.md` — step 3 correctness-guard prose;
  update ONLY to document the opt-in widening, keeping the default forbidden.
- `tests/` — new unit tests for the parser/validator and the reducers.

**Field grammar (implement exactly):** `merge_policy:` is optional. When
present, its value is one of:
- `append-only` — parallel outputs are concatenated in a deterministic
  (e.g. lexical-by-ticket-id) order; no line is dropped or reordered within a
  contributor's block.
- `owner-exclusive` — each parallel output owns a disjoint sub-region
  (e.g. distinct files / keys); the reducer verifies disjointness and unions
  them, FAILING if two outputs touch the same owned unit.
- `aggregate:<reducer>` — a named aggregation (e.g. `aggregate:sum`,
  `aggregate:union`); the reducer combines values by the named operation.
  An unknown `<reducer>` name is a validation error.

A `merge_policy` present with an empty or unrecognized value is a defect
(mirror the `check_dependency_graph.py` present-but-empty `zone:` treatment).
A `merge_policy` declared WITHOUT a `zone:` is a defect (the policy has no
anchor to attach to).

**AADL stage: GATE-3 Development.** This is org-engine (DasLab-platform) work.
Per QONUN Project Placement Law + board_lint R9, the frontmatter carries **no**
`project:` field.

## Acceptance criteria

- [ ] `merge_policy` frontmatter field is PARSED by `board_lint.py` (regex
      parser still works for all existing tickets) and VALIDATED: allowed forms
      are `append-only`, `owner-exclusive`, `aggregate:<reducer>`; empty /
      unrecognized value is a violation; `merge_policy` without a `zone:` is a
      violation.
- [ ] A new dependency-free `scripts/merge_reducers.py` module implements three
      reducers — `append-only`, `owner-exclusive`, and `aggregate:<reducer>`
      (at least `sum` and `union`) — each deterministically merging a list of
      parallel same-zone outputs, with `owner-exclusive` FAILING on overlap and
      `aggregate` FAILING on an unknown reducer name.
- [ ] `board_lint.py` permits a same-zone ticket **pair** in the schema ONLY
      when that zone declares a permitting `merge_policy`; the correctness
      guard's default (no policy) still forbids a same-zone pair.
- [ ] A merge test runs each reducer on representative parallel outputs and
      asserts the merged result is correct and deterministic (stable across
      input ordering where the policy promises order-independence; stable
      concat order for `append-only`).
- [ ] Default path proven: a same-zone pair with NO `merge_policy` declared is
      still rejected (fail-closed) — regression test asserts this.
- [ ] `python3 scripts/board_lint.py` and
      `python3 scripts/check_dependency_graph.py` both still exit 0 on the
      current board (no false positives introduced); new tests pass.
- [ ] `.claude/skills/daslab-cycle/SKILL.md` step-3 guard prose documents the
      opt-in widening (same-zone pair allowed only under a declared policy) and
      never weakens the no-policy default; the SKILL cache-prefix invariant is
      not disturbed (change lives in the mutable body, not the stable prefix).
- [ ] No `project:` field is added anywhere (board_lint R9 stays green); no new
      file is created outside `scripts/` and `tests/`.

## Log

### 2026-07-03 — CEO
Created from ORGANISM program-plan decomposition (/daslab-plan). Spec-of-record: docs/research/ORGANISM-PROGRAM-PLAN.md.
