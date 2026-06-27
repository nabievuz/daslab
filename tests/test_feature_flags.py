#!/usr/bin/env python3
"""tests/test_feature_flags.py — latent-machine feature flags (ADR-0019 / ADR-0002, P10)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import feature_flags as ff  # noqa: E402  (import after path manipulation)


def test_real_config_has_both_flags_off():
    flags = ff.load()
    assert flags == {"dgox_emit": False, "t4_t7_governors": False}


def test_enabled_reads_a_true_flag(tmp_path):
    p = tmp_path / "features.yaml"
    p.write_text("dgox_emit: true\nt4_t7_governors: false\n", encoding="utf-8")
    assert ff.enabled("dgox_emit", p) is True
    assert ff.enabled("t4_t7_governors", p) is False


def test_missing_file_falls_back_off(tmp_path):
    assert ff.load(tmp_path / "nope.yaml") == {"dgox_emit": False, "t4_t7_governors": False}


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text("dgox_emit: true\nbogus: true\n", encoding="utf-8")
    flags = ff.load(p)
    assert flags["dgox_emit"] is True and "bogus" not in flags


def test_empty_file_falls_back_off(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text("", encoding="utf-8")
    assert ff.load(p) == {"dgox_emit": False, "t4_t7_governors": False}
