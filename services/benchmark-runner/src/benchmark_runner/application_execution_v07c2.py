"""2E-0.7C2: TWO explicit local operations: authorize, then apply synthetic app.py.

No arbitrary repo; no network routes; no auto-approval; no auto-commit; no production use.
On interrupted source mutation, hold for explicit reconciliation, never reapply blindly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from benchmark_runner import agentic_workflow_v03 as fixture
from benchmark_runner import application_gate_v07c1 as gate
from benchmark_runner import continuous_remediation_worker_v05c as remediation
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner import operator_decisions_v07b as decisions
from benchmark_runner.durable_runtime_v04 import TransitionError, canonical_json, utc_now

APPLICATION_DB = Path("benchmarks/results/checkpoint2e/operator-applications-v07c2/applications.sqlite3")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REQ = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,95}\Z")
_AUTH_FIELDS = ("run_id", "target", "target_git_commit", "scope", "candidate_sha256",
                "verification_artifact_sha256", "decision_receipt_sha256", "principal_uid",
                "principal_name", "identity_assurance", "authorization_request_id", "created_at")
_ALLOWED_STATES = ("AUTHORIZED", "APPLYING", "APPLIED", "NEEDS_OPERATOR_RECOVERY")


def _digest(obj: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _validate_request(req: str) -> None:
    if not isinstance(req, str) or not _REQ.fullmatch(req):
        raise TransitionError("Unique, explicit application request ID required")


def _read(run_id: str, db_file: Path) -> dict[str, Any] | None:
    bridge.validate_run_id(run_id)
    db = decisions._open_existing(db_file)
    if db is None:
        return None
    with closing(db):
        try:
            row = db.execute("SELECT * FROM applications WHERE run_id=?", (run_id,)).fetchone()
            events = (db.execute("SELECT kind,request_id,created_at FROM application_events "
                                 "WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
                      if row is not None else ())
        except sqlite3.OperationalError as exc:
            raise TransitionError("Invalid application ledger schema") from exc
    if row is None:
        return None
    result = dict(row)
    if _digest({k: result[k] for k in _AUTH_FIELDS}) != result["authorization_sha256"]:
        raise TransitionError("Application authorization identity mismatch")
    if result["result_json"] is not None:
        if hashlib.sha256(result["result_json"].encode("utf-8")).hexdigest() != result["result_sha256"]:
            raise TransitionError("Post-application receipt integrity mismatch")
    if result["state"] not in _ALLOWED_STATES:
        raise TransitionError("Application ledger state invalid")
    if result["state"] == "APPLIED" and (result["result_json"] is None or result["applied_at"] is None):
        raise TransitionError("Completed application missing result receipt")
    return result | {"events": [dict(x) for x in events]}


def inspect(run_id: str, *, db_file: Path = APPLICATION_DB) -> dict[str, Any]:
    record = _read(run_id, db_file)
    return {"run_id": run_id, "application": record}


def _writer(db_file: Path) -> sqlite3.Connection:
    if db_file.is_symlink() or db_file.parent.is_symlink():
        raise TransitionError("Symlinked application ledger forbidden")
    db_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = db_file.parent.stat()
    if parent.st_uid != os.getuid() or (parent.st_mode & 0o077):
        raise TransitionError("Application ledger directory must be owner-private")
    if db_file.exists():
        info = db_file.stat()
        if not db_file.is_file() or info.st_uid != os.getuid() or (info.st_mode & 0o077):
            raise TransitionError("Application ledger file ownership/permissions invalid")
    mask = os.umask(0o077)
    try:
        db = sqlite3.connect(str(db_file), isolation_level=None, timeout=15)
        db.row_factory = sqlite3.Row
        os.chmod(db_file, 0o600)
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT OR IGNORE INTO metadata VALUES ('schema_version','1');
        CREATE TABLE IF NOT EXISTS applications (
          run_id TEXT PRIMARY KEY, target TEXT NOT NULL, target_git_commit TEXT NOT NULL,
          scope TEXT NOT NULL, candidate_sha256 TEXT NOT NULL,
          verification_artifact_sha256 TEXT NOT NULL, decision_receipt_sha256 TEXT NOT NULL,
          principal_uid INTEGER NOT NULL, principal_name TEXT NOT NULL,
          identity_assurance TEXT NOT NULL, authorization_request_id TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL, authorization_sha256 TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('AUTHORIZED','APPLYING','APPLIED','NEEDS_OPERATOR_RECOVERY')),
          execution_request_id TEXT UNIQUE, applied_at TEXT,
          result_sha256 TEXT, result_json TEXT
        );
        CREATE TABLE IF NOT EXISTS application_events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          kind TEXT NOT NULL, request_id TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS applications_no_delete BEFORE DELETE ON applications
          BEGIN SELECT RAISE(ABORT,'application row cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS application_events_no_update BEFORE UPDATE ON application_events
          BEGIN SELECT RAISE(ABORT,'application event is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS application_events_no_delete BEFORE DELETE ON application_events
          BEGIN SELECT RAISE(ABORT,'application event is immutable'); END;
        """)
        version = db.execute("SELECT value FROM metadata WHERE name='schema_version'").fetchone()
        if not version or version[0] != "1":
            raise TransitionError("Unsupported application schema version")
        return db
    except BaseException:
        if 'db' in locals():
            db.close()
        raise
    finally:
        os.umask(mask)


def _change(db: sqlite3.Connection, run_id: str, state: str, kind: str, request_id: str,
            *, result: dict[str, Any] | None = None) -> None:
    stamp = utc_now()
    db.execute("BEGIN IMMEDIATE")
    try:
        if result is None:
            db.execute("UPDATE applications SET state=?,execution_request_id=COALESCE(execution_request_id,?) "
                       "WHERE run_id=?", (state, request_id, run_id))
        else:
            packed = canonical_json(result)
            db.execute("UPDATE applications SET state=?,applied_at=?,result_sha256=?,result_json=? "
                       "WHERE run_id=?", (state, stamp, hashlib.sha256(packed.encode()).hexdigest(),
                        packed, run_id))
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise TransitionError("Application state transition lost")
        db.execute("INSERT INTO application_events (run_id,kind,request_id,created_at) "
                   "VALUES(?,?,?,?)", (run_id, kind, request_id, stamp))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def authorize(run_id: str, *, target: Path, expected_candidate_sha256: str,
              expected_verification_sha256: str, expected_decision_receipt_sha256: str,
              expected_target_commit: str, request_id: str, record: bool = False,
              db_file: Path = APPLICATION_DB, decision_db: Path = decisions.DECISION_DB,
              queue_db: Path = worker.BASE / "jobs.sqlite3", run_base: Path = bridge.BASE,
              locks: Path = worker.BASE / "locks") -> dict[str, Any]:
    """Separate local explicit authorization; recording it never writes app.py."""
    bridge.validate_run_id(run_id)
    _validate_request(request_id)
    if not re.fullmatch(r"[0-9a-f]{40}", expected_target_commit):
        raise TransitionError("Explicit target Git commit required")
    def check() -> dict[str, Any]:
        proof = gate.preflight(run_id, target=target,
            expected_candidate_sha256=expected_candidate_sha256,
            expected_verification_sha256=expected_verification_sha256,
            expected_decision_receipt_sha256=expected_decision_receipt_sha256,
            decision_db=decision_db, queue_db=queue_db, run_base=run_base)
        if proof["target_git_commit"] != expected_target_commit:
            raise TransitionError("Explicit expected target commit differs")
        return proof
    if not record:
        proof = check()
        if _read(run_id, db_file) is not None:
            raise TransitionError("Application already authorized; inspect existing record")
        return {**proof, "result": "APPLICATION_AUTHORIZATION_ELIGIBLE_DRY_RUN",
                "application_authorized": False, "applies_code": False}
    with decisions._run_lock(run_id, locks):
        proof = check()
        if _read(run_id, db_file) is not None:
            raise TransitionError("Application already authorized; do not reauthorize")
        who = decisions.principal()
        payload = dict(run_id=run_id, target=proof["target"],
            target_git_commit=expected_target_commit, scope=proof["scope"],
            candidate_sha256=proof["candidate_sha256"],
            verification_artifact_sha256=proof["verification_artifact_sha256"],
            decision_receipt_sha256=proof["decision_receipt_sha256"],
            principal_uid=who["uid"], principal_name=who["name"],
            identity_assurance=who["identity_assurance"],
            authorization_request_id=request_id, created_at=utc_now())
        with closing(_writer(db_file)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM applications WHERE run_id=? OR authorization_request_id=?",
                              (run_id, request_id)).fetchone():
                    raise TransitionError("Duplicate application authorization or request ID")
                row = {**payload, "authorization_sha256": _digest(payload),
                       "state": "AUTHORIZED", "execution_request_id": None,
                       "applied_at": None, "result_sha256": None, "result_json": None}
                db.execute("INSERT INTO applications VALUES (" + ",".join("?" for _ in row) + ")",
                           tuple(row.values()))
                db.execute("INSERT INTO application_events (run_id,kind,request_id,created_at) "
                           "VALUES(?,?,?,?)", (run_id, "AUTHORIZED", request_id, utc_now()))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return {"result": "APPLICATION_AUTHORIZATION_RECORDED", "run_id": run_id,
                "target": proof["target"], "candidate_sha256": proof["candidate_sha256"],
                "authorization_sha256": _digest(payload), "application_authorized": True,
                "applies_code": False}


def _assert_binding(row: dict[str, Any], run_id: str, target: Path,
                    decision_db: Path, queue_db: Path, run_base: Path) -> None:
    who = decisions.principal()
    if row["principal_uid"] != who["uid"] or row["principal_name"] != who["name"]:
        raise TransitionError("Applying identity differs from authorizing identity")
    if row["identity_assurance"] != "local_os_account_only":
        raise TransitionError("Unexpected identity assurance")
    expected_target = bridge.paths(run_id, run_base)["folder"] / "application_workspace"
    # Validate the entire run-scoped path, ownership, .git directory and symlinks
    # even when the target is now dirty following an interrupted source write.
    gate._target_path(run_id, target, run_base)
    if (Path(target).absolute() != expected_target.absolute()
            or Path(target).is_symlink() or expected_target.is_symlink()
            or ".." in Path(target).parts):
        raise TransitionError("Application target changed")
    if str(expected_target.absolute()) != row["target"]:
        raise TransitionError("Authorized target path changed")
    decision = decisions.inspect(run_id, db_file=decision_db)["decision"]
    if decision is None or decision["decision"] != "APPROVE" or decision["receipt_sha256"] != row["decision_receipt_sha256"]:
        raise TransitionError("Approved decision receipt changed")
    proof = decisions._eligible(run_id, expected_candidate_sha256=row["candidate_sha256"],
        expected_verification_sha256=row["verification_artifact_sha256"],
        queue_db=queue_db, run_base=run_base)
    if proof["fixture_commit"] != row["target_git_commit"] or proof["scope"] != row["scope"]:
        raise TransitionError("Authorized evidence/commit/scope changed")


def _candidate_source(run_id: str, base: Path, expected_sha: str) -> bytes:
    path = bridge.paths(run_id, base)["db"]
    if path.is_symlink():
        raise TransitionError("Symlinked durable ledger forbidden")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT payload_json FROM artifacts WHERE run_id=? AND artifact_type='CandidateChange'",
                         (run_id,)).fetchone()
    if row is None:
        raise TransitionError("Candidate not in durable ledger")
    obj = json.loads(row[0])
    source = obj.get("source")
    if not isinstance(source, str) or fixture.sha(source) != expected_sha or fixture.validate_patch(source):
        raise TransitionError("Candidate source invalid")
    return source.encode("utf-8")


def _postcheck(run_id: str, row: dict[str, Any], *, target: Path, run_base: Path,
               sandbox: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    expected = _candidate_source(run_id, run_base, row["candidate_sha256"])
    if target.is_symlink() or not target.is_dir() or not (target / ".git").is_dir():
        raise TransitionError("Application target changed during execution")
    if gate._git(target, "rev-parse", "HEAD") != row["target_git_commit"]:
        raise TransitionError("Target Git commit changed during execution")
    if Path(gate._git(target, "rev-parse", "--show-toplevel")).resolve(strict=True) != target.resolve(strict=True):
        raise TransitionError("Target Git root changed")
    if sorted(gate._git(target, "ls-files", "--cached").splitlines()) != sorted(gate._ALLOWLIST):
        raise TransitionError("Target tracked inventory changed")
    for name in ("app.py", "web.py", "verify.py", "README.md"):
        path = target / name
        if path.is_symlink() or not path.is_file():
            raise TransitionError("Application target contains unsafe file")
        actual = path.read_bytes()
        baseline = gate._git(target, "show", f"HEAD:{name}", raw=True)
        if actual != (expected if name == "app.py" else baseline):
            raise TransitionError("Application target differs from expected files")
    status = gate._git(target, "status", "--porcelain=v1", "--untracked-files=all")
    if status != "M app.py":
        raise TransitionError("Only app.py may be modified in target")
    # Docker UID 65534 must traverse the synthetic target and read only the
    # candidate + fixed, pinned verifier. Never chmod private run directories.
    if target.stat().st_mode & 0o005 != 0o005:
        os.chmod(target, target.stat().st_mode | 0o005)
    for name in ("app.py", "verify.py"):
        path = target / name
        if path.stat().st_mode & 0o004 == 0:
            os.chmod(path, path.stat().st_mode | 0o004)
    measured = sandbox(target)
    if measured != remediation.CANDIDATE_EXPECTED:
        raise TransitionError("Post-application Docker behavior does not match accepted verification")
    if gate._git(target, "status", "--porcelain=v1", "--untracked-files=all") != "M app.py":
        raise TransitionError("Application sandbox changed the target")
    # Reconfirm the original synthetic Git fixture is unmodified.
    original = bridge.paths(run_id, run_base)["repo"]
    if (gate._git(original, "rev-parse", "HEAD") != row["target_git_commit"]
            or gate._git(original, "status", "--porcelain=v1", "--untracked-files=all")):
        raise TransitionError("Original fixture changed")
    return {"run_id": run_id, "status": "APPLIED", "target": row["target"],
            "target_git_commit": row["target_git_commit"], "target_file": "app.py",
            "candidate_sha256": row["candidate_sha256"],
            "decision_receipt_sha256": row["decision_receipt_sha256"],
            "verification_artifact_sha256": row["verification_artifact_sha256"],
            "docker_candidate": measured, "original_fixture_unchanged": True,
            "git_diff_only_app_py": True, "git_commit_created": False}


def _write_app(target: Path, data: bytes) -> None:
    # Directory-relative O_NOFOLLOW / O_EXCL and atomic replacement protect
    # against accidental symlink targeting and partial app.py content.
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    dfd = os.open(target, flags)
    temp_name = ".axonvertex-app-" + uuid.uuid4().hex + ".tmp"
    try:
        if not stat.S_ISDIR(os.fstat(dfd).st_mode) or os.fstat(dfd).st_uid != os.getuid():
            raise TransitionError("Application directory ownership changed")
        current = os.open("app.py", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dfd)
        try:
            if not stat.S_ISREG(os.fstat(current).st_mode):
                raise TransitionError("Target app.py is not a regular file")
            with os.fdopen(current, "rb", closefd=False) as handle:
                if handle.read() != fixture.APP_VULNERABLE.encode("utf-8"):
                    raise TransitionError("Target app.py changed after preflight")
        finally:
            os.close(current)
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                     0o644, dir_fd=dfd)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, "app.py", src_dir_fd=dfd, dst_dir_fd=dfd)
            os.fsync(dfd)
        finally:
            try:
                os.unlink(temp_name, dir_fd=dfd)
            except FileNotFoundError:
                pass
    finally:
        os.close(dfd)


def execute(run_id: str, *, target: Path, request_id: str, apply: bool = False,
            db_file: Path = APPLICATION_DB, decision_db: Path = decisions.DECISION_DB,
            queue_db: Path = worker.BASE / "jobs.sqlite3", run_base: Path = bridge.BASE,
            locks: Path = worker.BASE / "locks",
            sandbox: Callable[[Path], dict[str, Any]] = fixture.docker_check) -> dict[str, Any]:
    """Explicit second operation: only --apply may mutate the target."""
    bridge.validate_run_id(run_id)
    _validate_request(request_id)
    record = _read(run_id, db_file)
    if record is None:
        raise TransitionError("Separate application authorization required")
    if (record["state"] == "APPLIED" and record["execution_request_id"] == request_id
            and record["target"] == str(Path(target).absolute())
            and record["principal_uid"] == decisions.principal()["uid"]
            and record["principal_name"] == decisions.principal()["name"]):
        return {"result": "APPLICATION_ALREADY_RECORDED", "run_id": run_id,
                "status": "APPLIED", "applies_code": False}
    if record["state"] != "AUTHORIZED":
        raise TransitionError("Application pending/completed; explicit reconciliation may be needed")
    if not apply:
        proof = gate.preflight(run_id, target=target,
            expected_candidate_sha256=record["candidate_sha256"],
            expected_verification_sha256=record["verification_artifact_sha256"],
            expected_decision_receipt_sha256=record["decision_receipt_sha256"],
            decision_db=decision_db, queue_db=queue_db, run_base=run_base)
        if proof["target_git_commit"] != record["target_git_commit"] or proof["target"] != record["target"]:
            raise TransitionError("Application authorization target changed")
        return {"result": "APPLICATION_EXECUTION_ELIGIBLE_DRY_RUN", "run_id": run_id,
                "target": record["target"], "applies_code": False}
    with decisions._run_lock(run_id, locks):
        record = _read(run_id, db_file)
        if record is None or record["state"] != "AUTHORIZED":
            raise TransitionError("Application no longer awaiting execution")
        _assert_binding(record, run_id, target, decision_db, queue_db, run_base)
        proof = gate.preflight(run_id, target=target,
            expected_candidate_sha256=record["candidate_sha256"],
            expected_verification_sha256=record["verification_artifact_sha256"],
            expected_decision_receipt_sha256=record["decision_receipt_sha256"],
            decision_db=decision_db, queue_db=queue_db, run_base=run_base)
        if proof["target"] != record["target"] or proof["target_git_commit"] != record["target_git_commit"]:
            raise TransitionError("Target was modified since application authorization")
        source = _candidate_source(run_id, run_base, record["candidate_sha256"])
        with closing(_writer(db_file)) as db:
            _change(db, run_id, "APPLYING", "APPLY_STARTED", request_id)
            try:
                _write_app(Path(record["target"]), source)
                result = _postcheck(run_id, record, target=Path(record["target"]),
                                    run_base=run_base, sandbox=sandbox)
            except Exception:
                _change(db, run_id, "NEEDS_OPERATOR_RECOVERY", "APPLY_INTERRUPTED", request_id)
                raise
            _change(db, run_id, "APPLIED", "APPLY_COMPLETED", request_id, result=result)
    return {"result": "APPLICATION_APPLIED", "run_id": run_id,
            "target": record["target"], "status": "APPLIED", "receipt_sha256": _digest(result),
            "git_commit_created": False, "applies_code": True}


def reconcile(run_id: str, *, target: Path, request_id: str, apply: bool = False,
              db_file: Path = APPLICATION_DB, decision_db: Path = decisions.DECISION_DB,
              queue_db: Path = worker.BASE / "jobs.sqlite3", run_base: Path = bridge.BASE,
              locks: Path = worker.BASE / "locks",
              sandbox: Callable[[Path], dict[str, Any]] = fixture.docker_check) -> dict[str, Any]:
    """Manual after crash: verify already-applied source; NEVER rewrite it."""
    bridge.validate_run_id(run_id)
    _validate_request(request_id)
    record = _read(run_id, db_file)
    if record is None or record["state"] not in ("APPLYING", "NEEDS_OPERATOR_RECOVERY"):
        raise TransitionError("No interrupted application available for reconciliation")
    if not apply:
        return {"result": "RECONCILIATION_REQUIRED", "run_id": run_id,
                "status": record["state"], "applies_code": False,
                "limitation": "Reconcile only after inspecting target; --apply reruns sandbox, never writes source"}
    with decisions._run_lock(run_id, locks):
        record = _read(run_id, db_file)
        if record is None or record["state"] not in ("APPLYING", "NEEDS_OPERATOR_RECOVERY"):
            raise TransitionError("Application state changed")
        _assert_binding(record, run_id, target, decision_db, queue_db, run_base)
        try:
            result = _postcheck(run_id, record, target=Path(record["target"]),
                                run_base=run_base, sandbox=sandbox)
        except Exception:
            with closing(_writer(db_file)) as db:
                if record["state"] == "APPLYING":
                    _change(db, run_id, "NEEDS_OPERATOR_RECOVERY", "RECONCILIATION_FAILED", request_id)
            raise
        with closing(_writer(db_file)) as db:
            _change(db, run_id, "APPLIED", "RECONCILED_AND_VERIFIED", request_id, result=result)
    return {"result": "APPLICATION_RECONCILED", "run_id": run_id, "status": "APPLIED",
            "receipt_sha256": _digest(result), "applies_code": False}
