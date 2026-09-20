"""0.7B local-only decision lifecycle and immutability regression."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import operator_decisions_v07b as ledger
from benchmark_runner.durable_runtime_v04 import TransitionError
import test_operator_review_v07a as review_fixture
RUN = review_fixture.RUN


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = review_fixture.OperatorReviewTests("test_full_projection_is_evidence_complete_and_redacted")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db = self.fixture.base / "decision-data" / "decisions.sqlite3"
        self.locks = self.fixture.base / "locks"
        self.snapshot = self.fixture.read()
        self.csha = self.snapshot["candidate_change"]["source_sha256"]
        self.vsha = next(a["content_sha256"] for a in self.snapshot["artifacts"]
                         if a["artifact_type"] == "VerificationResult")
        self.kw = dict(expected_candidate_sha256=self.csha,
            expected_verification_sha256=self.vsha, db_file=self.db,
            queue_db=self.fixture.queue, run_base=self.fixture.run_base,
            locks=self.locks, request_id="test-request-20260920-0001",
            justification="Reviewed the synthetic candidate and sandbox result.",
            decision="APPROVE", reason_code="VERIFIED_SYNTHETIC_FIX_ACCEPTED")
        self.patcher = patch.object(ledger,"principal",return_value={
            "uid":os.getuid(),"name":"fixture-operator","identity_assurance":"local_os_account_only"})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def decide(self, **updates):
        return ledger.decide(RUN,**(self.kw | updates))

    def test_dry_run_does_not_create_decisions_or_locks(self):
        result=self.decide()
        self.assertEqual(result["result"],"DECISION_ELIGIBLE_DRY_RUN")
        self.assertFalse(self.db.exists())
        self.assertFalse(self.locks.exists())
        self.assertIsNone(ledger.inspect(RUN,db_file=self.db)["decision"])


    def test_bad_run_id_refused_before_lock_file_creation(self):
        with self.assertRaises(ValueError):
            ledger.decide("../outside",**(self.kw | {"apply":True}))
        self.assertFalse(self.db.exists())
        self.assertFalse(self.locks.exists())

    def test_root_or_setuid_principal_refused(self):
        self.patcher.stop()
        try:
            with patch.object(ledger.os,"getuid",return_value=0), patch.object(ledger.os,"geteuid",return_value=0):
                with self.assertRaisesRegex(TransitionError,"root"):
                    ledger.principal()
            with patch.object(ledger.os,"getuid",return_value=1000), patch.object(ledger.os,"geteuid",return_value=1001):
                with self.assertRaisesRegex(TransitionError,"effective UID"):
                    ledger.principal()
        finally:
            self.patcher.start()

    def test_approve_records_hashes_and_os_identity_without_application(self):
        result=self.decide(apply=True)
        self.assertEqual(result["result"],"OPERATOR_DECISION_RECORDED")
        self.assertFalse(result["applies_code"])
        data=ledger.inspect(RUN,db_file=self.db)["decision"]
        self.assertEqual(data["candidate_sha256"],self.csha)
        self.assertEqual(data["verification_artifact_sha256"],self.vsha)
        self.assertEqual(data["principal_uid"],os.getuid())
        self.assertEqual(data["identity_assurance"],"local_os_account_only")
        self.assertEqual(data["decision"],"APPROVE")
        self.assertEqual(self.fixture.read()["runtime_status"],"VERIFIED_CANDIDATE_AWAITING_APPROVAL")
        self.assertEqual(self.db.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.db.parent.stat().st_mode & 0o777,0o700)

    def test_reject_has_separate_reason_code(self):
        self.decide(apply=True,decision="REJECT",reason_code="INSUFFICIENT_REVIEW_EVIDENCE")
        self.assertEqual(ledger.inspect(RUN,db_file=self.db)["decision"]["decision"],"REJECT")
        with self.assertRaisesRegex(TransitionError,"reason code"):
            self.decide(decision="REJECT", reason_code="VERIFIED_SYNTHETIC_FIX_ACCEPTED")

    def test_exact_replay_is_idempotent_and_does_not_write_new_row(self):
        first=self.decide(apply=True)
        second=self.decide(apply=True)
        self.assertEqual(second["result"],"DECISION_ALREADY_COMMITTED")
        self.assertEqual(first["receipt_sha256"],second["receipt_sha256"])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decisions").fetchone()[0],1)

    def test_conflicting_decision_is_refused_even_different_request(self):
        self.decide(apply=True)
        with self.assertRaisesRegex(TransitionError,"already final"):
            self.decide(apply=True,decision="REJECT",reason_code="FIX_NOT_ACCEPTED",
                        request_id="test-request-20260920-0002")

    def test_duplicate_request_id_for_new_run_refused(self):
        self.decide(apply=True)
        with self.assertRaisesRegex(TransitionError,"already final"):
            self.decide(apply=True,request_id="test-request-20260920-0001",
                        justification="Different justification to test conflict.")

    def test_no_decision_on_failed_verification(self):
        self.fixture.verify["passed"]=False
        self.fixture.save("VerificationResult",self.fixture.verify)
        with self.assertRaises(TransitionError):
            self.decide(apply=True)
        self.assertFalse(self.db.exists())

    def test_refuses_stale_candidate_and_verification_hash(self):
        with self.assertRaisesRegex(TransitionError,"Candidate hash"):
            self.decide(expected_candidate_sha256="0"*64)
        with self.assertRaisesRegex(TransitionError,"Verification artifact hash"):
            self.decide(expected_verification_sha256="0"*64)

    def test_tampered_security_review_refuses_decision(self):
        with sqlite3.connect(self.fixture.runtime) as db:
            db.execute("UPDATE artifacts SET payload_json=? WHERE artifact_type='SecurityReview'",
                       (json.dumps({"tampered":True}),))
        with self.assertRaisesRegex(TransitionError,"integrity mismatch"):
            self.decide(apply=True)
        self.assertFalse(self.db.exists())

    def test_undecided_run_must_be_in_approval_phase(self):
        with sqlite3.connect(self.fixture.queue) as db:
            db.execute("UPDATE jobs SET status='QUEUED' WHERE run_id=?",(RUN,))
        with self.assertRaisesRegex(TransitionError,"approval-pending"):
            self.decide()

    def test_sqlite_rejects_update_and_delete(self):
        self.decide(apply=True)
        with sqlite3.connect(self.db) as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError,"immutable"):
                db.execute("UPDATE decisions SET decision='REJECT'")
            with self.assertRaisesRegex(sqlite3.IntegrityError,"immutable"):
                db.execute("DELETE FROM decisions")

    def test_receipt_integrity_detects_manual_row_tampering(self):
        self.decide(apply=True)
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TRIGGER decisions_no_update")
            db.execute("UPDATE decisions SET reason_code='OTHER_REVIEW_REASON'")
        with self.assertRaisesRegex(TransitionError,"receipt content mismatch"):
            ledger.inspect(RUN,db_file=self.db)

    def test_decision_ledger_symlink_refused(self):
        self.db.parent.mkdir(mode=0o700)
        self.db.symlink_to(self.fixture.queue)
        with self.assertRaisesRegex(TransitionError,"Symlinked"):
            self.decide(apply=True)

    def test_read_missing_or_invalid_run_does_not_create_database(self):
        with self.assertRaises(ValueError):
            ledger.inspect("../escape",db_file=self.db)
        with self.assertRaises(TransitionError):
            self.decide(expected_candidate_sha256="not-sha")
        self.assertFalse(self.db.exists())

    def test_identity_binding_refuses_other_principal_on_retry(self):
        self.decide(apply=True)
        with patch.object(ledger,"principal",return_value={
            "uid":10000,"name":"other","identity_assurance":"local_os_account_only"}):
            with self.assertRaisesRegex(TransitionError,"already final"):
                self.decide(apply=True)


if __name__ == "__main__":
    unittest.main()
