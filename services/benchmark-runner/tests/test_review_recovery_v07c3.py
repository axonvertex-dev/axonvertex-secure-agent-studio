"""Offline versioned-review recovery tests: no live inference, no host candidate execution."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import agentic_workflow_v03 as old
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import continuous_review_worker_v05b as review
from benchmark_runner import continuous_remediation_worker_v05c as remediation
from benchmark_runner import review_recovery_v07c3 as retry
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner import operator_review_v07a as operator_review
from benchmark_runner import operator_decisions_v07b as decisions
from benchmark_runner.durable_runtime_v04 import TransitionError
from test_continuous_remediation_worker_v05c import FullProvider


class TypoProvider(FullProvider):
    def call(self, node, messages, *, tools=None, schema=None):
        result = super().call(node, messages, tools=tools, schema=schema)
        if node == "C":
            data = json.loads(result["content"])
            first = data["supporting_evidence_ids"][0]
            data["supporting_evidence_ids"][0] = first[:-5] + "b9" + first[-5:]
            result["content"] = json.dumps(data)
            result["raw_content_sha256"] = old.sha(result["content"])
        return result


class RecoveryContracts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.base = self.root / "runs"
        self.locks = self.root / "locks"
        self.queue_db = self.root / "jobs.sqlite3"
        self.decision_db = self.root / "decision.sqlite3"
        self.q = worker.Queue(self.queue_db)
        self.addCleanup(self.q.close)
        principal_patch = patch.object(decisions, "principal", return_value={
            "uid": 1000, "name": "axonvertex", "identity_assurance": "local_os_account_only"})
        principal_patch.start()
        self.addCleanup(principal_patch.stop)
        self.calls = {"A": 0, "B": 0, "C": 0, "Docker": 0}
        self.good = lambda _: FullProvider(self.calls)
        self.bad = lambda _: TypoProvider(self.calls)

    def sandbox(self, path):
        self.calls["Docker"] += 1
        if path.name == "fixture_repo":
            self.assertEqual((path / "app.py").read_text(), old.APP_VULNERABLE)
            return dict(remediation.BASELINE_EXPECTED)
        self.assertEqual((path / "app.py").read_text(), old.SAFE_EXAMPLE)
        return dict(remediation.CANDIDATE_EXPECTED)

    def step(self, factory=None):
        return remediation.advance(self.q, "proof", base=self.base, locks=self.locks,
            provider_factory=self.good, review_provider_factory=factory or self.good,
            remediation_provider_factory=self.good, sandbox=self.sandbox)

    def review_snapshot(self):
        with retry.RetryRuntime(bridge.paths("proof", self.base)["db"]) as rt:
            return rt.snapshot("proof")

    def quarantine(self):
        self.q.submit("proof")
        for _ in range(4):
            self.step()
        outcome = self.step(self.bad)
        self.assertEqual(outcome["status"], review.REVIEW_QUARANTINED)
        original = next(x for x in self.review_snapshot()["artifacts"]
                        if x["artifact_type"] == "SecurityReview")
        self.assertEqual(set(original["payload"]["validation_errors"]), retry.ERRORS)
        return original["content_sha256"]

    def recover(self, sha, *, apply=True):
        return retry.recover("proof", sha, apply=apply, base=self.base,
                             queue_db=self.queue_db, locks=self.locks,
                             decision_db=self.decision_db)

    def project(self):
        return operator_review.project("proof", queue_db=self.queue_db, run_base=self.base)

    def test_dry_run_keeps_quarantined_and_original(self):
        sha = self.quarantine()
        before = self.review_snapshot()
        result = self.recover(sha, apply=False)
        self.assertEqual(result["decision"], "REVIEW_RECOVERY_ELIGIBLE_DRY_RUN")
        self.assertEqual(self.review_snapshot()["artifacts"], before["artifacts"])
        self.assertEqual(self.q.inspect("proof")["job"]["status"], review.REVIEW_QUARANTINED)
        self.assertEqual(self.calls["C"], 1)

    def test_versioned_retry_e2e_accepted_no_repeat_ab_a(self):
        sha = self.quarantine()
        original = next(x for x in self.review_snapshot()["artifacts"]
                        if x["artifact_type"] == "SecurityReview")
        counts = self.calls.copy()
        out = self.recover(sha)
        self.assertEqual(out["decision"], "REVIEW_RETRY_QUEUED")
        self.assertEqual(self.q.inspect("proof")["job"]["phase"], retry.RETRY_PENDING)
        self.assertEqual(self.calls, counts)
        completed = self.step()
        self.assertEqual(completed["status"], review.REVIEW_COMPLETED)
        self.assertEqual(self.calls["C"], 2)
        self.assertEqual(self.calls["A"], counts["A"])
        self.assertEqual(self.calls["B"], counts["B"])
        snap = self.review_snapshot()
        rejected = next(a for a in snap["artifacts"] if a["artifact_type"] == "SecurityReview")
        accepted = next(a for a in snap["artifacts"] if a["artifact_type"] == "SecurityReviewRetry")
        self.assertEqual(rejected, original)
        self.assertFalse(rejected["payload"]["accepted"])
        self.assertTrue(accepted["payload"]["accepted"])
        self.assertEqual(self.project()["security_review"]["accepted_by_validator"], True)
        self.assertEqual(len(self.project()["security_review_history"]), 2)
        self.assertEqual(self.step()["phase"], remediation.REMEDIATION_PENDING)
        self.assertEqual(self.step()["phase"], remediation.CANDIDATE_READY)
        self.assertEqual(self.step()["phase"], remediation.VERIFY_PENDING)
        self.assertEqual(self.step()["status"], remediation.APPROVAL_PENDING)
        self.assertEqual(self.calls["A"], counts["A"] + 1)
        self.assertEqual(self.calls["B"], counts["B"])
        self.assertEqual(self.calls["Docker"], 2)
        projected = self.project()
        self.assertEqual(projected["candidate_change"]["review_artifact_id"], accepted["artifact_id"])
        self.assertEqual(projected["verification_result"]["passed"], True)
        candidate = projected["candidate_change"]["source_sha256"]
        verification = next(a["content_sha256"] for a in projected["artifacts"]
                            if a["artifact_type"] == "VerificationResult")
        eligible = decisions._eligible("proof", expected_candidate_sha256=candidate,
                                      expected_verification_sha256=verification,
                                      queue_db=self.queue_db, run_base=self.base)
        self.assertEqual(eligible["review_artifact_sha256"], accepted["content_sha256"])
        self.assertIsNone(decisions.inspect("proof", db_file=self.decision_db)["decision"])

    def test_no_second_authorization_or_modified_sha(self):
        sha = self.quarantine()
        self.recover(sha)
        with self.assertRaises(TransitionError):
            self.recover(sha)
        with self.assertRaises(TransitionError):
            self.recover("0" * 64)
        self.assertEqual(self.calls["C"], 1)

    def test_fresh_invalid_retry_keeps_two_rejected_and_stops(self):
        sha = self.quarantine()
        self.recover(sha)
        self.assertEqual(self.step(self.bad)["status"], review.REVIEW_QUARANTINED)
        self.assertEqual(self.calls["C"], 2)
        self.assertEqual(len(self.project()["security_review_history"]), 2)
        with self.assertRaises(TransitionError):
            self.recover(sha)
        self.assertEqual(self.calls["Docker"], 0)

    def test_wrong_digest_rejected_without_mutation(self):
        sha = self.quarantine()
        with self.assertRaises(TransitionError):
            self.recover("f" * 64)
        self.assertEqual(self.q.inspect("proof")["job"]["status"], review.REVIEW_QUARANTINED)
        self.assertFalse(any(a["artifact_type"] == "SecurityReviewRetry"
                             for a in self.review_snapshot()["artifacts"]))

    def test_recovery_blocks_original_review_tamper(self):
        sha = self.quarantine()
        db = bridge.paths("proof", self.base)["db"]
        with retry.RetryRuntime(db) as rt:
            rt.db.execute("UPDATE artifacts SET content_sha256=? WHERE artifact_id=?",
                          ("0" * 64, "proof:foundation-review"))
        with self.assertRaises(TransitionError):
            self.recover(sha)

    def test_crash_between_runtime_and_queue_reconcile_without_model_call(self):
        sha = self.quarantine()
        proof = retry._eligible("proof", sha, queue_db=self.queue_db,
                                base=self.base, decision_db=self.decision_db)
        with retry.RetryRuntime(bridge.paths("proof", self.base)["db"]) as rt:
            rt.schedule_retry("proof", proof, decisions.principal())
        self.assertEqual(self.q.inspect("proof")["job"]["status"], review.REVIEW_QUARANTINED)
        self.recover(sha)
        self.assertEqual(self.q.inspect("proof")["job"]["phase"], retry.RETRY_PENDING)
        self.assertEqual(self.calls["C"], 1)

    def test_crash_after_retry_receipt_queue_reconciliation_skips_model(self):
        sha = self.quarantine()
        self.recover(sha)
        prompt, ids, source, manifest = retry.retry_prompt("proof", base=self.base)
        with retry.RetryRuntime(bridge.paths("proof", self.base)["db"]) as rt:
            token = rt.claim_retry("proof")["lease_token"]
        result = self.good("proof").call("C", [{"role": "system", "content": "json"},
                                                {"role": "user", "content": prompt}], schema=old.REVIEW_SCHEMA)
        report = json.loads(result["content"])
        payload = {"review": report, "accepted": True, "validation_errors": [],
                   "response_sha256": old.sha(result["content"]), "prompt_sha256": old.sha(prompt),
                   "source_artifact_id": source, "evidence_ids": ids,
                   "model": result["model"], "node": "C"}
        with retry.RetryRuntime(bridge.paths("proof", self.base)["db"]) as rt:
            rt.commit_retry("proof", token, payload)
        count = self.calls["C"]
        self.assertEqual(self.step()["status"], review.REVIEW_COMPLETED)
        self.assertEqual(self.calls["C"], count)


if __name__ == "__main__":
    unittest.main()
