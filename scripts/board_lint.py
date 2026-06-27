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
   (no self-review).
9. Org board is platform-only: a ticket on ``board/tickets/`` must NOT declare a
   ``project:`` field — project tickets live in ``projects/<slug>/board-tickets/``
   (QONUN — Project Placement Law). Project boards (path ``…/board-tickets/``)
   are exempt; the field is valid there.

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = frozenset(
    {"backlog", "todo", "in_progress", "blocked", "in_review", "done"}
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
