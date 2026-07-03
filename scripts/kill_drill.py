#!/usr/bin/env python3
"""kill_drill.py — REAL kill/resume + fork recovery drill (DAS-1451, GATE-4).

Turns the T5 recovery-reliability gate (``scripts/check_recovery.py``) from a
shipped-but-inert lever into a gate backed by live evidence. Two drills:

  KILL DRILL (``run_kill_drill``)
      1. Spawn a *real* child process that runs a synthetic 3-wave run, durably
         (``O_APPEND`` + ``fsync``) emitting ``routing_decision`` events and
         per-ticket ``ticket_completion`` records, with a wave-boundary
         checkpoint at each boundary (via ``pulse_checkpoint``, DAS-1444).
      2. The child ``kill -9``s itself (``os.kill(getpid, SIGKILL)``) mid-wave-2
         — a genuine abrupt death: no cleanup, no atexit, no flush-on-exit.
      3. The parent resumes via ``resume_fork.resume_run`` (DAS-1445), which
         replays the durable event log + completion records and returns only the
         tickets that still need work, then re-dispatches exactly those.
      4. Assert **zero lost** (every planned ticket reaches a terminal state) and
         **zero duplicated** (no ticket's chain is corrupted and no completion
         record appears twice) across the resume boundary.

  FORK DRILL (``run_fork_drill``)
      Fork from a wave-1 checkpoint (``resume_fork.fork_run``), drive the fork to
      a DIVERGENT outcome (a ticket the original ran to ``done`` the fork runs to
      ``blocked``) in its OWN event store + checkpoint tree, and prove the
      original run is left intact (events byte-for-byte unchanged, checkpoints
      unchanged, still replays cleanly to the same final state).

Both drills emit ``recovery_drill`` events in the EXACT shape
``replay_qa --emit`` writes (``event_type: recovery_drill``, ``outcome``,
``corrupted``, ``run_id``, ``ticket_id``, ``created_at``) — by *invoking*
``replay_qa --emit`` over each drill's event store. So the existing
``metrics_lib.recovery_reliability`` / ``check_recovery.py`` scores them with NO
gate change: a clean resume ⇒ ``outcome=success, corrupted=false``; a corrupted
resume ⇒ ``corrupted=true`` ⇒ the gate FAILs (zero-corrupted guardrail).

EXTEND, do not replace: the T5 math (``metrics_lib.recovery_reliability``) and
``check_recovery.py``'s default no-arg scoring/exit contract are untouched. This
module is a new, self-contained driver under the ``scripts/recovery`` zone that
reuses ``pulse_checkpoint`` (checkpoints/completions), ``resume_fork``
(resume/fork), and ``replay_qa`` (replay + ``recovery_drill`` emission).

Shadow-rule note (mirrors ``resume_fork``): this module imports ``dgox.events``
to *produce* events via the typed builders and reads events ONLY through
``resume_fork`` in the explicit operator-invoked drill path — never in the normal
``/daslab-cycle`` dispatch path. It is therefore an event PRODUCER, listed in
``tests/test_dgox_phase1_shadow.py``'s ``_EVENT_PRODUCERS`` allowlist (precedent:
``pulse_checkpoint.py``, ``dispatch_emitter.py``). The "flag-on == flag-off
dispatch" guarantee for real waves is intact.

CLI
    python3 scripts/kill_drill.py --smoke            # cheap: 1 kill + 1 fork drill (CI, every PR)
    python3 scripts/kill_drill.py --iterations 20    # expensive: >=20 kill drills + fork (scheduled)
    python3 scripts/kill_drill.py --worker <spec>    # internal: the child process entrypoint

Exit codes: 0 = drills passed AND T5 gate exit 0; 1 = a drill failed
(lost/duplicated/corrupted) or the gate FAILed; 2 = usage.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# scripts/ on sys.path (same pattern as the sibling recovery scripts) so the
# child process and the driver resolve pulse_checkpoint / resume_fork / dgox.
# ---------------------------------------------------------------------------
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pulse_checkpoint as pc  # noqa: E402
import replay_qa  # noqa: E402
import resume_fork as rf  # noqa: E402
import wave_kpi  # noqa: E402
from dgox.events import EventStore, build_routing_decision  # noqa: E402

# ---------------------------------------------------------------------------
# Deterministic, strictly-increasing timestamps.
#
# replay_qa.replay_run sorts a ticket's transitions by ``created_at`` (string
# compare of fixed-width ISO-8601). The child uses the low sequence band and the
# parent's resume uses a band far above it, so every re-dispatched transition
# for a ticket sorts strictly AFTER the child's transitions for that ticket —
# keeping each ticket's chain intact across the crash boundary.
# ---------------------------------------------------------------------------
_BASE = datetime(2026, 7, 3, 0, 0, 0, tzinfo=UTC)
_RESUME_SEQ_BASE = 100_000  # ~27h ahead of the child band — never collides


def iso_at(seq: int) -> str:
    """Deterministic ISO-8601 ``Z`` timestamp for sequence ``seq`` (sortable)."""
    return (_BASE + timedelta(seconds=seq)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Low-level event/record primitives (typed builders — no raw dicts)
# ---------------------------------------------------------------------------


def _append_transition(
    store: EventStore, *, run_id: str, ticket: str, frm: str, to: str, seq: int
) -> None:
    """Durably append one ``routing_decision`` (frm -> to) for ``ticket``."""
    store.append(
        build_routing_decision(
            ticket_id=ticket,
            from_status=frm,
            to_status=to,
            assignee="qa-eng",
            model="sonnet",
            reason=f"kill-drill {ticket}: {frm} -> {to}",
            confidence=0.99,
            policy_checks=["kill_drill"],
            fallback="skip",
            created_at=iso_at(seq),
            run_id=run_id,
        )
    )


def _record_completion(
    runs_dir: Path, *, run_id: str, ticket: str, status: str, wave: int, seq: int
) -> None:
    """Durably append a per-ticket completion record (the commit point)."""
    pc.append_ticket_completion(
        run_id=run_id,
        ticket_id=ticket,
        status=status,
        wave=wave,
        created_at=iso_at(seq),
        runs_dir=runs_dir,
    )


def _completion_ids(runs_dir: Path, run_id: str) -> list[str]:
    """All ticket_ids with a durable completion record for ``run_id`` (with repeats)."""
    path = Path(runs_dir) / run_id / "completions.jsonl"
    ids: list[str] = []
    if not path.exists():
        return ids
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if ev.get("event_type") == "ticket_completion" and ev.get("run_id") == run_id:
            tid = ev.get("ticket_id")
            if tid:
                ids.append(str(tid))
    return ids


def _final_states(events_path: Path, run_id: str) -> tuple[dict[str, str], list[str]]:
    """Per-ticket final status + corrupted-chain list for ``run_id``.

    Reuses replay_qa.group_runs + replay_qa.replay_run (the canonical transition
    model) — the drill never re-implements the replay walk.
    """
    evs = wave_kpi.read_events(str(events_path))
    run_evs = replay_qa.group_runs(evs).get(run_id, [])
    per_ticket: dict[str, list[dict]] = {}
    for ev in run_evs:
        tid = str(ev.get("ticket_id") or "")
        if tid:
            per_ticket.setdefault(tid, []).append(ev)
    final: dict[str, str] = {}
    corrupted: list[str] = []
    for tid, tevs in per_ticket.items():
        result = replay_qa.replay_run(tevs)
        if result["corrupted"]:
            corrupted.append(tid)
        else:
            final[tid] = result["final_status"]
    return final, corrupted


# ---------------------------------------------------------------------------
# The synthetic worker — runs in a CHILD process and kills -9 itself mid-wave-2
# ---------------------------------------------------------------------------

# Default synthetic plan: 3 waves; the crash lands in wave 2.
DEFAULT_WAVES: list[list[str]] = [
    ["DAS-8001", "DAS-8002"],
    ["DAS-8003", "DAS-8004", "DAS-8005"],
    ["DAS-8006", "DAS-8007"],
]
DEFAULT_CRASH: dict[str, object] = {"wave": 2, "ticket_index": 1, "phase": "after_in_progress"}
DEFAULT_ANCHOR = "DAS-8001"


def _worker_run(spec: dict) -> None:
    """CHILD entrypoint: drive the synthetic run, SIGKILL-ing at the crash point.

    Ordering per ticket: durable in_progress event → (work) → durable done event
    → durable completion record (the commit point). The completion record is
    LAST, so the tiny window between the done event and the completion record is
    exercised by ``phase == 'after_done'`` (an idempotency-window crash).
    """
    run_id = str(spec["run_id"])
    anchor = str(spec["anchor"])
    events_path = Path(spec["events_path"])
    runs_dir = Path(spec["runs_dir"])
    waves: list[list[str]] = spec["waves"]
    crash: dict | None = spec.get("crash")

    store = EventStore(events_path)
    seq = 0
    cumulative: dict[str, str] = {}

    def _is_crash(wave_no: int, ti: int, phase: str) -> bool:
        return bool(
            crash
            and crash.get("wave") == wave_no
            and crash.get("ticket_index") == ti
            and crash.get("phase") == phase
        )

    for wave_no, wave in enumerate(waves, start=1):
        for ti, ticket in enumerate(wave):
            _append_transition(store, run_id=run_id, ticket=ticket, frm="todo", to="in_progress", seq=seq)
            seq += 1
            if _is_crash(wave_no, ti, "after_in_progress"):
                _crash_now()  # genuine kill -9 — never returns
            _append_transition(store, run_id=run_id, ticket=ticket, frm="in_progress", to="done", seq=seq)
            seq += 1
            if _is_crash(wave_no, ti, "after_done"):
                _crash_now()
            _record_completion(runs_dir, run_id=run_id, ticket=ticket, status="done", wave=wave_no, seq=seq)
            seq += 1
            cumulative[ticket] = "done"
        # Wave-boundary checkpoint (only reached for waves fully completed before
        # the crash — so the crash leaves the last VALID checkpoint at wave-1).
        pc.write_wave_checkpoint(
            run_id=run_id,
            wave=wave_no,
            ticket_id=anchor,
            curr_ticket_states=dict(cumulative),
            pending_interrupts=[],
            created_at=iso_at(seq),
            store_path=events_path,
            runs_dir=runs_dir,
        )
        seq += 1


def _crash_now() -> None:
    """Abrupt process death — SIGKILL to self. No cleanup, no flush, no atexit."""
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)


# ---------------------------------------------------------------------------
# KILL DRILL — spawn the child, kill it, resume, assert zero lost / zero dup
# ---------------------------------------------------------------------------


def run_kill_drill(work_dir: Path, *, waves: list[list[str]] | None = None,
                   crash: dict | None = None, anchor: str = DEFAULT_ANCHOR) -> dict:
    """Run one kill/resume drill in ``work_dir``; return a result dict.

    Returns keys: ``run_id``, ``events_path`` (str), ``killed`` (bool: child died
    by SIGKILL), ``zero_lost`` (bool), ``zero_duplicated`` (bool),
    ``chain_clean`` (bool), ``ok`` (bool: all three hold and the child was
    killed), and diagnostic ``lost`` / ``corrupted`` / ``dup_completions`` lists.
    """
    waves = waves if waves is not None else DEFAULT_WAVES
    crash = crash if crash is not None else DEFAULT_CRASH

    work_dir.mkdir(parents=True, exist_ok=True)
    run_id = pc.generate_ulid()
    events_path = work_dir / "events.jsonl"
    runs_dir = work_dir / "runs"
    spec = {
        "run_id": run_id,
        "anchor": anchor,
        "events_path": str(events_path),
        "runs_dir": str(runs_dir),
        "waves": waves,
        "crash": crash,
    }
    spec_path = work_dir / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    # 1. Spawn the child and let it kill -9 itself mid-wave-2.
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(spec_path)])
    proc.wait()
    killed = proc.returncode == -signal.SIGKILL

    flat = [t for wave in waves for t in wave]

    # 2. Resume via resume_fork (DAS-1445): the durable log + completion records
    #    tell us exactly what still needs work.
    resume_unfinished = rf.resume_run(run_id, events_path, runs_dir)  # {t: last_status}, excludes completed
    completed_before = pc.get_completed_tickets(run_id, runs_dir)
    run_evs = replay_qa.group_runs(wave_kpi.read_events(str(events_path))).get(run_id, [])
    started = {str(ev.get("ticket_id")) for ev in run_evs if ev.get("ticket_id")}

    # 3. Re-dispatch: resume the started-but-unfinished tickets from their last
    #    recorded status, and cold-start the tickets that never began. A ticket
    #    that is durably terminal in the log OR has a completion record is skipped
    #    (idempotent — no duplicate work).
    store = EventStore(events_path)
    seq = _RESUME_SEQ_BASE
    for wave_no, wave in enumerate(waves, start=1):
        for ticket in wave:
            if ticket in resume_unfinished:
                frm = resume_unfinished[ticket]
                _append_transition(store, run_id=run_id, ticket=ticket, frm=frm, to="done", seq=seq)
                seq += 1
                _record_completion(runs_dir, run_id=run_id, ticket=ticket, status="done", wave=wave_no, seq=seq)
                seq += 1
            elif ticket not in started and ticket not in completed_before:
                # never started and no durable record — cold dispatch
                _append_transition(store, run_id=run_id, ticket=ticket, frm="todo", to="in_progress", seq=seq)
                seq += 1
                _append_transition(store, run_id=run_id, ticket=ticket, frm="in_progress", to="done", seq=seq)
                seq += 1
                _record_completion(runs_dir, run_id=run_id, ticket=ticket, status="done", wave=wave_no, seq=seq)
                seq += 1
            # else: durably done (terminal in log or has completion record) — skip.

    # 4. Verify the resume boundary.
    final, corrupted = _final_states(events_path, run_id)
    lost = [t for t in flat if final.get(t) not in ("done", "blocked")]
    comp_ids = _completion_ids(runs_dir, run_id)
    dup_completions = sorted({t for t in comp_ids if comp_ids.count(t) > 1})

    zero_lost = not lost
    zero_duplicated = not corrupted and not dup_completions
    chain_clean = not corrupted
    ok = killed and zero_lost and zero_duplicated and chain_clean
    return {
        "run_id": run_id,
        "events_path": str(events_path),
        "killed": killed,
        "zero_lost": zero_lost,
        "zero_duplicated": zero_duplicated,
        "chain_clean": chain_clean,
        "ok": ok,
        "lost": lost,
        "corrupted": corrupted,
        "dup_completions": dup_completions,
    }


# ---------------------------------------------------------------------------
# FORK DRILL — fork from a wave-1 checkpoint into a divergent run; original intact
# ---------------------------------------------------------------------------


def run_fork_drill(work_dir: Path) -> dict:
    """Fork from a wave-1 checkpoint to a divergent outcome; prove original intact.

    Returns keys: ``base_run``, ``fork_run``, ``fork_events_path`` (str),
    ``divergent`` (bool), ``original_intact`` (bool), ``ok`` (bool), plus
    ``original_final`` / ``fork_final`` for reporting.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    base_run = pc.generate_ulid()
    anchor = "DAS-8501"
    events_b = work_dir / "base-events.jsonl"
    runs_dir = work_dir / "runs"
    store_b = EventStore(events_b)

    # Base run: DAS-8501 is in_progress at the wave-1 boundary, then done at wave-2.
    _append_transition(store_b, run_id=base_run, ticket=anchor, frm="todo", to="in_progress", seq=0)
    pc.write_wave_checkpoint(
        run_id=base_run, wave=1, ticket_id=anchor,
        curr_ticket_states={anchor: "in_progress"}, pending_interrupts=[],
        created_at=iso_at(1), store_path=events_b, runs_dir=runs_dir,
    )
    _append_transition(store_b, run_id=base_run, ticket=anchor, frm="in_progress", to="done", seq=2)
    pc.write_wave_checkpoint(
        run_id=base_run, wave=2, ticket_id=anchor,
        curr_ticket_states={anchor: "done"}, pending_interrupts=[],
        created_at=iso_at(3), store_path=events_b, runs_dir=runs_dir,
    )
    original_final, _ = _final_states(events_b, base_run)  # {DAS-8501: done}

    # Snapshot the original's on-disk state to prove intactness after the fork.
    events_b_before = events_b.read_bytes()
    cp1_path = runs_dir / base_run / "wave-001.checkpoint.json"
    cp2_path = runs_dir / base_run / "wave-002.checkpoint.json"
    cp1_before = cp1_path.read_bytes()
    cp2_before = cp2_path.read_bytes()

    # Fork at wave-1 (resume_fork.fork_run, DAS-1445): new run_id + inherited state.
    fork_run, fork_states = rf.fork_run(base_run, wave_num=1, runs_dir=runs_dir)

    # Drive the fork DIVERGENTLY in its OWN store + checkpoint tree: the ticket the
    # original ran to `done`, the fork runs to `blocked`.
    events_f = work_dir / "fork-events.jsonl"
    store_f = EventStore(events_f)
    start_status = fork_states.get(anchor, "in_progress")
    _append_transition(store_f, run_id=fork_run, ticket=anchor, frm=start_status, to="blocked", seq=10)
    pc.write_wave_checkpoint(
        run_id=fork_run, wave=1, ticket_id=anchor,
        curr_ticket_states={anchor: "blocked"}, pending_interrupts=[],
        created_at=iso_at(11), store_path=events_f, runs_dir=runs_dir,
    )
    fork_final, fork_corrupt = _final_states(events_f, fork_run)  # {DAS-8501: blocked}

    # Divergence: fork's outcome differs from the original's.
    divergent = fork_final.get(anchor) != original_final.get(anchor) and not fork_corrupt

    # Original intact: bytes unchanged, checkpoints unchanged, still replays clean
    # to the same final state, and the fork used a fresh run_id.
    events_b_after = events_b.read_bytes()
    orig_final_after, orig_corrupt = _final_states(events_b, base_run)
    original_intact = (
        events_b_after == events_b_before
        and cp1_path.read_bytes() == cp1_before
        and cp2_path.read_bytes() == cp2_before
        and not orig_corrupt
        and orig_final_after == original_final
        and fork_run != base_run
    )

    chain_clean = not fork_corrupt and not orig_corrupt
    ok = divergent and original_intact
    return {
        "base_run": base_run,
        "fork_run": fork_run,
        "fork_events_path": str(events_f),
        "divergent": divergent,
        "original_intact": original_intact,
        "chain_clean": chain_clean,
        "ok": ok,
        "original_final": original_final,
        "fork_final": fork_final,
    }


# ---------------------------------------------------------------------------
# T5 accumulation + scoring
# ---------------------------------------------------------------------------


def emit_recovery_drill(
    out_store: Path,
    *,
    run_id: str,
    outcome: str,
    corrupted: bool,
    created_at: str | None = None,
) -> None:
    """Append one ``recovery_drill`` event in the EXACT shape ``replay_qa --emit`` writes.

    The T5 gate (``metrics_lib.recovery_reliability`` → ``check_recovery.py``)
    already consumes this shape, so no gate change is needed. This is the
    "equivalent writer" the ticket sanctions: ``replay_qa --emit`` groups a whole
    run (all tickets sharing a ``run_id``) into ONE transition chain — correct for
    the single-ticket runs it was built for, but a multi-ticket drill run must be
    replayed PER TICKET. So the ``outcome``/``corrupted`` verdict is derived by the
    caller from ``replay_qa.replay_run`` applied per ticket (see ``_final_states``),
    and written here in ``replay_qa``'s own field set.
    """
    now = created_at or datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "event_type": "recovery_drill",
        "ticket_id": "DAS-KILLDRILL",
        "run_id": run_id,
        "created_at": now,
        "outcome": outcome,
        "corrupted": corrupted,
    }
    with open(out_store, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def run_drills(*, iterations: int, tmp_root: Path, target: float = 0.99) -> int:
    """Run ``iterations`` kill drills + one fork drill, emit recovery_drill events,
    then score them through check_recovery.py. Returns a process exit code.
    """
    import check_recovery  # noqa: PLC0415 (lazy — only the CLI path needs it)

    out_store = tmp_root / "drill-events.jsonl"
    failures: list[str] = []

    print(f"kill-drill: running {iterations} kill drill iteration(s) + 1 fork drill...")
    for i in range(iterations):
        res = run_kill_drill(tmp_root / f"kill-{i:03d}")
        status = "ok" if res["ok"] else "FAIL"
        print(
            f"  kill[{i:03d}] {status}: killed={res['killed']} "
            f"zero_lost={res['zero_lost']} zero_dup={res['zero_duplicated']} "
            f"chain_clean={res['chain_clean']}"
        )
        if not res["ok"]:
            failures.append(
                f"kill[{i}] lost={res['lost']} corrupted={res['corrupted']} "
                f"dup={res['dup_completions']} killed={res['killed']}"
            )
        # Emit the recovery_drill for this iteration's (resumed) run. A corrupted
        # resume chain sets corrupted=true → the T5 zero-corrupted guardrail FAILs.
        emit_recovery_drill(
            out_store,
            run_id=res["run_id"],
            outcome="success" if res["ok"] else "fail",
            corrupted=not res["chain_clean"],
        )

    fork = run_fork_drill(tmp_root / "fork")
    fstatus = "ok" if fork["ok"] else "FAIL"
    print(
        f"  fork      {fstatus}: divergent={fork['divergent']} "
        f"(original {fork['original_final']} -> fork {fork['fork_final']}), "
        f"original_intact={fork['original_intact']}"
    )
    if not fork["ok"]:
        failures.append(f"fork divergent={fork['divergent']} intact={fork['original_intact']}")
    emit_recovery_drill(
        out_store,
        run_id=fork["fork_run"],
        outcome="success" if fork["ok"] else "fail",
        corrupted=not fork["chain_clean"],
    )

    # Score the emitted recovery_drill events through the EXISTING T5 gate.
    print("kill-drill: scoring emitted recovery_drill events via check_recovery.py...")
    gate_rc = check_recovery.main(["--events", str(out_store), "--target", str(target)])

    if failures:
        sys.stderr.write("kill-drill FAILED:\n" + "\n".join(f"  - {f}" for f in failures) + "\n")
        return 1
    if gate_rc != 0:
        sys.stderr.write(f"kill-drill: T5 gate reported non-zero exit ({gate_rc}).\n")
        return 1
    print("kill-drill: OK — all drills passed and the T5 gate is green.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--smoke", action="store_true",
                       help="cheap CI variant: 1 kill drill + 1 fork drill, emit + score")
    group.add_argument("--iterations", type=int, default=None,
                       help="expensive scheduled variant: run N kill drills (>=20) + fork")
    group.add_argument("--worker", type=Path, default=None,
                       help="internal: child-process entrypoint; value is the spec JSON path")
    ap.add_argument("--target", type=float, default=0.99, help="T5 ratio target (default 0.99)")
    ap.add_argument("--keep", action="store_true", help="keep the temp drill directory (debug)")
    args = ap.parse_args(argv)

    # Child-process mode: run the synthetic worker (it kills -9 itself).
    if args.worker is not None:
        spec = json.loads(Path(args.worker).read_text(encoding="utf-8"))
        _worker_run(spec)
        return 0  # only reached when spec has no crash (clean run)

    iterations = 1 if args.smoke else (args.iterations if args.iterations is not None else 1)
    if iterations < 1:
        sys.stderr.write("--iterations must be >= 1\n")
        return 2

    tmp_root = Path(tempfile.mkdtemp(prefix="daslab-kill-drill-"))
    try:
        return run_drills(iterations=iterations, tmp_root=tmp_root, target=args.target)
    finally:
        if not args.keep:
            import shutil

            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
