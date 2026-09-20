"""0.7C2 offline-only integration: independent synthetic Git target and fake Docker."""
from __future__ import annotations

import difflib
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import application_execution_v07c2 as execution
from benchmark_runner import agentic_workflow_v03 as fixture
from benchmark_runner import continuous_remediation_worker_v05c as remediation
from benchmark_runner import operator_decisions_v07b as decisions
from benchmark_runner.durable_runtime_v04 import TransitionError
import test_application_gate_v07c1 as parent
import test_operator_review_v07a as review_cases

RUN = review_cases.RUN


class ApplicationExecutionTests(unittest.TestCase):
    def setUp(self):
        self.parent = parent.ApplicationPreflightTests("test_preflight_approved_and_read_only")
        self.parent.setUp()
        self.addCleanup(self.parent.doCleanups)
        self.target = self.parent.target
        shutil.copytree(self.parent.repo, self.parent.fixture.folder / "fixture_repo")
        self.parent.fixture.source = fixture.SAFE_EXAMPLE
        self.parent.fixture.candidate["source"] = fixture.SAFE_EXAMPLE
        self.parent.fixture.candidate["source_sha256"] = fixture.sha(fixture.SAFE_EXAMPLE)
        delta = "".join(difflib.unified_diff(
            fixture.APP_VULNERABLE.splitlines(keepends=True),
            fixture.SAFE_EXAMPLE.splitlines(keepends=True), fromfile="a/app.py", tofile="b/app.py"))
        self.parent.fixture.candidate["diff_sha256"] = fixture.sha(delta)
        self.parent.fixture.save("CandidateChange", self.parent.fixture.candidate)
        self.parent.fixture.verify["candidate_sha256"] = fixture.sha(fixture.SAFE_EXAMPLE)
        self.parent.fixture.save("VerificationResult", self.parent.fixture.verify)
        self.csha = fixture.sha(fixture.SAFE_EXAMPLE)
        self.vsha = next(a["content_sha256"] for a in self.parent.fixture.read()["artifacts"]
                         if a["artifact_type"] == "VerificationResult")
        receipt = self.parent.delegate.decide(apply=True,
            expected_candidate_sha256=self.csha, expected_verification_sha256=self.vsha)
        self.receipt = receipt["receipt_sha256"]
        self.commit = fixture.git(["rev-parse", "HEAD"], self.target)
        self.application_db = self.parent.fixture.base / "app-ledger" / "applications.sqlite3"
        self.authorization = dict(
            target=self.target,
            expected_candidate_sha256=self.csha,
            expected_verification_sha256=self.vsha,
            expected_decision_receipt_sha256=self.receipt,
            expected_target_commit=self.commit,
            request_id="application-auth-20260920-0001",
            db_file=self.application_db, decision_db=self.parent.db,
            queue_db=self.parent.fixture.queue, run_base=self.parent.fixture.run_base,
            locks=self.parent.delegate.locks)
        self.ex_args = dict(target=self.target, request_id="application-exec-20260920-0001",
            db_file=self.application_db, decision_db=self.parent.db,
            queue_db=self.parent.fixture.queue, run_base=self.parent.fixture.run_base,
            locks=self.parent.delegate.locks)
        self.sandbox_calls = 0

    def sandbox(self, path):
        self.sandbox_calls += 1
        self.assertEqual(path, self.target)
        self.assertEqual((path / "app.py").read_text(), fixture.SAFE_EXAMPLE)
        return dict(remediation.CANDIDATE_EXPECTED)

    def auth(self, **overrides):
        return execution.authorize(RUN, **(self.authorization | overrides))

    def run_apply(self, **overrides):
        return execution.execute(RUN, **(self.ex_args | {"sandbox": self.sandbox} | overrides))

    def reconcile(self, **overrides):
        return execution.reconcile(RUN, **(self.ex_args | {"sandbox": self.sandbox} | overrides))

    def test_authorization_dry_run_no_ledger_or_source_mutation(self):
        result = self.auth()
        self.assertEqual(result["result"], "APPLICATION_AUTHORIZATION_ELIGIBLE_DRY_RUN")
        self.assertFalse(self.application_db.exists())
        self.assertEqual((self.target / "app.py").read_text(), fixture.APP_VULNERABLE)

    def test_approval_alone_does_not_allow_execute(self):
        with self.assertRaisesRegex(TransitionError, "Separate application authorization"):
            self.run_apply(apply=True)
        self.assertFalse(self.application_db.exists())
        self.assertEqual((self.target / "app.py").read_text(), fixture.APP_VULNERABLE)

    def test_record_authorization_does_not_mutate_source(self):
        result = self.auth(record=True)
        self.assertEqual(result["result"], "APPLICATION_AUTHORIZATION_RECORDED")
        self.assertTrue(result["application_authorized"])
        self.assertFalse(result["applies_code"])
        self.assertEqual(execution.inspect(RUN, db_file=self.application_db)["application"]["state"],
                         "AUTHORIZED")
        self.assertEqual((self.target / "app.py").read_text(), fixture.APP_VULNERABLE)
        self.assertEqual(self.application_db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.application_db.parent.stat().st_mode & 0o777, 0o700)

    def test_record_requires_explicit_target_commit(self):
        with self.assertRaisesRegex(TransitionError, "target commit differs"):
            self.auth(expected_target_commit="0" * 40, record=True)
        self.assertFalse(self.application_db.exists())

    def test_no_target_other_than_independent_clone(self):
        with self.assertRaises(TransitionError):
            self.auth(target=self.parent.repo, record=True)
        self.assertFalse(self.application_db.exists())

    def test_duplicate_authorization_refuses(self):
        self.auth(record=True)
        with self.assertRaisesRegex(TransitionError, "already authorized"):
            self.auth(record=True)

    def test_execute_dry_run_no_target_mutation(self):
        self.auth(record=True)
        result = self.run_apply()
        self.assertEqual(result["result"], "APPLICATION_EXECUTION_ELIGIBLE_DRY_RUN")
        self.assertEqual(self.sandbox_calls, 0)
        self.assertEqual((self.target / "app.py").read_text(), fixture.APP_VULNERABLE)

    def test_apply_only_app_py_and_durable_receipt(self):
        self.auth(record=True)
        result = self.run_apply(apply=True)
        self.assertEqual(result["result"], "APPLICATION_APPLIED")
        self.assertFalse(result["git_commit_created"])
        self.assertEqual(self.sandbox_calls, 1)
        self.assertEqual((self.target / "app.py").read_text(), fixture.SAFE_EXAMPLE)
        self.assertEqual(fixture.git(["status", "--porcelain"], self.target), "M app.py")
        self.assertEqual(fixture.git(["status", "--porcelain"], self.parent.repo), "")
        entry = execution.inspect(RUN, db_file=self.application_db)["application"]
        self.assertEqual(entry["state"], "APPLIED")
        self.assertEqual([e["kind"] for e in entry["events"]],
                         ["AUTHORIZED", "APPLY_STARTED", "APPLY_COMPLETED"])
        self.assertEqual(entry["result_sha256"], result["receipt_sha256"])
        self.assertEqual(self.parent.delegate.fixture.read()["runtime_status"], remediation.APPROVAL_PENDING)

    def test_exact_execute_replay_does_not_rewrite_or_redocker(self):
        self.auth(record=True)
        self.run_apply(apply=True)
        source_stat = (self.target / "app.py").stat().st_mtime_ns
        again = self.run_apply(apply=True)
        self.assertEqual(again["result"], "APPLICATION_ALREADY_RECORDED")
        self.assertEqual(self.sandbox_calls, 1)
        self.assertEqual((self.target / "app.py").stat().st_mtime_ns, source_stat)

    def test_different_execute_request_after_applied_refuses(self):
        self.auth(record=True)
        self.run_apply(apply=True)
        with self.assertRaisesRegex(TransitionError, "pending/completed"):
            self.run_apply(apply=True, request_id="application-exec-20260920-0002")

    def test_tampered_target_after_authorization_fails_before_mutation(self):
        self.auth(record=True)
        (self.target / "web.py").write_text("# changed\n")
        with self.assertRaises(TransitionError):
            self.run_apply(apply=True)
        self.assertEqual(execution.inspect(RUN, db_file=self.application_db)["application"]["state"],
                         "AUTHORIZED")
        self.assertEqual(self.sandbox_calls, 0)

    def test_changed_decision_receipt_refuses(self):
        self.auth(record=True)
        with patch.object(decisions, "inspect", return_value={"decision": {"decision":"REJECT",
             "receipt_sha256":self.receipt}}):
            with self.assertRaisesRegex(TransitionError, "Approved decision"):
                self.run_apply(apply=True)
        self.assertEqual(self.sandbox_calls, 0)

    def test_failed_postcheck_holds_for_explicit_recovery(self):
        self.auth(record=True)
        def bad(_):
            raise RuntimeError("Docker deliberately failed")
        with self.assertRaises(RuntimeError):
            self.run_apply(apply=True, sandbox=bad)
        row = execution.inspect(RUN, db_file=self.application_db)["application"]
        self.assertEqual(row["state"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual((self.target / "app.py").read_text(), fixture.SAFE_EXAMPLE)
        with self.assertRaisesRegex(TransitionError, "pending/completed"):
            self.run_apply(apply=True)
        preview = self.reconcile()
        self.assertEqual(preview["result"], "RECONCILIATION_REQUIRED")
        self.assertEqual(self.sandbox_calls, 0)
        recovered = self.reconcile(apply=True)
        self.assertEqual(recovered["result"], "APPLICATION_RECONCILED")
        self.assertFalse(recovered["applies_code"])
        self.assertEqual(self.sandbox_calls, 1)
        self.assertEqual(execution.inspect(RUN, db_file=self.application_db)["application"]["state"],
                         "APPLIED")

    def test_crash_after_atomic_replace_reconcile_without_rewrite(self):
        self.auth(record=True)
        original_post = execution._postcheck
        def interruption(*args, **kwargs):
            raise KeyboardInterrupt("synthetic crash")
        with patch.object(execution, "_postcheck", side_effect=interruption):
            with self.assertRaises(KeyboardInterrupt):
                self.run_apply(apply=True)
        row = execution.inspect(RUN, db_file=self.application_db)["application"]
        self.assertEqual(row["state"], "APPLYING")
        before = (self.target / "app.py").stat().st_mtime_ns
        recovered = self.reconcile(apply=True)
        self.assertEqual(recovered["result"], "APPLICATION_RECONCILED")
        self.assertEqual((self.target / "app.py").stat().st_mtime_ns, before)

    def test_reconcile_refuses_tampered_applied_file(self):
        self.auth(record=True)
        with self.assertRaises(RuntimeError):
            self.run_apply(apply=True, sandbox=lambda _: (_ for _ in ()).throw(RuntimeError("failure")))
        (self.target / "app.py").write_text("# tamper\n")
        with self.assertRaisesRegex(TransitionError, "expected files"):
            self.reconcile(apply=True)
        self.assertEqual(execution.inspect(RUN, db_file=self.application_db)["application"]["state"],
                         "NEEDS_OPERATOR_RECOVERY")

    def test_refuses_conflicting_application_request_id(self):
        self.auth(record=True)
        with self.assertRaises(TransitionError):
            self.run_apply(request_id="bad", apply=True)

    def test_missing_inspection_does_not_create_application_db(self):
        response = execution.inspect(RUN, db_file=self.application_db)
        self.assertIsNone(response["application"])
        self.assertFalse(self.application_db.exists())

    def test_changed_applying_principal_refuses(self):
        self.auth(record=True)
        with patch.object(decisions, "principal", return_value={
            "uid":os.getuid()+1000,"name":"different","identity_assurance":"local_os_account_only"}):
            with self.assertRaisesRegex(TransitionError, "identity differs"):
                self.run_apply(apply=True)
        self.assertEqual((self.target / "app.py").read_text(), fixture.APP_VULNERABLE)

    def test_symlinked_app_after_authorization_refuses(self):
        self.auth(record=True)
        (self.target / "app.py").unlink()
        (self.target / "app.py").symlink_to(self.parent.repo / "app.py")
        with self.assertRaises(TransitionError):
            self.run_apply(apply=True)
        self.assertEqual(self.sandbox_calls, 0)

    def test_tampered_postapplication_receipt_refuses(self):
        self.auth(record=True)
        self.run_apply(apply=True)
        with sqlite3.connect(self.application_db) as db:
            db.execute("UPDATE applications SET result_json='{}' WHERE run_id=?", (RUN,))
        with self.assertRaisesRegex(TransitionError, "receipt integrity"):
            execution.inspect(RUN, db_file=self.application_db)

    def test_wrong_authorization_request_id_prevents_execute(self):
        self.auth(record=True)
        with self.assertRaises(TransitionError):
            self.run_apply(apply=True, request_id="bad")
        self.assertEqual((self.target / "app.py").read_text(), fixture.APP_VULNERABLE)

    def test_symlinked_application_ledger_refuses(self):
        self.application_db.parent.mkdir(mode=0o700)
        self.application_db.symlink_to(self.parent.db)
        with self.assertRaisesRegex(TransitionError, "Symlinked"):
            self.auth(record=True)


if __name__ == "__main__":
    unittest.main()
