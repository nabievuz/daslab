#!/usr/bin/env python3
"""tests/test_cockpit.py — Operator Cockpit v1 (R-7 / ADR-007)."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cockpit  # noqa: E402  (import after path manipulation)

PANELS = ("Current Wave", "Frontier Health", "Quality Health",
          "GATE-6 Decisions", "Risk Escalations", "Memory Health")


def test_glossary_covers_key_terms(capsys):
    assert cockpit.main(["--glossary"]) == 0
    out = capsys.readouterr().out
    for term in ("QONUN-5", "AADL", "T1-T7", "GATE-6", "BREAK-GLASS", "shadow mode"):
        assert term in out


def test_renders_six_panels_with_no_data(tmp_path, capsys):
    rc = cockpit.main([
        "--events", str(tmp_path / "e.jsonl"),
        "--wave-log", str(tmp_path / "w.log"),
        "--experiments", str(tmp_path / "exp"),
        "--board", str(tmp_path / "board"),
        "--memory-store", str(tmp_path / "m.jsonl"),
        "--memory-config", str(REPO_ROOT / "config" / "memory_governance.yaml"),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    for title in PANELS:
        assert title in out
    assert "shadow mode" in out  # honest: no fabricated numbers


def test_panel_current_wave_empty_is_nodata():
    assert cockpit.panel_current_wave([]) == [cockpit.NODATA]


def test_panel_memory_with_data(tmp_path):
    store = tmp_path / "m.jsonl"
    store.write_text(
        json.dumps({
            "id": "m1", "content": "x", "project": "p", "provenance": "verified_pr",
            "trust_score": 1.0, "created_at": "2026-06-20T00:00:00Z", "mem_type": "fact",
        }) + "\n",
        encoding="utf-8",
    )
    cfg = {"recall": {"min_trust": 0.3}, "ttl_days": {"fact": 180, "default": 120}, "health": {"decay_per_bad": 0.05}}
    lines = cockpit.panel_memory(store, cfg, dt.datetime(2026, 6, 21))
    assert any("memories: 1" in ln for ln in lines)
    assert any("recallable: 1" in ln for ln in lines)


def test_gate6_panel_shadow_when_empty(tmp_path):
    lines = cockpit.panel_gate6(tmp_path / "nope", [])
    assert any("loop is OFF" in ln for ln in lines)


def test_real_run_exits_0():
    # against the real (shadow) repo state -> always exit 0 (passive view, not a gate)
    assert cockpit.main([]) == 0


def _render_args(tmp_path, **over):
    args = {
        "events": tmp_path / "e.jsonl", "wave-log": tmp_path / "w.log",
        "experiments": tmp_path / "exp", "board": tmp_path / "board",
        "memory-store": tmp_path / "m.jsonl",
        "memory-config": REPO_ROOT / "config" / "memory_governance.yaml",
    }
    args.update(over)
    out = []
    for k, v in args.items():
        out += [f"--{k}", str(v)]
    return out


def test_survives_unreadable_ticket(tmp_path):
    # a directory named like a ticket makes read_text raise OSError -> must NOT crash
    tickets = tmp_path / "board" / "tickets"
    tickets.mkdir(parents=True)
    (tickets / "DAS-1-ok.md").write_text("---\nid: DAS-1\npriority: p0\nstatus: todo\n---\n", encoding="utf-8")
    (tickets / "DAS-2-bad.md").mkdir()
    assert cockpit.main(_render_args(tmp_path)) == 0


def test_survives_directory_memory_store(tmp_path):
    store_dir = tmp_path / "storedir"
    store_dir.mkdir()
    assert cockpit.main(_render_args(tmp_path, **{"memory-store": store_dir})) == 0
