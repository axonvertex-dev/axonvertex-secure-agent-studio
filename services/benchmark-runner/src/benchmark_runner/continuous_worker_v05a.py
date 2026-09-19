"""Checkpoint 2E-0.5A: single-host continuous dispatcher for the proven A->B->A bridge.

Submit once; the worker automatically executes plan / scout / resume via the
resident Gemma gateway, with one on-disk lock per run and a SQLite job/event
journal. This is NOT the complete Foundation Sec/remediation workflow.
No A2A, MCP, user repo access, or code mutation is enabled.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_runner import durable_gateway_bridge_v04d2 as gateway
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner.durable_runtime_v04 import TransitionError, canonical_json, utc_now

BASE = Path("benchmarks/results/checkpoint2e/continuous-worker-v05a")
RUN_BASE = bridge.BASE
HANDOFF_COMPLETE = "HANDOFF_COMPLETED"  # intentionally NOT verified remediation
MAX_ATTEMPTS = 3


def _ensure_run_id(run_id: str) -> None:
    bridge.validate_run_id(run_id)


class BusyWorker(RuntimeError):
    pass


class Queue:
    def __init__(self, db_file: Path):
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_file), isolation_level=None, timeout=15)
        os.chmod(self.db_file, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          run_id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          phase TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error_type TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS worker_events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES jobs(run_id),
          kind TEXT NOT NULL, reason_code TEXT NOT NULL,
          phase TEXT NOT NULL, details TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS worker_jobs_queue_idx ON jobs(status,created_at);
        """)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Queue":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _event(self, run_id: str, kind: str, reason: str, phase: str,
               details: dict[str, Any] | None = None) -> None:
        self.db.execute("INSERT INTO worker_events(run_id,kind,reason_code,phase,details,created_at) "
                        "VALUES(?,?,?,?,?,?)", (run_id, kind, reason, phase,
                                                 canonical_json(details or {}), utc_now()))

    def submit(self, run_id: str) -> dict[str, Any]:
        _ensure_run_id(run_id)
        stamp = utc_now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM jobs WHERE run_id=?", (run_id,)).fetchone():
                raise TransitionError("Run already submitted; inspect instead of submitting twice")
            self.db.execute("INSERT INTO jobs(run_id,status,phase,created_at,updated_at) "
                            "VALUES(?,?,?,?,?)", (run_id, "QUEUED", "PREPARE", stamp, stamp))
            self._event(run_id, "TASK_SUBMITTED", "USER_SUBMITTED", "PREPARE")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.inspect(run_id)

    def pending(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT run_id FROM jobs "
                    "WHERE status IN ('QUEUED','WORKING') ORDER BY created_at,run_id")]

    def inspect(self, run_id: str) -> dict[str, Any]:
        _ensure_run_id(run_id)
        item = self.db.execute("SELECT * FROM jobs WHERE run_id=?", (run_id,)).fetchone()
        if not item:
            raise TransitionError("Unknown submitted run")
        events = self.db.execute("SELECT seq,kind,reason_code,phase,details,created_at "
                                 "FROM worker_events WHERE run_id=? ORDER BY seq", (run_id,))
        return {"job": dict(item), "events": [
            {**dict(e), "details": json.loads(e["details"])} for e in events]}

    def begin(self, run_id: str) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT status,phase,attempts FROM jobs WHERE run_id=?",
                                  (run_id,)).fetchone()
            if not row or row["status"] not in ("QUEUED", "WORKING"):
                raise TransitionError("Job is not eligible for processing")
            self.db.execute("UPDATE jobs SET status='WORKING', attempts=attempts+1,updated_at=? "
                            "WHERE run_id=?", (utc_now(), run_id))
            self._event(run_id, "STAGE_STARTED", "RUN_LOCK_ACQUIRED", row["phase"],
                        {"attempt": row["attempts"] + 1})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def finish_stage(self, run_id: str, phase: str, *, complete: bool) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT status FROM jobs WHERE run_id=?", (run_id,)).fetchone()
            if not row or row["status"] != "WORKING":
                raise TransitionError("Stage completion requires an active job")
            status = HANDOFF_COMPLETE if complete else "QUEUED"
            self.db.execute("UPDATE jobs SET status=?,phase=?,attempts=0,last_error_type=NULL," 
                            "updated_at=? WHERE run_id=?", (status, phase, utc_now(), run_id))
            self._event(run_id, "STAGE_COMMITTED", "PERSISTED_BRIDGE_STATE", phase,
                        {"job_status": status})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def fail(self, run_id: str, phase: str, exc: Exception, *, hold: bool = False) -> dict[str, Any]:
        # Only exception TYPE is persisted. Never write gateway errors, auth, source or prompts.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT attempts FROM jobs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise TransitionError("Unknown run during failure")
            status = "NEEDS_OPERATOR_RECOVERY" if hold or row["attempts"] >= MAX_ATTEMPTS else "QUEUED"
            self.db.execute("UPDATE jobs SET status=?,phase=?,last_error_type=?,updated_at=? "
                            "WHERE run_id=?", (status, phase, type(exc).__name__, utc_now(), run_id))
            self._event(run_id, "STAGE_FAILED", "OPERATOR_RECOVERY_REQUIRED" if hold else
                        "BOUNDED_RETRY_OR_HOLD", phase, {"error_type": type(exc).__name__,
                        "job_status": status, "attempt": row["attempts"]})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.inspect(run_id)


@contextmanager
def run_lock(run_id: str, locks: Path) -> Iterator[bool]:
    """Single-host kernel flock. Released automatically if worker is killed.

    SQLite queue is persistent; flock prevents two Node A workers from starting
    the same external model request even if their individual processes restart.
    This deliberately does not promise multi-host distributed locking.
    """
    _ensure_run_id(run_id)
    locks.mkdir(parents=True, exist_ok=True)
    fd = os.open(locks / (run_id + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def source_state(run_id: str, *, base: Path = RUN_BASE) -> str:
    """Never guess success from an unverified JSON file alone."""
    ps = bridge.paths(run_id, base)
    if not ps["folder"].exists():
        return "PREPARE"
    if not ps["prep"].is_file() or not ps["db"].is_file():
        raise TransitionError("Partial preparation requires operator recovery")
    with bridge.BridgeRuntime(ps["db"]) as rt:
        status = rt.snapshot(run_id)["status"]
    if status not in ("WAITING_FOR_SCOUT", "READY_TO_RESUME", "GEMMA_RESUMED"):
        raise TransitionError("Unknown bridge state requires operator recovery")
    return status


def _safe_gateway_provider(run_id: str, *, base: Path) -> gateway.GatewayProvider:
    # Called once per *active* stage, not while workflow waits. No direct A fallback.
    return gateway.GatewayProvider(run_id, base=base)


def advance(queue: Queue, run_id: str, *, base: Path = RUN_BASE,
            provider_factory: Callable[[str], Any] | None = None,
            locks: Path = BASE / "locks") -> dict[str, Any]:
    """Perform at most ONE stage. Reinspect the bridge after each persisted step."""
    with run_lock(run_id, locks) as locked:
        if not locked:
            return {"run_id": run_id, "status": "BUSY_OTHER_WORKER"}
        job = queue.inspect(run_id)["job"]
        if job["status"] not in ("QUEUED", "WORKING"):
            return {"run_id": run_id, "status": job["status"], "phase": job["phase"]}
        queue.begin(run_id)
        try:
            phase = source_state(run_id, base=base)
        except (TransitionError, ValueError, OSError, sqlite3.Error) as exc:
            queue.fail(run_id, job["phase"], exc, hold=True)
            return {"run_id": run_id, "status": "NEEDS_OPERATOR_RECOVERY",
                    "phase": job["phase"], "error_type": type(exc).__name__}
        if phase == "GEMMA_RESUMED":
            queue.finish_stage(run_id, phase, complete=True)
            return {"run_id": run_id, "status": HANDOFF_COMPLETE, "phase": phase}
        try:
            provider = provider_factory(run_id) if provider_factory else _safe_gateway_provider(run_id, base=base)
            try:
                if phase == "PREPARE":
                    bridge.prepare(run_id, base=base, provider=provider)
                elif phase == "WAITING_FOR_SCOUT":
                    bridge.scout_live(run_id, base=base, provider=provider)
                else:
                    bridge.resume_live(run_id, base=base, provider=provider)
            finally:
                provider.close()
            result_phase = source_state(run_id, base=base)
            queue.finish_stage(run_id, result_phase, complete=result_phase == "GEMMA_RESUMED")
            return {"run_id": run_id,
                    "status": HANDOFF_COMPLETE if result_phase == "GEMMA_RESUMED" else "QUEUED",
                    "phase": result_phase}
        except (RuntimeError, ValueError, OSError, sqlite3.Error, KeyError, StopIteration) as exc:
            try:
                current = source_state(run_id, base=base)
            except (TransitionError, ValueError, OSError, sqlite3.Error):
                queue.fail(run_id, phase, exc, hold=True)
                return {"run_id": run_id, "status": "NEEDS_OPERATOR_RECOVERY",
                        "phase": phase, "error_type": type(exc).__name__}
            if current != phase:  # crash/retry after stage effects: reconcile via actual DB state
                queue.finish_stage(run_id, current, complete=current == "GEMMA_RESUMED")
                return {"run_id": run_id, "status": HANDOFF_COMPLETE if current == "GEMMA_RESUMED" else "QUEUED",
                        "phase": current, "recovered_committed_transition": True}
            job_after = queue.fail(run_id, phase, exc)
            return {"run_id": run_id, "status": job_after["job"]["status"],
                    "phase": phase, "error_type": type(exc).__name__}


def serve(queue: Queue, *, base: Path = RUN_BASE, locks: Path = BASE / "locks",
          poll_seconds: float = 2, stop_when_idle: bool = False,
          provider_factory: Callable[[str], Any] | None = None,
          max_steps: int | None = None) -> list[dict[str, Any]]:
    if not 0.05 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be 0.05-60")
    records: list[dict[str, Any]] = []
    while True:
        jobs = queue.pending()
        if not jobs:
            if stop_when_idle:
                return records
            time.sleep(poll_seconds)
            continue
        selected = None
        for run_id in jobs:
            result = advance(queue, run_id, base=base, provider_factory=provider_factory, locks=locks)
            if result.get("status") != "BUSY_OTHER_WORKER":
                selected = result
                break
        if selected is None:
            if stop_when_idle:
                return records
            time.sleep(poll_seconds)
            continue
        records.append(selected)
        print(json.dumps(selected, sort_keys=True), flush=True)
        if max_steps is not None and len(records) >= max_steps:
            return records
        if selected["status"] == "QUEUED" and selected.get("error_type"):
            time.sleep(poll_seconds)  # bounded retry delay, not a busy spin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("submit", "inspect", "step", "serve"))
    parser.add_argument("--run-id")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--stop-when-idle", action="store_true")
    args = parser.parse_args()
    try:
        if args.command != "serve" and not args.run_id:
            raise ValueError("--run-id required")
        with Queue(BASE / "jobs.sqlite3") as queue:
            if args.command == "submit":
                result = queue.submit(args.run_id)
            elif args.command == "inspect":
                result = queue.inspect(args.run_id)
                try:
                    result["bridge_status"] = source_state(args.run_id)
                except (TransitionError, OSError, sqlite3.Error):
                    result["bridge_status"] = "PARTIAL_OR_UNAVAILABLE"
            elif args.command == "step":
                result = advance(queue, args.run_id)
            else:
                serve(queue, poll_seconds=args.poll_seconds,
                      stop_when_idle=args.stop_when_idle)
                return 0
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (TransitionError, ValueError, OSError, sqlite3.Error) as exc:
        print("WORKER_ERROR: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
