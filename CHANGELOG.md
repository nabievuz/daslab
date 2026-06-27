# Changelog

All notable changes to DasLab are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and DasLab adheres to
[Semantic Versioning](https://semver.org/) (see [ADR 0022](docs/adr/0022-semantic-versioning-policy.md)).

## [1.0.0] — 2026-06-29

First public release of DasLab — a reproducible operating system for a 32-agent
AI software organization. A fresh `git clone` boots the entire org.

### Added

- **The 32-agent organization** — a four-level hierarchy (Board → CEO → C-suite →
  leads → ICs) across six departments, generated into `.claude/agents/` from the
  org tree and the model-allocation policy (opus ×10 / sonnet ×19 / haiku ×3).
- **The file-based board** — one ticket = one `board/tickets/DAS-*.md` file, with
  the `backlog → todo → in_progress → blocked → in_review → done` lifecycle. No
  timer, no server, no API.
- **Orchestration skills** — `/daslab-plan`, `/daslab-cycle`, and `/daslab-run`,
  with worktree-per-ticket concurrency and explicit per-dispatch model selection.
- **The AI-Agent Development Lifecycle (AADL)** — six gated stages
  (Planning → Design → Development → Testing → Deployment → Maintenance).
- **The quality engine** — the weighted 7-dimension 100/100 release gate
  (`scripts/diagnostics.py`) and the CI-enforced validator suite, including the
  fail-closed lint gate ([ADR 0021](docs/adr/0021-fail-closed-ruff-gate.md)).
- **The DGO-X control plane** — graph-orchestrated and gate-driven, running in
  shadow mode ([ADRs 0010–0012](docs/adr/)).
- **The ArcRift persistent-memory loop** — an optional MCP server for
  recall-at-start / store-at-end, scoped strictly per project.
- **The documentation set** — README, [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
  (with diagrams), [`docs/USAGE.md`](docs/USAGE.md), the ADR set
  ([`docs/adr/`](docs/adr/)), and CONTRIBUTING / SECURITY / CODE_OF_CONDUCT.

[1.0.0]: https://github.com/nabievuz/daslab/releases/tag/v1.0.0
