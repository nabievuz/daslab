#!/usr/bin/env python3
"""alerting.py — Threshold-based proactive alerting + Quiet Mode.

Turns the passive (look-only) cockpit into a proactive notifier: it reads the
current live state and raises an alert when a threshold is breached (config/
alert_thresholds.yaml). Quiet Mode (--quiet) emits only anomalies (warning /
critical), suppressing routine info — defeating noise-induced anxiety.

NOTE: With the loop off and no live waves, the readings are absent and the system
reports NO alerts — this ships the alerting LOGIC + thresholds, which activate
once live evidence exists.

Exit codes: 0 (a notifier); 1 only with --fail-on-critical when a critical alert fires.

Usage:
    python3 scripts/alerting.py
    python3 scripts/alerting.py --quiet --fail-on-critical
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import break_glass
import memory_lib
import wave_kpi
from _paths import ROOT

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write("PyYAML required: pip install pyyaml\n")
    sys.exit(2)

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
ANOMALY = {"warning", "critical"}


def evaluate_alerts(readings: dict, thresholds: dict) -> list[dict]:
    """Pure threshold evaluation: readings -> alerts, sorted critical-first."""
    alerts: list[dict] = []

    def add(severity: str, metric: str, message: str) -> None:
        alerts.append({"severity": severity, "metric": metric, "message": message})

    t1 = readings.get("t1_busy_fraction")
    if t1 is not None and t1 < thresholds.get("t1_busy_min", 0.60):
        add("warning", "T1", f"busy fraction {t1:.2f} below target {thresholds.get('t1_busy_min', 0.60)}")
    if readings.get("t7_regressed"):
        add("critical", "T7", "quality regression detected (hard blocker)")
    if readings.get("break_glass_active"):
        add("critical", "BREAK-GLASS", "an emergency override is ACTIVE")
    violations = readings.get("never_auto_violations", 0)
    if violations:
        n = len(violations) if isinstance(violations, list | tuple | set) else violations
        add("critical", "QONUN-5", f"{n} never-auto-approve violation(s)")
    mh = readings.get("memory_health")
    if mh is not None and mh < thresholds.get("memory_health_min", 0.80):
        add("warning", "memory", f"health {mh:.2f} below {thresholds.get('memory_health_min', 0.80)}")
    return sorted(alerts, key=lambda a: -SEVERITY_ORDER.get(a["severity"], 0))


def filter_quiet(alerts: list[dict]) -> list[dict]:
    """Quiet Mode: anomalies only (warning/critical), suppress routine info."""
    return [a for a in alerts if a["severity"] in ANOMALY]


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


def gather_readings(events: Path, memory_store: Path, memory_config: Path) -> dict:
    """Pull what live data supports; None / False / 0 where the data is absent (inert)."""
    evs = wave_kpi.read_events(str(events))
    t1, _ = wave_kpi.busy_fraction_from_events(evs)
    mems = _load_jsonl(memory_store)
    mh = memory_lib.memory_health(mems, datetime.now(tz=UTC).replace(tzinfo=None), _load_yaml(memory_config)) if mems else None
    return {
        "t1_busy_fraction": t1,
        "memory_health": mh,
        "break_glass_active": break_glass.is_active(datetime.now(tz=UTC), str(events)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", type=Path, default=ROOT / "board" / ".events.jsonl")
    ap.add_argument("--memory-store", type=Path, default=ROOT / "board" / ".arcrift-outbox.jsonl")
    ap.add_argument("--memory-config", type=Path, default=ROOT / "config" / "memory_governance.yaml")
    ap.add_argument("--thresholds", type=Path, default=ROOT / "config" / "alert_thresholds.yaml")
    ap.add_argument("--quiet", action="store_true", help="emit anomalies only (suppress routine info)")
    ap.add_argument("--fail-on-critical", action="store_true", help="exit 1 if a critical alert fires (CI)")
    args = ap.parse_args(argv)

    thresholds = _load_yaml(args.thresholds).get("thresholds", {})
    readings = gather_readings(args.events, args.memory_store, args.memory_config)
    alerts = evaluate_alerts(readings, thresholds)
    if args.quiet:
        alerts = filter_quiet(alerts)

    if not alerts:
        print("Alerts: none — system nominal (or no live data yet; P5 alerting is trigger-gated).")
        return 0

    for a in alerts:
        print(f"[{a['severity'].upper()}] {a['metric']}: {a['message']}")
    if args.fail_on_critical and any(a["severity"] == "critical" for a in alerts):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
