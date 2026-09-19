"""2E-0.5C offline contracts: real SQLite and Git fixture, fake models/sandbox.

Never execute a generated candidate on the host; fake Docker results for contract tests.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import continuous_remediation_worker_v05c as c
from benchmark_runner import continuous_worker_v05a as a
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner import agentic_workflow_v03 as old
from test_continuous_review_worker_v05b import FakeProvider


class FullProvider(FakeProvider):
    def __init__(self, counts, *, invalid=False, offline=False):
        super().__init__(counts)
        self.invalid, self.offline = invalid, offline

    def call(self, node, messages, *, tools=None, schema=None):
        if node != "A" or self.counts["A"] < 2:
            return super().call(node, messages, tools=tools, schema=schema)
        self.counts["A"] += 1
        if self.offline:
            raise RuntimeError("private bearer secret and sensitive upstream error")
        content = "```python\ndef bad(conn, username):\n    pass\n```" if self.invalid else (
            "```python\n" + old.SAFE_EXAMPLE + "```")
        return {"node": "A", "model": "fake-A", "content": content, "finish_reason": "stop",
                "tool_calls": [], "format_leak_detected": False, "raw_content_sha256": old.sha(content),
                "prompt_tokens": 50, "completion_tokens": 80, "reasoning_tokens": None,
                "latency_ms": 1, "request_sha256": "fake"}


class RemediationContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "runs"
        self.locks = self.root / "locks"
        self.queue_file = self.root / "jobs.sqlite3"
        self.q = a.Queue(self.queue_file)
        self.addCleanup(lambda: self.q.close())
        self.calls = {"A": 0, "B": 0, "C": 0, "Docker": 0}
        self.provider = lambda _: FullProvider(self.calls)

    def sandbox(self, path):
        self.calls["Docker"] += 1
        if path.name == "fixture_repo":
            self.assertEqual((path / "app.py").read_text(), old.APP_VULNERABLE)
            return dict(c.BASELINE_EXPECTED)
        self.assertEqual(path.name, "candidate_workspace")
        self.assertEqual((path / "app.py").read_text(), old.SAFE_EXAMPLE)
        return dict(c.CANDIDATE_EXPECTED)

    def step(self, **opts):
        return c.advance(self.q, "proof", base=self.base, locks=self.locks,
                         provider_factory=self.provider, review_provider_factory=self.provider,
                         remediation_provider_factory=opts.get("provider", self.provider),
                         sandbox=opts.get("sandbox", self.sandbox))

    def reach_review(self):
        self.q.submit("proof")
        for _ in range(5):
            self.step()
        self.assertEqual(self.q.inspect("proof")["job"]["status"], "REVIEW_COMPLETED")

    def reach_candidate(self):
        self.reach_review()
        self.assertEqual(self.step()["phase"], c.REMEDIATION_PENDING)
        self.assertEqual(self.step()["phase"], c.CANDIDATE_READY)

    def snapshot(self):
        with c.RemediationRuntime(b.paths("proof", self.base)["db"]) as rt:
            return rt.snapshot("proof")

    def test_single_submission_auto_a_b_a_c_patch_sandbox_approval(self):
        self.q.submit("proof")
        records = c.serve(self.q, base=self.base, locks=self.locks, stop_when_idle=True,
                          provider_factory=self.provider, review_provider_factory=self.provider,
                          remediation_provider_factory=self.provider, sandbox=self.sandbox)
        self.assertEqual([x["phase"] for x in records], [
            "WAITING_FOR_SCOUT", "READY_TO_RESUME", "GEMMA_RESUMED", "REVIEW_PENDING",
            "REVIEW_COMPLETED", c.REMEDIATION_PENDING, c.CANDIDATE_READY,
            c.VERIFY_PENDING, c.APPROVAL_PENDING])
        self.assertEqual(self.calls, {"A": 3, "B": 3, "C": 1, "Docker": 2})
        snap = self.snapshot()
        self.assertEqual(snap["status"], c.APPROVAL_PENDING)
        self.assertEqual(c.artifact(snap, "VerificationResult")["payload"]["passed"], True)
        self.assertEqual(c.artifact(snap, "CandidateChange")["payload"]["source"], old.SAFE_EXAMPLE)
        self.assertEqual(next(t for t in snap["tasks"] if t["task_id"] == "proof:root")["state"],
                         "AWAITING_APPROVAL")
        self.assertEqual(self.step()["status"], c.APPROVAL_PENDING)
        self.assertEqual(self.calls["A"], 3)
        self.assertEqual(self.calls["Docker"], 2)
        self.assertEqual(old.git(["status", "--porcelain"], b.paths("proof", self.base)["repo"]), "")

    def test_schedule_crash37_and_recovery_in_new_process(self):
        self.reach_review()
        # Recreate CLI paths for the old completed run; copy current run dir to it,
        # and recreate only queue row with its terminal status.
        cli_base = self.root / b.BASE
        cli_base.mkdir(parents=True)
        import shutil
        shutil.copytree(self.base / "proof", cli_base / "proof")
        cli_queue_path = self.root / a.BASE / "jobs.sqlite3"
        with a.Queue(cli_queue_path) as queue:
            queue.submit("proof")
            queue.db.execute("UPDATE jobs SET status='REVIEW_COMPLETED',phase='REVIEW_COMPLETED' "
                             "WHERE run_id='proof'")
        script = Path(c.__file__).resolve()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(script.parents[1])
        proc = subprocess.run([sys.executable, str(script), "schedule-remediation", "--run-id", "proof",
                               "--crash-after-remediation-schedule"], cwd=self.root, env=env,
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 37, proc.stderr)
        with a.Queue(cli_queue_path) as queue:
            self.assertEqual(queue.inspect("proof")["job"]["phase"], c.REMEDIATION_PENDING)
            with c.RemediationRuntime(cli_base / "proof" / "runtime.sqlite3") as rt:
                self.assertEqual(rt.snapshot("proof")["status"], "WAITING_FOR_REMEDIATION")
            out = c.advance(queue, "proof", base=cli_base, locks=self.root / "cli-locks",
                            remediation_provider_factory=self.provider, sandbox=self.sandbox)
            self.assertEqual(out["phase"], c.CANDIDATE_READY)
        self.assertEqual(self.calls["A"], 3)

    def test_crash_between_outbox_and_queue_reconciles_without_reschedule(self):
        self.reach_review()
        prompt, ctx = c.trusted_context("proof", base=self.base)
        with c.RemediationRuntime(b.paths("proof", self.base)["db"]) as rt:
            rt._schedule("proof", ctx["prompt_sha256"])
        self.assertEqual(self.step()["phase"], c.REMEDIATION_PENDING)
        self.assertEqual(self.step()["phase"], c.CANDIDATE_READY)

    def test_committed_candidate_before_queue_receipt_no_repeated_model(self):
        self.reach_candidate()
        self.q.db.execute("UPDATE jobs SET status='WORKING',phase=? WHERE run_id='proof'",
                          (c.REMEDIATION_PENDING,))
        self.assertEqual(self.step()["phase"], c.CANDIDATE_READY)
        self.assertEqual(self.calls["A"], 3)

    def test_committed_verification_before_queue_receipt_no_repeated_docker(self):
        self.reach_candidate()
        self.step()  # schedule verify
        with c.RemediationRuntime(b.paths("proof", self.base)["db"]) as rt:
            claim = rt.claim_job("proof", "verification")
        receipt = c.verify_candidate("proof", base=self.base, sandbox=self.sandbox)
        with c.RemediationRuntime(b.paths("proof", self.base)["db"]) as rt:
            rt.commit_verification("proof", claim["lease_token"], receipt)
        self.assertEqual(self.calls["Docker"], 2)
        self.assertEqual(self.step()["status"], c.APPROVAL_PENDING)
        self.assertEqual(self.calls["Docker"], 2)

    def test_bounded_invalid_patch_rejects_without_docker(self):
        self.reach_review()
        self.step()
        bad = lambda _: FullProvider(self.calls, invalid=True)
        self.assertEqual(self.step(provider=bad)["status"], c.REMEDIATION_REJECTED)
        self.assertEqual(self.calls["A"], 4)
        self.assertEqual(self.calls["Docker"], 0)
        self.assertEqual(self.snapshot()["status"], c.REMEDIATION_REJECTED)
        self.assertFalse(any(x["artifact_type"] == "CandidateChange" for x in self.snapshot()["artifacts"]))

    def test_gateway_failure_fails_closed_no_direct_fallback_and_redacted(self):
        self.reach_review()
        self.step()
        broken = lambda _: FullProvider(self.calls, offline=True)
        for _ in range(a.MAX_ATTEMPTS):
            last = self.step(provider=broken)
        self.assertEqual(last["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.calls["A"], 2 + a.MAX_ATTEMPTS)
        self.assertNotIn("private bearer secret", self.queue_file.read_bytes().decode("utf8", "ignore"))
        self.assertNotIn("private bearer secret", b.paths("proof", self.base)["db"].read_bytes().decode("utf8", "ignore"))
        self.assertFalse(any(x["artifact_type"] == "CandidateChange" for x in self.snapshot()["artifacts"]))

    def test_docker_unavailable_no_host_fallback(self):
        self.reach_candidate()
        self.step()
        fail = lambda _: (_ for _ in ()).throw(RuntimeError("private Docker error / secret"))
        for _ in range(a.MAX_ATTEMPTS):
            last = self.step(sandbox=fail)
        self.assertEqual(last["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertNotIn("private Docker error", self.queue_file.read_bytes().decode("utf8", "ignore"))
        self.assertNotIn("private Docker error", b.paths("proof", self.base)["db"].read_bytes().decode("utf8", "ignore"))

    def test_sandbox_bad_behavior_is_rejected(self):
        self.reach_candidate()
        self.step()
        bad = lambda p: dict(c.BASELINE_EXPECTED)
        self.assertEqual(self.step(sandbox=bad)["status"], c.VERIFICATION_REJECTED)
        self.assertEqual(self.snapshot()["status"], c.VERIFICATION_REJECTED)
        self.assertFalse(any(e["event_type"] == "APPROVAL_GATE" for e in self.snapshot()["events"]))

    def test_tampered_original_blocks_before_remediation_model(self):
        self.reach_review()
        self.step()
        (b.paths("proof", self.base)["repo"] / "app.py").write_text("# changed\n")
        self.assertEqual(self.step()["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.calls["A"], 2)

    def test_tampered_candidate_blocks_sandbox(self):
        self.reach_candidate()
        self.step()
        spot = b.paths("proof", self.base)["folder"] / "candidate_workspace"
        spot.mkdir()
        (spot / "app.py").write_text("# evil\n")
        self.assertEqual(self.step()["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.calls["Docker"], 0)

    def test_terminal_no_auto_apply_and_no_reinference(self):
        self.reach_candidate()
        self.step()
        self.step()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["status"], c.APPROVAL_PENDING)
        self.assertFalse(any(t["state"] == "APPLIED" for t in snapshot["tasks"]))
        self.assertNotIn("APPLY_PATCH", json.dumps(snapshot))
        self.assertEqual(self.step()["status"], c.APPROVAL_PENDING)
        self.assertEqual(self.calls["A"], 3)
