#!/usr/bin/env python3
"""loop_controller.py — Self-optimization loop promotion controller.

The self-optimizing loop is promoted up the ladder

    shadow -> measured -> limited_live -> full

ONE rung at a time, and ONLY when BOTH hold:
  1. >= 1 week (7 days) of clean live T1-T7 readings, AND
  2. a complete, HUMAN-APPROVED GATE-6 capability_promotion record (max_quality_drop 0)
     authorizing exactly that rung.

This controller NEVER promotes anything — it EVALUATES eligibility and (with
--propose) emits an UNAPPROVED GATE-6 draft. Applying a promotion means editing
config/loop.yaml, which is a governance change -> never-auto-approve (QONUN-5). So
the loop stays OFF until a human, holding real evidence, signs off. With no live
data (the state today) it reports 'not eligible' and never fabricates readiness.

Exit codes: 0 (an evaluator/reporter — never a mutator).

Usage:
    python3 scripts/loop_controller.py
    python3 scripts/loop_controller.py --propose
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from _paths import ROOT

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write("PyYAML required: pip install pyyaml\n")
    sys.exit(2)

LADDER = ["shadow", "measured", "limited_live", "full"]
MIN_CLEAN_DAYS = 7

# Promotion-readiness targets (PRD-001 §1). A clean day meets all of these + T7 holds.
DEFAULT_TARGETS = {"t1_min": 0.60, "t2_max": 0.15, "t3_min": 6, "t4_min": 0.25, "t5_min": 0.99}


def next_mode(current: str) -> str | None:
    """The next rung up the ladder, or None at the top / for an unknown mode.
    One rung only — promotions can never skip a stage (C4)."""
    if current not in LADDER:
        return None
    i = LADDER.index(current)
    return LADDER[i + 1] if i + 1 < len(LADDER) else None


def day_is_clean(day: dict, targets: dict) -> bool:
    """A day is clean iff every gated metric meets its target and T7 holds."""
    if not isinstance(day, dict):
        return False
    try:
        return (
            float(day.get("t1", -1)) >= targets["t1_min"]
            and float(day.get("t2", 1)) <= targets["t2_max"]
            and float(day.get("t3", -1)) >= targets["t3_min"]
            and float(day.get("t4", -1)) >= targets["t4_min"]
            and float(day.get("t5", -1)) >= targets["t5_min"]
            and bool(day.get("t7_holds", False))
        )
    except (TypeError, ValueError):
        return False


def clean_live_days(metrics_history: list[dict], targets: dict) -> int:
    """Consecutive clean days at the END of the (oldest->newest) history."""
    streak = 0
    for day in reversed(metrics_history):
        if day_is_clean(day, targets):
            streak += 1
        else:
            break
    return streak


def has_approved_promotion_record(records: list[dict], current: str, target: str) -> bool:
    """A complete, HUMAN-APPROVED GATE-6 record authorizing exactly current->target.
    A draft (approved_by empty) never counts — only a human sign-off authorizes."""
    for rec in records:
        r = rec.get("gate_6_record", rec) if isinstance(rec, dict) else None
        if not isinstance(r, dict) or r.get("change_type") != "capability_promotion":
            continue
        pc = r.get("proposed_change")
        if not (isinstance(pc, dict) and pc.get("from_mode") == current and pc.get("to_mode") == target):
            continue
        if (r.get("guardrails") or {}).get("max_quality_drop") not in (0, 0.0):
            continue
        approver = (r.get("approval") or {}).get("approved_by")
        if isinstance(approver, str) and approver.strip():  # a draft ('' or whitespace) never counts
            return True
    return False


def evaluate_promotion(current_mode: str, records: list[dict], metrics_history: list[dict],
                       targets: dict) -> dict:
    """Report (never apply) promotion eligibility for the next rung."""
    if current_mode not in LADDER:
        return {"eligible": False, "current": current_mode, "target": None,
                "blockers": [f"unknown loop mode {current_mode!r}"], "clean_days": 0}
    target = next_mode(current_mode)
    if target is None:
        return {"eligible": False, "current": current_mode, "target": None,
                "blockers": ["already at 'full' — no further promotion"], "clean_days": 0}

    streak = clean_live_days(metrics_history, targets)
    blockers: list[str] = []
    if streak < MIN_CLEAN_DAYS:
        blockers.append(f"insufficient clean live evidence: {streak}/{MIN_CLEAN_DAYS} clean day(s)")
    if not has_approved_promotion_record(records, current_mode, target):
        blockers.append(f"no human-approved GATE-6 record for promotion {current_mode}->{target}")
    return {"eligible": not blockers, "current": current_mode, "target": target,
            "blockers": blockers, "clean_days": streak}


def promotion_draft(current: str, target: str, created_at: str) -> dict:
    """An UNAPPROVED GATE-6 promotion draft (human must fill evidence + approve to apply)."""
    return {"gate_6_record": {
        "id": f"GATE6-PROMOTE-{current}-to-{target}",
        "created_at": created_at,
        "proposed_by": "loop_controller",
        "change_type": "capability_promotion",
        "hypothesis": f"Promote the self-optimizing loop {current} -> {target} after >=1 week clean live T1-T7.",
        "baseline_metrics": {"note": "one-week live T1-T7 readings"},
        "proposed_change": {"description": f"loop mode {current} -> {target}", "from_mode": current,
                            "to_mode": target, "config_diff_hash": "sha256:PENDING", "blast_radius": "high"},
        "guardrails": {"max_quality_drop": 0, "rollback_condition": "revert to previous mode on any T7 drop or incident"},
        "evidence": {"trace_ids": [], "ci_runs": [], "review_ids": [], "experiment_ids": []},
        "approval": {"required_role": "founder", "approved_by": "", "approved_at": ""},
        "rollout": {"mode": "shadow"},
        "result": {"status": "deferred"},
    }}


def _load_yaml(path: Path) -> dict:
    try:
        loaded = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _load_records(experiments: Path) -> list[dict]:
    records: list[dict] = []
    if not experiments.exists():
        return records
    for f in sorted(list(experiments.rglob("*.yaml")) + list(experiments.rglob("*.yml"))):
        if "TEMPLATE" in f.name.upper():
            continue
        try:
            data = yaml.safe_load(f.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--loop-config", type=Path, default=ROOT / "config" / "loop.yaml")
    ap.add_argument("--experiments", type=Path, default=ROOT / "experiments")
    ap.add_argument("--metrics-history", type=Path, default=ROOT / "board" / ".metrics-history.jsonl")
    ap.add_argument("--propose", action="store_true", help="emit an unapproved GATE-6 promotion draft")
    args = ap.parse_args(argv)

    current = str(_load_yaml(args.loop_config).get("mode", "shadow"))
    result = evaluate_promotion(current, _load_records(args.experiments),
                                _load_jsonl(args.metrics_history), DEFAULT_TARGETS)

    if result["eligible"]:
        print(
            f"Loop promotion {result['current']} -> {result['target']}: ELIGIBLE "
            f"({result['clean_days']} clean day(s) + an approved GATE-6 record). Applying is a governance "
            f"change (a human edits config/loop.yaml) — never auto-applied."
        )
        return 0

    print(f"Loop stays in '{result['current']}' — promotion NOT eligible:")
    for blocker in result["blockers"]:
        print(f"  - {blocker}")
    if args.propose and result["target"]:
        draft = promotion_draft(result["current"], result["target"],
                                datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        print("\nProposed GATE-6 promotion DRAFT (UNAPPROVED — fill evidence + human approval to apply):")
        print(json.dumps(draft["gate_6_record"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
