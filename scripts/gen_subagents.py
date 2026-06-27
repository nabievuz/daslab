#!/usr/bin/env python3
"""Generate Claude Code subagent definitions from the DasLab org tree.

For every <dept>/agents/<role-key>/AGENTS.md role overlay, emit
.claude/agents/<role-key>.md (the Claude Code subagent definition) plus
board/ROUTING.md (role -> reviewer/manager table used for in_review routing).

The overlays stay the single source of truth for each role's mission; the
generated subagent is a thin shim that (a) points the subagent at its overlay
and dept charter, and (b) states the file-based board protocol directly — edit the
ticket file; its `status`/`## Log` ARE the state, and there is no external API.

Re-run after editing any overlay. Idempotent — output is fully regenerated.
Runtime pilots tied to non-Claude runtimes are skipped (they were adapter
experiments, not Claude roles).
"""
import re

from _paths import ROOT

OUT = ROOT / ".claude" / "agents"
SKIP = set()  # (no external-runtime pilots)
DEPTS = ["governance", "engineering", "product", "design", "marketing", "operations"]

# Binding model allocation (board policy). The table in that file is the single
# source of truth: | `role` | opus/sonnet/haiku | effort | rationale | (ADR 0013).
# (Fable 5 is retired/disabled — Tier F runs on opus; there is no fable tier.)
MODEL_POLICY = ROOT / "governance" / "policies" / "model-allocation.md"
# Capture role, model, and the OPTIONAL Effort cell (col 3); rationale (col 4) is
# ignored. A 3-col row (no effort cell) fails this regex, so the table edit and
# this generator change land together (ADR 0013). Haiku's effort cell is blank.
ROW_RE = re.compile(
    r"^\|\s*`?([a-z0-9-]+)`?\s*\|\s*(opus|sonnet|haiku)\s*\|"
    r"\s*(max|xhigh|high|medium|low)?\s*\|",
    re.M,
)
# An explicit per-role Effort cell wins; this is the fallback for a blank cell.
# Haiku takes NO effort parameter (400 error) — its frontmatter omits the line.
EFFORT_DEFAULT_BY_MODEL = {"opus": "high", "sonnet": "medium"}


def load_alloc():
    if not MODEL_POLICY.exists():
        raise SystemExit(f"FATAL: {MODEL_POLICY} missing — model allocation is board policy")
    models, efforts = {}, {}
    for role, model, effort in ROW_RE.findall(MODEL_POLICY.read_text()):
        models[role] = model
        efforts[role] = None if model == "haiku" else (effort or EFFORT_DEFAULT_BY_MODEL[model])
    return models, efforts


def field(text, name):
    m = re.search(rf"^\-\s*\*\*{name}:\*\*\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()

    roles = []  # (key, display, dept, reports_to)
    for dept in DEPTS:
        for d in sorted((ROOT / dept / "agents").iterdir()):
            key = d.name
            overlay = d / "AGENTS.md"
            if key in SKIP or not overlay.exists():
                continue
            text = overlay.read_text()
            display = field(text, "Display name") or key
            reports = field(text, "Reports to")
            roles.append((key, display, dept, reports))

    models, efforts = load_alloc()
    missing = [k for k, _, _, _ in roles if k not in models]
    if missing:
        raise SystemExit(
            f"FATAL: no model row in {MODEL_POLICY.name} for: {', '.join(missing)} — "
            "add them to the allocation table, then re-run")

    for key, display, dept, reports in roles:
        overlay_rel = f"{dept}/agents/{key}/AGENTS.md"
        effort = efforts[key]
        effort_line = f"\neffort: {effort}" if effort else ""
        body = f"""---
name: {key}
model: {models[key]}{effort_line}
description: DasLab {dept} role — {display}. Spawn with exactly ONE ticket file path from board/tickets/ to execute that ticket per the role overlay. Reports to {reports or 'the Board'}.
---

You are **{display}** in DasLab's {dept} department, running as a Claude Code subagent.
Work from the repository root — your current working directory (the folder the Claude Code session was started in).

## Read first (one parallel batch — Read all three in a single message)
Issue these three Reads together as parallel tool calls, not one-by-one — they
have no dependency on each other, so reading them serially only adds latency:
- `{dept}/CLAUDE.md` — dept charter: what you may and may not decide.
- `{overlay_rel}` — YOUR role overlay: identity, mission, definition of done.
- `board/README.md` — the ticket schema and board rules.
Then read the ticket file named in your prompt and start work.

## How you work a ticket (binding)
- The *ticket* is the file in `board/tickets/` named in your prompt. Work ONLY that one (WIP = 1).
- Edit that file directly — there is no remote API to call; your edits ARE the state.
- Update the `status:` frontmatter field (and `updated:`) as the work moves.
- Append under `## Log`: `### <date> — {display}` + what you did / found / decided.
- This is a single run: do the ticket's next concrete step, update the file, and return.
- Dispatch pacing is the orchestrator's concern, not yours.

## Hard rules (AGENTS.md §6, unchanged in spirit)
- Engineering work in a git repo: one issue = one branch = one PR; a git worktree
  per issue; never commit to `main`; `in_review` requires a pushed branch/PR;
  `done` requires the PR merged with green CI.
- Never review your own work: when your work is ready, set `status: in_review`
  and set `assignee:` to your reviewer per `board/ROUTING.md` (your manager{': ' + reports if reports else ''}).
- Blocked → `status: blocked` + a precise reason in the log. Never sit silent.
- A decision above your charter authority → log an escalation in the ticket,
  leave status unchanged, and say so in your report.
- You cannot spawn other agents. Anything needing another role goes in the log
  + your report so the orchestrator routes it.

## Report
Your final message is read by the orchestrator, not a human. Return: ticket id,
what you changed, the new status, files/branches/PRs touched, and anything that
must be routed (reviews, escalations, new work discovered).
"""
        (OUT / f"{key}.md").write_text(body)
        print(f"  ✓ .claude/agents/{key}.md")

    routing = ["# Role routing — reviewer/manager per role", "",
               "> Generated by scripts/gen_subagents.py — do not edit by hand.",
               "> `in_review` tickets are assigned to the author's manager below;",
               "> if the manager IS the author, escalate one level (ultimately CTO/CEO).", "",
               "| Role key | Display name | Dept | Reports to (reviewer) |",
               "|---|---|---|---|"]
    for key, display, dept, reports in roles:
        routing.append(f"| `{key}` | {display} | {dept} | {reports or '—'} |")
    (ROOT / "board" / "ROUTING.md").write_text("\n".join(routing) + "\n")
    print(f"  ✓ board/ROUTING.md ({len(roles)} roles)")


if __name__ == "__main__":
    main()
