"""dgox/events.py — DGO-X Phase-1 append-only event store.

Implements the JSONL event store specified in ADR 0011 §2.  Writes one JSON
object per line to ``board/.events.jsonl`` (gitignored runtime state, like
``board/.wave-log`` and ``board/.arcrift-outbox.jsonl``).

Design principles (from ADR 0011):
- Append-only, NEVER rewritten.  A correction is a new compensating event.
- One event per routing / tool / gate / approval / run change.
- Common envelope: ``event_type``, ``ticket_id``, ``created_at``, ``run_id``.
- Two load-bearing shapes: ``routing_decision`` (§8.2) and
  ``agent_invocation`` (§8.3).
- Durable, concurrency-safe append: uses ``O_APPEND`` + ``O_CREAT`` on POSIX
  (single-system-call atomic-line-append guarantee on POSIX; single-writer
  discipline recommended at the orchestrator level).
- Pure-Python, self-locating root via ``scripts/_paths``; no network.
- ``created_at`` is an *argument*, never generated inside pure helpers —
  callers pass a timestamp so helpers are fully deterministic and testable.
  A convenience wrapper ``utcnow()`` is provided for production callers.

Usage (library):

    from dgox.events import EventStore, build_routing_decision, build_agent_invocation

    store = EventStore()               # writes to board/.events.jsonl
    ts = "2026-06-20T00:00:00Z"
    ev = build_routing_decision(
        ticket_id="DAS-1234",
        from_status="todo",
        to_status="in_progress",
        assignee="backend-eng-1",
        model="sonnet",
        reason="Stage 3 backend implementation.",
        confidence=0.91,
        policy_checks=["aadl_predecessor_gate_closed", "repo_area_available"],
        fallback="block_and_escalate_to_backend-em",
        created_at=ts,
    )
    store.append(ev)

Shadow mode (ADR 0011 §4): the store is an advisory observer in Phase 1.
Nothing dispatches off the events it contains.  /daslab-cycle is unaffected.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Self-locating root (LAW A — never a hardcoded path).
# When imported from within the scripts/ namespace the regular sys.path
# already has scripts/ at index 0 via the package or a direct run.
# ---------------------------------------------------------------------------

def _resolve_root() -> Path:
    """Resolve the repo root at import time (same logic as scripts/_paths.py)."""
    override = os.environ.get("DASLAB_ROOT")
    if override:
        return Path(override).resolve()
    try:
        import subprocess
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if top:
            return Path(top).resolve()
    except Exception:
        pass
    # Fallback: scripts/dgox/events.py → scripts/dgox/ → scripts/ → repo root
    return Path(__file__).resolve().parents[2]


_ROOT = _resolve_root()

# Canonical path for the event store (gitignored runtime state — ADR 0011 §2).
DEFAULT_STORE_PATH: Path = _ROOT / "board" / ".events.jsonl"

# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string ending in 'Z'.

    This is the *only* place ``datetime.now()`` is called in this module.
    Pure builder/validator helpers receive ``created_at`` as an argument so
    they remain deterministic and easy to test without monkeypatching.
    """
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

_ENVELOPE_REQUIRED = frozenset({"event_type", "ticket_id", "created_at"})
_VALID_EVENT_TYPES = frozenset(
    {
        "routing_decision",
        "agent_invocation",
        "state_violation",
        "mirror_divergence",
        # reserved for future phases:
        "gate_check",
        "approval",
        "tool_call",
        "run_start",
        "run_end",
        "tool_unavailable",
    }
)


def validate_envelope(event: dict[str, Any]) -> list[str]:
    """Return a list of validation errors for the common event envelope.

    An empty list means the envelope is valid.  Does NOT raise — callers
    decide whether errors are fatal.

    Envelope rules (ADR 0011 §2):
    - ``event_type`` present and a known type string.
    - ``ticket_id`` present and a non-empty string starting with ``DAS-``.
    - ``created_at`` present as a non-empty ISO-8601 string (basic check).
    - ``run_id``, if present, must be a non-empty string.
    """
    errors: list[str] = []
    for field in _ENVELOPE_REQUIRED:
        if field not in event or event[field] is None:
            errors.append(f"missing required field: {field!r}")
    et = event.get("event_type")
    if et is not None and et not in _VALID_EVENT_TYPES:
        errors.append(
            f"unknown event_type {et!r}; expected one of {sorted(_VALID_EVENT_TYPES)}"
        )
    tid = event.get("ticket_id")
    if tid is not None and (not isinstance(tid, str) or not tid.startswith("DAS-") or len(tid) <= 4):
        errors.append(
            f"ticket_id must be a string starting with 'DAS-'; got {tid!r}"
        )
    ca = event.get("created_at")
    if ca is not None and (not isinstance(ca, str) or not ca):
        errors.append(f"created_at must be a non-empty string; got {ca!r}")
    rid = event.get("run_id")
    if rid is not None and (not isinstance(rid, str) or not rid):
        errors.append(f"run_id must be a non-empty string when present; got {rid!r}")
    return errors


# ---------------------------------------------------------------------------
# Shape A — routing_decision (ADR 0011 §2, report §8.2)
# ---------------------------------------------------------------------------

_ROUTING_REQUIRED = frozenset(
    {
        "event_type",
        "ticket_id",
        "from_status",
        "to_status",
        "assignee",
        "model",
        "reason",
        "confidence",
        "policy_checks",
        "fallback",
        "created_at",
    }
)


def build_routing_decision(
    *,
    ticket_id: str,
    from_status: str,
    to_status: str,
    assignee: str,
    model: str,
    reason: str,
    confidence: float,
    policy_checks: list[str],
    fallback: str,
    created_at: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a ``routing_decision`` event dict (Shape A — ADR 0011 §2 / report §8.2).

    Args:
        ticket_id:     DAS-NNNN ticket identifier.
        from_status:   Source lifecycle status (e.g. ``"todo"``).
        to_status:     Target lifecycle status (e.g. ``"in_progress"``).
        assignee:      Role key being assigned (supervisor-authored; never a worker).
        model:         Explicit model name (LAW 3 / ADR 0007 — never inferred from
                       frontmatter, matching ADR 0011's ``model`` field spec).
        reason:        Human-readable routing rationale.
        confidence:    Supervisor confidence score in [0.0, 1.0].
        policy_checks: List of preflight gate names that must pass.
        fallback:      Deterministic action if a policy check fails.
        created_at:    ISO-8601 UTC timestamp string (caller-supplied; injectable
                       for tests — do NOT call ``utcnow()`` inside this helper).
        run_id:        Optional run correlation identifier.

    Returns:
        A dict conforming to the ``routing_decision`` shape ready for ``EventStore.append``.
    """
    event: dict[str, Any] = {
        "event_type": "routing_decision",
        "ticket_id": ticket_id,
        "from_status": from_status,
        "to_status": to_status,
        "assignee": assignee,
        "model": model,
        "reason": reason,
        "confidence": confidence,
        "policy_checks": list(policy_checks),
        "fallback": fallback,
        "created_at": created_at,
    }
    if run_id is not None:
        event["run_id"] = run_id
    return event


def validate_routing_decision(event: dict[str, Any]) -> list[str]:
    """Return validation errors for a ``routing_decision`` event.

    Checks the envelope first, then shape-specific constraints:
    - ``confidence`` in [0.0, 1.0].
    - ``policy_checks`` is a non-empty list of strings.
    - ``model`` is a non-empty string.
    - ``assignee`` is a non-empty string.
    """
    errors = validate_envelope(event)
    if event.get("event_type") not in (None, "routing_decision"):
        errors.append(
            f"event_type must be 'routing_decision'; got {event.get('event_type')!r}"
        )
    confidence = event.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, int | float) or not (0.0 <= float(confidence) <= 1.0)
    ):
        errors.append(
            f"confidence must be a float in [0.0, 1.0]; got {confidence!r}"
        )
    pc = event.get("policy_checks")
    if pc is not None and (not isinstance(pc, list) or not pc or not all(isinstance(s, str) for s in pc)):
        errors.append(
            "policy_checks must be a non-empty list of strings"
        )
    model = event.get("model")
    if model is not None and (not isinstance(model, str) or not model):
        errors.append("model must be a non-empty string")
    assignee = event.get("assignee")
    if assignee is not None and (not isinstance(assignee, str) or not assignee):
        errors.append("assignee must be a non-empty string")
    for field in ("from_status", "to_status", "reason", "fallback"):
        v = event.get(field)
        if v is not None and (not isinstance(v, str) or not v):
            errors.append(f"{field!r} must be a non-empty string")
    return errors


# ---------------------------------------------------------------------------
# Shape B — agent_invocation (ADR 0011 §2, report §8.3)
# ---------------------------------------------------------------------------

_AGENT_INVOCATION_REQUIRED = frozenset(
    {
        "event_type",
        "ticket_id",
        "run_id",
        "role_key",
        "model",
        "workspace_id",
        "context_contract",
        "allowed_tools",
        "secrets_policy",
        "exit_contract",
        "created_at",
    }
)


def build_agent_invocation(
    *,
    ticket_id: str,
    run_id: str,
    role_key: str,
    model: str,
    workspace_id: str,
    context_contract: dict[str, Any],
    allowed_tools: list[str],
    secrets_policy: str,
    exit_contract: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """Build an ``agent_invocation`` event dict (Shape B — ADR 0011 §2 / report §8.3).

    Args:
        ticket_id:        DAS-NNNN ticket identifier (board is canonical — ADR 0010 C2).
        run_id:           Correlation key joining this run across logs, events, traces,
                          CI, and the ticket log — the join key for all observability (P4).
        role_key:         ``.claude/agents/<role>.md``-compatible role identifier (RACI).
        model:            Explicit model dispatch — LAW 3 / ADR 0007, provider-abstracted,
                          never inferred from frontmatter (claude-code#44385).
        workspace_id:     Sandbox / worktree identity (ADR 0005 worktree = f(ticket)).
        context_contract: Minimal task context dict — NEVER raw full org state (report §10
                          prompt-injection control; Security-consulted per ADR 0011 §2).
        allowed_tools:    Tool allowlist by task class (least privilege — report §10
                          worker-overreach control).
        secrets_policy:   Secrets handling policy — defaults to ``"no_secrets"``; only
                          ``"scoped_creds_gate_approved"`` when gate-approved (report §10).
        exit_contract:    Required exit conditions: ticket log entry, artifacts, test
                          evidence, memory store result (board audit law + ADR 0008
                          store-at-end; or explicit ``tool_unavailable``).
        created_at:       ISO-8601 UTC timestamp string (caller-supplied — injectable for
                          tests; do NOT call ``utcnow()`` inside this helper).

    Returns:
        A dict conforming to the ``agent_invocation`` shape ready for ``EventStore.append``.
    """
    return {
        "event_type": "agent_invocation",
        "ticket_id": ticket_id,
        "run_id": run_id,
        "role_key": role_key,
        "model": model,
        "workspace_id": workspace_id,
        "context_contract": dict(context_contract),
        "allowed_tools": list(allowed_tools),
        "secrets_policy": secrets_policy,
        "exit_contract": dict(exit_contract),
        "created_at": created_at,
    }


def validate_agent_invocation(event: dict[str, Any]) -> list[str]:
    """Return validation errors for an ``agent_invocation`` event.

    Checks the envelope first, then shape-specific constraints:
    - ``run_id`` is required (non-empty string).
    - ``role_key``, ``model``, ``workspace_id``, ``secrets_policy`` are non-empty strings.
    - ``context_contract`` and ``exit_contract`` are dicts.
    - ``allowed_tools`` is a list of strings.
    """
    errors = validate_envelope(event)
    if event.get("event_type") not in (None, "agent_invocation"):
        errors.append(
            f"event_type must be 'agent_invocation'; got {event.get('event_type')!r}"
        )
    # run_id is required for agent_invocation (not optional like in routing_decision)
    run_id = event.get("run_id")
    if not run_id or not isinstance(run_id, str):
        errors.append("run_id is required for agent_invocation and must be a non-empty string")
    for str_field in ("role_key", "model", "workspace_id", "secrets_policy"):
        v = event.get(str_field)
        if v is not None and (not isinstance(v, str) or not v):
            errors.append(f"{str_field!r} must be a non-empty string")
    for dict_field in ("context_contract", "exit_contract"):
        v = event.get(dict_field)
        if v is not None and not isinstance(v, dict):
            errors.append(f"{dict_field!r} must be a dict")
    at = event.get("allowed_tools")
    if at is not None and (
        not isinstance(at, list) or not all(isinstance(s, str) for s in at)
    ):
        errors.append("allowed_tools must be a list of strings")
    return errors


# ---------------------------------------------------------------------------
# Event store — durable, concurrency-safe JSONL appender
# ---------------------------------------------------------------------------


class EventStore:
    """Append-only JSONL event store (ADR 0011 §2).

    Appends one JSON line per event to ``path`` (default:
    ``board/.events.jsonl``).  Each line is a single ``json.dumps`` call
    followed by a newline — this is the JSONL contract.

    **Concurrency safety:** uses ``fcntl.flock(LOCK_EX)`` on POSIX before
    every write, releasing immediately after.  Combined with ``O_APPEND``
    semantics (which guarantee the kernel advances the file offset
    atomically on POSIX), this provides safe single-host concurrent writers.
    On non-POSIX systems (Windows) the lock is silently skipped; the module
    is intended for POSIX-only CI/run environments.

    The store is **write-only by design** — reading/replaying is handled by
    the free function ``iter_events`` (below), which never goes through this
    class so the store interface stays minimal.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_STORE_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, event: dict[str, Any]) -> None:
        """Append *event* to the store as a single JSONL line.

        The envelope is validated before writing.  If validation finds errors
        a ``ValueError`` is raised and nothing is written — the store is never
        left in a partial state.

        The parent directory is created on first use (``board/`` already
        exists in practice; the guard is for tests using tmp_path).
        """
        errors = validate_envelope(event)
        if errors:
            raise ValueError(
                f"Cannot append invalid event (errors: {errors}): {event!r}"
            )
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append mode — O_APPEND is atomic per POSIX on local filesystems.
        with open(self.path, "a", encoding="utf-8") as fh:
            with contextlib.suppress(AttributeError, OSError):
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                with contextlib.suppress(AttributeError, OSError):
                    fcntl.flock(fh, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Reader / replay helper
# ---------------------------------------------------------------------------


def iter_events(
    path: Path | str | None = None,
    *,
    ticket_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate over events from a JSONL store, with optional filters.

    Args:
        path:        Path to the JSONL store (default: ``board/.events.jsonl``).
        ticket_id:   If given, yield only events whose ``ticket_id`` matches.
        run_id:      If given, yield only events whose ``run_id`` matches.
        event_type:  If given, yield only events of this type.

    Yields:
        Parsed event dicts, in append order (oldest first).  Lines that
        cannot be parsed as JSON are silently skipped (corrupted/partial
        writes are tolerated in replay; they never corrupt the iterator).

    Notes:
        - The store file may not exist yet (no waves run): returns immediately.
        - This is a generator — it does not load the whole file into memory.
    """
    p = Path(path) if path is not None else DEFAULT_STORE_PATH
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ticket_id is not None and event.get("ticket_id") != ticket_id:
                continue
            if run_id is not None and event.get("run_id") != run_id:
                continue
            if event_type is not None and event.get("event_type") != event_type:
                continue
            yield event
