"""tests/test_dgox_events.py — pytest suite for scripts/dgox/events.py.

Coverage:
- Common envelope: build + validate (valid and invalid cases).
- Shape A (routing_decision): build + validate (valid and invalid cases).
- Shape B (agent_invocation): build + validate (valid and invalid cases).
- Append-then-replay round-trip (uses tmp_path — never touches board/.events.jsonl).
- iter_events filtering by ticket_id, run_id, and event_type.
- Malformed-line tolerance in iter_events.
- gitignore exclusion: ``git check-ignore board/.events.jsonl`` → ignored.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup — make scripts/ importable and scripts/dgox/ importable as a
# namespace package regardless of how pytest is invoked.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import metrics_lib  # noqa: E402
from dgox.events import (  # noqa: E402
    RUN_END_METRICS_FIELDS,
    EventStore,
    build_agent_invocation,
    build_checkpoint,
    build_routing_decision,
    build_run_end,
    build_run_start,
    build_wave,
    iter_events,
    utcnow,
    validate_agent_invocation,
    validate_checkpoint,
    validate_envelope,
    validate_routing_decision,
    validate_run_end,
    validate_run_start,
    validate_wave,
)

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

FIXED_TS = "2026-06-20T00:00:00Z"


def _make_routing_event(**overrides):
    defaults = {
        "ticket_id": "DAS-1234",
        "from_status": "todo",
        "to_status": "in_progress",
        "assignee": "backend-eng-1",
        "model": "sonnet",
        "reason": "Stage 3 backend implementation; Backend EM owns review.",
        "confidence": 0.91,
        "policy_checks": ["aadl_predecessor_gate_closed", "repo_area_available"],
        "fallback": "block_and_escalate_to_backend-em",
        "created_at": FIXED_TS,
    }
    defaults.update(overrides)
    return build_routing_decision(**defaults)


def _make_invocation_event(**overrides):
    defaults = {
        "ticket_id": "DAS-1234",
        "run_id": "run-abc-001",
        "role_key": "backend-eng-1",
        "model": "sonnet",
        "workspace_id": "worktree-DAS-1234",
        "context_contract": {"ticket": "DAS-1234", "task": "implement event store"},
        "allowed_tools": ["Read", "Edit", "Bash"],
        "secrets_policy": "no_secrets",
        "exit_contract": {"ticket_log": True, "artifacts": True, "memory_store": True},
        "created_at": FIXED_TS,
    }
    defaults.update(overrides)
    return build_agent_invocation(**defaults)


def _make_run_start_event(**overrides):
    defaults = {
        "ticket_id": "DAS-1443",
        "run_id": "01J9Z8QK3M7Q0W9E4R5T6Y7U8I",
        "goal": "organism-ws1-pulse",
        "engine_version": "1.0.0",
        "created_at": FIXED_TS,
    }
    defaults.update(overrides)
    return build_run_start(**defaults)


def _make_run_end_event(**overrides):
    defaults = {
        "ticket_id": "DAS-1443",
        "run_id": "01J9Z8QK3M7Q0W9E4R5T6Y7U8I",
        "outcome": "success",
        "model": "haiku",
        "merged_pr": "https://github.com/nabievuz/daslab/pull/42",
        "ci_status": "green",
        "t7_pass": True,
        "t7_score": 0.95,
        "created_at": FIXED_TS,
    }
    defaults.update(overrides)
    return build_run_end(**defaults)


def _make_wave_event(**overrides):
    defaults = {
        "ticket_id": "DAS-1443",
        "run_id": "01J9Z8QK3M7Q0W9E4R5T6Y7U8I",
        "wave": 1,
        "tickets": ["DAS-1443", "DAS-1444"],
        "created_at": FIXED_TS,
    }
    defaults.update(overrides)
    return build_wave(**defaults)


def _make_checkpoint_event(**overrides):
    defaults = {
        "ticket_id": "DAS-1443",
        "run_id": "01J9Z8QK3M7Q0W9E4R5T6Y7U8I",
        "wave": 2,
        "board_hash": "sha256:1f3a",
        "event_offset": 10432,
        "ticket_states": {"DAS-1443": "done", "DAS-1444": "in_review"},
        "ledger_hashes": {"prev": "sha256:0b7c", "self": "sha256:9de5"},
        "created_at": FIXED_TS,
    }
    defaults.update(overrides)
    return build_checkpoint(**defaults)


# ---------------------------------------------------------------------------
# Envelope tests
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_valid_envelope_no_errors(self):
        ev = {"event_type": "routing_decision", "ticket_id": "DAS-1", "created_at": FIXED_TS}
        assert validate_envelope(ev) == []

    def test_missing_event_type(self):
        ev = {"ticket_id": "DAS-1", "created_at": FIXED_TS}
        errors = validate_envelope(ev)
        assert any("event_type" in e for e in errors)

    def test_missing_ticket_id(self):
        ev = {"event_type": "routing_decision", "created_at": FIXED_TS}
        errors = validate_envelope(ev)
        assert any("ticket_id" in e for e in errors)

    def test_missing_created_at(self):
        ev = {"event_type": "routing_decision", "ticket_id": "DAS-1"}
        errors = validate_envelope(ev)
        assert any("created_at" in e for e in errors)

    def test_unknown_event_type(self):
        ev = {"event_type": "foo_bar", "ticket_id": "DAS-1", "created_at": FIXED_TS}
        errors = validate_envelope(ev)
        assert any("unknown event_type" in e for e in errors)

    def test_ticket_id_must_start_with_das(self):
        ev = {"event_type": "routing_decision", "ticket_id": "JIRA-1234", "created_at": FIXED_TS}
        errors = validate_envelope(ev)
        assert any("ticket_id" in e for e in errors)

    def test_run_id_empty_string_is_invalid(self):
        ev = {
            "event_type": "routing_decision",
            "ticket_id": "DAS-1",
            "created_at": FIXED_TS,
            "run_id": "",
        }
        errors = validate_envelope(ev)
        assert any("run_id" in e for e in errors)

    def test_run_id_valid_string_passes(self):
        ev = {
            "event_type": "routing_decision",
            "ticket_id": "DAS-1",
            "created_at": FIXED_TS,
            "run_id": "run-xyz",
        }
        assert validate_envelope(ev) == []


# ---------------------------------------------------------------------------
# Shape A — routing_decision
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_build_produces_expected_shape(self):
        ev = _make_routing_event()
        assert ev["event_type"] == "routing_decision"
        assert ev["ticket_id"] == "DAS-1234"
        assert ev["from_status"] == "todo"
        assert ev["to_status"] == "in_progress"
        assert ev["assignee"] == "backend-eng-1"
        assert ev["model"] == "sonnet"
        assert ev["confidence"] == 0.91
        assert ev["policy_checks"] == [
            "aadl_predecessor_gate_closed",
            "repo_area_available",
        ]
        assert ev["fallback"] == "block_and_escalate_to_backend-em"
        assert ev["created_at"] == FIXED_TS
        # run_id is absent when not provided
        assert "run_id" not in ev

    def test_build_with_run_id(self):
        ev = _make_routing_event(run_id="run-xyz-001")
        assert ev["run_id"] == "run-xyz-001"

    def test_policy_checks_is_a_copy(self):
        original = ["aadl_predecessor_gate_closed"]
        ev = _make_routing_event(policy_checks=original)
        original.append("mutated")
        # The event should not reflect the mutation
        assert "mutated" not in ev["policy_checks"]

    def test_validate_valid_event_no_errors(self):
        ev = _make_routing_event()
        assert validate_routing_decision(ev) == []

    def test_validate_wrong_event_type_is_error(self):
        ev = _make_routing_event()
        ev["event_type"] = "agent_invocation"
        errors = validate_routing_decision(ev)
        assert any("routing_decision" in e for e in errors)

    def test_validate_confidence_out_of_range(self):
        ev = _make_routing_event(confidence=1.5)
        errors = validate_routing_decision(ev)
        assert any("confidence" in e for e in errors)

    def test_validate_confidence_zero_ok(self):
        ev = _make_routing_event(confidence=0.0)
        assert validate_routing_decision(ev) == []

    def test_validate_confidence_one_ok(self):
        ev = _make_routing_event(confidence=1.0)
        assert validate_routing_decision(ev) == []

    def test_validate_empty_policy_checks_is_error(self):
        ev = _make_routing_event(policy_checks=[])
        errors = validate_routing_decision(ev)
        assert any("policy_checks" in e for e in errors)

    def test_validate_missing_ticket_id_propagates(self):
        ev = _make_routing_event()
        del ev["ticket_id"]
        errors = validate_routing_decision(ev)
        assert any("ticket_id" in e for e in errors)


# ---------------------------------------------------------------------------
# Shape B — agent_invocation
# ---------------------------------------------------------------------------


class TestAgentInvocation:
    def test_build_produces_expected_shape(self):
        ev = _make_invocation_event()
        assert ev["event_type"] == "agent_invocation"
        assert ev["ticket_id"] == "DAS-1234"
        assert ev["run_id"] == "run-abc-001"
        assert ev["role_key"] == "backend-eng-1"
        assert ev["model"] == "sonnet"
        assert ev["workspace_id"] == "worktree-DAS-1234"
        assert ev["secrets_policy"] == "no_secrets"
        assert ev["context_contract"] == {"ticket": "DAS-1234", "task": "implement event store"}
        assert ev["allowed_tools"] == ["Read", "Edit", "Bash"]
        assert ev["exit_contract"] == {
            "ticket_log": True,
            "artifacts": True,
            "memory_store": True,
        }
        assert ev["created_at"] == FIXED_TS

    def test_context_contract_is_a_copy(self):
        original = {"ticket": "DAS-1234"}
        ev = _make_invocation_event(context_contract=original)
        original["mutated"] = True
        assert "mutated" not in ev["context_contract"]

    def test_allowed_tools_is_a_copy(self):
        original = ["Read"]
        ev = _make_invocation_event(allowed_tools=original)
        original.append("mutated")
        assert "mutated" not in ev["allowed_tools"]

    def test_validate_valid_event_no_errors(self):
        ev = _make_invocation_event()
        assert validate_agent_invocation(ev) == []

    def test_validate_wrong_event_type_is_error(self):
        ev = _make_invocation_event()
        ev["event_type"] = "routing_decision"
        errors = validate_agent_invocation(ev)
        assert any("agent_invocation" in e for e in errors)

    def test_validate_missing_run_id_is_error(self):
        ev = _make_invocation_event()
        del ev["run_id"]
        errors = validate_agent_invocation(ev)
        assert any("run_id" in e for e in errors)

    def test_validate_context_contract_must_be_dict(self):
        ev = _make_invocation_event()
        ev["context_contract"] = ["not", "a", "dict"]
        errors = validate_agent_invocation(ev)
        assert any("context_contract" in e for e in errors)

    def test_validate_exit_contract_must_be_dict(self):
        ev = _make_invocation_event()
        ev["exit_contract"] = "string"
        errors = validate_agent_invocation(ev)
        assert any("exit_contract" in e for e in errors)

    def test_validate_allowed_tools_must_be_list_of_strings(self):
        ev = _make_invocation_event()
        ev["allowed_tools"] = ["ok", 42]
        errors = validate_agent_invocation(ev)
        assert any("allowed_tools" in e for e in errors)


# ---------------------------------------------------------------------------
# Shape C — run_start
# ---------------------------------------------------------------------------


class TestRunStart:
    def test_build_produces_expected_shape(self):
        ev = _make_run_start_event()
        assert ev["event_type"] == "run_start"
        assert ev["ticket_id"] == "DAS-1443"
        assert ev["run_id"] == "01J9Z8QK3M7Q0W9E4R5T6Y7U8I"
        assert ev["goal"] == "organism-ws1-pulse"
        assert ev["engine_version"] == "1.0.0"
        assert ev["created_at"] == FIXED_TS

    def test_validate_valid_event_no_errors(self):
        assert validate_run_start(_make_run_start_event()) == []

    def test_validate_wrong_event_type_is_error(self):
        ev = _make_run_start_event()
        ev["event_type"] = "run_end"
        errors = validate_run_start(ev)
        assert any("run_start" in e for e in errors)

    def test_validate_missing_run_id_is_error(self):
        ev = _make_run_start_event()
        del ev["run_id"]
        errors = validate_run_start(ev)
        assert any("run_id" in e for e in errors)

    def test_validate_empty_goal_is_error(self):
        ev = _make_run_start_event(goal="")
        errors = validate_run_start(ev)
        assert any("goal" in e for e in errors)

    def test_appendable_envelope_valid(self):
        # run_start must satisfy the store envelope (append path).
        assert validate_envelope(_make_run_start_event()) == []


# ---------------------------------------------------------------------------
# Shape D — run_end (load-bearing metrics_lib.py contract)
# ---------------------------------------------------------------------------


class TestRunEnd:
    def test_build_produces_expected_shape(self):
        ev = _make_run_end_event()
        assert ev["event_type"] == "run_end"
        assert ev["ticket_id"] == "DAS-1443"
        assert ev["run_id"] == "01J9Z8QK3M7Q0W9E4R5T6Y7U8I"
        assert ev["outcome"] == "success"
        assert ev["model"] == "haiku"
        assert ev["merged_pr"] == "https://github.com/nabievuz/daslab/pull/42"
        assert ev["ci_status"] == "green"
        assert ev["t7_pass"] is True
        assert ev["t7_score"] == 0.95
        assert ev["created_at"] == FIXED_TS

    def test_build_emits_all_metrics_contract_fields(self):
        ev = _make_run_end_event()
        # Every field metrics_lib reads must be present on the built event.
        assert set(ev) >= RUN_END_METRICS_FIELDS
        assert {"event_type", "ticket_id"} <= set(ev)

    def test_validate_valid_event_no_errors(self):
        assert validate_run_end(_make_run_end_event()) == []

    def test_validate_wrong_event_type_is_error(self):
        ev = _make_run_end_event()
        ev["event_type"] = "run_start"
        errors = validate_run_end(ev)
        assert any("run_end" in e for e in errors)

    def test_validate_missing_run_id_is_error(self):
        ev = _make_run_end_event()
        del ev["run_id"]
        errors = validate_run_end(ev)
        assert any("run_id" in e for e in errors)

    def test_validate_missing_outcome_is_error(self):
        ev = _make_run_end_event()
        del ev["outcome"]
        errors = validate_run_end(ev)
        assert any("outcome" in e for e in errors)

    def test_validate_missing_t7_score_is_error(self):
        ev = _make_run_end_event()
        del ev["t7_score"]
        errors = validate_run_end(ev)
        assert any("t7_score" in e for e in errors)

    def test_validate_non_numeric_t7_score_is_error(self):
        ev = _make_run_end_event(t7_score="not-a-number")
        errors = validate_run_end(ev)
        assert any("t7_score" in e for e in errors)

    def test_validate_empty_model_is_error(self):
        ev = _make_run_end_event(model="")
        errors = validate_run_end(ev)
        assert any("model" in e for e in errors)


# ---------------------------------------------------------------------------
# Schema-conformance — build_run_end MUST satisfy the metrics_lib readers.
# If any field is renamed the builder/consumer diverge and these fail.
# ---------------------------------------------------------------------------


class TestRunEndMetricsConformance:
    """A build_run_end(...) event must flow through the metrics readers and be
    COUNTED (not silently dropped) — proving the producer/consumer field names
    match exactly (ADR 0023 §4 hard contract)."""

    def test_field_set_matches_metrics_readers(self):
        # Single source of truth mirrors exactly what metrics_lib consumes.
        assert {
            "run_id",
            "created_at",
            "outcome",
            "model",
            "merged_pr",
            "ci_status",
            "t7_pass",
            "t7_score",
        } == RUN_END_METRICS_FIELDS

    def test_model_mix_counts_the_run_end(self):
        ev = _make_run_end_event(model="haiku")
        result = metrics_lib.model_mix([ev])
        assert result is not None, "run_end was dropped by model_mix (field mismatch)"
        assert result["total"] == 1
        assert result["low_cost"] == 1  # 'haiku' ∈ LOW_COST_MODELS
        assert result["ratio"] == 1.0

    def test_gaming_violations_sees_full_evidence(self):
        ev = _make_run_end_event()
        result = metrics_lib.gaming_violations([ev])
        assert result is not None
        assert result["completions"] == 1
        # merged_pr + green ci + t7_pass all present → no violation reported.
        assert result["violations"] == []

    def test_gaming_violations_flags_missing_evidence(self):
        ev = _make_run_end_event(merged_pr="", ci_status="red", t7_pass=False)
        result = metrics_lib.gaming_violations([ev])
        assert result is not None
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert "no merged PR" in v and "no green CI" in v and "no T7 pass" in v

    def test_t1b_high_impact_counts_the_run_end(self):
        ev = _make_run_end_event(t7_pass=True, t7_score=0.95)
        result = metrics_lib.t1b_high_impact([ev])
        assert result is not None
        assert result["completions"] == 1
        assert result["high_impact"] == 1  # t7_score 0.95 >= 0.90
        assert result["rate"] == 1.0

    def test_run_intervals_pairs_start_and_end(self):
        rid = "01J9Z8QK3M7Q0W9E4R5T6Y7U8I"
        start = _make_run_start_event(run_id=rid, created_at="2026-07-03T12:00:00Z")
        end = _make_run_end_event(run_id=rid, created_at="2026-07-03T12:41:00Z")
        intervals = metrics_lib.run_intervals([start, end])
        assert len(intervals) == 1, "run_start/run_end were not paired by run_id"
        s, e = intervals[0]
        assert e >= s

    def test_bad_outcome_is_not_counted_as_success(self):
        # A non-success outcome must be excluded by model_mix (T4 correctness).
        ev = _make_run_end_event(outcome="error")
        assert metrics_lib.model_mix([ev]) is None


# ---------------------------------------------------------------------------
# Shape E — wave
# ---------------------------------------------------------------------------


class TestWave:
    def test_build_produces_expected_shape(self):
        ev = _make_wave_event()
        assert ev["event_type"] == "wave"
        assert ev["ticket_id"] == "DAS-1443"
        assert ev["run_id"] == "01J9Z8QK3M7Q0W9E4R5T6Y7U8I"
        assert ev["wave"] == 1
        assert ev["tickets"] == ["DAS-1443", "DAS-1444"]
        assert ev["created_at"] == FIXED_TS
        assert "routing" not in ev

    def test_build_with_routing(self):
        ev = _make_wave_event(routing={"DAS-1443": {"role": "backend-em", "model": "sonnet"}})
        assert ev["routing"] == {"DAS-1443": {"role": "backend-em", "model": "sonnet"}}

    def test_tickets_is_a_copy(self):
        original = ["DAS-1443"]
        ev = _make_wave_event(tickets=original)
        original.append("DAS-9999")
        assert "DAS-9999" not in ev["tickets"]

    def test_routing_is_a_copy(self):
        original = {"DAS-1443": {"role": "backend-em"}}
        ev = _make_wave_event(routing=original)
        original["DAS-9999"] = {"role": "x"}
        assert "DAS-9999" not in ev["routing"]

    def test_validate_valid_event_no_errors(self):
        assert validate_wave(_make_wave_event()) == []

    def test_validate_wrong_event_type_is_error(self):
        ev = _make_wave_event()
        ev["event_type"] = "checkpoint"
        errors = validate_wave(ev)
        assert any("wave" in e for e in errors)

    def test_validate_non_positive_wave_is_error(self):
        ev = _make_wave_event(wave=0)
        errors = validate_wave(ev)
        assert any("wave" in e for e in errors)

    def test_validate_tickets_must_be_list_of_strings(self):
        ev = _make_wave_event()
        ev["tickets"] = ["DAS-1", 42]
        errors = validate_wave(ev)
        assert any("tickets" in e for e in errors)


# ---------------------------------------------------------------------------
# Shape F — checkpoint
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_build_produces_expected_shape(self):
        ev = _make_checkpoint_event()
        assert ev["event_type"] == "checkpoint"
        assert ev["ticket_id"] == "DAS-1443"
        assert ev["run_id"] == "01J9Z8QK3M7Q0W9E4R5T6Y7U8I"
        assert ev["wave"] == 2
        assert ev["board_hash"] == "sha256:1f3a"
        assert ev["event_offset"] == 10432
        assert ev["ticket_states"] == {"DAS-1443": "done", "DAS-1444": "in_review"}
        assert ev["ledger_hashes"] == {"prev": "sha256:0b7c", "self": "sha256:9de5"}
        assert ev["pending_interrupts"] == []
        assert ev["created_at"] == FIXED_TS

    def test_build_with_pending_interrupts(self):
        ev = _make_checkpoint_event(pending_interrupts=["DAS-1445"])
        assert ev["pending_interrupts"] == ["DAS-1445"]

    def test_ticket_states_is_a_copy(self):
        original = {"DAS-1443": "done"}
        ev = _make_checkpoint_event(ticket_states=original)
        original["DAS-9999"] = "todo"
        assert "DAS-9999" not in ev["ticket_states"]

    def test_ledger_hashes_is_a_copy(self):
        original = {"prev": "sha256:0b7c", "self": "sha256:9de5"}
        ev = _make_checkpoint_event(ledger_hashes=original)
        original["extra"] = "x"
        assert "extra" not in ev["ledger_hashes"]

    def test_validate_valid_event_no_errors(self):
        assert validate_checkpoint(_make_checkpoint_event()) == []

    def test_validate_wrong_event_type_is_error(self):
        ev = _make_checkpoint_event()
        ev["event_type"] = "wave"
        errors = validate_checkpoint(ev)
        assert any("checkpoint" in e for e in errors)

    def test_validate_negative_event_offset_is_error(self):
        ev = _make_checkpoint_event(event_offset=-1)
        errors = validate_checkpoint(ev)
        assert any("event_offset" in e for e in errors)

    def test_validate_missing_ledger_chain_link_is_error(self):
        ev = _make_checkpoint_event()
        del ev["ledger_hashes"]["self"]
        errors = validate_checkpoint(ev)
        assert any("self" in e for e in errors)

    def test_validate_ticket_states_must_be_dict(self):
        ev = _make_checkpoint_event()
        ev["ticket_states"] = ["not", "a", "dict"]
        errors = validate_checkpoint(ev)
        assert any("ticket_states" in e for e in errors)


# ---------------------------------------------------------------------------
# New shapes round-trip through the append-only store
# ---------------------------------------------------------------------------


class TestNewShapesRoundTrip:
    def test_run_lifecycle_events_round_trip(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)
        events = [
            _make_run_start_event(),
            _make_wave_event(),
            _make_checkpoint_event(),
            _make_run_end_event(),
        ]
        for ev in events:
            store.append(ev)  # envelope-valid → append must not raise
        read_back = list(iter_events(store_path))
        assert read_back == events


# ---------------------------------------------------------------------------
# Append + replay round-trip (tmp_path — never writes real board/.events.jsonl)
# ---------------------------------------------------------------------------


class TestEventStoreRoundTrip:
    def test_append_then_read_single_event(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        ev = _make_routing_event()
        store.append(ev)

        events = list(iter_events(store_path))
        assert len(events) == 1
        assert events[0] == ev

    def test_append_multiple_events_preserves_order(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        ev1 = _make_routing_event(ticket_id="DAS-0001")
        ev2 = _make_routing_event(ticket_id="DAS-0002")
        ev3 = _make_invocation_event(ticket_id="DAS-0003", run_id="run-001")
        for ev in (ev1, ev2, ev3):
            store.append(ev)

        events = list(iter_events(store_path))
        assert len(events) == 3
        assert events[0]["ticket_id"] == "DAS-0001"
        assert events[1]["ticket_id"] == "DAS-0002"
        assert events[2]["ticket_id"] == "DAS-0003"

    def test_filter_by_ticket_id(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        store.append(_make_routing_event(ticket_id="DAS-0001"))
        store.append(_make_routing_event(ticket_id="DAS-0002"))
        store.append(_make_routing_event(ticket_id="DAS-0001"))

        events = list(iter_events(store_path, ticket_id="DAS-0001"))
        assert len(events) == 2
        assert all(e["ticket_id"] == "DAS-0001" for e in events)

    def test_filter_by_run_id(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        store.append(_make_invocation_event(ticket_id="DAS-1", run_id="run-AAA"))
        store.append(_make_invocation_event(ticket_id="DAS-2", run_id="run-BBB"))
        store.append(_make_invocation_event(ticket_id="DAS-3", run_id="run-AAA"))

        events = list(iter_events(store_path, run_id="run-AAA"))
        assert len(events) == 2
        assert all(e["run_id"] == "run-AAA" for e in events)

    def test_filter_by_event_type(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        store.append(_make_routing_event(ticket_id="DAS-1"))
        store.append(_make_invocation_event(ticket_id="DAS-2", run_id="run-001"))
        store.append(_make_routing_event(ticket_id="DAS-3"))

        routing = list(iter_events(store_path, event_type="routing_decision"))
        invoc = list(iter_events(store_path, event_type="agent_invocation"))
        assert len(routing) == 2
        assert len(invoc) == 1

    def test_combined_filters(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        store.append(_make_invocation_event(ticket_id="DAS-1", run_id="run-AAA"))
        store.append(_make_invocation_event(ticket_id="DAS-1", run_id="run-BBB"))
        store.append(_make_invocation_event(ticket_id="DAS-2", run_id="run-AAA"))

        events = list(iter_events(store_path, ticket_id="DAS-1", run_id="run-AAA"))
        assert len(events) == 1
        assert events[0]["ticket_id"] == "DAS-1"
        assert events[0]["run_id"] == "run-AAA"

    def test_nonexistent_store_returns_empty(self, tmp_path):
        events = list(iter_events(tmp_path / "nonexistent.jsonl"))
        assert events == []

    def test_store_creates_parent_dirs(self, tmp_path):
        store_path = tmp_path / "nested" / "dir" / "events.jsonl"
        store = EventStore(store_path)
        store.append(_make_routing_event())
        assert store_path.exists()

    def test_invalid_event_raises_before_write(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)
        bad_event = {"event_type": "routing_decision"}  # missing ticket_id, created_at
        with pytest.raises(ValueError, match="missing required field"):
            store.append(bad_event)
        # File should not have been created
        assert not store_path.exists()

    def test_malformed_lines_are_skipped_in_replay(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        # Write one valid event and one garbage line
        ev = _make_routing_event()
        valid_line = json.dumps(ev) + "\n"
        store_path.write_text(valid_line + "NOT_JSON{{{\n", encoding="utf-8")

        events = list(iter_events(store_path))
        assert len(events) == 1
        assert events[0]["event_type"] == "routing_decision"

    def test_empty_lines_are_skipped_in_replay(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        ev = _make_routing_event()
        valid_line = json.dumps(ev) + "\n"
        # Surround valid line with blank lines
        store_path.write_text("\n" + valid_line + "\n\n", encoding="utf-8")

        events = list(iter_events(store_path))
        assert len(events) == 1

    def test_each_line_is_valid_json(self, tmp_path):
        store_path = tmp_path / "events.jsonl"
        store = EventStore(store_path)

        store.append(_make_routing_event())
        store.append(_make_invocation_event(run_id="run-001"))

        for line in store_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)  # must not raise
                assert isinstance(obj, dict)

    def test_utcnow_returns_nonempty_string(self):
        ts = utcnow()
        assert isinstance(ts, str)
        assert ts.endswith("Z")
        assert "T" in ts


# ---------------------------------------------------------------------------
# gitignore exclusion
# ---------------------------------------------------------------------------


class TestGitignore:
    def test_events_jsonl_is_gitignored(self):
        """git check-ignore board/.events.jsonl must exit 0 (file is ignored)."""
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "board/.events.jsonl"],
            cwd=_REPO_ROOT,
            capture_output=True,
        )
        assert result.returncode == 0, (
            "board/.events.jsonl is NOT gitignored — add it to .gitignore following "
            "the board/.wave-log / board/.arcrift-outbox.jsonl precedent (ADR 0011 §2)"
        )
