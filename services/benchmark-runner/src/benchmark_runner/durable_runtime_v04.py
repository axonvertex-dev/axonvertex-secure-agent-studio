"""Checkpoint 2E-0.4A: SQLite-backed durable task transitions and resume outbox.

NARROW CONTRACT: proves restart survival and transactional/idempotent state changes.
Does not call Gemma/Antares, verify evidence, or provide exactly-once model execution.
Do not persist model private reasoning or credentials here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def artifact_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class TransitionError(RuntimeError):
    """An operation violates the persisted runtime state or lease precondition."""


class DurableRuntime:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self._schema()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "DurableRuntime":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _schema(self) -> None:
        # SQLite's persistent metadata is initialized once and checked thereafter.
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (
          name TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          context_snapshot_id TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          task_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES runs(run_id),
          owner TEXT NOT NULL, purpose TEXT NOT NULL,
          state TEXT NOT NULL, dependency_task_id TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
          artifact_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES runs(run_id),
          producer_task_id TEXT NOT NULL REFERENCES tasks(task_id),
          artifact_type TEXT NOT NULL,
          content_sha256 TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES runs(run_id),
          event_key TEXT NOT NULL,
          event_type TEXT NOT NULL, actor TEXT NOT NULL,
          reason_code TEXT NOT NULL, task_id TEXT,
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(run_id, event_key)
        );
        CREATE TABLE IF NOT EXISTS outbox (
          job_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES runs(run_id),
          task_id TEXT NOT NULL REFERENCES tasks(task_id),
          kind TEXT NOT NULL, status TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          lease_token TEXT, lease_until REAL,
          attempts INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_claim
          ON outbox(run_id, kind, status, lease_until);
        """)
        self.db.execute("INSERT OR IGNORE INTO metadata(name,value) VALUES('schema_version',?)",
                        (str(SCHEMA_VERSION),))
        version = self.db.execute("SELECT value FROM metadata WHERE name='schema_version'").fetchone()[0]
        if version != str(SCHEMA_VERSION):
            raise TransitionError(f"Unsupported durable runtime schema version: {version}")

    def _begin(self) -> None:
        self.db.execute("BEGIN IMMEDIATE")

    def _event(self, run_id: str, key: str, event_type: str, actor: str,
               reason: str, task_id: str | None = None,
               payload: dict[str, Any] | None = None) -> None:
        self.db.execute("""INSERT OR IGNORE INTO events
          (run_id,event_key,event_type,actor,reason_code,task_id,payload_json,created_at)
          VALUES (?,?,?,?,?,?,?,?)""",
          (run_id, key, event_type, actor, reason, task_id,
           canonical_json(payload or {}), utc_now()))

    @staticmethod
    def _task_id(run_id: str, suffix: str) -> str:
        return f"{run_id}:{suffix}"

    def start(self, run_id: str, context_snapshot_id: str) -> dict[str, Any]:
        if not run_id or not context_snapshot_id:
            raise ValueError("Nonempty run ID and context snapshot ID required")
        if len(run_id) > 128 or len(context_snapshot_id) > 256:
            raise ValueError("Identifier exceeds length limit")
        root, scout, stamp = self._task_id(run_id, "root"), self._task_id(run_id, "scout"), utc_now()
        self._begin()
        try:
            existing = self.db.execute("SELECT context_snapshot_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                if existing["context_snapshot_id"] != context_snapshot_id:
                    raise TransitionError("Run ID already exists with a different context snapshot")
            else:
                self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?)",
                                (run_id, "WAITING_FOR_SCOUT", context_snapshot_id, stamp, stamp))
                for task, owner, purpose, state, dependency in (
                    (root, "AgentRuntime/Gemma", "Resume Gemma after scoped scout result", "WAITING", scout),
                    (scout, "SecurityScout/Antares", "Produce bounded read-only scout artifact", "READY", None),
                ):
                    self.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)",
                                    (task, run_id, owner, purpose, state, dependency, stamp, stamp))
                self.db.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (f"{run_id}:dispatch-scout", run_id, scout,
                                 "DISPATCH_SCOUT", "PENDING", canonical_json({"context_snapshot_id": context_snapshot_id}),
                                 None, None, 0, stamp, stamp))
                self._event(run_id, "workflow-created", "WORKFLOW_CREATED", "AgentRuntime",
                            "USER_REQUEST", root, {"context_snapshot_id": context_snapshot_id})
                self._event(run_id, "scout-delegated", "TASK_DELEGATED", "AgentRuntime/Gemma",
                            "CANDIDATE_EVIDENCE_REQUIRED", scout, {"root_state": "WAITING"})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.snapshot(run_id)

    def complete_scout(self, run_id: str, artifact_id: str,
                       evidence_ids: list[str]) -> dict[str, Any]:
        if not artifact_id or len(artifact_id) > 256:
            raise ValueError("A bounded artifact ID is required")
        if not evidence_ids or any(not isinstance(x, str) or not x or len(x) > 256 for x in evidence_ids):
            raise ValueError("One or more nonempty evidence references required")
        if len(evidence_ids) > 100 or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("Duplicate or excessive evidence references")
        payload = {"evidence_ids": evidence_ids, "artifact_source": "reference_only_unverified"}
        digest, scout, root, stamp = (artifact_digest(payload), self._task_id(run_id, "scout"),
                                      self._task_id(run_id, "root"), utc_now())
        self._begin()
        try:
            state = self.db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not state:
                raise TransitionError("Unknown run")
            previous = self.db.execute("SELECT content_sha256 FROM artifacts WHERE artifact_id=?",
                                       (artifact_id,)).fetchone()
            if previous:
                if previous["content_sha256"] != digest:
                    raise TransitionError("Artifact ID conflicts with different content")
                # Only the exact same completion of this run is idempotent.
                owned = self.db.execute("SELECT 1 FROM artifacts WHERE artifact_id=? AND run_id=? AND producer_task_id=?",
                                        (artifact_id, run_id, scout)).fetchone()
                if not owned:
                    raise TransitionError("Artifact ID belongs to another task")
                self.db.commit()
                return self.snapshot(run_id)
            if state["status"] != "WAITING_FOR_SCOUT":
                raise TransitionError("Scout result not expected in current state")
            self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
                            (artifact_id, run_id, scout, "CandidateFinding", digest, canonical_json(payload), stamp))
            self.db.execute("UPDATE tasks SET state='COMPLETED',updated_at=? WHERE task_id=? AND state='READY'",
                            (stamp, scout))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1:
                raise TransitionError("Scout task is not READY")
            self.db.execute("UPDATE tasks SET state='READY',updated_at=? WHERE task_id=? AND state='WAITING'",
                            (stamp, root))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1:
                raise TransitionError("Root task is not waiting")
            self.db.execute("UPDATE runs SET status='READY_TO_RESUME',updated_at=? WHERE run_id=?",
                            (stamp, run_id))
            self.db.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (f"{run_id}:resume-gemma", run_id, root, "RESUME_GEMMA", "PENDING",
                             canonical_json({"artifact_id": artifact_id, "context_snapshot_id":
                                             self.db.execute("SELECT context_snapshot_id FROM runs WHERE run_id=?",
                                                             (run_id,)).fetchone()[0]}),
                             None, None, 0, stamp, stamp))
            self.db.execute("UPDATE outbox SET status='DONE',updated_at=? WHERE job_id=?",
                            (stamp, f"{run_id}:dispatch-scout"))
            self._event(run_id, "scout-completed", "ARTIFACT_RECEIVED", "SecurityScout/Antares",
                        "SCOUT_RESULT_AVAILABLE", scout, {"artifact_id": artifact_id, "content_sha256": digest})
            self._event(run_id, "gemma-resume-ready", "AGENT_RESUME_READY", "AgentRuntime",
                        "DEPENDENCY_SATISFIED", root, {"artifact_id": artifact_id})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.snapshot(run_id)

    def claim_resume(self, run_id: str, worker_id: str, *, lease_seconds: float = 60,
                     now_epoch: float | None = None) -> dict[str, Any] | None:
        if not worker_id or len(worker_id) > 128 or not 0 < lease_seconds <= 3600:
            raise ValueError("Invalid worker ID or lease duration")
        now_epoch = time.time() if now_epoch is None else now_epoch
        self._begin()
        try:
            run = self.db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not run:
                raise TransitionError("Unknown run")
            if run["status"] != "READY_TO_RESUME":
                self.db.commit()
                return None
            job = self.db.execute("""SELECT * FROM outbox WHERE run_id=? AND kind='RESUME_GEMMA'
                AND (status='PENDING' OR (status='LEASED' AND lease_until<=?))""",
                (run_id, now_epoch)).fetchone()
            if not job:
                self.db.commit()
                return None
            token, stamp = secrets.token_hex(24), utc_now()
            self.db.execute("""UPDATE outbox SET status='LEASED',lease_token=?,lease_until=?,
                attempts=attempts+1,updated_at=? WHERE job_id=?""",
                (token, now_epoch + lease_seconds, stamp, job["job_id"]))
            self._event(run_id, f"lease:{job['attempts'] + 1}", "RESUME_LEASED", worker_id,
                        "WORKER_CLAIMED_DEPENDENCY", job["task_id"], {"attempt": job["attempts"] + 1})
            self.db.commit()
            return {"job_id": job["job_id"], "run_id": run_id, "task_id": job["task_id"],
                    "lease_token": token, "attempt": job["attempts"] + 1,
                    "payload": json.loads(job["payload_json"])}
        except BaseException:
            self.db.rollback()
            raise

    def ack_resume(self, run_id: str, lease_token: str) -> dict[str, Any]:
        if not lease_token:
            raise ValueError("Lease token required")
        root, stamp = self._task_id(run_id, "root"), utc_now()
        self._begin()
        try:
            job = self.db.execute("SELECT * FROM outbox WHERE job_id=?",
                                  (f"{run_id}:resume-gemma",)).fetchone()
            if not job or job["status"] != "LEASED" or not secrets.compare_digest(job["lease_token"] or "", lease_token):
                raise TransitionError("Resume lease is missing or stale")
            if job["lease_until"] < time.time():
                raise TransitionError("Resume lease expired")
            self.db.execute("UPDATE tasks SET state='RUNNING',updated_at=? WHERE task_id=? AND state='READY'",
                            (stamp, root))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1:
                raise TransitionError("Gemma task is not ready")
            self.db.execute("UPDATE runs SET status='GEMMA_RESUMED',updated_at=? WHERE run_id=? AND status='READY_TO_RESUME'",
                            (stamp, run_id))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1:
                raise TransitionError("Run is not ready to resume")
            self.db.execute("UPDATE outbox SET status='DONE',lease_token=NULL,lease_until=NULL,updated_at=? WHERE job_id=?",
                            (stamp, job["job_id"]))
            self._event(run_id, "gemma-resumed", "AGENT_RESUMED", "AgentRuntime/Gemma",
                        "SCOUT_ARTIFACT_AVAILABLE", root,
                        {"artifact_id": json.loads(job["payload_json"])["artifact_id"]})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.snapshot(run_id)

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise TransitionError("Unknown run")
        tasks = self.db.execute("SELECT task_id,owner,purpose,state,dependency_task_id FROM tasks WHERE run_id=? ORDER BY task_id",
                                (run_id,)).fetchall()
        artifacts = self.db.execute("SELECT artifact_id,producer_task_id,artifact_type,content_sha256,payload_json FROM artifacts WHERE run_id=? ORDER BY artifact_id",
                                    (run_id,)).fetchall()
        outbox = self.db.execute("SELECT job_id,kind,status,attempts FROM outbox WHERE run_id=? ORDER BY job_id",
                                 (run_id,)).fetchall()
        events = self.db.execute("SELECT seq,event_type,actor,reason_code,task_id,payload_json FROM events WHERE run_id=? ORDER BY seq",
                                 (run_id,)).fetchall()
        return {"run_id": run_id, "status": run["status"],
                "context_snapshot_id": run["context_snapshot_id"],
                "tasks": [dict(x) for x in tasks],
                "artifacts": [{**{k: x[k] for k in ("artifact_id", "producer_task_id", "artifact_type", "content_sha256")},
                               "payload": json.loads(x["payload_json"])} for x in artifacts],
                "outbox": [dict(x) for x in outbox],
                "events": [{**{k: x[k] for k in ("seq", "event_type", "actor", "reason_code", "task_id")},
                            "payload": json.loads(x["payload_json"])} for x in events]}


def cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("start", "crash-after-start", "inspect", "complete-scout",
                                        "claim-resume", "ack-resume"))
    p.add_argument("--db", required=True, help="Persistent SQLite DB path (under ignored benchmark results)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--context-id", default="ctx-synthetic-checkpoint2e04")
    p.add_argument("--artifact-id", default="artifact-synthetic-scout-001")
    p.add_argument("--evidence-id", action="append", default=[])
    p.add_argument("--worker", default="node-a-demo-worker")
    p.add_argument("--lease-token")
    args = p.parse_args()
    try:
        with DurableRuntime(args.db) as runtime:
            if args.command in ("start", "crash-after-start"):
                result = runtime.start(args.run_id, args.context_id)
                if args.command == "crash-after-start":
                    # Deliberately bypass process-level cleanup to test committed DB survival.
                    os._exit(37)
            elif args.command == "inspect":
                result = runtime.snapshot(args.run_id)
            elif args.command == "complete-scout":
                result = runtime.complete_scout(args.run_id, args.artifact_id, args.evidence_id)
            elif args.command == "claim-resume":
                result = runtime.claim_resume(args.run_id, args.worker)
            else:
                result = runtime.ack_resume(args.run_id, args.lease_token or "")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (TransitionError, ValueError, sqlite3.Error) as exc:
        print(f"DURABLE_RUNTIME_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
