#!/usr/bin/env python3
"""check_approved_goal_queue.py — QONUN-3 approved-goal-queue enforcement (ADR-0014).

QONUN-3: a project's board tickets may be created only from a Founder-approved
``projects/<name>/APPROVED-GOAL-QUEUE.md``. This validator enforces two layers:

A. QUEUE INTEGRITY (always runs): every ``APPROVED-GOAL-QUEUE.md`` that EXISTS must
   carry an explicit Founder approval marker (``APPROVED`` / ``TASDIQLANDI`` /
   ``founder_approved``). An unapproved queue must never masquerade as authorization.

B. TICKET -> QUEUE MAPPING (local only): a board ticket that DECLARES its project via
   a ``project: <slug>`` frontmatter field and is past ``backlog`` must have an
   approved ``projects/<slug>/`` queue.

   Placement note (QONUN — Project Placement Law): the org ``board/tickets/`` is
   platform-only and must NOT carry a ``project:`` field (``board_lint.py`` R9), so
   against the default ``--board board/tickets`` this mapping check finds nothing and
   is a vestigial backstop. The ``project:`` field — and therefore this check — applies
   when ``--board`` points at a project's own board (``projects/<slug>/board-tickets/``).

   Structural limit (honest): ``projects/`` is gitignored (QONUN-1 — each project is
   its own repo), so a fresh CI runner has an EMPTY ``projects/`` and **check B is
   skipped there**. The authoritative "no approved queue -> no tickets" enforcement is
   at ``/daslab-plan`` time, which has the local project tree; check B is the local
   developer backstop, and check A is the CI gate. Tickets without a ``project:`` field
   (org-engine work like ADRs/validators) are not project-scoped and are not checked.

Usage:
    python scripts/check_approved_goal_queue.py [--projects projects] [--board board/tickets]

Exit 0 = clean. Exit 1 = violation(s). Exit 2 = usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECTS = REPO_ROOT / "projects"
DEFAULT_TICKETS = REPO_ROOT / "board" / "tickets"
QUEUE_NAME = "APPROVED-GOAL-QUEUE.md"
APPROVAL_RE = re.compile(r"\b(APPROVED|TASDIQLANDI|founder_approved)\b", re.IGNORECASE)


def _fm_field(text: str, key: str) -> str | None:
    """Return a top-level YAML frontmatter scalar (lowercased), or None."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i] in ("---", "...")), None)
    if end is None:
        return None
    for line in lines[1:end]:
        if line.strip().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'").lower()
    return None


def _queue_approved(projects_dir: Path, slug: str) -> bool:
    queue = projects_dir / slug / QUEUE_NAME
    return queue.is_file() and bool(APPROVAL_RE.search(queue.read_text(encoding="utf-8", errors="ignore")))


def scan_queue_integrity(projects_dir: Path) -> list[tuple[str, str]]:
    """A — every existing queue carries a Founder approval marker."""
    violations: list[tuple[str, str]] = []
    for queue in sorted(projects_dir.glob(f"*/{QUEUE_NAME}")):
        text = queue.read_text(encoding="utf-8", errors="ignore")
        if not APPROVAL_RE.search(text):
            violations.append(
                (queue.parent.name,
                 "queue present but no explicit Founder approval marker "
                 "(APPROVED / TASDIQLANDI / founder_approved)")
            )
    return violations


def scan_ticket_mapping(board_dir: Path, projects_dir: Path) -> list[tuple[str, str]]:
    """B — a project-scoped, past-backlog ticket must have an approved project queue.

    Local-only: returns [] when projects_dir is absent (the CI state) since the
    gitignored queues are not present to check against.
    """
    if not projects_dir.is_dir() or not board_dir.is_dir():
        return []
    violations: list[tuple[str, str]] = []
    for md in sorted(board_dir.glob("DAS-*.md")):
        text = md.read_text(encoding="utf-8", errors="ignore")
        slug = _fm_field(text, "project")
        if not slug:
            continue
        if _fm_field(text, "status") == "backlog":
            continue  # not yet dispatchable
        if not _queue_approved(projects_dir, slug):
            violations.append(
                (md.name, f"declares project '{slug}' but projects/{slug}/{QUEUE_NAME} "
                          "is missing or not Founder-approved (QONUN-3)")
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", default=str(DEFAULT_PROJECTS))
    ap.add_argument("--board", default=str(DEFAULT_TICKETS))
    args = ap.parse_args(argv)

    projects_dir = Path(args.projects)
    board_dir = Path(args.board)

    if not projects_dir.is_dir():
        # CI state: gitignored projects/ absent -> nothing to check (both layers).
        print(f"OK: no projects/ directory ({projects_dir}) — nothing to check.")
        return 0

    queues = sorted(projects_dir.glob(f"*/{QUEUE_NAME}"))
    violations = scan_queue_integrity(projects_dir) + scan_ticket_mapping(board_dir, projects_dir)
    if violations:
        sys.stderr.write("FAIL: approved-goal-queue violations (QONUN-3):\n")
        for who, reason in violations:
            sys.stderr.write(f"  - {who}: {reason}\n")
        sys.stderr.write(f"\n{len(violations)} violation(s).\n")
        return 1

    print(f"OK: {len(queues)} queue(s) checked (integrity + local ticket→queue mapping), all Founder-approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
