"""Contract tests: checkpoint 2E-0.4D2. No live inference or network access."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import durable_gateway_bridge_v04d2 as d
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner.durable_runtime_v04 import TransitionError


class BOnly:
    nodes = {"B": {"model": "fake-antares"}}

    def __init__(self):
        self.calls = []

    def close(self):
        pass

    def call(self, node, messages, *, tools=None, schema=None):
        self.calls.append(node)
        if node != "B":
            raise AssertionError("Direct Gemma call detected")
        turn = len(self.calls)
        if turn == 1:
            name, args = "terminal", {"command": "ls"}
        elif turn == 2:
            name, args = "terminal", {"command": "cat app.py"}
        else:
            name, args = "submit_vulnerable_files", {"file_paths": ["app.py"], "reason": "Observed concatenation"}
        return {"node": "B", "model": "fake-antares", "finish_reason": "tool_calls",
                "content": "", "format_leak_detected": False,
                "tool_calls": [{"id": f"t{turn}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
                "raw_content_sha256": d.old.sha(""), "prompt_tokens": 12,
                "completion_tokens": 22, "reasoning_tokens": None, "latency_ms": 1,
                "request_sha256": "mock-request"}


class GatewayContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.requests = []
        self.b_provider = BOnly()
        self.failure = None

        def handler(request):
            self.requests.append(request)
            if self.failure == "network":
                raise httpx.ConnectError("upstream private details", request=request)
            if self.failure == "denied":
                return httpx.Response(401, json={"error": {"secret": "not for logs"}})
            incoming = json.loads(request.content)
            self.assertEqual(incoming["model"], "fake-gemma")
            self.assertEqual(request.headers["x-axonvertex-lane"], "workflow")
            self.assertEqual(request.headers["x-axonvertex-context-id"], "workflow:proof")
            self.assertEqual(request.headers["authorization"], "Bearer " + "a" * 48)
            self.assertNotIn("tools", incoming)
            self.assertFalse(incoming["chat_template_kwargs"]["enable_thinking"])
            response = "Plan: inspect app.py" if len(self.requests) == 1 else "app.py concatenates SQL; web.py passes request.args; public deployment unverified."
            return httpx.Response(200, json={"model": "fake-gemma", "choices": [{"finish_reason": "stop", "message": {"content": response}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40}},
                headers={"X-Axonvertex-Queue-Ms": "3", "X-Axonvertex-Inference-Ms": "21"})

        self.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(self.client.close)
        self.config = {"GEMMA_MODEL": "fake-gemma", "GEMMA_GATEWAY_WORKFLOW_KEY": "a" * 48,
                       "GEMMA_GATEWAY_URL": d.GATEWAY_ROOT}

    def provider(self):
        return d.GatewayProvider("proof", config=self.config, node_provider=self.b_provider,
                                 gateway_http=self.client, base=self.base)

    def test_full_A_gateway_B_direct_A_gateway_durable_commit(self):
        p = self.provider()
        prepared = b.prepare("proof", base=self.base, provider=p)
        self.assertEqual(prepared["status"], "WAITING_FOR_SCOUT")
        self.assertEqual(b.scout_live("proof", base=self.base, provider=p)["status"], "READY_TO_RESUME")
        result = b.resume_live("proof", base=self.base, provider=p)
        self.assertEqual(result["status"], "GEMMA_RESUMED")
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.b_provider.calls, ["B", "B", "B"])
        b.resume_live("proof", base=self.base, provider=p)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual([j["status"] for j in b.inspect("proof", base=self.base)["outbox"]], ["DONE", "DONE"])
        audit = (b.paths("proof", self.base)["folder"] / "gateway-calls.jsonl").read_text()
        entries = [json.loads(v) for v in audit.splitlines()]
        self.assertEqual([v["status"] for v in entries], [200, 200])
        self.assertEqual(len({v["task_id"] for v in entries}), 2)
        self.assertTrue(all(v["lane"] == "workflow" for v in entries))
        self.assertNotIn("Bearer", audit)
        self.assertNotIn("Plan: inspect app.py", audit)
        self.assertNotIn("a" * 48, audit)

    def test_gateway_down_fails_closed_before_first_delegation(self):
        self.failure = "network"
        with self.assertRaisesRegex(RuntimeError, "fallback prohibited"):
            b.prepare("proof", base=self.base, provider=self.provider())
        self.assertEqual(self.b_provider.calls, [])

    def test_gateway_denied_fails_closed_without_disclosing_remote_body(self):
        self.failure = "denied"
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as cm:
            b.prepare("proof", base=self.base, provider=self.provider())
        self.assertNotIn("not for logs", str(cm.exception))
        audit = (b.paths("proof", self.base)["folder"] / "gateway-calls.jsonl").read_text()
        self.assertNotIn("not for logs", audit)
        self.assertNotIn("a" * 48, audit)

    def test_gateway_fails_after_scout_result_without_ack(self):
        p = self.provider()
        b.prepare("proof", base=self.base, provider=p)
        b.scout_live("proof", base=self.base, provider=p)
        self.failure = "network"
        with self.assertRaisesRegex(RuntimeError, "fallback prohibited"):
            b.resume_live("proof", base=self.base, provider=p)
        snapshot = b.inspect("proof", base=self.base)
        self.assertEqual(snapshot["status"], "READY_TO_RESUME")
        self.assertFalse(any(a["artifact_type"] == "GemmaResumeOutput" for a in snapshot["artifacts"]))
        self.assertEqual(self.b_provider.calls, ["B", "B", "B"])

    def test_missing_key_fails_before_network(self):
        config = {"GEMMA_MODEL": "fake-gemma"}
        with self.assertRaisesRegex(RuntimeError, "credential"):
            d.GatewayProvider("proof", config=config, node_provider=self.b_provider, gateway_http=self.client, base=self.base)
        self.assertEqual(self.requests, [])

    def test_invalid_gateway_url_fails_closed(self):
        config = {**self.config, "GEMMA_GATEWAY_URL": "http://100.82.103.57:11433"}
        with self.assertRaisesRegex(RuntimeError, "local"):
            d.GatewayProvider("proof", config=config, node_provider=self.b_provider, gateway_http=self.client, base=self.base)

    def test_unsupported_gemma_tools_and_nodeC_rejected(self):
        p = self.provider()
        with self.assertRaisesRegex(RuntimeError, "prohibits"):
            p.call("A", [{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
        with self.assertRaisesRegex(RuntimeError, "Only Gemma/A"):
            p.call("C", [{"role": "user", "content": "hi"}])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
