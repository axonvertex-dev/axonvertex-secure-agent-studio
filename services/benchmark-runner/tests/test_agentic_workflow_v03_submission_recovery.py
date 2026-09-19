"""Scoped Antares submission rejection and recovery, with no live inference or Docker."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import agentic_workflow_v03 as w
from test_agentic_workflow_v03 import FakeProvider, fake_sandbox


class RetryProvider(FakeProvider):
    def __init__(self, eventually_valid=True):
        super().__init__()
        self.eventually_valid = eventually_valid

    def call(self, node, messages, *, tools=None, schema=None):
        if node == "B" and self.b >= 3:
            self.b = 2  # Replay the submission contract; no extra privilege.
        result = super().call(node, messages, tools=tools, schema=schema)
        if node == "B" and self.b >= 3:
            t = result["tool_calls"][0]
            t["id"] = "retry-" + str(len(messages))
            if self.eventually_valid and len(messages) > 7:
                submitted = ["app.py"]
            else:
                submitted = ["web.py"]
            t["function"]["arguments"] = json.dumps({"file_paths": submitted})
        return result


class SubmissionRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_results = w.RESULTS
        w.RESULTS = Path(self.tmp.name) / "results"

    def tearDown(self):
        w.RESULTS = self.old_results
        self.tmp.cleanup()

    def test_rejected_wrong_candidate_can_be_corrected(self):
        code, out = w.workflow("recover-scout", RetryProvider(True), verify=fake_sandbox)
        self.assertEqual(code, 0)
        trace = json.loads((out / "trace.json").read_text())
        self.assertEqual(trace["status"], "verified_candidate_awaiting_approval")
        events = [json.loads(s) for s in (out / "events.jsonl").read_text().splitlines()]
        self.assertTrue(any(e["event_type"] == "CANDIDATE_REJECTED" for e in events))
        self.assertTrue(any(e["event_type"] == "CANDIDATE_SUBMITTED" for e in events))
        self.assertEqual((out / "fixture_repo/app.py").read_text(), w.APP_VULNERABLE)

    def test_repeated_wrong_candidate_fails_closed(self):
        code, out = w.workflow("reject-scout", RetryProvider(False), verify=fake_sandbox)
        self.assertEqual(code, 1)
        trace = json.loads((out / "trace.json").read_text())
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["failure"]["last_scout_submission_rejection"],
                         "KNOWN_POSITIVE_CANDIDATE_MISSING")
        events = [json.loads(s) for s in (out / "events.jsonl").read_text().splitlines()]
        self.assertFalse(any(e["event_type"] == "CANDIDATE_SUBMITTED" for e in events))
        self.assertEqual((out / "fixture_repo/app.py").read_text(), w.APP_VULNERABLE)
