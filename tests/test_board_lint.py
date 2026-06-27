"""tests/test_board_lint.py — pytest suite for scripts/board_lint.py.

Each test builds a minimal in-memory board (a dict mapping ticket ID ->
frontmatter dict) or a temporary directory of .md files, then asserts that
the linter fires exactly the expected error(s).

Rules under test
----------------
R1  bad status enum
R2  unknown assignee
R3  unknown author
R4  missing parent (dangling parent reference)
R5  orphan subtask (has parent, no goal)
R6  in_review self-review
R7  required field missing
R8  invalid priority
R9  project: field forbidden on the org board/tickets/ (platform-only)
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# Make sure the scripts/ directory is importable regardless of how pytest is
# invoked.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from board_lint import lint_tickets, load_known_roles, load_tickets  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KNOWN_ROLES = frozenset(
    {
        "qa-eng",
        "qa-lead",
        "cto",
        "backend-eng-1",
        "backend-em",
        "senior-pm",
        "ceo",
        "sre-lead",
    }
)

_BASE_FM: dict[str, str] = {
    "id": "DAS-9001",
    "title": "Fixture ticket",
    "status": "todo",
    "assignee": "qa-eng",
    "author": "ceo",
    "dept": "engineering",
    "priority": "p1",
    "created": "2026-06-18",
    "updated": "2026-06-18",
    "parent": "",
    "goal": "",
}


def make_ticket(**overrides: str) -> dict[str, str]:
    """Return a valid frontmatter dict with the given fields overridden."""
    fm = dict(_BASE_FM)
    fm.update(overrides)
    return fm


def run_lint(tickets: list[dict[str, str]]) -> list[str]:
    """Run lint_tickets with a Path placeholder and return the error list."""
    fake_path = Path("board/tickets/DAS-FAKE.md")
    pairs = [(fake_path, t) for t in tickets]
    return lint_tickets(pairs, _KNOWN_ROLES)


def make_ticket_file(tmp_path: Path, fm: dict[str, str]) -> Path:
    """Write a full ticket .md file to *tmp_path* and return its path."""
    ticket_id = fm["id"]
    # load_tickets uses glob "DAS-*.md" — keep the DAS- prefix uppercase
    path = tmp_path / f"{ticket_id}-fixture.md"
    lines = ["---"]
    for k, v in fm.items():
        # Skip keys with empty values so parent/goal absence is explicit
        lines.append(f"{k}: {v}")
    lines += ["---", "", "## Description", "Fixture.", "", "## Log"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# R1 — bad status enum
# ---------------------------------------------------------------------------


def test_bad_status_fires() -> None:
    ticket = make_ticket(status="shipped")
    errors = run_lint([ticket])
    assert any("invalid status" in e for e in errors), errors
    assert any("shipped" in e for e in errors), errors


def test_valid_statuses_are_accepted() -> None:
    valid = ("backlog", "todo", "in_progress", "blocked", "in_review", "done")
    for s in valid:
        ticket = make_ticket(status=s, assignee="qa-lead", author="ceo")
        errors = run_lint([ticket])
        status_errors = [e for e in errors if "invalid status" in e]
        assert not status_errors, f"Status '{s}' unexpectedly flagged: {errors}"


# ---------------------------------------------------------------------------
# R2 — unknown assignee
# ---------------------------------------------------------------------------


def test_unknown_assignee_fires() -> None:
    ticket = make_ticket(assignee="ghost-user")
    errors = run_lint([ticket])
    assert any("unknown assignee" in e for e in errors), errors
    assert any("ghost-user" in e for e in errors), errors


def test_empty_assignee_is_accepted() -> None:
    """Empty assignee means 'needs routing' — that is valid per board rules."""
    ticket = make_ticket(assignee="")
    errors = run_lint([ticket])
    assignee_errors = [e for e in errors if "unknown assignee" in e]
    assert not assignee_errors, errors


# ---------------------------------------------------------------------------
# R3 — unknown author
# ---------------------------------------------------------------------------


def test_unknown_author_fires() -> None:
    ticket = make_ticket(author="nobody")
    errors = run_lint([ticket])
    assert any("unknown author" in e for e in errors), errors
    assert any("nobody" in e for e in errors), errors


# ---------------------------------------------------------------------------
# R4 — dangling parent reference
# ---------------------------------------------------------------------------


def test_dangling_parent_fires() -> None:
    """A parent ID that doesn't exist in the board should be flagged."""
    ticket = make_ticket(parent="DAS-9999", goal="v1-release")
    errors = run_lint([ticket])
    assert any("does not exist" in e for e in errors), errors
    assert any("DAS-9999" in e for e in errors), errors


def test_valid_parent_is_accepted() -> None:
    """When the parent ticket is in the same board, no error should fire."""
    parent_ticket = make_ticket(id="DAS-9000", status="done", parent="", goal="v1-release")
    child_ticket = make_ticket(
        id="DAS-9001", parent="DAS-9000", goal="v1-release"
    )
    fake_path = Path("board/tickets/DAS-FAKE.md")
    pairs = [(fake_path, parent_ticket), (fake_path, child_ticket)]
    errors = lint_tickets(pairs, _KNOWN_ROLES)
    parent_errors = [e for e in errors if "does not exist" in e]
    assert not parent_errors, errors


# ---------------------------------------------------------------------------
# R5 — orphan subtask (parent set but goal missing)
# ---------------------------------------------------------------------------


def test_orphan_subtask_fires() -> None:
    """Subtask with parent but no goal is an orphan — must be flagged."""
    parent_ticket = make_ticket(id="DAS-9000", parent="", goal="v1-release")
    orphan = make_ticket(id="DAS-9001", parent="DAS-9000", goal="")
    fake_path = Path("board/tickets/DAS-FAKE.md")
    pairs = [(fake_path, parent_ticket), (fake_path, orphan)]
    errors = lint_tickets(pairs, _KNOWN_ROLES)
    assert any("no 'goal'" in e or "goal" in e for e in errors), errors


# ---------------------------------------------------------------------------
# R6 — in_review self-review
# ---------------------------------------------------------------------------


def test_in_review_self_review_fires() -> None:
    ticket = make_ticket(status="in_review", assignee="qa-eng", author="qa-eng")
    errors = run_lint([ticket])
    assert any("self-review" in e for e in errors), errors


def test_in_review_different_reviewer_accepted() -> None:
    ticket = make_ticket(status="in_review", assignee="qa-lead", author="qa-eng")
    errors = run_lint([ticket])
    self_review_errors = [e for e in errors if "self-review" in e]
    assert not self_review_errors, errors


# ---------------------------------------------------------------------------
# R7 — required field missing
# ---------------------------------------------------------------------------


def test_missing_required_field_fires() -> None:
    ticket = make_ticket()
    del ticket["priority"]
    errors = run_lint([ticket])
    assert any("missing required field" in e for e in errors), errors
    assert any("priority" in e for e in errors), errors


def test_all_required_fields_accepted() -> None:
    ticket = make_ticket()
    errors = run_lint([ticket])
    required_errors = [e for e in errors if "missing required field" in e]
    assert not required_errors, errors


# ---------------------------------------------------------------------------
# R8 — invalid priority
# ---------------------------------------------------------------------------


def test_invalid_priority_fires() -> None:
    ticket = make_ticket(priority="critical")
    errors = run_lint([ticket])
    assert any("invalid priority" in e for e in errors), errors
    assert any("critical" in e for e in errors), errors


def test_valid_priorities_accepted() -> None:
    for p in ("p0", "p1", "p2"):
        ticket = make_ticket(priority=p)
        errors = run_lint([ticket])
        prio_errors = [e for e in errors if "invalid priority" in e]
        assert not prio_errors, f"Priority '{p}' unexpectedly flagged: {errors}"


# ---------------------------------------------------------------------------
# R9 — project: field forbidden on the org board (platform-only)
# ---------------------------------------------------------------------------


def test_project_field_on_org_board_fires() -> None:
    """A board/tickets/ ticket that declares project: must be flagged —
    project tickets belong in projects/<slug>/board-tickets/."""
    ticket = make_ticket(project="acme-app")
    errors = run_lint([ticket])  # run_lint uses a board/tickets/ path
    assert any("project tickets belong in" in e for e in errors), errors
    assert any("acme-app" in e for e in errors), errors


def test_no_project_field_on_org_board_ok() -> None:
    """An org-engine ticket (no project: field) on board/tickets/ is fine."""
    ticket = make_ticket()
    errors = run_lint([ticket])
    project_errors = [e for e in errors if "project tickets belong in" in e]
    assert not project_errors, errors


def test_project_field_on_project_board_is_exempt() -> None:
    """The same project: field on a project's own board (…/board-tickets/) is
    valid and must NOT fire R9."""
    ticket = make_ticket(project="acme-app")
    project_path = Path("projects/acme-app/board-tickets/DAS-7001-x.md")
    pairs = [(project_path, ticket)]
    errors = lint_tickets(pairs, _KNOWN_ROLES)
    project_errors = [e for e in errors if "project tickets belong in" in e]
    assert not project_errors, errors


# ---------------------------------------------------------------------------
# Integration — file-system round-trip via load_tickets
# ---------------------------------------------------------------------------


def test_load_tickets_roundtrip(tmp_path: Path) -> None:
    """Write a ticket to disk, load it, lint it — no violations expected."""
    fm = make_ticket(id="DAS-9001")
    make_ticket_file(tmp_path, fm)
    loaded = load_tickets(tmp_path)
    assert len(loaded) == 1
    errors = lint_tickets(loaded, _KNOWN_ROLES)
    assert not errors, errors


def test_load_tickets_bad_status_file(tmp_path: Path) -> None:
    """Ticket file with bad status must surface a violation after load."""
    fm = make_ticket(id="DAS-9002", status="wontfix")
    make_ticket_file(tmp_path, fm)
    loaded = load_tickets(tmp_path)
    errors = lint_tickets(loaded, _KNOWN_ROLES)
    assert any("invalid status" in e for e in errors), errors


def test_load_tickets_self_review_file(tmp_path: Path) -> None:
    """in_review ticket with self-review must be caught via load_tickets."""
    fm = make_ticket(
        id="DAS-9003", status="in_review", assignee="qa-eng", author="qa-eng"
    )
    make_ticket_file(tmp_path, fm)
    loaded = load_tickets(tmp_path)
    errors = lint_tickets(loaded, _KNOWN_ROLES)
    assert any("self-review" in e for e in errors), errors


# ---------------------------------------------------------------------------
# load_known_roles — verify ROUTING.md parsing
# ---------------------------------------------------------------------------


def test_load_known_roles_parses_routing(tmp_path: Path) -> None:
    """load_known_roles should return a set of role keys from a ROUTING.md stub."""
    routing_md = textwrap.dedent(
        """\
        # Role routing

        | Role key | Display name | Dept | Reports to |
        |---|---|---|---|
        | `qa-eng` | QA Engineer | engineering | QA Lead |
        | `cto` | CTO | engineering | CEO |
        | `backend-eng-1` | Backend Engineer 1 | engineering | Backend EM |
        """
    )
    routing_path = tmp_path / "ROUTING.md"
    routing_path.write_text(routing_md, encoding="utf-8")

    roles = load_known_roles(routing_path)
    assert "qa-eng" in roles
    assert "cto" in roles
    assert "backend-eng-1" in roles
    assert "nonexistent-role" not in roles
