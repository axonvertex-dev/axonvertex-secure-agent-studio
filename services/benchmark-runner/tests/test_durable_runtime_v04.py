"""Checkpoint 2E-0.4A: restart and state-machine contracts; stdlib only."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "src/benchmark_runner/durable_runtime_v04.py"
spec = importlib.util.spec_from_file_location("durable_runtime_v04", RUNNER)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
DurableRuntime = mod.DurableRuntime
TransitionError = mod.TransitionError


class DurableContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "state.sqlite3"
        self.run_id = "demo-restart-01"

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(RUNNER), *args,
                               "--db", str(self.db), "--run-id", self.run_id],
                              text=True, capture_output=True, timeout=20)

    def seed(self):
        with DurableRuntime(self.db) as r:
            return r.start(self.run_id, "ctx-synthetic-checkpoint2e04")

    def complete(self):
        with DurableRuntime(self.db) as r:
            return r.complete_scout(self.run_id, "scout-001", ["ev-synthetic-001"])

    def test_crash_after_commit_and_restart_in_other_processes(self):
        abrupt = self.cli("crash-after-start")
        self.assertEqual(abrupt.returncode, 37, abrupt.stderr)
        inspected = self.cli("inspect")
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        before = json.loads(inspected.stdout)
        self.assertEqual(before["status"], "WAITING_FOR_SCOUT")
        self.assertEqual([x["event_type"] for x in before["events"]],
                         ["WORKFLOW_CREATED", "TASK_DELEGATED"])
        result = self.cli("complete-scout", "--artifact-id", "scout-001",
                          "--evidence-id", "ev-synthetic-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "READY_TO_RESUME")
        claimed = self.cli("claim-resume", "--worker", "node-a-worker-1")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        token = json.loads(claimed.stdout)["lease_token"]
        self.assertEqual(json.loads(self.cli("claim-resume").stdout), None)
        ack = self.cli("ack-resume", "--lease-token", token)
        self.assertEqual(ack.returncode, 0, ack.stderr)
        final = json.loads(self.cli("inspect").stdout)
        self.assertEqual(final["status"], "GEMMA_RESUMED")
        self.assertEqual(sum(e["event_type"] == "TASK_DELEGATED" for e in final["events"]), 1)
        self.assertEqual(sum(e["event_type"] == "AGENT_RESUMED" for e in final["events"]), 1)
        self.assertEqual(len(final["artifacts"]), 1)
        self.assertEqual([x["status"] for x in final["outbox"]], ["DONE", "DONE"])

    def test_start_is_idempotent_and_context_conflict_rejected(self):
        first = self.seed()
        with DurableRuntime(self.db) as r:
            second = r.start(self.run_id, "ctx-synthetic-checkpoint2e04")
            self.assertEqual(first, second)
            with self.assertRaises(TransitionError):
                r.start(self.run_id, "different-context")
            self.assertEqual(r.snapshot(self.run_id), first)

    def test_scout_result_is_idempotent_with_same_receipt(self):
        self.seed()
        first = self.complete()
        with DurableRuntime(self.db) as r:
            second = r.complete_scout(self.run_id, "scout-001", ["ev-synthetic-001"])
            self.assertEqual(first, second)
            self.assertEqual(len(second["artifacts"]), 1)
            self.assertEqual(sum(e["event_type"] == "AGENT_RESUME_READY" for e in second["events"]), 1)

    def test_conflicting_result_fails_closed_without_change(self):
        self.seed()
        first = self.complete()
        with DurableRuntime(self.db) as r:
            with self.assertRaises(TransitionError):
                r.complete_scout(self.run_id, "scout-001", ["ev-different"])
            self.assertEqual(r.snapshot(self.run_id), first)
            with self.assertRaises(TransitionError):
                r.complete_scout(self.run_id, "scout-002", ["ev-different"])
            self.assertEqual(r.snapshot(self.run_id), first)

    def test_missing_evidence_rejected_before_write(self):
        first = self.seed()
        with DurableRuntime(self.db) as r:
            with self.assertRaises(ValueError):
                r.complete_scout(self.run_id, "scout-001", [])
            self.assertEqual(r.snapshot(self.run_id), first)

    def test_no_early_resume_and_one_active_claim(self):
        self.seed()
        with DurableRuntime(self.db) as r:
            self.assertIsNone(r.claim_resume(self.run_id, "worker-one"))
        self.complete()
        with DurableRuntime(self.db) as r:
            first = r.claim_resume(self.run_id, "worker-one", now_epoch=1000)
            self.assertIsNotNone(first)
            self.assertIsNone(r.claim_resume(self.run_id, "worker-two", now_epoch=1001))
            self.assertEqual(r.snapshot(self.run_id)["outbox"][1]["attempts"], 1)

    def test_expired_lease_can_be_reclaimed_stale_token_fails(self):
        self.seed()
        self.complete()
        with DurableRuntime(self.db) as r:
            old = r.claim_resume(self.run_id, "worker-one", lease_seconds=10, now_epoch=1000)
            fresh = r.claim_resume(self.run_id, "worker-two", lease_seconds=60, now_epoch=1011)
            self.assertNotEqual(old["lease_token"], fresh["lease_token"])
            self.assertEqual(fresh["attempt"], 2)
            with self.assertRaises(TransitionError):
                r.ack_resume(self.run_id, old["lease_token"])
            self.assertEqual(r.snapshot(self.run_id)["status"], "READY_TO_RESUME")
            # ACK of synthetic historical time is correctly expired in wall-clock time.
            with self.assertRaises(TransitionError):
                r.ack_resume(self.run_id, fresh["lease_token"])
        # Reclaim with a live lease and acknowledge it.
        with DurableRuntime(self.db) as r:
            active = r.claim_resume(self.run_id, "worker-three")
            self.assertEqual(active["attempt"], 3)
            done = r.ack_resume(self.run_id, active["lease_token"])
            self.assertEqual(done["status"], "GEMMA_RESUMED")
            self.assertIsNone(r.claim_resume(self.run_id, "worker-four"))

    def test_duplicate_ack_does_not_repeat_transition(self):
        self.seed()
        self.complete()
        with DurableRuntime(self.db) as r:
            active = r.claim_resume(self.run_id, "worker-one")
            done = r.ack_resume(self.run_id, active["lease_token"])
            with self.assertRaises(TransitionError):
                r.ack_resume(self.run_id, active["lease_token"])
            self.assertEqual(r.snapshot(self.run_id), done)
            self.assertEqual(sum(e["event_type"] == "AGENT_RESUMED" for e in done["events"]), 1)

    def test_inspection_excludes_lease_token(self):
        self.seed()
        self.complete()
        with DurableRuntime(self.db) as r:
            active = r.claim_resume(self.run_id, "worker-one")
            text = json.dumps(r.snapshot(self.run_id))
            self.assertNotIn(active["lease_token"], text)
            self.assertEqual(r.snapshot(self.run_id)["outbox"][1]["status"], "LEASED")


if __name__ == "__main__":
    unittest.main()
