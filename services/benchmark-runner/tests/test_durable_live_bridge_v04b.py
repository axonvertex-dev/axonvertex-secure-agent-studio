"""Offline contract tests; fake provider only, no live node access."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner.durable_runtime_v04 import TransitionError


class FakeProvider:
    def __init__(self):
        self.a_calls = 0
        self.b_calls = 0

    def call(self, node, messages, *, tools=None, schema=None):
        if node == "A":
            self.a_calls += 1
            text = ("Inspect app.py with read-only tools; establish caller and source evidence."
                    if self.a_calls == 1 else
                    "app.py directly concatenates username into SQL; web.py passes request.args. "
                    "No production network route proven. Verified source refs only.")
            return self._result(node, "stop", text, [])
        self.b_calls += 1
        if self.b_calls == 1:
            name, args = "terminal", {"command": "ls"}
        elif self.b_calls == 2:
            name, args = "terminal", {"command": "cat app.py"}
        else:
            name, args = "submit_vulnerable_files", {"file_paths": ["app.py"], "reason": "SQL string concatenation"}
        return self._result(node, "tool_calls", "", [{"id": f"tool-{self.b_calls}",
                "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}])

    def _result(self, node, finish, content, tools):
        return {"node": node, "model": "mock-" + node, "finish_reason": finish,
                "content": content, "format_leak_detected": False, "tool_calls": tools,
                "raw_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "prompt_tokens": 10, "completion_tokens": 25,
                "reasoning_tokens": None, "latency_ms": 1,
                "request_sha256": "fake-request"}


class BridgeContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.id = "proof"
        self.provider = FakeProvider()

    def prep(self):
        return b.prepare(self.id, base=self.base, provider=self.provider)

    def scout(self):
        return b.scout_live(self.id, base=self.base, provider=self.provider)

    def test_complete_live_mocked_A_B_A_and_idempotent_resume(self):
        a = self.prep()
        self.assertEqual(a["status"], "WAITING_FOR_SCOUT")
        with b.BridgeRuntime(b.paths(self.id,self.base)["db"]) as rt:
            self.assertEqual(rt.snapshot(self.id)["tasks"][0]["state"], "WAITING")
        scout = self.scout()
        self.assertEqual(scout["status"], "READY_TO_RESUME")
        self.assertEqual(len(scout["evidence_ids"]), 2)
        result = b.resume_live(self.id, base=self.base, provider=self.provider)
        self.assertEqual(result["status"], "GEMMA_RESUMED")
        self.assertEqual(self.provider.a_calls, 2)
        self.assertEqual(self.provider.b_calls, 3)
        again = b.resume_live(self.id, base=self.base, provider=self.provider)
        self.assertEqual(again["content_sha256"], result["content_sha256"])
        self.assertEqual(self.provider.a_calls, 2)
        snap = b.inspect(self.id, base=self.base)
        self.assertEqual([x["artifact_type"] for x in snap["artifacts"]],
                         ["GemmaResumeOutput", "CandidateFinding"])
        self.assertEqual([x["kind"] for x in snap["outbox"]],
                         ["DISPATCH_SCOUT", "RESUME_GEMMA"])
        self.assertTrue(all(x["status"]=="DONE" for x in snap["outbox"]))

    def test_scout_recovers_verified_manifest_without_duplicate_B_inference(self):
        self.prep()
        self.scout()
        initial = self.provider.b_calls
        self.scout()
        self.assertEqual(self.provider.b_calls, initial)

    def test_no_resume_before_scout(self):
        self.prep()
        with self.assertRaises(TransitionError):
            b.resume_live(self.id, base=self.base, provider=self.provider)
        self.assertEqual(self.provider.a_calls, 1)

    def test_tampered_manifest_is_not_admitted_to_resumed_gemma(self):
        self.prep()
        self.scout()
        ps = b.paths(self.id, self.base)
        obj = b.read_json(ps["scout"])
        obj["source_evidence"][0]["exact_source_excerpt"] = "invented"
        b.write_json_atomic(ps["scout"], obj)
        with self.assertRaises(TransitionError):
            b.resume_live(self.id, base=self.base, provider=self.provider)
        self.assertEqual(self.provider.a_calls, 1)

    def test_no_ack_if_model_fails_after_resume_lease(self):
        self.prep()
        self.scout()
        with patch.object(self.provider, "call", side_effect=RuntimeError("simulated model failure")):
            with self.assertRaises(RuntimeError):
                b.resume_live(self.id, base=self.base, provider=self.provider)
        snap = b.inspect(self.id, base=self.base)
        self.assertEqual(snap["status"], "READY_TO_RESUME")
        self.assertEqual(snap["outbox"][1]["status"], "LEASED")
        self.assertFalse(any(a["artifact_type"] == "GemmaResumeOutput" for a in snap["artifacts"]))

    def test_atomic_ack_rejects_wrong_lease_and_preserves_wait(self):
        self.prep()
        scout = self.scout()
        with b.BridgeRuntime(b.paths(self.id,self.base)["db"]) as rt:
            rt.claim_resume(self.id, "test")
            payload = {"content": "source reviewed", "model": "fake", "node": "A",
                    "source_artifact_id": scout["source_artifact_id"],
                    "response_sha256": hashlib.sha256(b"source reviewed").hexdigest(),
                    "prompt_sha256": "fake", "evidence_ids": scout["evidence_ids"]}
            with self.assertRaises(TransitionError):
                rt.store_resume_and_ack(self.id, "wrong-token", payload)
            self.assertEqual(rt.snapshot(self.id)["status"], "READY_TO_RESUME")
            self.assertFalse(any(a["artifact_type"] == "GemmaResumeOutput"
                                 for a in rt.snapshot(self.id)["artifacts"]))

    def test_output_conflict_fails_closed_after_commit(self):
        self.prep()
        scout = self.scout()
        b.resume_live(self.id, base=self.base, provider=self.provider)
        with b.BridgeRuntime(b.paths(self.id,self.base)["db"]) as rt:
            fake = {"content": "another", "model": "fake", "node": "A",
                    "source_artifact_id": scout["source_artifact_id"],
                    "response_sha256": hashlib.sha256(b"another").hexdigest(),
                    "prompt_sha256": "fake", "evidence_ids": scout["evidence_ids"]}
            with self.assertRaises(TransitionError):
                rt.store_resume_and_ack(self.id, "anything", fake)


if __name__ == "__main__":
    unittest.main()
