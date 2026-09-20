"""Checkpoint 2E-0.7A: local, read-only projection of one fixture-scoped investigation.

NO approvals, rejections, model calls, Docker calls, API routes, file writes, or
Git mutation. SQLite is opened with mode=ro + query_only, not via constructors
that initialize schemas or change database permissions. Content is opt-in.
"""
from __future__ import annotations

import difflib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from benchmark_runner import agentic_workflow_v03 as fixture
from benchmark_runner import continuous_remediation_worker_v05c as remediation
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner.durable_runtime_v04 import TransitionError, artifact_digest

SCOPE = "synthetic_CWE-89_fixture_only"
MAX_RECEIPTS = 64
MAX_EVENTS = 1000


def _read_database(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise TransitionError("Read-only ledger missing or symlinked")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def _rows(db: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def _read_receipts(file: Path) -> dict[str, Any]:
    # These are local operational receipts, NOT cryptographically authenticated proof
    # and NOT an exhaustive statement about inference calls or model execution.
    if not file.exists():
        return {"present": False, "call_count": None, "entries": [],
                "integrity": "not_cryptographically_authenticated"}
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 128 * 1024:
        raise TransitionError("Gateway receipt file invalid")
    entries: list[dict[str, Any]] = []
    with file.open("r", encoding="utf-8") as stream:
        for line in stream:
            if len(entries) >= MAX_RECEIPTS:
                raise TransitionError("Too many gateway receipts")
            item = json.loads(line)
            if not isinstance(item, dict):
                raise TransitionError("Invalid gateway receipt")
            entries.append({key: item.get(key) for key in (
                "status", "lane", "transport", "inference_ms")})
    return {"present": True, "call_count": len(entries), "entries": entries,
            "integrity": "not_cryptographically_authenticated"}


def project(run_id: str, *, queue_db: Path = worker.BASE / "jobs.sqlite3",
            run_base: Path = bridge.BASE,
            include_content: bool = False) -> dict[str, Any]:
    """Build a verified, payload-minimal operator view from existing ledgers.

    `include_content` explicitly authorizes printing potentially sensitive/untrusted
    model review summary, Python source, and a unified diff to local stdout.
    """
    bridge.validate_run_id(run_id)
    with closing(_read_database(queue_db)) as queue:
        jobs = _rows(queue, "SELECT run_id,status,phase,attempts,last_error_type,created_at,updated_at "
                     "FROM jobs WHERE run_id=?", (run_id,))
        if len(jobs) != 1:
            raise TransitionError("Unknown worker run")
        job = jobs[0]
        worker_events = _rows(queue, "SELECT seq,kind,reason_code,phase,created_at "
                              "FROM worker_events WHERE run_id=? ORDER BY seq LIMIT ?",
                              (run_id, MAX_EVENTS + 1))
    if len(worker_events) > MAX_EVENTS:
        raise TransitionError("Worker event projection requires pagination")
    response: dict[str, Any] = {
        "run_id": run_id, "scope": SCOPE,
        "limitations": ["controlled synthetic fixture only",
                        "external exploitability not established",
                        "inspection is not approval or application"],
        "job": job, "runtime_status": "NOT_PREPARED", "tasks": [],
        "outbox": [], "artifacts": [], "security_review": None,
        "candidate_change": None, "verification_result": None,
        "gateway_receipts": {"present": False, "call_count": None, "entries": [],
                             "integrity": "not_cryptographically_authenticated"},
        "timeline": [{"ledger": "worker", **row} for row in worker_events],
        "content_included": include_content,
    }
    if job["phase"] == "PREPARE":
        return response
    ps = bridge.paths(run_id, run_base)
    if ps["folder"].is_symlink():
        raise TransitionError("Run directory symlink forbidden")
    with closing(_read_database(ps["db"])) as runtime:
        runs = _rows(runtime, "SELECT status FROM runs WHERE run_id=?", (run_id,))
        if len(runs) != 1:
            raise TransitionError("Missing durable run")
        response["runtime_status"] = runs[0]["status"]
        response["tasks"] = _rows(runtime,
            "SELECT task_id,owner,purpose,state,dependency_task_id FROM tasks "
            "WHERE run_id=? ORDER BY task_id", (run_id,))
        response["outbox"] = _rows(runtime,
            "SELECT job_id,kind,status,attempts FROM outbox WHERE run_id=? ORDER BY job_id", (run_id,))
        artifacts = _rows(runtime,
            "SELECT artifact_id,artifact_type,producer_task_id,content_sha256,payload_json,created_at "
            "FROM artifacts WHERE run_id=? ORDER BY artifact_id", (run_id,))
        runtime_events = _rows(runtime,
            "SELECT seq,event_type,actor,reason_code,task_id,created_at FROM events "
            "WHERE run_id=? ORDER BY seq LIMIT ?", (run_id, MAX_EVENTS + 1))
    if len(runtime_events) > MAX_EVENTS:
        raise TransitionError("Runtime event projection requires pagination")

    # Verify EVERY committed artifact before returning ANY view; never disclose
    # any raw payload by default or project unverified material.
    payloads: dict[str, dict[str, Any]] = {}
    for a in artifacts:
        obj = json.loads(a["payload_json"])
        if not isinstance(obj, dict) or artifact_digest(obj) != a["content_sha256"]:
            raise TransitionError("Artifact integrity mismatch")
        if a["artifact_type"] in payloads:
            raise TransitionError("Duplicate artifact type")
        payloads[a["artifact_type"]] = obj
        response["artifacts"].append({key: a[key] for key in (
            "artifact_id", "artifact_type", "producer_task_id", "content_sha256", "created_at")})

    first_review = payloads.get("SecurityReview")
    retry_review = payloads.get("SecurityReviewRetry")
    if retry_review is not None and (first_review is None or first_review.get("accepted") is not False):
        raise TransitionError("Versioned review must preserve rejected first attempt")
    if retry_review is not None and (not any(a["artifact_type"] == "SecurityReviewRetry"
            and a["artifact_id"] == f"{run_id}:foundation-review-retry-1" for a in artifacts)):
        raise TransitionError("Unexpected retry review identity")
    review = retry_review if retry_review is not None else first_review
    response["security_review_history"] = []
    for kind in ("SecurityReview", "SecurityReviewRetry"):
        previous = payloads.get(kind)
        if previous is not None:
            response["security_review_history"].append({
                "artifact_type": kind, "accepted_by_validator": previous.get("accepted"),
                "validation_errors": previous.get("validation_errors"),
                "content_sha256": next(a["content_sha256"] for a in artifacts
                                       if a["artifact_type"] == kind),
            })
    if review is not None:
        report = review.get("review")
        if not isinstance(report, dict) and not (report is None and review.get("accepted") is False):
            raise TransitionError("Malformed security review")
        fields = ("source_pattern", "caller_path", "external_exploitability",
                  "supporting_evidence_ids", "missing_evidence")
        response["security_review"] = {
            "accepted_by_validator": review.get("accepted"),
            "validation_errors": review.get("validation_errors"),
            "node": review.get("node"), "model": review.get("model"),
            "evidence_ids": review.get("evidence_ids"),
            "review": {k: report.get(k) for k in fields} if isinstance(report, dict) else None,
        }
        if include_content and isinstance(report, dict):
            response["security_review"]["review"]["review_summary"] = report.get("review_summary")

    change = payloads.get("CandidateChange")
    if change is not None:
        source = change.get("source")
        sha = change.get("source_sha256")
        if not isinstance(source, str) or not isinstance(sha, str) or fixture.sha(source) != sha:
            raise TransitionError("Candidate source identity mismatch")
        delta = "".join(difflib.unified_diff(
            fixture.APP_VULNERABLE.splitlines(keepends=True),
            source.splitlines(keepends=True), fromfile="a/app.py", tofile="b/app.py"))
        if fixture.sha(delta) != change.get("diff_sha256"):
            raise TransitionError("Candidate diff identity mismatch")
        accepted_id = (f"{run_id}:foundation-review-retry-1" if retry_review is not None
                       else f"{run_id}:foundation-review")
        if review is None or review.get("accepted") is not True or change.get("review_artifact_id") != accepted_id:
            raise TransitionError("Candidate does not bind to the accepted review attempt")
        response["candidate_change"] = {k: change.get(k) for k in (
            "source_sha256", "diff_sha256", "fixture_commit", "review_artifact_id",
            "evidence_ids", "node", "model")}
        if include_content:
            response["candidate_change"].update({"source": source, "unified_diff": delta})

    verification = payloads.get("VerificationResult")
    if verification is not None:
        if (verification.get("source_artifact_id") != f"{run_id}:candidate-change" or
                change is None or verification.get("candidate_sha256") != change["source_sha256"]):
            raise TransitionError("Verification candidate identity mismatch")
        expected_pass = (verification.get("baseline") == remediation.BASELINE_EXPECTED
                         and verification.get("candidate") == remediation.CANDIDATE_EXPECTED
                         and verification.get("original_fixture_unchanged") is True)
        if verification.get("passed") is not expected_pass:
            raise TransitionError("Verification behavior receipt inconsistent")
        response["verification_result"] = {k: verification.get(k) for k in (
            "candidate_sha256", "baseline", "candidate", "passed", "sandbox_image",
            "original_fixture_unchanged")}

    response["timeline"].extend({"ledger": "runtime", **row} for row in runtime_events)
    response["timeline"].sort(key=lambda row: (row["created_at"], row["ledger"], row["seq"]))
    response["gateway_receipts"] = _read_receipts(ps["folder"] / "gateway-calls.jsonl")
    if (response["runtime_status"] == remediation.APPROVAL_PENDING
            and (response["verification_result"] is None
                 or response["verification_result"]["passed"] is not True
                 or not any(t["task_id"] == f"{run_id}:root"
                            and t["state"] == "AWAITING_APPROVAL" for t in response["tasks"]))):
        raise TransitionError("Inconsistent approval boundary")
    return response
