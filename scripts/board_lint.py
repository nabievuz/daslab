#!/usr/bin/env python3
"""board_lint.py — validate every board/tickets/*.md against the DasLab ticket schema.

Reads every ``board/tickets/DAS-*.md`` file, parses YAML frontmatter, and
enforces the rules defined in ``board/README.md``.  Exits non-zero with a
human-readable error list on any violation; exits 0 (silent) when the board is
clean.

Rules enforced
--------------
1. Required fields present: id, title, status, assignee, author, dept, priority,
   created, updated.
2. ``status`` is one of the allowed enum values.
3. ``assignee`` is empty OR a known role key from ROUTING.md.
4. ``author`` is a known role key from ROUTING.md.
5. ``priority`` is one of p0 / p1 / p2.
6. Subtasks (``parent`` is non-empty) must also carry ``goal``.
7. ``parent`` references an ID that exists in the board (no dangling pointers).
8. ``in_review`` tickets: ``assignee`` must differ from ``author``
   (no self-review). This rule is scoped to ``status == "in_review"`` only, so
   an ``interrupted`` ticket is out of its scope — it is never rejected or
   stranded by R8 (DAS-1446 consumer sweep).
9. Org board is platform-only: a ticket on ``board/tickets/`` must NOT declare a
   ``project:`` field — project tickets live in ``projects/<slug>/board-tickets/``
   (QONUN — Project Placement Law). Project boards (path ``…/board-tickets/``)
   are exempt; the field is valid there.
10. ``merge_policy`` (OPTIONAL) is well-formed: when present its value is one of
   ``append-only`` / ``owner-exclusive`` / ``aggregate:<reducer>`` (grammar owned
   by ``scripts/merge_reducers.py``); a present-but-empty or unrecognized value
   is a defect, and a ``merge_policy`` declared WITHOUT a ``zone:`` anchor is a
   defect. R10 is a per-ticket grammar check only.

Wave correctness guard (exported, not a whole-board rule)
--------------------------------------------------------
The "never two tickets in the same repo ``zone:`` in one wave" correctness guard
(ADR-0016) is a **per-wave** property, not repo state — the board legitimately
holds many same-zone tickets across different waves. So it is NOT enforced over
the whole board here (that would false-positive). Instead this module exports
``same_zone_pair_allowed`` / ``zone_wave_conflicts`` — pure, fail-closed
decision helpers over a *candidate wave* that ``/daslab-cycle`` (and tests) call.
The default is unchanged: a same-zone pair is FORBIDDEN unless every member of
the same-zone group declares the SAME valid, permitting ``merge_policy``.

Usage::

    python3 scripts/board_lint.py [--board <path>] [--routing <path>]

Exit codes: 0 = clean, 1 = violations found, 2 = usage/IO error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _paths import ROOT
from merge_reducers import is_valid_policy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ``interrupted`` (added DAS-1446): a running agent paused itself to ask the
# Founder a question via an interrupt card (see board/interrupts/README.md). It
# is distinct from ``blocked`` (external-dependency stall, never auto-dispatched)
# and ``in_review`` (awaiting a reviewer). Legal transitions:
#   in_progress -> interrupted   (agent raises an interrupt card and yields)
#   interrupted -> in_progress   (Founder writes resume:<value>; re-enters wave)
#   interrupted -> blocked       (question abandoned; needs a log reason, R-per-board)
VALID_STATUSES = frozenset(
    {"backlog", "todo", "in_progress", "blocked", "in_review", "done", "interrupted"}
)
VALID_PRIORITIES = frozenset({"p0", "p1", "p2"})
REQUIRED_FIELDS = (
    "id",
    "title",
    "status",
    "assignee",
    "author",
    "dept",
    "priority",
    "created",
    "updated",
)

# Repo root is two levels up from this script (scripts/ -> root)
_REPO_ROOT = ROOT


# ---------------------------------------------------------------------------
# ROUTING.md parser — extract valid role keys
# ---------------------------------------------------------------------------

_ROLE_ROW_RE = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|", re.MULTILINE)


def load_known_roles(routing_path: Path) -> frozenset[str]:
    """Return the set of role keys listed in ROUTING.md."""
    text = routing_path.read_text(encoding="utf-8")
    return frozenset(_ROLE_ROW_RE.findall(text))


# ---------------------------------------------------------------------------
# Frontmatter parser — lightweight, no external deps
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*):[^\S\n]*(.*?)[^\S\n]*$', re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return key->value dict from YAML frontmatter, or None if absent/malformed."""
    m = _FM_RE.match(text)
    if not m:
        return None
    block = m.group(1)
    data: dict[str, str] = {}
    for key, value in _KV_RE.findall(block):
        # Strip inline YAML quotes if present
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        data[key] = value
    return data


# ---------------------------------------------------------------------------
# Tolerant field readers (zone / merge_policy)
# ---------------------------------------------------------------------------
# The regex parser captures every value as a raw string. These helpers strip
# surrounding whitespace and inline YAML quotes so callers compare clean values.
# They mirror the tolerant read pattern in check_dependency_graph._fm_field.

def _zone_of(fm: dict[str, str]) -> str:
    """Return the ticket's declared ``zone:``, cleaned; '' if absent/empty."""
    return fm.get("zone", "").strip().strip('"').strip("'")


def _merge_policy_of(fm: dict[str, str]) -> str:
    """Return the ticket's declared ``merge_policy:``, cleaned; '' if absent."""
    return fm.get("merge_policy", "").strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# Wave correctness guard — same-zone pair decision (exported, fail-closed)
# ---------------------------------------------------------------------------
# SAFETY: these decide whether two tickets touching the SAME repo zone may run
# in ONE wave. They are called by /daslab-cycle at dispatch (and by tests), NOT
# over the whole board (the board holds many same-zone tickets across waves).
# The default is fail-closed: a same-zone pair is forbidden UNLESS every member
# declares the SAME valid, permitting merge_policy for that zone.

def same_zone_pair_allowed(fm_a: dict[str, str], fm_b: dict[str, str]) -> bool:
    """Return True iff two tickets MAY co-dispatch in one wave.

    Fail-closed contract:
    - Different (or absent) zones → not a same-zone pair; the guard does not
      apply, so the pair is allowed (returns True).
    - SAME non-empty zone but no / mismatched / empty / invalid merge_policy →
      FORBIDDEN (returns False). This is the unchanged default.
    - SAME non-empty zone AND both declare the SAME valid permitting
      merge_policy → allowed (returns True).
    """
    za, zb = _zone_of(fm_a), _zone_of(fm_b)
    if not za or za != zb:
        return True  # not a same-zone pair — guard is silent
    pa, pb = _merge_policy_of(fm_a), _merge_policy_of(fm_b)
    if not pa or pa != pb:
        return False  # same zone, no shared policy → default forbids
    return is_valid_policy(pa)  # same zone + same valid permitting policy → OK


def zone_wave_conflicts(
    tickets: list[tuple[Path, dict[str, str]]],
) -> list[str]:
    """Return violation strings for same-zone groups in a *candidate wave*.

    A same-zone group of two or more tickets is permitted to co-dispatch ONLY
    when every member declares the SAME valid, permitting ``merge_policy``.
    Otherwise every such group is a violation (fail-closed default). Groups of
    one, and tickets with no ``zone:``, are ignored.
    """
    by_zone: dict[str, list[tuple[Path, dict[str, str]]]] = {}
    for path, fm in tickets:
        zone = _zone_of(fm)
        if zone:
            by_zone.setdefault(zone, []).append((path, fm))

    violations: list[str] = []
    for zone, group in sorted(by_zone.items()):
        if len(group) < 2:
            continue
        policies = {_merge_policy_of(fm) for _p, fm in group}
        if len(policies) == 1:
            (pol,) = tuple(policies)
            if pol and is_valid_policy(pol):
                continue  # zone opted in with one shared valid policy → allowed
        ids = sorted((fm.get("id") or p.name) for p, fm in group)
        violations.append(
            f"same-zone wave conflict on zone '{zone}': {ids} would co-dispatch "
            "but do not all declare the same permitting merge_policy "
            "(default forbids two same-zone tickets in one wave)"
        )
    return violations


# ---------------------------------------------------------------------------
# Ticket collection
# ---------------------------------------------------------------------------

def load_tickets(board_dir: Path) -> list[tuple[Path, dict[str, str]]]:
    """Return list of (path, frontmatter) for every DAS-*.md in *board_dir*."""
    results: list[tuple[Path, dict[str, str]]] = []
    for path in sorted(board_dir.glob("DAS-*.md")):
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm is None:
            # Treat missing frontmatter as an empty dict — R1 will catch it
            fm = {}
        results.append((path, fm))
    return results


# ---------------------------------------------------------------------------
# Lint rules
# ---------------------------------------------------------------------------

def lint_tickets(
    tickets: list[tuple[Path, dict[str, str]]],
    known_roles: frozenset[str],
) -> list[str]:
    """Apply all rules and return a list of human-readable violation strings."""
    errors: list[str] = []

    # Build a set of known ticket IDs for parent-reference check (rule 7)
    known_ids: set[str] = set()
    for _, fm in tickets:
        tid = fm.get("id", "").strip()
        if tid:
            known_ids.add(tid)

    for path, fm in tickets:
        ticket_label = fm.get("id") or path.name

        def err(msg: str, ticket_label: str = ticket_label) -> None:
            errors.append(f"{ticket_label}: {msg}")

        # R1 — Required fields
        for field in REQUIRED_FIELDS:
            if field not in fm:
                err(f"missing required field '{field}'")

        status = fm.get("status", "").strip()
        assignee = fm.get("assignee", "").strip()
        author = fm.get("author", "").strip()
        parent = fm.get("parent", "").strip()
        goal = fm.get("goal", "").strip()
        priority = fm.get("priority", "").strip()

        # R2 — status enum
        if status and status not in VALID_STATUSES:
            err(f"invalid status '{status}'; must be one of {sorted(VALID_STATUSES)}")

        # R3 — assignee is empty OR a known role
        if assignee and assignee not in known_roles:
            err(f"unknown assignee '{assignee}'")

        # R4 — author is a known role
        if author and author not in known_roles:
            err(f"unknown author '{author}'")

        # R5 — priority
        if priority and priority not in VALID_PRIORITIES:
            err(f"invalid priority '{priority}'; must be one of {sorted(VALID_PRIORITIES)}")

        # R6 — subtasks need goal
        if parent and not goal:
            err(f"subtask has parent '{parent}' but no 'goal' field")

        # R7 — parent must exist
        if parent and parent not in known_ids:
            err(f"parent '{parent}' does not exist in the board")

        # R8 — in_review cannot be self-reviewed
        if status == "in_review" and assignee and author and assignee == author:
            err(
                f"in_review ticket has assignee == author '{assignee}'; "
                "self-review is not allowed"
            )

        # R9 — org board/tickets/ is platform-only: no project: field.
        # The org board path contains "board/tickets/" (slash); a project's own
        # board is "…/board-tickets/" (hyphen), so the field stays valid there.
        project = fm.get("project", "").strip()
        on_org_board = "board/tickets/" in str(path).replace("\\", "/")
        if on_org_board and project:
            err(
                f"declares project '{project}' but lives on the org board/tickets/; "
                "project tickets belong in projects/<slug>/board-tickets/ "
                "(board/tickets/ is DasLab-platform only)"
            )

        # R10 — merge_policy grammar + zone anchor (per-ticket check).
        # Optional: additive, so tickets without it lint exactly as before. The
        # grammar is owned by scripts/merge_reducers.py (single source of truth).
        if "merge_policy" in fm:
            merge_policy = _merge_policy_of(fm)
            zone = _zone_of(fm)
            if not merge_policy:
                err("merge_policy is present but empty; remove it or set "
                    "append-only / owner-exclusive / aggregate:<reducer>")
            elif not is_valid_policy(merge_policy):
                err(f"invalid merge_policy '{merge_policy}'; allowed: "
                    "append-only, owner-exclusive, aggregate:<sum|union>")
            if merge_policy and not zone:
                err("merge_policy declared without a zone: to anchor it "
                    "(a merge policy relaxes the same-zone wave guard, so it "
                    "needs a zone)")

    return errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--board",
        type=Path,
        default=_REPO_ROOT / "board" / "tickets",
        help="Path to the board/tickets/ directory (default: auto-detected from repo root)",
    )
    p.add_argument(
        "--routing",
        type=Path,
        default=_REPO_ROOT / "board" / "ROUTING.md",
        help="Path to board/ROUTING.md (default: auto-detected from repo root)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    board_dir: Path = args.board
    routing_path: Path = args.routing

    if not board_dir.is_dir():
        print(f"ERROR: board directory not found: {board_dir}", file=sys.stderr)
        return 2
    if not routing_path.is_file():
        print(f"ERROR: ROUTING.md not found: {routing_path}", file=sys.stderr)
        return 2

    try:
        known_roles = load_known_roles(routing_path)
    except OSError as exc:
        print(f"ERROR reading ROUTING.md: {exc}", file=sys.stderr)
        return 2

    try:
        tickets = load_tickets(board_dir)
    except OSError as exc:
        print(f"ERROR reading board tickets: {exc}", file=sys.stderr)
        return 2

    errors = lint_tickets(tickets, known_roles)

    if errors:
        print(f"board_lint: {len(errors)} violation(s) found:\n", file=sys.stderr)
        for e in errors:
            print(f"  FAIL  {e}", file=sys.stderr)
        return 1

    print(f"board_lint: OK — {len(tickets)} ticket(s) checked, 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
