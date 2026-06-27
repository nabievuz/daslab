#!/usr/bin/env python3
"""tests/test_check_dependency_graph.py — Phase 3 dependency graph (ADR-0016 / ADR-0002)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_dependency_graph as dg  # noqa: E402  (import after path manipulation)


def _board(tmp_path: Path, *tickets: tuple[str, str, str]) -> Path:
    """tickets: (id, depends_on_inline, zone). '' omits the field."""
    bdir = tmp_path / "board"
    bdir.mkdir(exist_ok=True)
    for tid, deps, zone in tickets:
        fm = f"---\nid: {tid}\nstatus: todo\nauthor: ceo\n"
        if deps:
            fm += f"depends_on: {deps}\n"
        if zone != "_OMIT_":
            fm += f"zone: {zone}\n"
        fm += "---\n\n## Description\nx\n"
        (bdir / f"{tid}-t.md").write_text(fm, encoding="utf-8")
    return bdir


def _run(board: Path) -> int:
    return dg.main(["--board", str(board)])


def test_empty_board_passes(tmp_path):
    assert _run(_board(tmp_path, ("DAS-1", "", "_OMIT_"))) == 0


def test_valid_dependency_passes(tmp_path):
    assert _run(_board(tmp_path, ("DAS-1", "", "_OMIT_"), ("DAS-2", "[DAS-1]", "_OMIT_"))) == 0


def test_dangling_dependency_fails(tmp_path):
    assert _run(_board(tmp_path, ("DAS-2", "[DAS-9999]", "_OMIT_"))) == 1


def test_self_cycle_fails(tmp_path):
    assert _run(_board(tmp_path, ("DAS-1", "[DAS-1]", "_OMIT_"))) == 1


def test_two_node_cycle_fails(tmp_path):
    assert _run(_board(tmp_path, ("DAS-1", "[DAS-2]", "_OMIT_"), ("DAS-2", "[DAS-1]", "_OMIT_"))) == 1


def test_three_node_cycle_fails(tmp_path):
    board = _board(
        tmp_path,
        ("DAS-1", "[DAS-2]", "_OMIT_"),
        ("DAS-2", "[DAS-3]", "_OMIT_"),
        ("DAS-3", "[DAS-1]", "_OMIT_"),
    )
    assert _run(board) == 1


def test_dag_diamond_passes(tmp_path):
    board = _board(
        tmp_path,
        ("DAS-1", "", "_OMIT_"),
        ("DAS-2", "[DAS-1]", "_OMIT_"),
        ("DAS-3", "[DAS-1]", "_OMIT_"),
        ("DAS-4", "[DAS-2, DAS-3]", "_OMIT_"),
    )
    assert _run(board) == 0


def test_valid_zone_passes(tmp_path):
    assert _run(_board(tmp_path, ("DAS-1", "", "apps/web"))) == 0


def test_empty_zone_fails(tmp_path):
    assert _run(_board(tmp_path, ("DAS-1", "", ""))) == 1


def test_missing_board_dir_exit_2(tmp_path):
    assert dg.main(["--board", str(tmp_path / "nope")]) == 2


def test_real_repo_passes():
    assert dg.main([]) == 0


# --- skill-rule guards (the runtime same-zone / dep-blocked rules live in the skill) ---

def _cycle_skill_flat() -> str:
    p = REPO_ROOT / ".claude" / "skills" / "daslab-cycle" / "SKILL.md"
    return " ".join(p.read_text(encoding="utf-8").lower().split())


def test_skill_reads_zone_in_correctness_guard():
    assert "zone:" in _cycle_skill_flat()


def test_skill_keeps_dep_blocked_rule():
    skill = _cycle_skill_flat()
    assert "depends_on" in skill and "dep-blocked" in skill
