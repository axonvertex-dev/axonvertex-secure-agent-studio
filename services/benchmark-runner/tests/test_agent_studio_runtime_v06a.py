"""0.6A: offline REST/API contract; no real inference or Docker."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import agent_studio_runtime_v06a as app
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner import continuous_remediation_worker_v05c as engine
from benchmark_runner.durable_runtime_v04 import artifact_digest

KEY = "test-api-key-used-only-in-offline-unit-tests-123456"


class FrontDoorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cfg = app.RuntimeConfig(self.root / "jobs.sqlite3", self.root / "runs",
                                     self.root / "locks", KEY)
        self.server = app.make_api(self.cfg, port=0)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.urlport = self.server.server_port

    def call(self, verb, path, data=None, *, auth=True, headers=None):
        h = {"Content-Type": "application/json"}
        if auth:
            h["Authorization"] = "Bearer " + KEY
        h.update(headers or {})
        body = None if data is None else (data if isinstance(data, bytes)
                                          else json.dumps(data).encode("utf-8"))
        conn = http.client.HTTPConnection("127.0.0.1", self.urlport, timeout=3)
        try:
            conn.request(verb, path, body, h)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw), dict(response.getheaders())
        finally:
            conn.close()

    def test_health_is_explicit_api_only_not_worker_liveness(self):
        status, obj, head = self.call("GET", "/health", auth=False)
        self.assertEqual(status, 200)
        self.assertEqual(obj["worker_process"], "separate")
        self.assertEqual(head["Cache-Control"], "no-store")

    def test_unauthorized_read_and_write_rejected(self):
        for verb, path, data in (("GET", "/v1/runs", None),
                                 ("POST", "/v1/runs", {"run_id": "r1"})):
            status, obj, _ = self.call(verb, path, data, auth=False)
            self.assertEqual(status, 401)
            self.assertEqual(obj["error"]["code"], "UNAUTHORIZED")
        with worker.Queue(self.cfg.queue_db) as queue:
            self.assertEqual(queue.pending(), [])

    def test_submit_once_and_duplicate_conflict(self):
        status, result, _ = self.call("POST", "/v1/runs", {"run_id": "test-0001"})
        self.assertEqual(status, 201)
        self.assertEqual(result["job"]["phase"], "PREPARE")
        self.assertEqual(result["bridge_status"], "NOT_PREPARED")
        status, result, _ = self.call("POST", "/v1/runs", {"run_id": "test-0001"})
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "RUN_ALREADY_EXISTS")
        status, result, _ = self.call("GET", "/v1/runs")
        self.assertEqual([r["run_id"] for r in result["runs"]], ["test-0001"])

    def test_reject_extra_payload_and_duplicate_json_keys(self):
        for body in ({"run_id": "r1", "command": "rm -rf /"},
                     {"run_id": "../escape"}, ["r1"], {"run_id": 5},
                     b'{"run_id":"r1","run_id":"r2"}'):
            status, _, _ = self.call("POST", "/v1/runs", body)
            self.assertEqual(status, 400)
        with worker.Queue(self.cfg.queue_db) as queue:
            self.assertEqual(queue.pending(), [])

    def test_large_body_rejected(self):
        status, obj, _ = self.call("POST", "/v1/runs", b"x" * 4097)
        self.assertEqual(status, 413)
        self.assertEqual(obj["error"]["code"], "REQUEST_TOO_LARGE")

    def test_missing_and_invalid_run_id_fail_closed(self):
        status, obj, _ = self.call("GET", "/v1/runs/missing")
        self.assertEqual(status, 404)
        self.assertEqual(obj["error"]["code"], "UNKNOWN_RUN_OR_STATE")
        for path in ("/v1/runs/%2e%2e", "/v1/runs/..", "/v1/runs/test-0001/patch",
                     "/v1/runs/test-0001/approve"):
            status, _, _ = self.call("GET", path)
            self.assertIn(status, (400, 404))
        status, _, _ = self.call("POST", "/v1/runs/abc/approve", {"yes": True})
        self.assertEqual(status, 404)

    def test_event_cursors_and_metadata_are_payload_free(self):
        with worker.Queue(self.cfg.queue_db) as queue:
            queue.submit("proof")
            queue._event("proof", "TEST_EVENT", "REDACTED", "PREPARE",
                         {"private_secret": "DO_NOT_EXPOSE"})
        status, obj, _ = self.call("GET", "/v1/runs/proof/events?limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(obj["worker_events"]), 1)
        self.assertNotIn("private_secret", json.dumps(obj))
        cursor = obj["next_worker_after"]
        status, obj, _ = self.call("GET", f"/v1/runs/proof/events?worker_after={cursor}&limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(obj["worker_events"][0]["kind"], "TEST_EVENT")
        for q in ("?limit=1000", "?limit=-1", "?limit=invalid", "?runtime_after=99999999999999999999999",
                  "?other=1", "?limit=1&limit=2"):
            status, _, _ = self.call("GET", "/v1/runs/proof/events" + q)
            self.assertEqual(status, 400)

    def test_metadata_preserves_prior_run_and_redacts_payloads(self):
        with worker.Queue(self.cfg.queue_db) as queue:
            queue.submit("proof")
            queue.db.execute("UPDATE jobs SET phase='WAITING_FOR_SCOUT',status='QUEUED' WHERE run_id='proof'")
        p = bridge.paths("proof", self.cfg.run_base)
        p["folder"].mkdir(parents=True)
        with engine.RemediationRuntime(p["db"]) as rt:
            rt.start("proof", "ctx-proof")
        status, result, _ = self.call("GET", "/v1/runs/proof")
        self.assertEqual(status, 200)
        self.assertEqual(result["bridge_status"], "WAITING_FOR_SCOUT")
        self.assertIn("outbox", result)
        self.assertIn("tasks", result)
        self.assertNotIn("context_snapshot_id", json.dumps(result))
        status, result, _ = self.call("GET", "/v1/runs/proof/events")
        self.assertEqual(status, 200)
        self.assertTrue(result["runtime_events"])
        self.assertNotIn("payload", json.dumps(result))

    def test_payload_metadata_hash_integrity_checked(self):
        with worker.Queue(self.cfg.queue_db) as queue:
            queue.submit("proof")
            queue.db.execute("UPDATE jobs SET phase='WAITING_FOR_SCOUT' WHERE run_id='proof'")
        p = bridge.paths("proof", self.cfg.run_base)
        p["folder"].mkdir(parents=True)
        with engine.RemediationRuntime(p["db"]) as rt:
            rt.start("proof", "ctx-proof")
            rt.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)", (
                "proof:test", "proof", "proof:root", "CandidateChange", "deadbeef",
                json.dumps({"private_secret": "DO_NOT_EXPOSE"}), "2026-09-19T00:00:00Z"))
        status, result, _ = self.call("GET", "/v1/runs/proof")
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "INTEGRITY_FAILURE")
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(result))

    def test_uses_existing_worker_without_new_inference_backend(self):
        with patch.object(engine, "serve", return_value=[]) as serve:
            rc = app.main(["serve", "--stop-when-idle"], cfg=self.cfg)
        self.assertEqual(rc, 0)
        self.assertTrue(serve.call_args.kwargs["stop_when_idle"])
        self.assertEqual(serve.call_args.kwargs["base"], self.cfg.run_base)

    def test_reject_missing_reused_api_key(self):
        with self.assertRaises(RuntimeError):
            app.make_api(app.RuntimeConfig(api_key="short"), port=0)
        with patch("benchmark_runner.agent_studio_runtime_v06a.os.environ", {
            "AGENT_STUDIO_API_KEY": KEY, "GEMMA_GATEWAY_WORKFLOW_KEY": KEY}):
            with patch("benchmark_runner.agent_studio_runtime_v06a.Path.cwd", return_value=self.root):
                with self.assertRaises(RuntimeError):
                    app.api_key_from_environment()


if __name__ == "__main__":
    unittest.main()
