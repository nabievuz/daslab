# Architecture Decision Records (ADRs)

Each ADR records one significant, hard-to-reverse decision: its **context**, the
**decision**, and the **consequences** we accept. ADRs are append-only — a
superseded decision gets a new ADR that references the old one, rather than an
edit in place. New ADRs take the next free number.

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-status-handoff-protocol.md) | Completion status protocol + finding format | Accepted | 2026-06-06 |
| [0002](0002-enforcement-as-code.md) | Enforcement-as-code — advisory laws become CI-gating validators | Accepted | 2026-06-18 |
| [0003](0003-self-locating-root.md) | Self-locating repository root (no hardcoded paths) | Accepted | 2026-06-18 |
| [0004](0004-project-agnostic-engine.md) | Project-agnostic engine (one factory, any goal) | Accepted | 2026-06-18 |
| [0005](0005-worktree-per-ticket-dispatch-ownership.md) | Worktree-per-ticket dispatch ownership | Proposed | 2026-06-19 |
| [0006](0006-static-cache-prefix-layout.md) | Static cache-prefix layout + invalidation rule | Proposed | 2026-06-19 |
| [0007](0007-model-retier-cascade-boundary.md) | Model re-tier boundary: haiku-eligible vs. opus floor | Proposed | 2026-06-19 |
| [0008](0008-nonblocking-arcrift-memory-loop.md) | Non-blocking ArcRift memory loop | Proposed | 2026-06-19 |
| [0009](0009-harness-owns-transport-admission-layer.md) | Harness owns the LLM transport — LAW 8 is an admission layer, a proxy only in a future SDK runner | Proposed | 2026-06-19 |
| [0010](0010-adopt-dgox-graph-orchestrated-control-plane.md) | Adopt DGO-X — graph-orchestrated, gate-driven control plane; phased + feature-flagged | Accepted | 2026-06-20 |
| [0011](0011-dgox-phase-1-data-contracts.md) | DGO-X Phase-1 data contracts — `graph_state`, append-only event store, board adapter, shadow-mode rule | Accepted | 2026-06-20 |
| [0012](0012-dgox-event-store-content-classification-redaction-policy.md) | DGO-X event store content-classification + redaction policy (the P2/P3 tool-event security contract) | Accepted | 2026-06-22 |
| [0013](0013-effort-tier-boundary.md) | Effort-tier boundary — per-role `effort` under a fixed opus floor | Accepted | 2026-06-26 |
| [0014](0014-native-clarify-gate.md) | Native ticket-altitude Clarify gate — `[NEEDS CLARIFICATION]` marker + Definition-of-Ready | Accepted | 2026-06-26 |
| [0015](0015-spec-driven-epic-layer.md) | Size-gated per-epic `SPEC.md` + `FR-NNN`/`SC-NNN` traceability | Accepted | 2026-06-26 |
| [0016](0016-ticket-dependency-graph.md) | Machine-readable ticket dependency graph (`depends_on` + `zone`) | Accepted | 2026-06-26 |
| [0017](0017-release-scorer-real-quality.md) | Release scorer measures real quality (ruff gate), not just artifact presence | Accepted | 2026-06-27 |
| [0018](0018-role-overlay-contract.md) | Role-overlay contract — Mission / Scope / Definition of Done / Escalation in every overlay | Accepted | 2026-06-27 |
| [0019](0019-latent-machine-feature-flags.md) | Latent-machine feature flags — DGO-X shadow + T4/T7 governors default OFF | Accepted | 2026-06-27 |
| [0020](0020-gate-promotion-no-false-green.md) | Gate promotion — warn→enforce only with data discipline; unmeasured is SKIPPED, not green | Accepted | 2026-06-27 |
| [0021](0021-fail-closed-ruff-gate.md) | The lint gate is fail-closed — an absent `ruff` fails the Code-quality dimension; an unmeasured lint never scores 100 | Accepted | 2026-06-27 |
| [0022](0022-semantic-versioning-policy.md) | Semantic versioning & release policy — `VERSION` + `CHANGELOG.md` + annotated tags / GitHub Releases; the release gate enforces VERSION/CHANGELOG | Accepted | 2026-06-29 |

## Themes

- **Foundations ([0001](0001-status-handoff-protocol.md)–[0004](0004-project-agnostic-engine.md)).**
  The completion/handoff protocol, enforcement-as-code (laws become CI-gating
  validators with `diagnostics.py` as the 100/100 release gate), a self-locating
  repository root, and the project-agnostic engine principle.
- **Concurrency, cost & memory ([0005](0005-worktree-per-ticket-dispatch-ownership.md)–[0009](0009-harness-owns-transport-admission-layer.md)).**
  Worktree-per-ticket dispatch ownership, a byte-stable static cache prefix,
  the model re-tier boundary under a fixed opus floor, the non-blocking ArcRift
  memory loop, and the honest ceiling that the harness owns the LLM transport
  (LAW 8 is an admission layer, not a transport proxy).
- **DGO-X control plane ([0010](0010-adopt-dgox-graph-orchestrated-control-plane.md)–[0012](0012-dgox-event-store-content-classification-redaction-policy.md)).**
  Adopting the graph-orchestrated, gate-driven control plane (phased and
  feature-flagged, in shadow mode), its Phase-1 data contracts, and the event
  store's content-classification + redaction policy.
- **Planning, quality & release gates ([0013](0013-effort-tier-boundary.md)–[0022](0022-semantic-versioning-policy.md)).**
  Per-role effort tiers, the Clarify gate / Definition-of-Ready, the optional
  size-gated spec layer and ticket dependency graph, a real-quality release
  scorer, the role-overlay contract, latent-machine feature flags,
  data-disciplined gate promotion (no false green), a fail-closed lint gate, and
  the semantic-versioning & release policy.
