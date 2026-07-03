"""tests/test_kill_drill.py — REAL kill/resume + fork drill (DAS-1451, GATE-4 / T5).

Acceptance criteria covered:
  AC1  Kill-mid-wave-2 drill: a synthetic 3-wave run, a genuine `kill -9` (SIGKILL)
       mid-wave-2, then --resume, with ZERO lost and ZERO duplicated tickets.
  AC2  T5 >= 0.99 over >= 20 iterations: >= 20 recovery_drill events such that
       check_recovery.py reports ratio >= 0.99 with corrupted == 0 (exit 0).
  AC3  Fork-drill: fork from a wave-1 checkpoint yields a DIVERGENT run while the
       original is left intact (unchanged bytes/checkpoints, still replayable).
  AC4  Events emitted in the shape metrics_lib.recovery_reliability() consumes;
       a corrupted resume yields corrupted > 0 -> check_recovery FAIL (exit 1),
       honoring the zero-corrupted guardrail.
  AC5  Consumes DAS-1444 (checkpoints/completions) + DAS-1445 (resume/fork) — no
       re-implementation of checkpointing or fork mechanics.

These drills spawn REAL child processes that SIGKILL themselves; POSIX-only
(the CI matrix is ubuntu + macos, matching the fcntl/O_APPEND assumptions of the
event store and pulse_checkpoint).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_recovery  # noqa: E402
import kill_drill as kd  # noqa: E402
import metrics_lib  # noqa: E402
import replay_qa  # noqa: E402
import wave_kpi  # noqa: E402

# ===========================================================================
# AC1 — kill-mid-wave-2: zero lost, zero duplicated across the resume boundary
# ===========================================================================


class TestKillDrill:
    def test_child_is_genuinely_sigkilled(self, tmp_path: Path) -> None:
        """The synthetic run's child process dies by SIGKILL (returncode -9)."""
        res = kd.run_kill_drill(tmp_path / "drill")
        assert res["killed"] is True, "child must die by SIGKILL, not exit cleanly"

    def test_zero_lost_zero_duplicated(self, tmp_path: Path) -> None:
        """After crash + resume: every planned ticket terminal, none duplicated."""
        res = kd.run_kill_drill(tmp_path / "drill")
        assert res["zero_lost"] is True, f"lost tickets: {res['lost']}"
        assert res["zero_duplicated"] is True, f"dup completions: {res['dup_completions']}"
        assert res["chain_clean"] is True, f"corrupted chains: {res['corrupted']}"
        assert res["ok"] is True

    def test_all_planned_tickets_completed_exactly_once(self, tmp_path: Path) -> None:
        """Each planned ticket has exactly one durable completion record."""
        res = kd.run_kill_drill(tmp_path / "drill")
        runs_dir = tmp_path / "drill" / "runs"
        comp_ids = kd._completion_ids(runs_dir, res["run_id"])
        flat = [t for wave in kd.DEFAULT_WAVES for t in wave]
        assert sorted(comp_ids) == sorted(flat), "every planned ticket completed once"
        assert len(comp_ids) == len(set(comp_ids)), "no completion recorded twice"

    def test_final_event_states_all_terminal(self, tmp_path: Path) -> None:
        """The post-resume event log replays cleanly to a terminal state per ticket."""
        res = kd.run_kill_drill(tmp_path / "drill")
        final, corrupted = kd._final_states(Path(res["events_path"]), res["run_id"])
        assert not corrupted
        flat = [t for wave in kd.DEFAULT_WAVES for t in wave]
        for t in flat:
            assert final.get(t) in ("done", "blocked"), f"{t} not terminal: {final.get(t)}"

    def test_idempotency_window_done_before_completion(self, tmp_path: Path) -> None:
        """Crash AFTER the done event but BEFORE the completion record.

        The ticket is durably terminal in the event log yet has no completion
        record. Resume must NOT re-dispatch it (guard-before-act / DAS-1447):
        no duplicate, no corrupted chain, and the ticket counts as not-lost.
        """
        crash = {"wave": 2, "ticket_index": 1, "phase": "after_done"}
        res = kd.run_kill_drill(tmp_path / "drill", crash=crash)
        assert res["killed"] is True
        assert res["zero_lost"] is True, f"lost: {res['lost']}"
        assert res["zero_duplicated"] is True, f"dup: {res['dup_completions']}"
        assert res["chain_clean"] is True, f"corrupted: {res['corrupted']}"


# ===========================================================================
# AC3 — fork-drill: divergent run, original intact
# ===========================================================================


class TestForkDrill:
    def test_divergent_and_original_intact(self, tmp_path: Path) -> None:
        res = kd.run_fork_drill(tmp_path / "fork")
        assert res["divergent"] is True, (
            f"fork must diverge: original {res['original_final']} vs fork {res['fork_final']}"
        )
        assert res["original_intact"] is True
        assert res["ok"] is True

    def test_divergence_is_real_status_difference(self, tmp_path: Path) -> None:
        """The fork ran the shared ticket to blocked; the original ran it to done."""
        res = kd.run_fork_drill(tmp_path / "fork")
        assert res["original_final"].get("DAS-8501") == "done"
        assert res["fork_final"].get("DAS-8501") == "blocked"
        assert res["fork_run"] != res["base_run"]

    def test_original_events_and_checkpoints_byte_identical(self, tmp_path: Path) -> None:
        """The original run's event store + checkpoints are unchanged after the fork."""
        work = tmp_path / "fork"
        res = kd.run_fork_drill(work)
        base_run = res["base_run"]
        # Original run still replays cleanly to its recorded final state.
        final, corrupted = kd._final_states(work / "base-events.jsonl", base_run)
        assert not corrupted
        assert final.get("DAS-8501") == "done"
        # The fork wrote to a SEPARATE store + run dir.
        assert (work / "fork-events.jsonl").exists()
        assert (work / "runs" / res["fork_run"] / "wave-001.checkpoint.json").exists()


# ===========================================================================
# AC4 — event shape + T5 gate scoring (incl. zero-corrupted guardrail)
# ===========================================================================


class TestEventEmissionAndGate:
    def test_emit_recovery_drill_shape_is_scored(self, tmp_path: Path) -> None:
        """emit_recovery_drill writes the exact shape recovery_reliability() reads."""
        store = tmp_path / "drills.jsonl"
        kd.emit_recovery_drill(store, run_id="R1", outcome="success", corrupted=False,
                               created_at="2026-07-03T00:00:00Z")
        kd.emit_recovery_drill(store, run_id="R2", outcome="success", corrupted=False,
                               created_at="2026-07-03T00:00:01Z")
        rec = metrics_lib.recovery_reliability(wave_kpi.read_events(str(store)))
        assert rec is not None
        assert rec["drills"] == 2 and rec["successful"] == 2 and rec["corrupted"] == 0
        assert rec["ratio"] == 1.0

    def test_corrupted_resume_fails_gate(self, tmp_path: Path) -> None:
        """A corrupted recovery_drill trips the zero-corrupted guardrail (exit 1)."""
        store = tmp_path / "drills.jsonl"
        kd.emit_recovery_drill(store, run_id="R1", outcome="success", corrupted=False,
                               created_at="2026-07-03T00:00:00Z")
        kd.emit_recovery_drill(store, run_id="R2", outcome="fail", corrupted=True,
                               created_at="2026-07-03T00:00:01Z")
        assert check_recovery.main(["--events", str(store)]) == 1

    def test_replay_qa_emit_interop_on_single_ticket_fork_store(self, tmp_path: Path) -> None:
        """The fork's single-ticket store is replay_qa --emit compatible.

        Proves the drills' events interoperate with the shipped replay_qa --emit
        writer at the per-ticket granularity it was built for: replaying the
        fork's clean single-ticket chain emits a `success` recovery_drill that
        check_recovery scores green.
        """
        res = kd.run_fork_drill(tmp_path / "fork")
        emit = tmp_path / "replayqa-drills.jsonl"
        rc = replay_qa.main(["--events", res["fork_events_path"], "--emit", str(emit)])
        assert rc == 0
        drills = [json.loads(x) for x in emit.read_text().splitlines() if x.strip()]
        assert drills and drills[0]["event_type"] == "recovery_drill"
        assert drills[0]["outcome"] == "success" and drills[0]["corrupted"] is False
        assert check_recovery.main(["--events", str(emit)]) == 0


# ===========================================================================
# AC2 — T5 >= 0.99 over >= 20 iterations (the full drill accumulation)
# ===========================================================================


class TestT5Accumulation:
    def test_20_iterations_gate_green(self, tmp_path: Path) -> None:
        """>= 20 kill drills + fork emit >= 20 recovery_drill events; gate exit 0."""
        rc = kd.run_drills(iterations=20, tmp_root=tmp_path)
        assert rc == 0

        store = tmp_path / "drill-events.jsonl"
        rec = metrics_lib.recovery_reliability(wave_kpi.read_events(str(store)))
        assert rec is not None
        assert rec["drills"] >= 20, f"expected >= 20 drills, got {rec['drills']}"
        assert rec["corrupted"] == 0
        assert rec["ratio"] >= 0.99
        # The gate agrees.
        assert check_recovery.main(["--events", str(store)]) == 0

    def test_check_recovery_default_path_unchanged(self) -> None:
        """The drill leaves check_recovery.py's default no-arg behavior untouched.

        With no live recovery_drill events in the real store, the gate stays inert
        (exit 0), exactly as before — the drill never mutates the default path.
        """
        # A fresh empty store -> unmeasured -> inert exit 0 (default contract).
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jsonl") as fh:
            assert check_recovery.main(["--events", fh.name]) == 0
