"""Checkpoint 2E-0.5A offline contracts; real nodes are not contacted."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import continuous_worker_v05a as w
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner import agentic_workflow_v03 as old
from benchmark_runner.durable_runtime_v04 import TransitionError


class FakeProvider:
    def __init__(self, counter):
        self.counter = counter
        self.nodes = {"A": {"model": "fake-gemma"}, "B": {"model": "fake-antares"}}

    def close(self):
        pass

    def call(self, node, messages, *, tools=None, schema=None):
        self.counter[node] += 1
        if node == "A":
            text = ("Plan read-only source inspection, do not assert deployment." if self.counter[node] == 1 else
                    "app.py concatenates SQL, web.py passes request args; production deployment unverified")
            finish, tool_calls = "stop", []
        elif node == "B":
            turn = self.counter[node]
            if turn % 3 == 1:
                name, args = "terminal", {"command": "ls"}
            elif turn % 3 == 2:
                name, args = "terminal", {"command": "cat app.py"}
            else:
                name, args = "submit_vulnerable_files", {"file_paths": ["app.py"], "reason": "source observation"}
            text, finish = "", "tool_calls"
            tool_calls = [{"id": f"b{turn}", "type": "function", "function":
                           {"name": name, "arguments": json.dumps(args)}}]
        else:
            raise AssertionError("No Foundation Sec stage in v05a")
        return {"node": node, "model": self.nodes[node]["model"],
                "finish_reason": finish, "content": text, "tool_calls": tool_calls,
                "format_leak_detected": False, "raw_content_sha256": old.sha(text),
                "prompt_tokens": 90, "completion_tokens": 100, "reasoning_tokens": None,
                "latency_ms": 1, "request_sha256": "mock-req"}


class WorkerContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "runs"
        self.locks = self.root / "locks"
        self.queue_file = self.root / "worker.sqlite3"
        self.q = w.Queue(self.queue_file)
        self.addCleanup(self.q.close)
        self.calls = {"A": 0, "B": 0}

    def factory(self, _id):
        return FakeProvider(self.calls)

    def one(self, run="proof"):
        return w.advance(self.q, run, base=self.base, locks=self.locks,
                         provider_factory=self.factory)

    def test_submit_idempotency_is_explicit_and_invalid_id_fails(self):
        self.q.submit("proof")
        with self.assertRaisesRegex(TransitionError, "already submitted"):
            self.q.submit("proof")
        with self.assertRaises(ValueError):
            self.q.submit("../escape")
        self.assertEqual(len(self.q.pending()), 1)

    def test_submit_once_then_auto_A_B_A_and_reopen_queue(self):
        self.q.submit("proof")
        r = w.serve(self.q, base=self.base, locks=self.locks,
                    provider_factory=self.factory, stop_when_idle=True)
        self.assertEqual([a["phase"] for a in r],
                         ["WAITING_FOR_SCOUT", "READY_TO_RESUME", "GEMMA_RESUMED"])
        self.assertEqual(r[-1]["status"], w.HANDOFF_COMPLETE)
        self.assertEqual(self.calls, {"A": 2, "B": 3})
        snapshot = b.inspect("proof", base=self.base)
        self.assertEqual(snapshot["status"], "GEMMA_RESUMED")
        self.assertEqual([j["status"] for j in snapshot["outbox"]], ["DONE", "DONE"])
        self.assertEqual(len([x for x in snapshot["artifacts"] if x["artifact_type"] == "GemmaResumeOutput"]), 1)
        with w.Queue(self.queue_file) as fresh:
            self.assertEqual(fresh.inspect("proof")["job"]["status"], w.HANDOFF_COMPLETE)
            self.assertEqual(fresh.pending(), [])
        self.assertEqual(self.one()["status"], w.HANDOFF_COMPLETE)
        self.assertEqual(self.calls, {"A": 2, "B": 3})

    def test_interruption_between_stages_uses_persisted_state(self):
        self.q.submit("proof")
        self.assertEqual(self.one()["phase"], "WAITING_FOR_SCOUT")
        self.q.close()
        self.q = w.Queue(self.queue_file)
        self.assertEqual(self.one()["phase"], "READY_TO_RESUME")
        self.q.close()
        self.q = w.Queue(self.queue_file)
        self.assertEqual(self.one()["phase"], "GEMMA_RESUMED")
        self.assertEqual(self.calls, {"A": 2, "B": 3})

    def test_recover_committed_prepare_before_worker_stage_receipt(self):
        self.q.submit("proof")
        p = self.factory("proof")
        b.prepare("proof", base=self.base, provider=p)
        self.assertEqual(self.one()["phase"], "READY_TO_RESUME")
        self.assertEqual(self.calls["A"], 1)
        self.assertEqual(self.one()["phase"], "GEMMA_RESUMED")
        self.assertEqual(self.calls["A"], 2)

    def test_recover_committed_resume_before_worker_stage_receipt(self):
        self.q.submit("proof")
        self.assertEqual(self.one()["phase"], "WAITING_FOR_SCOUT")
        self.assertEqual(self.one()["phase"], "READY_TO_RESUME")
        b.resume_live("proof", base=self.base, provider=self.factory("proof"))
        self.assertEqual(self.calls["A"], 2)
        self.assertEqual(self.one()["status"], w.HANDOFF_COMPLETE)
        self.assertEqual(self.calls["A"], 2)

    def test_partial_prepare_requires_manual_recovery(self):
        self.q.submit("proof")
        ps = b.paths("proof", self.base)
        ps["folder"].mkdir(parents=True)
        result = self.one()
        self.assertEqual(result["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.calls, {"A": 0, "B": 0})
        self.assertNotIn("proof", self.q.pending())

    def test_kernel_lock_denies_second_worker_without_dispatch(self):
        self.q.submit("proof")
        with w.run_lock("proof", self.locks) as acquired:
            self.assertTrue(acquired)
            result = self.one()
            self.assertEqual(result["status"], "BUSY_OTHER_WORKER")
        self.assertEqual(self.calls, {"A": 0, "B": 0})
        self.assertEqual(self.one()["phase"], "WAITING_FOR_SCOUT")

    def test_fail_closed_after_bounded_attempts_and_redact_failure_details(self):
        self.q.submit("proof")
        class Broken:
            def __init__(self, counter):
                self.counter = counter
            def close(self):
                pass
            def call(self, node, messages, *, tools=None, schema=None):
                self.counter["A"] += 1
                raise RuntimeError("super secret bearer key")
        # Pre-create fully valid prepared task; otherwise failed initial preparation
        # correctly needs operator intervention due to ambiguous partial effects.
        b.prepare("proof", base=self.base, provider=self.factory("proof"))
        self.assertEqual(self.calls["A"], 1)
        def broken(_run):
            return Broken(self.calls)
        for i in range(w.MAX_ATTEMPTS):
            result = w.advance(self.q, "proof", base=self.base, locks=self.locks,
                               provider_factory=broken)
        self.assertEqual(result["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertNotIn("super secret", self.queue_file.read_bytes().decode("utf-8", "ignore"))
        self.assertNotIn("Bearer", json.dumps(self.q.inspect("proof")))

    def test_no_invented_foundation_sec_or_approval_claim(self):
        self.q.submit("proof")
        results = w.serve(self.q, base=self.base, locks=self.locks, provider_factory=self.factory,
                          stop_when_idle=True)
        self.assertEqual(results[-1]["status"], "HANDOFF_COMPLETED")
        self.assertNotIn("VERIFIED_CANDIDATE_AWAITING_APPROVAL", json.dumps(self.q.inspect("proof")))
        self.assertEqual(set(self.calls), {"A", "B"})


if __name__ == "__main__":
    unittest.main()
