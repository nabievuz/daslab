---
name: daslab-cycle
description: Run ONE DasLab work wave — triage the file-based board, dispatch every actionable role subagent in parallel (no policy cap; harness-bounded), collect results, report. Use when the user says to run the org, work the board, or process tickets. Args - optional integer N (cap the wave to N if you want a smaller batch).
---

# DasLab cycle — one wave over the board

You are the DasLab orchestrator. One invocation = ONE operator-invoked
wave. The runtime has no night driver, background loop, or timer chain.

**Wave size:** **no policy cap** — dispatch every actionable ticket the
selection step finds, in one parallel batch. Real concurrency is bounded only
by the Claude Code harness (it queues excess subagents and runs them as slots
free). `N` from args is an optional *upper bound* if you deliberately want a
smaller wave (e.g. a quick test run); omit it to run the whole board.
(Owner removed the hard cap on 2026-06-14: Max-plan usage was barely moving,
so the 10-cap and the opus wave-mix guard were pure throttle. Thermal limit
was already lifted.) The only remaining bounds are **correctness guards** in
the selection step — keep those.

## Steps

0. **ArcRift memory prewarm — one recall per wave (ADR 0008, W7).**
   Issue ONE `recall_context` call before any subagent is spawned, with:
   - `project` = `"daslab"` for org-level waves; `"daslab-<slug>"` for
     project-specific waves. **Never mix projects** — a wave spanning multiple
     projects prewarms per-project, injecting only the matching context into
     each project's agents (LAW 4 strict project scoping).
   - `prompt` = a compact wave-intent sentence (e.g. "wave for DAS-13xx platform
     tickets") — no ticket IDs, no timestamps (those go in the dynamic tail).

   The returned `<ARCRIFT_retrieved_context>` block is carried as a single
   read-once payload into the **dynamic tail** of each agent's prompt (slot 4:
   "Last-N scratchpad / ArcRift recall" — after the last `cache_control`
   breakpoint, never in the stable prefix). This collapses N blocking per-agent
   recalls into 1 prewarmed wave-level read.

   **Durable outbox for store_memory (fire-and-forget, LAW 4):** Each agent
   enqueues its close-of-task `store_memory` payload to a durable local outbox
   (append-only file at `board/.arcrift-outbox.jsonl`, never committed — in
   `.gitignore`) before reporting done. The agent does NOT wait for the MCP
   call to complete. A single background drainer — the orchestrator, after step 6
   collect — reads the outbox and issues `store_memory` calls one at a time
   (single-drainer prevents the known concurrency race). On transient failure
   the drainer retries with exponential backoff until the store lands; it never
   silently drops a pending entry. On orchestrator shutdown, the drainer flushes
   the remaining outbox before exit (or leaves it durable for replay on next start).
   **Zero stores are ever dropped.** Project scoping is per-entry: each outbox
   record carries its own `project` key; the drainer passes that key verbatim —
   never merges across projects.

1. **Read state.** `board/README.md` (schema), `board/ROUTING.md` (reviewer
   map), then the frontmatter of every `board/tickets/*.md`. A missing tickets
   dir is an identity failure → stop. **This wave dispatches the org
   `board/tickets/` only — DasLab-platform (org-engine) work. A project's board
   (`projects/<slug>/board-tickets/`) is run by a `/daslab-cycle` wave invoked in
   that project's own context, never pulled into `board/tickets/`
   (QONUN — Project Placement Law).**

2. **Triage (orchestrator-only edits, cheap, do them all):**
   - **Zombie/stale-worktree reap pass (run first, before any routing edit).**
     Run `git worktree list --porcelain` and collect every path matching
     `.claude/worktrees/DAS-*`. For each such path, check whether its ticket is
     `done`, `blocked`, or the branch has already been merged into `origin/main`
     (`git branch -r --merged origin/main | grep <branch>`). If so: run
     `git worktree remove --force <path>` then `git worktree prune`. Log a note
     in the wave-log line for that ticket (or append a freeform line
     `reaped <id> — <reason>`). This closes the zombie accumulation observed in
     the pre-W1 baseline (stale worktree entries from crashed past runs).
   - `todo` with empty `assignee` → assign a role using the ticket's `dept` +
     the RACI in `governance/policies/raci.md`; log the routing in the ticket.
   - `in_review` where `assignee` == `author` → reassign to the author's
     reviewer per ROUTING.md (manager; if manager is the author, one level up).
   - Skip tickets whose title/description matches external blocks
     (RAHMAT / UZINFOCOM / IKPU / tax / legal entity) — leave them, count them.

3. **Select every actionable ticket** (or the first `N` if args set a bound),
   priority order: `p0` first, then `in_review` (unblock the pipeline), then
   `in_progress`, then `todo`. A role MAY take multiple tickets in one wave —
   spawn one subagent instance per ticket (each works WIP=1 in its own
   worktree). **Correctness guard (keep):** never two tickets touching the
   same repo area / file set in the same wave — use the declared `zone:` field
   (ADR-0016) when both tickets have one, else fall back to `parent` + title
   overlap; the loser waits for the next wave. Parallel work on the same files
   causes merge conflicts and rework, which *lowers* throughput. A ticket whose
   `depends_on:` names an id that is not yet `done` is NOT actionable — skip it
   and count it `dep-blocked` (like the AADL gate-order skip).
   **AADL gate order** (`governance/policies/ai-agent-lifecycle.md`): a ticket
   whose parent is a `Stage N` epic is NOT actionable while the same project's
   `Stage N-1` epic is not `done` — skip it and count it as gate-blocked in
   the report.
   **Clarify gate (Definition of Ready — ADR-0014):** a ticket carrying an
   unresolved `[NEEDS CLARIFICATION: …]` marker (in plain prose, not a code
   example) is NOT actionable — skip it and count it as `clarify-blocked`. If it
   is `todo`, reassign it to the author's reviewer per `ROUTING.md` (a thinking,
   opus-tier role) to resolve the marker; NEVER dispatch a marked ticket to a code
   subagent. **Circuit-breaker:** if `clarify-blocked` is at least half of the
   actionable set, HALT the wave and emit a blocker report (listing each marked
   ticket) instead of looping — an autonomous run must not stall on agents
   over-flagging to dodge hard tickets. (Enforced fail-closed in CI by
   `scripts/check_clarifications.py --strict`; ADR-0013 ratified 2026-06-26.)

   **W6 — Batch review (pipeline compression):** A single reviewer agent MAY
   clear multiple `in_review` tickets in one wave — spawn one subagent
   instance per ticket as usual, all in parallel. The reviewer's WIP=1
   constraint is per-subagent (each instance handles exactly one ticket);
   the orchestrator may spawn multiple reviewer-role subagents in the same
   wave, one per outstanding `in_review` ticket assigned to that reviewer.
   The correctness guard (no two tickets in the same repo zone) still applies
   — if two `in_review` items touch the same file set, the second waits for
   the next wave.

   If the selection set is empty, run the approved-goal refill check exactly
   once (W5 — never-starve hardening; loop-safe):
   - **Blocker-first:** if any non-done ticket is blocked on external input or
     an open lifecycle gate, emit an explicit report listing each blocker with
     its reason, then stop this wave. Do not plan around real blockers; do not
     restart selection.
   - **Scan for approved queue item:** scan `projects/*/APPROVED-GOAL-QUEUE.md`
     for the first `founder_approved` item with empty `ticket_refs`. This scan
     runs exactly once per empty-selection event — never in a loop.
   - **Board drained — explicit stop report:** if no such item exists (queue is
     empty, exhausted, or every item is already planned/done), emit the
     following literal report and stop immediately:
     > Board drained. No founder-approved queue item available. Awaiting
     > Founder input before the next goal can be planned. (daslab-cycle stop)
     Never invent a new goal, never fabricate a queue item, and never restart
     selection when this branch is taken. The supervisor (`/daslab-run`) will
     surface this stop to the operator.
   - **Refill:** if exactly one `founder_approved` item exists with empty
     `ticket_refs`, apply the `/daslab-plan` decomposition rules to that queue
     item inside this invocation. **Write the tickets to the target board per the
     Placement Law:** a project item's tickets go to that project's OWN board
     (`projects/<slug>/board-tickets/`, carrying `project: <slug>`) — never to the
     org `board/tickets/`; a platform (org-engine) item's tickets go to
     `board/tickets/` with no `project:` field. Update the queue item to `planned`
     with ticket refs, then restart selection once. The org wave selects and
     dispatches only org `board/tickets/` (platform) tickets, so newly-created
     **platform** tickets are dispatched now; newly-created **project** tickets are
     actionable in a `/daslab-cycle` wave run in that project's own context —
     report them as ready rather than pulling them into the org wave.
     Do not run Founder Discovery from `/daslab-cycle`; that belongs to
     `/daslab-plan`. The restart-once constraint is hard: if the newly created
     tickets are themselves immediately empty (e.g. all gate-blocked or all in a
     project board), take the blocker-first branch above — do not restart selection
     a second time.

4. **Wave-log emission (KPI instrumentation — append-only, do this step before
   spawning subagents).** Write the wave-start marker and dispatch table to
   `board/.wave-log` (create if absent; never truncate):

   ```
   ===== wave YYYY-MM-DD HH:MM:SS =====
   | DAS-xxxx  title-slug  todo → in_progress  sre-eng  sonnet |
   | DAS-yyyy  title-slug  in_review → done    qa-lead  opus   |
   ```

   - First line: `===== wave <YYYY-MM-DD> <HH:MM:SS> =====` (UTC wall-clock
     at the moment of dispatch, before any subagent is spawned).
   - One pipe-delimited row per dispatched ticket:
     `| <id>  <short-title>  <old-status> → <new-status>  <assignee>  <model> |`
   - If the selection set is empty (no actionable tickets), append instead:
     `nothing actionable — <YYYY-MM-DD HH:MM:SS>`
   - This log is consumed by `scripts/wave_kpi.py`; do not alter the marker
     format without updating that script. Path: `board/.wave-log` (listed in
     `.gitignore` so it is never committed).

5. **Dispatch (worktree-per-ticket isolation — ADR 0005, W1).** Before spawning
   any subagent, the **orchestrator** creates an isolated git worktree for every
   code-touching ticket in the wave. Do this in order, for each ticket:

   a. **Determine if a worktree is needed.** A ticket is "code-touching" (needs
      a worktree) if it will produce a branch / PR. Pure-doc / planning /
      governance tickets that only append to the board or write a single additive
      doc in a zone-disjoint area may run in the main checkout; the rule is:
      "isolate anything that produces a branch/PR." When in doubt, create the
      worktree — isolation is cheap.

   b. **Create the worktree (orchestrator, before spawn).** For code-touching
      tickets, derive the branch slug from the ticket id and title:
      `feat/<ticket-id-lowercase>-<short-slug>` (e.g. `feat/das-1365-worktree-dispatch`).
      Then:
      ```
      git fetch origin
      git worktree add .claude/worktrees/<TICKET-ID>/ \
          -b feat/<ticket-id-lowercase>-<short-slug> \
          origin/main
      ```
      Path is a **pure function of the ticket id** — `\.claude/worktrees/<TICKET-ID>/`
      — so no two agents ever share a worktree. This is the mechanical enforcement
      of LAW 6 at the filesystem layer. If a worktree at that path already exists
      (previous stalled wave), reuse it rather than re-creating (skip `worktree add`).

   c. **Spawn the subagent** (Agent tool, `subagent_type` = role key) — all in
      ONE message so they run in parallel. **Always pass `model` explicitly** =
      the `model:` frontmatter of `.claude/agents/<role>.md` (canon:
      `governance/policies/model-allocation.md`; frontmatter alone is unreliable
      at runtime — claude-code#44385). **No opus wave-mix cap** — dispatch as many
      opus roles as the wave needs (owner removed the 3-opus guard 2026-06-14;
      Max usage wasn't the constraint). Prompt per agent — include the
      **worktree path** so the agent works only there:
      > Work the ticket `board/tickets/<file>.md` (repo root: <worktree-path>).
      > Your working directory is `<worktree-path>` — do all file edits,
      > `git add`, `git commit`, and `git push` from that path. Do NOT create
      > or delete worktrees. Do its next concrete step per your role overlay,
      > update the ticket file (status + log), and report.

      For non-code tickets (no worktree), use the original prompt without a path
      override:
      > Work the ticket `board/tickets/<file>.md`. Do its next concrete step per
      > your role overlay, update the ticket file (status + log), and report.

      **W6 — Same-wave build + review (pipeline compression):** When a
      `todo` or `in_progress` ticket and its subsequent `in_review` step can
      be handled by two DISTINCT agent roles in the same wave, dispatch both
      in the same parallel batch. The build agent sets status to `in_review`
      (and its subagent run ends); the reviewer agent — spawned in the same
      `Agent` tool call, running concurrently — then picks it up. Preconditions
      that must ALL be true before applying same-wave build+review:
        1. The reviewer role key differs from the author role key (self-review
           is impossible by the triage reassignment in step 2; this confirms it).
        2. The reviewer is a cheaper or equal-cost model than the builder
           (haiku or sonnet reviewer alongside a sonnet or opus builder).
        3. The ticket is NOT security-touching (see security guard below).
        4. The correctness guard passes — no zone overlap with any other
           ticket in the wave.
      If any precondition fails, dispatch build only; review happens in the
      next wave as normal.

      **Security guard (LAW 2; RACI 5.1 — no compression):** A ticket is
      "security-touching" if its title, description, or parent epic mentions
      auth, secrets, encryption, CVE, supply-chain, or the `security-*` role
      handles it. Security-touching tickets MUST have a blocking security audit
      (security-lead or security-eng review) that runs in its own wave after
      the build wave completes. Do NOT apply same-wave build+review compression
      to security-touching tickets under any circumstances. The step-2 triage
      reassignment guard (assignee == author → reassign to manager) remains
      fully active for all tickets.

   d. **DGO-X shadow emission — `routing_decision` event (ADR 0011, Phase 1).**
      **Feature-gated (ADR-0019): emit ONLY if `config/features.yaml` `dgox_emit` is
      `true`. It defaults OFF — when off, SKIP this whole sub-step (no Phase-2 consumer
      exists yet, so the shadow emission would only burn tokens). Read it via
      `python3 scripts/feature_flags.py`.** When on:
      SHADOW / ADVISORY ONLY — ADR 0010 constraint C3 + Phase-1 shadow rule.
      The emitted records are pure observers. NOTHING in `/daslab-cycle` reads
      or routes off them. Dispatch decisions are entirely unchanged. Phase 2 is
      where a supervisor may read these events; not now.

      For EVERY ticket dispatched in this step (both code-touching and non-code),
      after the worktree is created (or confirmed present) and before the subagent
      is spawned, append one `routing_decision` event to the event store
      (`board/.events.jsonl`) using `scripts/dgox/events.py`. Record:

      - `ticket_id` — the DAS-NNNN id from the ticket frontmatter.
      - `from_status` — the ticket's status at the start of this wave (before
        any orchestrator edit in step 2).
      - `to_status` — the status the ticket will have after dispatch (e.g.
        `in_progress` for a `todo` ticket being dispatched, `done` for an
        `in_review` ticket cleared in the same wave).
      - `assignee` — the role key being dispatched.
      - `model` — the explicit model string passed to the Agent tool call
        (never inferred from frontmatter — LAW 3 / ADR 0007).
      - `reason` — a one-sentence human-readable rationale for the routing.
      - `confidence` — orchestrator confidence score in [0.0, 1.0]; use 0.9 as
        the default for normal scheduled dispatch; lower for ambiguous routing.
      - `policy_checks` — list of gate names that were verified before dispatch
        (e.g. `["aadl_predecessor_gate_closed", "repo_area_available",
        "not_external_blocked"]`). Must be a non-empty list.
      - `fallback` — what happens if a policy check fails (e.g.
        `"skip_to_next_wave"` for zone conflicts, `"block_and_escalate"` for
        AADL failures).
      - `created_at` — call `utcnow()` from `dgox.events` at emission time.

      Emit using the library pattern (not a subprocess):
      ```python
      from dgox.events import EventStore, build_routing_decision, utcnow
      store = EventStore()          # writes to board/.events.jsonl
      ev = build_routing_decision(
          ticket_id=...,
          from_status=...,
          to_status=...,
          assignee=...,
          model=...,
          reason=...,
          confidence=0.9,
          policy_checks=[...],
          fallback=...,
          created_at=utcnow(),
      )
      store.append(ev)
      ```

      If `EventStore.append` raises (malformed event or I/O error): log the
      error in the wave-log line for that ticket and continue — the shadow
      emission MUST NEVER block dispatch. Dispatch proceeds regardless of
      emission success or failure. This is the single-writer enforcement:
      only the orchestrator emits routing_decision events, never subagents.

6. **Collect & verify.** After all return: re-read each dispatched ticket —
   confirm `status`/`updated`/log actually changed (a subagent that returned
   text but didn't edit the file gets its result written into the log by YOU,
   marked `(orchestrator-recorded)`). Apply any routing the reports request.

   **Live CI/PR done-gate (ADR 0008, W7 — LAW 5: green CI = done).**
   Before marking any engineering ticket `done`, the orchestrator MUST verify
   that its PR's CI checks are actually green:
   ```
   gh pr checks <PR-number>
   ```
   A ticket transitions to `done` only when ALL listed checks pass (exit 0).
   If any check is failing or still running, set `status: in_progress` (not
   done), log the failing check name and its URL, and schedule a follow-up
   check in the next wave. **"Done" is never assumed from a subagent's report
   alone** — the orchestrator confirms it by querying GitHub directly. This gate
   applies to all engineering tickets that have a PR; documentation-only tickets
   with no branch/PR are exempt.

   **ArcRift outbox drain (ADR 0008, W7):** After step 6 collect and before
   emitting the step 7 wave report, the orchestrator reads `board/.arcrift-outbox.jsonl`
   and drains any pending store entries. For each entry (in append order):
   call `store_memory` with the entry's `project`, `content`, and metadata;
   on success, mark the entry acked (append a `{"acked": true, "id": ...}` line);
   on transient failure retry up to 3× with 2-second back-off before leaving
   the entry for the next wave's drainer. A failed entry is never removed —
   it stays for replay. The single-drainer pattern (only the orchestrator calls
   store_memory, never agents directly) prevents the known concurrency race.

   **Worktree reap on resolution (ADR 0005 §4).** For each code-touching ticket
   whose new status is `done` or `blocked` (abandoned), remove its worktree and
   prune:
   ```
   git worktree remove --force .claude/worktrees/<TICKET-ID>/
   git worktree prune
   ```
   Tickets that are `in_review` keep their worktree alive (the branch still
   exists; the reviewer needs it). When a ticket transitions from `in_review` to
   `done` in a future wave, the reap pass in step 2 will catch it.
   If `worktree remove` fails (path already gone, or lock held by a crashed
   agent), log the failure and continue — the step 2 reap pass in the next wave
   will clean it up.

7. **Report the wave** (this is what the user reads):
   - table: ticket → old status → new status → agent → one-line outcome
   - blocked tickets with reasons; escalations; orphaned todos still unrouted
   - what the next wave would pick up.

## Prompt-cache prefix layout (ADR 0006 — W4)

### Why this matters

Every dispatched agent re-sends a large shared preamble (~27 KB of QONUN laws,
AADL gate model, board schema, dept charters, and the role overlay invariant
text). Anthropic prompt-cache reads bill at ~10% of base input price, so a
stable cached prefix cuts the input cost of that region by ~90%. A single
volatile byte — a timestamp, run-id, or ticket-id — placed **before** the
`cache_control` breakpoint invalidates the entire downstream cache fleet-wide
and re-pays full input cost on every agent call.

### Byte-stable prefix rule

The **stable prefix** is the only content allowed before the last
`cache_control: {type: "ephemeral"}` breakpoint. It contains exactly:

1. The frozen system text (QONUN laws, AADL gate model, board schema, dept
   charter, the role overlay's invariant paragraphs) — same bytes for every
   agent, every wave, every run.
2. The **deterministically sorted** tool list (sorted by tool name before
   serialisation) — order must never vary across calls for the same agent type.

**Nothing else belongs in the stable prefix.** In particular, the following
are PROHIBITED before the breakpoint:

- ISO timestamps (e.g. `2026-06-19T14:30:00Z`)
- Run IDs, wave counters, or UUIDs (`run-id`, `wave-N`, UUIDv4 patterns)
- Ticket IDs or ticket text (e.g. `DAS-1367`, ticket body)
- Per-wave summaries or current-state snapshots

### Minimum cacheable prefix

Opus 4.8's minimum cacheable prefix is **1024 tokens**. A breakpoint placed
after fewer than 1024 tokens of stable content causes the cache to emit a miss
on every call — no savings at all. (The earlier note of "4096" was stale and
referred to a different model generation; 1024 is the correct Opus 4.8 figure.)

Ensure the stable prefix is long enough to cross this threshold. If charter
consolidation trims the preamble, add a linter check (see below) rather than
silently losing the cache.

### Dynamic tail (after the last breakpoint)

All volatile content goes strictly after the last `cache_control` breakpoint,
in this order:

1. Global ticket summary (cross-wave board state snapshot)
2. Per-phase or per-epic summary
3. The specific ticket text (body + acceptance criteria)
4. Last-N scratchpad (recent agent outputs, ArcRift recall)
5. Run-id / wave counter / current timestamp

### Bounded STATUS summaries (~1–2k tokens)

The dynamic tail may include STATUS summaries — a compact digest of the current
wave state provided to each spawned subagent so it understands the broader
context without re-reading every ticket. Keep these **bounded to ~1–2k tokens**
per summary. A summary that grows without bound eventually defeats the cost
savings it was designed to enable. Enforce this in the wave-log or a dedicated
truncation pass before injection.

### CI enforcement (check_cache_prefix.py)

`scripts/check_cache_prefix.py` is the machine check for the above invariant.
It fails the build if:

- (a) The byte-content of the designated stable-prefix region changes without
  an accompanying version bump — prevents silent cache-version drift.
- (b) Any dynamic marker (ISO timestamp, run-id/UUID pattern, ticket-id
  pattern, wave counter) appears inside the stable-prefix region.
- (c) The stable-prefix region is shorter than 1024 tokens (Opus 4.8 minimum).

Run standalone: `python3 scripts/check_cache_prefix.py`
CI: wired into the `validate` job in `.github/workflows/ci.yml`.

CACHE_PREFIX_VERSION: v10-adr-renumber

## Boundaries

- You dispatch and route; you do NOT do the tickets' work yourself.
- Don't create tickets here (that's /daslab-plan) — except (a) a follow-up
  ticket a subagent's report explicitly asks for, or (b) the one approved-goal
  refill case above. New project discovery is never done by cycle.
- Board state lives only in the ticket files — never cache between waves.
