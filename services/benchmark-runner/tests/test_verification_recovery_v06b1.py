"""Fixture-only sandbox access and explicit recovery; generated Python never runs on host."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from benchmark_runner import agentic_workflow_v03 as old
from benchmark_runner import continuous_remediation_worker_v05c as c
from benchmark_runner import continuous_worker_v05a as w
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner.durable_runtime_v04 import TransitionError
from test_continuous_remediation_worker_v05c import FullProvider

OPS = Path(__file__).resolve().parents[3] / "scripts/ops/recover_verification_v06b1.py"
spec = importlib.util.spec_from_file_location("recover_verification_v06b1", OPS)
assert spec is not None and spec.loader is not None
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.base, self.locks, self.db = root / "runs", root / "locks", root / "jobs.sqlite3"
        self.q = w.Queue(self.db)
        self.addCleanup(self.q.close)
        self.calls = {"A": 0, "B": 0, "C": 0, "Docker": 0}
        self.provider = lambda _: FullProvider(self.calls)
        self.run_id = "proof"

    def advance(self, sandbox=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return c.advance(self.q, self.run_id, base=self.base, locks=self.locks,
                             provider_factory=self.provider, review_provider_factory=self.provider,
                             remediation_provider_factory=self.provider,
                             sandbox=sandbox or self.sandbox)

    def sandbox(self, path):
        self.calls["Docker"] += 1
        self.assertEqual(path.stat().st_mode & 0o777, 0o755)
        for name in ("app.py", "verify.py"):
            self.assertEqual((path / name).stat().st_mode & 0o777, 0o644)
        if path.name == "fixture_repo":
            return dict(c.BASELINE_EXPECTED)
        return dict(c.CANDIDATE_EXPECTED)

    def pending_verification(self):
        self.q.submit(self.run_id)
        for _ in range(8):
            self.advance()  # A-B-A-C-A -> verification scheduled
        self.assertEqual(self.q.inspect(self.run_id)["job"]["phase"], c.VERIFY_PENDING)
        with c.RemediationRuntime(b.paths(self.run_id, self.base)["db"]) as rt:
            return c.artifact(rt.snapshot(self.run_id), "CandidateChange")["payload"]["source_sha256"]

    def recover(self, sha, *, apply):
        return recovery.recover(self.run_id, sha, apply=apply,
                                base=self.base, queue_file=self.db, locks=self.locks)

    def test_private_umask_keeps_db_private_and_docker_inputs_readable(self):
        umask = os.umask(0o077)
        try:
            self.pending_verification()
            original = b.paths(self.run_id, self.base)["repo"]
            self.assertEqual(original.stat().st_mode & 0o777, 0o700)
            self.assertEqual((original / "verify.py").stat().st_mode & 0o777, 0o600)
            self.advance()  # sandbox mock asserts both fixture directories are 755 + files 644
            self.assertEqual(self.q.inspect(self.run_id)["job"]["status"], c.APPROVAL_PENDING)
            self.assertEqual(old.git(["status", "--porcelain"], original), "")
            self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        finally:
            os.umask(umask)

    def test_operator_recovery_only_requeues_failed_verification(self):
        sha = self.pending_verification()
        def fail(_):
            raise RuntimeError("Private sandbox message; must not leak to SQLite")
        for _ in range(w.MAX_ATTEMPTS):
            self.advance(sandbox=fail)
        self.assertEqual(self.q.inspect(self.run_id)["job"]["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.advance()["status"], "NEEDS_OPERATOR_RECOVERY")
        counts_before = dict(self.calls)
        with self.assertRaises(TransitionError):
            self.recover("0"*64, apply=True)
        dry = self.recover(sha, apply=False)
        self.assertEqual(dry["decision"], "DRY_RUN_RECOVERY_ELIGIBLE")
        self.assertEqual(self.q.inspect(self.run_id)["job"]["attempts"], 3)
        applied = self.recover(sha, apply=True)
        self.assertEqual(applied["decision"], "VERIFICATION_ONLY_REQUEUED")
        self.assertEqual(self.q.inspect(self.run_id)["job"]["status"], "QUEUED")
        self.assertEqual(self.q.inspect(self.run_id)["job"]["attempts"], 0)
        with c.RemediationRuntime(b.paths(self.run_id, self.base)["db"]) as rt:
            outbox = rt.db.execute("SELECT attempts FROM outbox WHERE job_id=?",
                                   (self.run_id + ":dispatch-verification",)).fetchone()
            self.assertEqual(outbox["attempts"], 0)
        self.assertEqual(self.advance()["status"], c.APPROVAL_PENDING)
        self.assertEqual(self.calls["A"], counts_before["A"])
        self.assertEqual(self.calls["B"], counts_before["B"])
        self.assertEqual(self.calls["C"], counts_before["C"])
        self.assertEqual(self.calls["Docker"], 2)
        self.assertNotIn(b"Private sandbox message", self.db.read_bytes())

    def test_no_preemptive_recovery_or_second_reauthorization(self):
        sha = self.pending_verification()
        with self.assertRaises(TransitionError):
            self.recover(sha, apply=True)
        def fail(_):
            raise RuntimeError("offline")
        for _ in range(w.MAX_ATTEMPTS):
            self.advance(sandbox=fail)
        self.recover(sha, apply=True)
        # Simulate a different failure after an already authorized requeue.
        for _ in range(w.MAX_ATTEMPTS):
            self.advance(sandbox=fail)
        with self.assertRaises(TransitionError):
            self.recover(sha, apply=True)

    def test_candidate_tampering_refuses_operator_recovery(self):
        sha = self.pending_verification()
        def fail(_):
            raise RuntimeError("unavailable")
        for _ in range(w.MAX_ATTEMPTS):
            self.advance(sandbox=fail)
        p = b.paths(self.run_id, self.base)["folder"] / "candidate_workspace" / "app.py"
        p.write_text("def evil(): pass\n")
        with self.assertRaises(TransitionError):
            self.recover(sha, apply=True)
        self.assertEqual(self.q.inspect(self.run_id)["job"]["status"], "NEEDS_OPERATOR_RECOVERY")

    def test_two_database_commit_crash_can_be_resumed_without_second_authorization(self):
        sha = self.pending_verification()
        def fail(_):
            raise RuntimeError("offline")
        for _ in range(w.MAX_ATTEMPTS):
            self.advance(sandbox=fail)
        with c.RemediationRuntime(b.paths(self.run_id, self.base)["db"]) as rt:
            rt._begin()
            rt.db.execute("UPDATE outbox SET attempts=0 WHERE job_id=?",
                          (self.run_id + ":dispatch-verification",))
            rt._event(self.run_id, recovery.EVENT_KEY, "OPERATOR_RECOVERY", "Operator",
                      recovery.REASON, self.run_id + ":verification",
                      {"candidate_sha256": sha})
            rt.db.commit()
        self.assertEqual(self.recover(sha, apply=True)["decision"], "VERIFICATION_ONLY_REQUEUED")
        self.assertEqual(self.advance()["status"], c.APPROVAL_PENDING)


if __name__ == "__main__":
    unittest.main()
