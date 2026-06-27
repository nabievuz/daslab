#!/usr/bin/env python3
"""check_dependency_graph.py — Phase 3 ticket dependency graph (ADR-0016, ADR-0002).

Validates the OPTIONAL `depends_on:` / `zone:` board frontmatter:

- NO DANGLING DEPS — every id in a ticket's `depends_on` is a real board ticket.
- ACYCLIC — the `depends_on` graph has no cycle (a cycle would deadlock dispatch).
- WELL-FORMED ZONE — a present-but-empty `zone:` is a defect.

CI-safe / dormant: passes when no ticket uses these fields (the state today). The
runtime "no two same-zone tickets in one wave" rule is a /daslab-cycle property (not
repo state) and is guarded separately by a skill-token test, not here.

Usage:
    python scripts/check_dependency_graph.py [--board board/tickets]

Exit 0 = clean. Exit 1 = violation(s). Exit 2 = usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BOARD = REPO_ROOT / "board" / "tickets"
DAS_RE = re.compile(r"\bDAS-\d+\b")


def _fm_field(text: str, key: str) -> str | None:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i] in ("---", "...")), None)
    if end is None:
        return None
    for line in lines[1:end]:
        if line.strip().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def _load(board_dir: Path) -> tuple[dict[str, list[str]], dict[str, str | None], dict[str, str]]:
    """Return (deps_by_id, zone_by_id, file_by_id)."""
    deps: dict[str, list[str]] = {}
    zones: dict[str, str | None] = {}
    files: dict[str, str] = {}
    for md in sorted(board_dir.glob("DAS-*.md")):
        text = md.read_text(encoding="utf-8", errors="ignore")
        tid = (_fm_field(text, "id") or md.name.split("-t.md")[0]).strip()
        dep_raw = _fm_field(text, "depends_on")
        deps[tid] = DAS_RE.findall(dep_raw) if dep_raw else []
        zone_raw = _fm_field(text, "zone")
        zones[tid] = None if zone_raw is None else zone_raw.strip().strip('"').strip("'")
        files[tid] = md.name
    return deps, zones, files


def _find_cycle(deps: dict[str, list[str]]) -> list[str] | None:
    """Return a cycle path if the depends_on graph has one, else None (DFS, 3-colour)."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(deps, WHITE)

    def visit(node: str, path: list[str]) -> list[str] | None:
        colour[node] = GREY
        path.append(node)
        for nxt in deps.get(node, []):
            if nxt not in colour:
                continue  # dangling — reported separately
            if colour[nxt] == GREY:
                return path[path.index(nxt):] + [nxt]
            if colour[nxt] == WHITE:
                found = visit(nxt, path)
                if found:
                    return found
        colour[node] = BLACK
        path.pop()
        return None

    for n in deps:
        if colour[n] == WHITE:
            found = visit(n, [])
            if found:
                return found
    return None


def scan(board_dir: Path) -> list[tuple[str, str]]:
    deps, zones, files = _load(board_dir)
    all_ids = set(deps)
    violations: list[tuple[str, str]] = []

    for tid, dep_list in deps.items():
        for d in dep_list:
            if d not in all_ids:
                violations.append((files[tid], f"depends_on {d} — no such ticket on the board"))

    for tid, zone in zones.items():
        if zone is not None and zone == "":
            violations.append((files[tid], "zone: is present but empty"))

    cycle = _find_cycle(deps)
    if cycle:
        violations.append(("dependency-graph", "cycle: " + " → ".join(cycle)))

    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default=str(DEFAULT_BOARD))
    args = ap.parse_args(argv)

    board_dir = Path(args.board)
    if not board_dir.is_dir():
        sys.stderr.write(f"ERROR: board dir not found: {board_dir}\n")
        return 2

    violations = scan(board_dir)
    if violations:
        sys.stderr.write("FAIL: ticket dependency-graph violations (ADR-0016):\n")
        for who, reason in violations:
            sys.stderr.write(f"  - {who}: {reason}\n")
        sys.stderr.write(f"\n{len(violations)} violation(s).\n")
        return 1

    n_with_deps = sum(1 for d in _load(board_dir)[0].values() if d)
    print(f"OK: dependency graph acyclic, no dangling deps ({n_with_deps} ticket(s) declare depends_on).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
