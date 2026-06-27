#!/usr/bin/env python3
"""memory_lib.py — ArcRift memory governance.

Five controls over recall: **TTL** (per-type lifespan), **dedupe** (embedding
similarity), **trust-score** (provenance), **contradiction check**, and
**quarantine**. The LIVE store is ArcRift (an external MCP server using Ollama
nomic-embed-text embeddings); these pure functions implement the governance logic
over memory records so it can be enforced and tested in CI. Without a live
embedding model, dedupe uses a deterministic token-Jaccard proxy (documented) —
the live recall path uses real embedding similarity.

A memory record (the migrated schema, config/memory_governance.yaml):
    {id, content, project, mem_type, provenance, trust_score, created_at,
     ttl_days?, status?(active|quarantined|contradicted), contradicts?[ids]}
"""
from __future__ import annotations

import datetime as dt
import re


def parse_iso(ts: str) -> dt.datetime | None:
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' (or a date 'YYYY-MM-DD') into UTC-naive, or None."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(ts, fmt)
        except (ValueError, TypeError):
            continue
    return None


def trust_for(provenance: str, tiers: dict) -> float:
    """Map a provenance label to its trust score (unverified default)."""
    return float(tiers.get(str(provenance), tiers.get("unverified_claim", 0.0)))


def ttl_for(mem: dict, ttl_config: dict) -> float:
    """Resolve a memory's TTL in days: explicit ttl_days, else per-type, else default."""
    explicit = mem.get("ttl_days")
    if isinstance(explicit, int | float) and not isinstance(explicit, bool):
        return float(explicit)
    return float(ttl_config.get(str(mem.get("mem_type", "")), ttl_config.get("default", 0)))


def is_expired(mem: dict, now: dt.datetime, ttl_config: dict) -> bool:
    created = parse_iso(str(mem.get("created_at", "")))
    if created is None:
        return False
    return now > created + dt.timedelta(days=ttl_for(mem, ttl_config))


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


def jaccard(a: str, b: str) -> float:
    """Token-Jaccard similarity in [0, 1] — the offline proxy for embedding similarity."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def duplicate_pairs(memories: list[dict], threshold: float = 0.85) -> list[tuple[str, str]]:
    """Near-duplicate (id, id) pairs within the same project above the similarity threshold."""
    pairs: list[tuple[str, str]] = []
    for i in range(len(memories)):
        for j in range(i + 1, len(memories)):
            a, b = memories[i], memories[j]
            if not str(a.get("content", "")).strip() or not str(b.get("content", "")).strip():
                continue  # empty content is not a meaningful duplicate
            if a.get("project") == b.get("project") and jaccard(a.get("content", ""), b.get("content", "")) >= threshold:
                pairs.append((str(a.get("id")), str(b.get("id"))))
    return pairs


def is_quarantined(mem: dict) -> bool:
    """A memory is excluded from recall if quarantined, marked contradicted, or it
    declares it contradicts another memory."""
    return str(mem.get("status", "")).lower() in ("quarantined", "contradicted") or bool(mem.get("contradicts"))


def recallable(memories: list[dict], now: dt.datetime, config: dict) -> list[dict]:
    """Memories eligible for recall: not quarantined/contradicted, not expired, and
    at or above the minimum trust score."""
    min_trust = float(config.get("recall", {}).get("min_trust", 0.0))
    ttl_cfg = config.get("ttl_days", {}) or {}
    out = []
    for m in memories:
        if is_quarantined(m):
            continue
        if is_expired(m, now, ttl_cfg):
            continue
        if float(m.get("trust_score", 0) or 0) < min_trust:
            continue
        out.append(m)
    return out


def memory_health(memories: list[dict], now: dt.datetime, config: dict) -> float:
    """Decaying health score in [0, 1]: 1.0 minus a decay per stale/quarantined memory."""
    if not memories:
        return 1.0
    ttl_cfg = config.get("ttl_days", {}) or {}
    bad = sum(1 for m in memories if is_quarantined(m) or is_expired(m, now, ttl_cfg))
    decay = float(config.get("health", {}).get("decay_per_bad", 0.05))
    return max(0.0, 1.0 - decay * bad)


def explain_exclusion(mem: dict, now: dt.datetime, config: dict) -> str:
    """Plain-English reason a memory is excluded from recall, or '' if recallable —
    backs the cockpit's 'Memory Health Explanation' affordance (RFC-003 §2)."""
    if str(mem.get("status", "")).lower() in ("quarantined", "contradicted"):
        return f"quarantined (status: {mem.get('status')})"
    if mem.get("contradicts"):
        return f"contradicts {mem.get('contradicts')}"
    if is_expired(mem, now, config.get("ttl_days", {}) or {}):
        return "expired (past TTL)"
    min_trust = float(config.get("recall", {}).get("min_trust", 0.0))
    if float(mem.get("trust_score", 0) or 0) < min_trust:
        return f"trust {mem.get('trust_score')} below minimum {min_trust}"
    return ""
