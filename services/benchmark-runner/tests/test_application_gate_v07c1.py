"""2E-0.7C1: no-source-write application preflight, target and decision binding."""
from __future__ import annotations

import os
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import application_gate_v07c1 as gate
from benchmark_runner import operator_decisions_v07b as decision
from benchmark_runner.durable_runtime_v04 import TransitionError
import test_operator_decisions_v07b as fixture_cases


class ApplicationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.delegate = fixture_cases.DecisionTests("test_approve_records_hashes_and_os_identity_without_application")
        self.delegate.setUp()
        self.addCleanup(self.delegate.doCleanups)
        self.fixture = self.delegate.fixture
        self.db = self.delegate.db
        self.csha = self.delegate.csha
        self.vsha = self.delegate.vsha
        self.synthetic, commit = self.fixture.base / "application_fixture_source", ""
        from benchmark_runner import agentic_workflow_v03 as old
        self.synthetic.mkdir()
        self.repo, commit = old.make_fixture(self.synthetic)
        self.fixture.candidate["fixture_commit"] = commit
        self.fixture.save("CandidateChange", self.fixture.candidate)
        self.target = self.fixture.folder / "application_workspace"
        subprocess.run(["git", "clone", "-q", "--no-local", str(self.repo), str(self.target)],
                       check=True, capture_output=True)
        self.expected = dict(target=self.target, decision_db=self.db,
            queue_db=self.fixture.queue, run_base=self.fixture.run_base,
            expected_candidate_sha256=self.csha, expected_verification_sha256=self.vsha)
        self.receipt = None

    def authorize(self, decision_value="APPROVE", reason_code="VERIFIED_SYNTHETIC_FIX_ACCEPTED"):
        receipt = self.delegate.decide(apply=True, decision=decision_value, reason_code=reason_code)
        self.receipt = receipt["receipt_sha256"]
        return receipt

    def plan(self, **kwargs):
        return gate.preflight(fixture_cases.RUN,
            **(self.expected | {"expected_decision_receipt_sha256": self.receipt} | kwargs))

    def test_missing_approval_refused_without_target_mutation(self):
        with self.assertRaisesRegex(TransitionError, "SHA-256"):
            self.plan()
        self.receipt = "0" * 64
        before = (self.target / "app.py").read_bytes()
        with self.assertRaisesRegex(TransitionError, "committed APPROVE"):
            self.plan()
        self.assertEqual(before, (self.target / "app.py").read_bytes())

    def test_preflight_approved_and_read_only(self):
        self.authorize()
        before = (self.target / "app.py").read_bytes()
        result = self.plan()
        self.assertEqual(result["result"], "APPLICATION_PREFLIGHT_ELIGIBLE")
        self.assertFalse(result["applies_code"])
        self.assertFalse(result["application_authorized"])
        self.assertEqual(before, (self.target / "app.py").read_bytes())
        self.assertFalse((self.target / "app.py.tmp").exists())

    def test_rejected_decision_blocks_application(self):
        self.authorize("REJECT", "FIX_NOT_ACCEPTED")
        with self.assertRaisesRegex(TransitionError, "committed APPROVE"):
            self.plan()

    def test_missing_or_wrong_target_path_blocks(self):
        self.authorize()
        for target in (self.repo, self.fixture.folder / "fixture_repo",
                       self.fixture.folder / "candidate_workspace", self.target / ".." / "application_workspace"):
            with self.subTest(target=target), self.assertRaises(TransitionError):
                self.plan(target=target)

    def test_bad_decision_receipt_blocks(self):
        self.authorize()
        with self.assertRaisesRegex(TransitionError, "receipt changed"):
            self.plan(expected_decision_receipt_sha256="1" * 64)

    def test_other_os_principal_blocks(self):
        self.authorize()
        with patch.object(decision, "principal", return_value={
            "uid": os.getuid() + 1000, "name": "other-user",
            "identity_assurance": "local_os_account_only"}):
            with self.assertRaisesRegex(TransitionError, "principal differs"):
                self.plan()

    def test_git_commit_change_blocks(self):
        self.authorize()
        subprocess.run(["git", "-C", str(self.target), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@invalid.test", "commit", "--allow-empty",
                        "-q", "-m", "changed target"], check=True)
        with self.assertRaisesRegex(TransitionError, "commit differs"):
            self.plan()

    def test_dirty_tracked_file_blocks(self):
        self.authorize()
        (self.target / "app.py").write_text("# changed\n")
        with self.assertRaisesRegex(TransitionError, "uncommitted"):
            self.plan()

    def test_dirty_untracked_file_blocks(self):
        self.authorize()
        (self.target / "generated.txt").write_text("unexpected\n")
        with self.assertRaisesRegex(TransitionError, "uncommitted"):
            self.plan()

    def test_missing_git_repo_blocks(self):
        self.authorize()
        import shutil
        shutil.rmtree(self.target)
        with self.assertRaisesRegex(TransitionError, "Pre-provisioned"):
            self.plan()

    def test_tampered_candidate_refuses(self):
        self.authorize()
        self.fixture.candidate["source"] = "# tampered\n"
        self.fixture.save("CandidateChange", self.fixture.candidate)
        with self.assertRaisesRegex(TransitionError, "source identity mismatch"):
            self.plan()

    def test_stale_candidate_or_verification_refuses(self):
        self.authorize()
        with self.assertRaisesRegex(TransitionError, "Candidate hash"):
            self.plan(expected_candidate_sha256="0" * 64)
        with self.assertRaisesRegex(TransitionError, "Verification artifact hash"):
            self.plan(expected_verification_sha256="0" * 64)

    def test_symlinked_target_refused(self):
        self.authorize()
        import shutil
        shutil.rmtree(self.target)
        self.target.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(TransitionError, "Unsafe application target"):
            self.plan()

    def test_symlinked_tracked_file_refused(self):
        self.authorize()
        f = self.target / "app.py"
        f.unlink()
        f.symlink_to(self.repo / "app.py")
        with self.assertRaises(TransitionError):
            self.plan()

    def test_bad_run_id_refuses_before_git_access(self):
        self.authorize()
        with self.assertRaises(ValueError):
            gate.preflight("../bad", **(self.expected | {
                "expected_decision_receipt_sha256": self.receipt}))
