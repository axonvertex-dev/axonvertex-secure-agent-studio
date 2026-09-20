"""Checkpoint 2E-0.7B: LOCAL-only, fixture-scoped, durable operator decision ledger.

A decision is not application, production authorization, signature, or a claim
of verified human identity beyond the distinct OS account executing the CLI.
No model, Docker, Git or Agent Studio HTTP endpoints are invoked.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from benchmark_runner import continuous_remediation_worker_v05c as remediation
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner import operator_review_v07a as review
from benchmark_runner.durable_runtime_v04 import TransitionError, canonical_json, utc_now

DECISION_DB = Path("benchmarks/results/checkpoint2e/operator-decisions-v07b/decisions.sqlite3")
_DECISIONS = frozenset({"APPROVE", "REJECT"})
_REASONS = {
    "APPROVE": frozenset({"VERIFIED_SYNTHETIC_FIX_ACCEPTED"}),
    "REJECT": frozenset({"FIX_NOT_ACCEPTED", "INSUFFICIENT_REVIEW_EVIDENCE",
                         "UNACCEPTABLE_FUNCTIONAL_CHANGE", "OTHER_REVIEW_REASON"}),
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REQ = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,95}\Z")


def principal() -> dict[str, Any]:
    """OS principal; shared Unix accounts are NOT unique human identities."""
    uid, euid = os.getuid(), os.geteuid()
    if uid != euid or uid == 0:
        raise TransitionError("Refusing root or mismatched effective UID")
    return {"uid": uid, "name": pwd.getpwuid(uid).pw_name,
            "identity_assurance": "local_os_account_only"}


def _hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def _eligible(run_id: str, *, expected_candidate_sha256: str,
              expected_verification_sha256: str,
              queue_db: Path, run_base: Path) -> dict[str, Any]:
    bridge.validate_run_id(run_id)
    if not _SHA.fullmatch(expected_candidate_sha256) or not _SHA.fullmatch(expected_verification_sha256):
        raise TransitionError("Explicit 64-hex candidate and verification hashes required")
    projection = review.project(run_id, queue_db=queue_db, run_base=run_base)
    if (projection["job"]["status"] != remediation.APPROVAL_PENDING
            or projection["job"]["phase"] != remediation.APPROVAL_PENDING
            or projection["runtime_status"] != remediation.APPROVAL_PENDING):
        raise TransitionError("Only verified, approval-pending candidates may be decided")
    candidate, verification, security = (
        projection["candidate_change"], projection["verification_result"],
        projection["security_review"])
    if not candidate or not verification or not security or not security["accepted_by_validator"]:
        raise TransitionError("Candidate, accepted review and verification required")
    if not verification["passed"] or not verification["original_fixture_unchanged"]:
        raise TransitionError("Synthetic verification must pass")
    if candidate["source_sha256"] != expected_candidate_sha256:
        raise TransitionError("Candidate hash does not match reviewed candidate")
    artifact_by_type = {a["artifact_type"]: a for a in projection["artifacts"]}
    if ("VerificationResult" not in artifact_by_type
            or artifact_by_type["VerificationResult"]["content_sha256"] != expected_verification_sha256):
        raise TransitionError("Verification artifact hash mismatch")
    if not any(t["task_id"] == f"{run_id}:root" and t["state"] == "AWAITING_APPROVAL"
               for t in projection["tasks"]):
        raise TransitionError("No pending root approval task")
    if not any(o["kind"] == "DISPATCH_VERIFICATION" and o["status"] == "DONE"
               for o in projection["outbox"]):
        raise TransitionError("Verification dispatch is not complete")
    accepted_id = candidate["review_artifact_id"]
    accepted_review = next((a for a in projection["artifacts"]
                            if a["artifact_id"] == accepted_id and
                            a["artifact_type"] in ("SecurityReview", "SecurityReviewRetry")), None)
    if accepted_review is None:
        raise TransitionError("Approved candidate review attempt missing")
    return {
        "run_id": run_id, "scope": review.SCOPE,
        "candidate_sha256": candidate["source_sha256"],
        "diff_sha256": candidate["diff_sha256"],
        "fixture_commit": candidate["fixture_commit"],
        "verification_artifact_sha256": expected_verification_sha256,
        "review_artifact_sha256": accepted_review["content_sha256"],
        "approval_boundary": remediation.APPROVAL_PENDING,
    }


def _validate(decision: str, reason_code: str, justification: str, request_id: str) -> None:
    if decision not in _DECISIONS or reason_code not in _REASONS.get(decision, ()):
        raise TransitionError("Invalid decision or decision-specific reason code")
    if (not isinstance(justification, str) or not 12 <= len(justification.strip()) <= 1024
            or any(ord(c) < 32 and c not in "\t\n" for c in justification)):
        raise TransitionError("Justification must be 12–1024 printable characters")
    if not isinstance(request_id, str) or not _REQ.fullmatch(request_id):
        raise TransitionError("Explicit idempotency request ID required")


def _open_existing(db_file: Path) -> sqlite3.Connection | None:
    if db_file.is_symlink():
        raise TransitionError("Symlinked decision ledger forbidden")
    if not db_file.exists():
        return None
    if not db_file.is_file():
        raise TransitionError("Decision ledger is not a regular file")
    if db_file.stat().st_uid != os.getuid() or (db_file.stat().st_mode & 0o077):
        raise TransitionError("Decision ledger owner or permissions invalid")
    db = sqlite3.connect(db_file.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def inspect(run_id: str, *, db_file: Path = DECISION_DB) -> dict[str, Any]:
    bridge.validate_run_id(run_id)
    db = _open_existing(db_file)
    if db is None:
        return {"run_id": run_id, "decision": None}
    with closing(db):
        try:
            row = db.execute("SELECT * FROM decisions WHERE run_id=?", (run_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise TransitionError("Invalid decision ledger schema") from exc
    if row is None:
        return {"run_id": run_id, "decision": None}
    result = dict(row)
    receipt = result.pop("receipt_sha256")
    if _hash(result) != receipt:
        raise TransitionError("Decision receipt content mismatch")
    return {"run_id": run_id, "decision": result | {"receipt_sha256": receipt,
        "integrity": "local_digest_not_signed"}}


@contextmanager
def _run_lock(run_id: str, locks: Path) -> Iterator[None]:
    bridge.validate_run_id(run_id)
    # Same run-level flock contract as the continuous worker; serializes local
    # operator changes against model/verification worker operations.
    import fcntl
    if locks.is_symlink():
        raise TransitionError("Symlinked lock directory forbidden")
    locks.mkdir(parents=True, exist_ok=True, mode=0o700)
    file = locks / (run_id + ".lock")
    if file.is_symlink():
        raise TransitionError("Symlinked run lock forbidden")
    fd = os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _open_writer(db_file: Path) -> sqlite3.Connection:
    if db_file.is_symlink() or db_file.parent.is_symlink():
        raise TransitionError("Symlinked decision ledger path forbidden")
    db_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if db_file.parent.stat().st_uid != os.getuid() or db_file.parent.stat().st_mode & 0o077:
        raise TransitionError("Decision directory must be owner-private")
    if db_file.exists() and (not db_file.is_file() or db_file.stat().st_uid != os.getuid()
                             or db_file.stat().st_mode & 0o077):
        raise TransitionError("Decision ledger permissions invalid")
    previous_umask = os.umask(0o077)
    try:
        db = sqlite3.connect(str(db_file), isolation_level=None, timeout=15)
        db.row_factory = sqlite3.Row
        os.chmod(db_file, 0o600)
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO metadata VALUES('schema_version','1');
            CREATE TABLE IF NOT EXISTS decisions (
                run_id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                candidate_sha256 TEXT NOT NULL, diff_sha256 TEXT NOT NULL,
                fixture_commit TEXT NOT NULL,
                verification_artifact_sha256 TEXT NOT NULL,
                review_artifact_sha256 TEXT NOT NULL,
                approval_boundary TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('APPROVE','REJECT')),
                request_id TEXT NOT NULL UNIQUE,
                principal_uid INTEGER NOT NULL, principal_name TEXT NOT NULL,
                identity_assurance TEXT NOT NULL,
                reason_code TEXT NOT NULL, justification TEXT NOT NULL,
                created_at TEXT NOT NULL, receipt_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS decisions_no_update
              BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'decision is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS decisions_no_delete
              BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'decision is immutable'); END;
        """)
        v = db.execute("SELECT value FROM metadata WHERE name='schema_version'").fetchone()
        if not v or v[0] != "1":
            raise TransitionError("Unsupported decision schema version")
        return db
    except BaseException:
        if 'db' in locals():
            db.close()
        raise
    finally:
        os.umask(previous_umask)


def decide(run_id: str, *, decision: str, reason_code: str, justification: str,
           request_id: str, expected_candidate_sha256: str,
           expected_verification_sha256: str,
           apply: bool = False, db_file: Path = DECISION_DB,
           queue_db: Path = worker.BASE / "jobs.sqlite3",
           run_base: Path = bridge.BASE, locks: Path = worker.BASE / "locks") -> dict[str, Any]:
    """Preview by default. --apply commits exactly one decision; never applies code."""
    bridge.validate_run_id(run_id)
    _validate(decision, reason_code, justification, request_id)
    who = principal()
    if not apply:
        # Dry run never opens the writer or creates any ledger/lock file.
        evidence = _eligible(run_id, expected_candidate_sha256=expected_candidate_sha256,
                             expected_verification_sha256=expected_verification_sha256,
                             queue_db=queue_db, run_base=run_base)
        old = inspect(run_id, db_file=db_file)
        if old["decision"] is not None:
            raise TransitionError("Decision already recorded")
        return {"result": "DECISION_ELIGIBLE_DRY_RUN", **evidence, "decision": decision,
                "operator": who, "reason_code": reason_code, "applies_code": False}
    # Do NOT obtain or persist an approval from the bearer-only API.
    with _run_lock(run_id, locks):
        evidence = _eligible(run_id, expected_candidate_sha256=expected_candidate_sha256,
                             expected_verification_sha256=expected_verification_sha256,
                             queue_db=queue_db, run_base=run_base)
        with closing(_open_writer(db_file)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute("SELECT * FROM decisions WHERE run_id=? OR request_id=?",
                                      (run_id, request_id)).fetchone()
                if existing:
                    old = dict(existing)
                    digest = old.pop("receipt_sha256")
                    if _hash(old) != digest:
                        raise TransitionError("Existing decision digest mismatch")
                    matching = (old["run_id"] == run_id and old["request_id"] == request_id
                        and old["decision"] == decision and old["principal_uid"] == who["uid"]
                        and old["principal_name"] == who["name"] and old["reason_code"] == reason_code
                        and old["justification"] == justification.strip()
                        and all(old[k] == evidence[k] for k in evidence))
                    if not matching:
                        raise TransitionError("Decision already final or request ID reused")
                    db.commit()
                    return {"result": "DECISION_ALREADY_COMMITTED", "run_id": run_id,
                            "decision": decision, "receipt_sha256": digest, "applies_code": False}
                row = {**evidence, "decision": decision, "request_id": request_id,
                    "principal_uid": who["uid"], "principal_name": who["name"],
                    "identity_assurance": who["identity_assurance"],
                    "reason_code": reason_code, "justification": justification.strip(),
                    "created_at": utc_now()}
                digest = _hash(row)
                fields = [*row.keys(), "receipt_sha256"]
                db.execute("INSERT INTO decisions (" + ",".join(fields) + ") VALUES ("
                           + ",".join("?" for _ in fields) + ")",
                           (*row.values(), digest))
                db.commit()
                return {"result": "OPERATOR_DECISION_RECORDED", "run_id": run_id,
                        "decision": decision, "receipt_sha256": digest,
                        "operator": who, "applies_code": False}
            except BaseException:
                db.rollback()
                raise
