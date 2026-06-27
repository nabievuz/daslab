#!/usr/bin/env python3
"""check_metric_gaming.py — anti-gaming rule.

T1-T6 may count a unit of work ONLY if it ended in a merged PR + green CI + a T7
pass. This flags counted completions that lack that evidence — busy/concurrency
without delivered value must not inflate the metrics (Goodhart defence). It also
reports the orthogonal **T1b** high-impact-completion rate (T7 >= 0.90) for HUMAN
oversight only; T1b is never a target agents see, so it cannot be gamed. Reads the
event store; inert (exit 0) when there are no completions yet.

Exit codes: 0 = no gaming OR unmeasured, 1 = counted busywork found, 2 = usage error.

Usage:
    python3 scripts/check_metric_gaming.py [--events board/.events.jsonl]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import metrics_lib
import wave_kpi
from _paths import ROOT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", type=Path, default=ROOT / "board" / ".events.jsonl")
    args = ap.parse_args(argv)

    events = wave_kpi.read_events(str(args.events))
    gaming = metrics_lib.gaming_violations(events)
    if gaming is None:
        print("Anti-gaming: unmeasured — no completions yet. Gate inert (loop off).")
        return 0

    t1b = metrics_lib.t1b_high_impact(events)
    t1b_note = f" T1b high-impact rate {t1b['rate']:.3f} (human-oversight)." if t1b else ""

    if gaming["violations"]:
        sys.stderr.write("FAIL: anti-gaming (R-9) — counted work without delivered value:\n")
        for v in gaming["violations"]:
            sys.stderr.write(f"  - {v}\n")
        sys.stderr.write(
            f"\n{len(gaming['violations'])} of {gaming['completions']} completion(s) gamed.{t1b_note}\n"
        )
        return 1

    print(f"OK: {gaming['completions']} completion(s), all merged+CI+T7.{t1b_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
