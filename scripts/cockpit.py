#!/usr/bin/env python3
"""cockpit.py — Operator Cockpit v1.

A PASSIVE, live, six-panel, view-only cockpit, each panel bound to a REAL data
source. Where live telemetry does not exist yet (the loop is in shadow mode and no
waves have run), the panel says so plainly — nothing is mocked, no number is
fabricated. Threshold alerting, historical trends, and drill-down are deferred.
UAT: an operator can explain the current system state in plain
English from this cockpit alone — the plain-English glossary (--glossary) backs that.

Usage:
    python3 scripts/cockpit.py
    python3 scripts/cockpit.py --glossary
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import memory_lib
import metrics_lib
import wave_kpi
from _paths import ROOT

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None

GLOSSARY = {
    "QONUN-5": "The human-only approval law — new goals, security, schema migrations, GATE-5 deploys, "
               "governance, and permission/secret changes are NEVER auto-approved.",
    "AADL": "The six-stage lifecycle every build follows: Planning -> Design -> Development -> Testing -> "
            "Deployment -> Maintenance, each closed by a GATE.",
    "T1-T7": "The seven health metrics: T1 busy fraction, T2 idle waves, T3 concurrency, T4 cost/model-mix, "
             "T5 recovery, T6 review efficiency, T7 quality (the immutable hard blocker).",
    "GATE-6": "The evidence record every self-tuning change must file before it applies (max quality drop = 0).",
    "BREAK-GLASS": "A 60-minute, single-rollback emergency override — logged, auto-expiring, with a "
                   "mandatory post-incident review within 24h.",
    "shadow mode": "The self-optimizing loop is OFF: it may read metrics but applies no change. Real numbers "
                   "appear here once live waves run.",
    "intent preview": "Before an agent runs, see what it plans to do and whether it needs human approval "
                      "(scripts/intent_preview.py).",
    "escalation context": "When an agent escalates, the decision trace + recent memory + error context in one "
                          "package (scripts/escalation_context.py).",
    "approval digest": "Low-risk pending approvals batched into one summary; QONUN-5 items routed to individual "
                       "review (scripts/approval_digest.py).",
    "alerting": "Threshold-based proactive notifications; Quiet Mode alerts only on anomalies "
                "(scripts/alerting.py). P5 — trigger-gated.",
    "trends": "Time-series trend (improving/degrading) of the metrics over windows (scripts/trends.py). P5.",
    "adaptive taxonomy": "Proposes SOFT risk-tier recalibrations from history as GATE-6 drafts — NEVER the "
                         "immutable QONUN-5 list, never auto-applied (scripts/adaptive_taxonomy.py). P5.",
    "blind review": "Reviewer doesn't see the author + rotation, to prevent T6 reviewer drift "
                    "(scripts/check_blind_review.py). P5.",
    "loop controller": "Reports whether the self-optimizing loop may advance a rung "
                       "(shadow->measured->limited_live->full) — requires >=1wk clean live T1-T7 + a "
                       "human-approved GATE-6 record; NEVER auto-promotes (scripts/loop_controller.py). P6 capstone.",
}

NODATA = "(no data yet — appears once live waves run; the loop is in shadow mode)"


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:  # missing, a directory, or unreadable — treat as no data
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


def panel_current_wave(waves: list[dict]) -> list[str]:
    if not waves:
        return [NODATA]
    w = waves[-1]
    disp = w.get("disp") or []
    mix: dict[str, int] = {}
    for m in disp:
        mix[m] = mix.get(m, 0) + 1
    mix_str = ", ".join(f"{n} {mdl}" for mdl, n in sorted(mix.items())) or "none"
    return [
        f"latest wave: {w['start']:%Y-%m-%d %H:%M}",
        f"dispatched: {len(disp)} (models: {mix_str})",
    ]


def panel_frontier(waves: list[dict]) -> list[str]:
    r = metrics_lib.idle_wave_rates(waves)
    if r is None:
        return [NODATA]
    return [f"idle (T2a): {r['t2a_rate']:.0%}", f"blocked (T2b): {r['t2b_rate']:.0%}", f"over {r['total']} wave(s)"]


def panel_quality(events: list[dict]) -> list[str]:
    lines = ["T7 rubric: intact, immutable (hard blocker)"]
    eff = metrics_lib.review_efficiency(events)
    if eff is None:
        lines.append(f"reviews: {NODATA}")
    else:
        lines.append(
            f"reviews: {eff['reviews']}, rework {eff['rework_rate']:.0%}, "
            f"median cycle {eff['median_cycle_s'] / 60:.0f}m"
        )
    return lines


def panel_gate6(experiments: Path, events: list[dict]) -> list[str]:
    counts = {"applied": 0, "reverted": 0, "deferred": 0, "failed": 0}
    if yaml is not None and experiments.exists():
        for f in sorted(list(experiments.rglob("*.yaml")) + list(experiments.rglob("*.yml"))):
            if "TEMPLATE" in f.name.upper():
                continue
            try:
                data = yaml.safe_load(f.read_text())
            except yaml.YAMLError:
                continue
            rec = data.get("gate_6_record", data) if isinstance(data, dict) else None
            if isinstance(rec, dict):
                status = str((rec.get("result") or {}).get("status", "")).lower()
                if status in counts:
                    counts[status] += 1
    tuning = sum(1 for e in events if e.get("event_type") == "gate6_tuning" or e.get("change_type"))
    if sum(counts.values()) == 0 and tuning == 0:
        return ["no tuning changes — loop is OFF (shadow); ship levers, not results"]
    return [
        f"records: applied {counts['applied']}, reverted {counts['reverted']}, deferred {counts['deferred']}",
        f"tuning events: {tuning}",
    ]


def panel_risk(board: Path) -> list[str]:
    tickets_dir = board / "tickets"
    tickets = sorted(tickets_dir.glob("DAS-*.md")) if tickets_dir.is_dir() else []
    if not tickets:
        return [NODATA]
    p0 = blocked = in_review = 0
    for t in tickets:
        try:
            text = t.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # unreadable / directory — skip, never crash the cockpit
            continue
        fm = _frontmatter(text)
        p0 += fm.get("priority") == "p0"
        blocked += fm.get("status") == "blocked"
        in_review += fm.get("status") == "in_review"
    return [
        f"tickets: {len(tickets)}",
        f"p0 high-risk: {p0}, blocked: {blocked}, in-review (pending approval): {in_review}",
    ]


def panel_memory(store: Path, config: dict, now: datetime) -> list[str]:
    mems = _load_jsonl(store)
    if not mems:
        return ["no memory store yet (ArcRift is the live backend)"]
    recall = memory_lib.recallable(mems, now, config)
    health = memory_lib.memory_health(mems, now, config)
    return [f"memories: {len(mems)}, recallable: {len(recall)}", f"health score: {health:.0%}"]


def _render_panel(num: int, title: str, lines: list[str]) -> str:
    head = f"== {num}. {title} " + "=" * max(2, 50 - len(title))
    body = "\n".join(f"   {ln}" for ln in lines)
    return f"{head}\n{body}"


def render(events_path: Path, wave_log: Path, experiments: Path, board: Path,
           mem_store: Path, mem_config: Path, now: datetime) -> str:
    events = wave_kpi.read_events(str(events_path))
    waves = metrics_lib.read_waves(str(wave_log))
    config: dict = {}
    if yaml is not None and mem_config.is_file():
        try:
            loaded = yaml.safe_load(mem_config.read_text())
        except (OSError, yaml.YAMLError):
            loaded = None
        config = loaded if isinstance(loaded, dict) else {}
    panels = [
        ("Current Wave", panel_current_wave(waves)),
        ("Frontier Health", panel_frontier(waves)),
        ("Quality Health", panel_quality(events)),
        ("GATE-6 Decisions", panel_gate6(experiments, events)),
        ("Risk Escalations", panel_risk(board)),
        ("Memory Health", panel_memory(mem_store, config, now)),
    ]
    out = ["DasLab Operator Cockpit v1 (passive · live · shadow mode)", ""]
    out += [_render_panel(i, t, lines) for i, (t, lines) in enumerate(panels, 1)]
    out += [
        "",
        "Trust affordances (operator tools): intent_preview.py (what an agent will do before it runs),",
        "  approval_digest.py (batch low-risk approvals), escalation_context.py (diagnose an escalation).",
        "Proactive (P5, trigger-gated): alerting.py (threshold alerts + Quiet Mode), trends.py (metric trends).",
        "Capstone (P6): loop_controller.py reports loop-promotion eligibility — the loop stays OFF until a human approves.",
        "Tip: `cockpit.py --glossary` explains QONUN-5 / AADL / T1-T7 / GATE-6 in plain English.",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", type=Path, default=ROOT / "board" / ".events.jsonl")
    ap.add_argument("--wave-log", type=Path, default=ROOT / "board" / ".wave-log")
    ap.add_argument("--experiments", type=Path, default=ROOT / "experiments")
    ap.add_argument("--board", type=Path, default=ROOT / "board")
    ap.add_argument("--memory-store", type=Path, default=ROOT / "board" / ".arcrift-outbox.jsonl")
    ap.add_argument("--memory-config", type=Path, default=ROOT / "config" / "memory_governance.yaml")
    ap.add_argument("--glossary", action="store_true", help="print the plain-English glossary and exit")
    args = ap.parse_args(argv)

    if args.glossary:
        print("DasLab Cockpit — plain-English glossary\n")
        for term, meaning in GLOSSARY.items():
            print(f"{term}: {meaning}\n")
        return 0

    now = datetime.now(tz=UTC).replace(tzinfo=None)
    print(render(args.events, args.wave_log, args.experiments, args.board,
                 args.memory_store, args.memory_config, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
