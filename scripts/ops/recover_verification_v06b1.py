#!/usr/bin/env python3
"""2E-0.6B1: explicit, single-use, fixture-only operator requeue of failed verification.

Run from repository root. Deliberately no arbitrary-stage recovery and no model call.
Two SQLite stores cannot share a transaction: first reset the durable outbox,
then the worker queue. Re-running after a crash between those commits is safe.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/benchmark-runner/src"))

from benchmark_runner import agentic_workflow_v03 as old
from benchmark_runner import continuous_remediation_worker_v05c as c
from benchmark_runner import continuous_worker_v05a as w
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner.durable_runtime_v04 import TransitionError, utc_now

REASON = "SANDBOX_INPUT_PERMISSIONS_REPAIRED"
EVENT_KEY = "verification-operator-recovery-v06b1"


def validate(run_id: str, expected_sha: str, queue: w.Queue, *, base: Path) -> tuple[Path, dict]:
    b.validate_run_id(run_id)
    if len(expected_sha) != 64 or any(x not in "0123456789abcdef" for x in expected_sha):
        raise TransitionError("Exact lowercase candidate source sha256 required")
    job = queue.inspect(run_id)["job"]
    if (job["phase"] != c.VERIFY_PENDING or job["status"] != "NEEDS_OPERATOR_RECOVERY"
            or job["attempts"] != w.MAX_ATTEMPTS or job["last_error_type"] != "RuntimeError"):
        raise TransitionError("Run is not held at exhausted sandbox verification")
    ps = b.paths(run_id, base)
    prompt, context = c.trusted_context(run_id, base=base)
    with c.RemediationRuntime(ps["db"]) as rt:
        snap = rt.snapshot(run_id)
        if snap["status"] != "WAITING_FOR_VERIFICATION":
            raise TransitionError("Verification durable state changed")
        change = c.artifact(snap, "CandidateChange")["payload"]
        if (change["source_sha256"] != expected_sha
                or change["prompt_sha256"] != old.sha(prompt)
                or change["fixture_commit"] != context["fixture_commit"]
                or change["review_artifact_id"] != context["review_artifact_id"]
                or change["evidence_ids"] != context["evidence_ids"]
                or old.sha(change["source"]) != expected_sha
                or old.validate_patch(change["source"])):
            raise TransitionError("Candidate identity, review, or narrow patch contract mismatch")
        if any(x["artifact_type"] == "VerificationResult" for x in snap["artifacts"]):
            raise TransitionError("Verification result already committed")
        if not any(x["task_id"] == f"{run_id}:verification" and x["state"] == "READY"
                   for x in snap["tasks"]):
            raise TransitionError("Verification task not ready")
        dispatch = rt.db.execute("SELECT * FROM outbox WHERE job_id=? AND run_id=?",
                                 (f"{run_id}:dispatch-verification", run_id)).fetchone()
        if not dispatch or dispatch["kind"] != "DISPATCH_VERIFICATION" or dispatch["status"] != "PENDING":
            raise TransitionError("Verification outbox not pending")
        if dispatch["lease_token"] is not None or dispatch["lease_until"] is not None:
            raise TransitionError("Verification lease still held")
        prior = rt.db.execute("SELECT 1 FROM events WHERE run_id=? AND event_key=?",
                              (run_id, EVENT_KEY)).fetchone()
        # attempts=0 with prior event is an interrupted operator recovery,
        # not a fresh reauthorization or silent extension of the retry budget.
        if not ((dispatch["attempts"] == w.MAX_ATTEMPTS and not prior)
                or (dispatch["attempts"] == 0 and prior)):
            raise TransitionError("Recovery already used or unexpected retry budget")
    repo = ps["repo"]
    candidate = ps["folder"] / "candidate_workspace"
    if (repo.is_symlink() or candidate.is_symlink() or
            old.git(["rev-parse", "HEAD"], repo) != context["fixture_commit"] or
            old.git(["status", "--porcelain"], repo)):
        raise TransitionError("Original fixture not at clean pinned commit")
    for directory, expected in (
        (repo, {"app.py": old.APP_VULNERABLE, "verify.py": old.VERIFY_SOURCE}),
        (candidate, {"app.py": change["source"], "verify.py": old.VERIFY_SOURCE}),
    ):
        if not directory.is_dir() or directory.stat().st_mode & 0o005 != 0o005:
            raise TransitionError("Fixture sandbox directory is not readable/traversable")
        for name, data in expected.items():
            item = directory / name
            if (item.is_symlink() or not item.is_file() or
                    item.read_bytes() != data.encode("utf-8") or
                    item.stat().st_mode & 0o004 != 0o004):
                raise TransitionError("Sandbox input not repaired or content changed")
    return ps["db"], {"run_id": run_id, "candidate_sha256": expected_sha,
                        "worker_phase": job["phase"], "worker_status": job["status"],
                        "verification_outbox_attempts": dispatch["attempts"],
                        "recovery_reason": REASON}


def recover(run_id: str, expected_sha: str, *, apply: bool = False,
            base: Path = b.BASE, queue_file: Path = w.BASE / "jobs.sqlite3",
            locks: Path = w.BASE / "locks") -> dict:
    with w.run_lock(run_id, locks) as locked:
        if not locked:
            raise TransitionError("Run currently held by an active worker")
        with w.Queue(queue_file) as queue:
            db, result = validate(run_id, expected_sha, queue, base=base)
            if not apply:
                return {"decision": "DRY_RUN_RECOVERY_ELIGIBLE", **result}
            with c.RemediationRuntime(db) as rt:
                rt._begin()
                try:
                    current = rt.db.execute("SELECT attempts,status FROM outbox WHERE job_id=?",
                                            (f"{run_id}:dispatch-verification",)).fetchone()
                    if not current or current["status"] != "PENDING" or current["attempts"] not in (0, w.MAX_ATTEMPTS):
                        raise TransitionError("Verification outbox changed")
                    if current["attempts"] == w.MAX_ATTEMPTS:
                        stamp = utc_now()
                        rt.db.execute("UPDATE outbox SET attempts=0,updated_at=? WHERE job_id=?",
                                      (stamp, f"{run_id}:dispatch-verification"))
                        rt._event(run_id, EVENT_KEY, "OPERATOR_RECOVERY", "Operator",
                                  REASON, f"{run_id}:verification",
                                  {"candidate_sha256": expected_sha,
                                   "stage": "verification", "original_attempts": w.MAX_ATTEMPTS})
                    rt.db.commit()
                except BaseException:
                    rt.db.rollback()
                    raise
            # Separate DB: if interrupted here, rerun --apply; outbox=0 plus
            # unique OPERATOR_RECOVERY event proves the first transaction committed.
            queue.db.execute("BEGIN IMMEDIATE")
            try:
                job = queue.db.execute("SELECT phase,status,attempts FROM jobs WHERE run_id=?",
                                       (run_id,)).fetchone()
                if (not job or job["phase"] != c.VERIFY_PENDING or
                        job["status"] != "NEEDS_OPERATOR_RECOVERY" or
                        job["attempts"] != w.MAX_ATTEMPTS):
                    raise TransitionError("Worker job changed before recovery")
                queue.db.execute("UPDATE jobs SET status='QUEUED',attempts=0,last_error_type=NULL,"
                                 "updated_at=? WHERE run_id=?", (utc_now(), run_id))
                queue._event(run_id, "OPERATOR_RECOVERY", REASON, c.VERIFY_PENDING,
                             {"candidate_sha256": expected_sha, "only_stage": "verification"})
                queue.db.commit()
            except BaseException:
                queue.db.rollback()
                raise
            return {"decision": "VERIFICATION_ONLY_REQUEUED", **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--reason-code", required=True, choices=(REASON,))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        # Do not print model content, credentials or infrastructure error strings.
        outcome = recover(args.run_id, args.expected_candidate_sha256, apply=args.apply)
        print(json.dumps(outcome, indent=2, sort_keys=True))
        return 0
    except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
        print("VERIFICATION_RECOVERY_REFUSED: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
