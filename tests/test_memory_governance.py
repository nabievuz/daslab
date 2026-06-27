#!/usr/bin/env python3
"""tests/test_memory_governance.py — ArcRift memory governance (R-5 / ADR-005)."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_memory_governance as cmg  # noqa: E402  (import after path manipulation)
import memory_lib as ml  # noqa: E402

REAL_CONFIG = REPO_ROOT / "config" / "memory_governance.yaml"
NOW = dt.datetime(2026, 6, 21, 0, 0, 0)
CFG = {
    "schema": {"required_fields": ["id", "content", "project", "provenance", "trust_score", "created_at"]},
    "trust_tiers": {"verified_pr": 1.0, "review_validated": 0.7, "cited_source": 0.5, "unverified_claim": 0.2},
    "recall": {"min_trust": 0.3, "dedupe_similarity": 0.85},
    "ttl_days": {"fact": 180, "default": 120},
    "health": {"decay_per_bad": 0.05},
}


def _mem(mid="m1", provenance="verified_pr", trust=1.0, content="alpha beta gamma",
         created="2026-06-20T00:00:00Z", **extra) -> dict:
    m = {"id": mid, "content": content, "project": "daslab", "provenance": provenance,
         "trust_score": trust, "created_at": created, "mem_type": "fact"}
    m.update(extra)
    return m


# --------------------------------------------------------------------------- #
# Library controls
# --------------------------------------------------------------------------- #

def test_trust_for():
    assert ml.trust_for("verified_pr", CFG["trust_tiers"]) == 1.0
    assert ml.trust_for("unknown", CFG["trust_tiers"]) == 0.2  # unverified default


def test_is_expired():
    old = _mem(created="2020-01-01T00:00:00Z")
    fresh = _mem(created="2026-06-20T00:00:00Z")
    assert ml.is_expired(old, NOW, CFG["ttl_days"]) is True
    assert ml.is_expired(fresh, NOW, CFG["ttl_days"]) is False


def test_jaccard_and_duplicates():
    assert ml.jaccard("alpha beta", "alpha beta") == 1.0
    dupes = ml.duplicate_pairs([_mem("a", content="alpha beta gamma"), _mem("b", content="alpha beta gamma")])
    assert ("a", "b") in dupes


def test_quarantined_detection():
    assert ml.is_quarantined(_mem(status="quarantined")) is True
    assert ml.is_quarantined(_mem(contradicts=["m9"])) is True
    assert ml.is_quarantined(_mem()) is False


def test_recallable_excludes_bad_memories():
    good = _mem("good")
    low_trust = _mem("low", provenance="unverified_claim", trust=0.2)
    quarantined = _mem("q", status="quarantined")
    expired = _mem("old", created="2020-01-01T00:00:00Z")
    recall = ml.recallable([good, low_trust, quarantined, expired], NOW, CFG)
    assert [m["id"] for m in recall] == ["good"]


def test_memory_health_decays():
    assert ml.memory_health([], NOW, CFG) == 1.0
    mems = [_mem("good"), _mem("q", status="quarantined"), _mem("old", created="2020-01-01T00:00:00Z")]
    assert ml.memory_health(mems, NOW, CFG) == 0.9  # 2 bad * 0.05 decay


# --------------------------------------------------------------------------- #
# CLI validator
# --------------------------------------------------------------------------- #

def _store(tmp_path: Path, mems: list[dict]) -> Path:
    p = tmp_path / ".arcrift-outbox.jsonl"
    p.write_text("".join(json.dumps(m) + "\n" for m in mems), encoding="utf-8")
    return p


def _run(tmp_path: Path, mems: list[dict]) -> int:
    return cmg.main([
        "--store", str(_store(tmp_path, mems)),
        "--config", str(REAL_CONFIG), "--now", "2026-06-21T00:00:00Z",
    ])


def test_cli_inert_without_store(tmp_path):
    assert cmg.main(["--store", str(tmp_path / "nope.jsonl"), "--config", str(REAL_CONFIG)]) == 0


def test_cli_clean_store_exit_0(tmp_path):
    assert _run(tmp_path, [_mem("m1"), _mem("m2", provenance="review_validated", trust=0.7, content="distinct words here")]) == 0


def test_cli_missing_trust_score_exit_1(tmp_path):
    bad = _mem("m1")
    del bad["trust_score"]
    assert _run(tmp_path, [bad]) == 1


def test_cli_trust_mismatch_exit_1(tmp_path):
    # provenance verified_pr should be 1.0, not 0.5
    assert _run(tmp_path, [_mem("m1", provenance="verified_pr", trust=0.5)]) == 1


def test_cli_contradicted_not_quarantined_exit_1(tmp_path):
    mems = [_mem("m1"), _mem("m2", contradicts=["m1"], status="active")]
    assert _run(tmp_path, mems) == 1


def test_cli_contradicted_and_quarantined_exit_0(tmp_path):
    mems = [_mem("m1"), _mem("m2", provenance="review_validated", trust=0.7,
                              content="totally different content", contradicts=["m1"], status="quarantined")]
    assert _run(tmp_path, mems) == 0


def test_zero_trust_tier_is_consistent():
    # a 0.0 provenance tier with trust_score 0.0 must NOT false-fail (review-found `or -1` bug)
    cfg = dict(CFG, trust_tiers=dict(CFG["trust_tiers"], rumor=0.0))
    assert cmg.violations([_mem("m1", provenance="rumor", trust=0.0)], cfg, NOW) == []


def test_unparseable_created_at_flagged():
    assert any("unparseable created_at" in p for p in cmg.violations([_mem("m1", created="yesterday")], CFG, NOW))
