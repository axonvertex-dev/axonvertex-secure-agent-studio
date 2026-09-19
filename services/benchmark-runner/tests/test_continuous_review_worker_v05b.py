"""2E-0.5B: deterministic Node C review contracts; no external model calls."""
import json
import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import continuous_worker_v05a as a
from benchmark_runner import continuous_review_worker_v05b as w
from benchmark_runner import durable_live_bridge_v04b as b
from benchmark_runner import agentic_workflow_v03 as old
from benchmark_runner.durable_runtime_v04 import TransitionError


class FakeProvider:
    def __init__(self, counts, *, failure=False, contradiction=False, invented=False):
        self.counts, self.failure, self.contradiction, self.invented = counts, failure, contradiction, invented
        self.nodes = {x: {"model": "fake-" + x} for x in "ABC"}

    def close(self):
        pass

    def call(self, node, messages, *, tools=None, schema=None):
        self.counts[node] += 1
        turn = self.counts[node]
        if node == "A":
            content = "Read-only plan" if turn == 1 else "app.py concatenates SQL; web.py passes request.args; external deployment unknown."
            finish, calls = "stop", []
        elif node == "B":
            if turn == 1:
                name, args = "terminal", {"command": "ls"}
            elif turn == 2:
                name, args = "terminal", {"command": "cat app.py"}
            else:
                name, args = "submit_vulnerable_files", {"file_paths": ["app.py"], "reason": "source evidence"}
            content, finish = "", "tool_calls"
            calls = [{"id": "b" + str(turn), "type": "function", "function":
                      {"name": name, "arguments": json.dumps(args)}}]
        elif node == "C":
            if schema != old.REVIEW_SCHEMA or tools is not None:
                raise AssertionError("Node C must receive strict structured schema, no tools")
            if self.failure:
                raise RuntimeError("private remote failure bearer secret")
            # Derive exact accepted IDs from independent canonical source evidence in prompt.
            data = messages[1]["content"]
            ids = list(dict.fromkeys(__import__("re").findall(r'ev-git-[a-f0-9]{20}', data)))
            if len(ids) != 2:
                raise AssertionError("Expected exactly two canonical evidence IDs")
            review = {
                "source_pattern": "not_observed" if self.contradiction else "unsafe_sql_concatenation",
                "caller_path": "request_args_observed",
                "external_exploitability": "insufficient_evidence",
                "supporting_evidence_ids": ids + (["ev-invented"] if self.invented else []),
                "missing_evidence": ["deployed network route not verified"],
                "review_summary": "Source-level CWE-89 pattern; deployment remains unverified.",
            }
            content, finish, calls = json.dumps(review), "stop", []
        else:
            raise AssertionError("Invalid node")
        return {"node": node, "model": self.nodes[node]["model"], "content": content,
                "finish_reason": finish, "tool_calls": calls, "format_leak_detected": False,
                "prompt_tokens": 40, "completion_tokens": 100, "reasoning_tokens": None,
                "raw_content_sha256": old.sha(content), "latency_ms": 1, "request_sha256": "fake"}


class ReviewContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "runs"
        self.locks = self.root / "locks"
        self.queuefile = self.root / "jobs.sqlite3"
        self.q = a.Queue(self.queuefile)
        self.addCleanup(self.q.close)
        self.calls = {"A": 0, "B": 0, "C": 0}

    def provider(self, _id):
        return FakeProvider(self.calls)

    def review_provider(self, _id):
        return FakeProvider(self.calls)

    def step(self, **kw):
        return w.advance(self.q, "proof", base=self.base, locks=self.locks,
                         provider_factory=self.provider,
                         review_provider_factory=kw.get("review_factory", self.review_provider))

    def handoff(self):
        self.q.submit("proof")
        for _ in range(3):
            self.step()
        self.assertEqual(self.q.inspect("proof")["job"]["status"], "HANDOFF_COMPLETED")

    def snapshot(self):
        with w.ReviewRuntime(b.paths("proof", self.base)["db"]) as rt:
            return rt.snapshot("proof")

    def test_submit_once_auto_a_b_a_c(self):
        self.q.submit("proof")
        rows = w.serve(self.q, base=self.base, locks=self.locks, stop_when_idle=True,
                       provider_factory=self.provider,
                       review_provider_factory=self.review_provider)
        self.assertEqual([x.get("phase") for x in rows],
                         ["WAITING_FOR_SCOUT", "READY_TO_RESUME", "GEMMA_RESUMED", "REVIEW_PENDING", "REVIEW_COMPLETED"])
        self.assertEqual(self.calls, {"A": 2, "B": 3, "C": 1})
        snap = self.snapshot()
        self.assertEqual(snap["status"], "REVIEW_COMPLETED")
        self.assertEqual(next(x for x in snap["tasks"] if x["task_id"].endswith(":root"))["state"], "READY")
        self.assertEqual(next(x for x in snap["artifacts"] if x["artifact_type"] == "SecurityReview")
                         ["payload"]["accepted"], True)
        self.assertEqual(self.step()["status"], "REVIEW_COMPLETED")
        self.assertEqual(self.calls, {"A": 2, "B": 3, "C": 1})

    def test_persist_review_schedule_survives_new_worker(self):
        self.handoff()
        self.assertEqual(self.step()["phase"], "REVIEW_PENDING")
        self.q.close()
        self.q = a.Queue(self.queuefile)
        self.assertEqual(self.step()["status"], "REVIEW_COMPLETED")
        self.assertEqual(self.calls["C"], 1)

    def test_crash_between_review_outbox_and_queue_state_reconciles(self):
        self.handoff()
        prompt, _, _, _ = w.review_context("proof", base=self.base)
        with w.ReviewRuntime(b.paths("proof", self.base)["db"]) as rt:
            rt.schedule("proof", expected_input_sha256=old.sha(prompt))
        # Emulates crash after durable task commit but before queue update.
        self.assertEqual(self.q.inspect("proof")["job"]["status"], "HANDOFF_COMPLETED")
        self.assertEqual(self.step()["phase"], "REVIEW_PENDING")
        self.assertEqual(self.step()["status"], "REVIEW_COMPLETED")
        self.assertEqual(self.calls["C"], 1)

    def test_crash_after_review_commit_before_worker_receipt_skips_inference(self):
        self.handoff()
        self.step()  # schedule
        prompt, ids, source, manifest = w.review_context("proof", base=self.base)
        with w.ReviewRuntime(b.paths("proof", self.base)["db"]) as rt:
            token = rt.claim("proof")["lease_token"]
        result = self.review_provider("proof").call("C", [{"role": "system", "content": "JSON"},
                                                      {"role": "user", "content": prompt}], schema=old.REVIEW_SCHEMA)
        review = json.loads(result["content"])
        self.assertEqual(old.validate_review(review, manifest["source_evidence"], manifest["observations"]), [])
        with w.ReviewRuntime(b.paths("proof", self.base)["db"]) as rt:
            rt.commit_review("proof", token, {"review": review, "accepted": True, "validation_errors": [],
                 "response_sha256": old.sha(result["content"]), "prompt_sha256": old.sha(prompt),
                 "source_artifact_id": source, "evidence_ids": ids, "model": result["model"], "node": "C"})
        self.assertEqual(self.step()["status"], "REVIEW_COMPLETED")
        self.assertEqual(self.calls["C"], 1)

    def test_contradictory_review_quarantined_no_remediation(self):
        self.handoff()
        self.step()
        result = self.step(review_factory=lambda _: FakeProvider(self.calls, contradiction=True))
        self.assertEqual(result["status"], "REVIEW_QUARANTINED")
        snap = self.snapshot()
        self.assertEqual(snap["status"], "REVIEW_QUARANTINED")
        self.assertEqual(next(x for x in snap["tasks"] if x["task_id"].endswith(":root"))["state"], "BLOCKED")
        self.assertNotIn("VERIFIED_CANDIDATE_AWAITING_APPROVAL", json.dumps(snap))

    def test_invented_evidence_quarantined(self):
        self.handoff()
        self.step()
        self.assertEqual(self.step(review_factory=lambda _: FakeProvider(self.calls, invented=True))["status"],
                         "REVIEW_QUARANTINED")

    def test_transient_failure_redacted_and_bounded(self):
        self.handoff()
        self.step()
        for _ in range(a.MAX_ATTEMPTS):
            result = self.step(review_factory=lambda _: FakeProvider(self.calls, failure=True))
        self.assertEqual(result["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.calls["C"], a.MAX_ATTEMPTS)
        self.assertNotIn("private remote failure", self.queuefile.read_bytes().decode("utf8", "ignore"))
        self.assertNotIn("private remote failure", b.paths("proof", self.base)["db"].read_bytes().decode("utf8", "ignore"))
        self.assertEqual(self.snapshot()["status"], "WAITING_FOR_REVIEW")

    def test_lease_busy_does_not_invoke_second_model(self):
        self.handoff()
        self.step()
        with w.ReviewRuntime(b.paths("proof", self.base)["db"]) as rt:
            self.assertIsNotNone(rt.claim("proof"))
        self.assertEqual(self.step()["status"], "REVIEW_LEASE_BUSY")
        self.assertEqual(self.calls["C"], 0)

    def test_original_fixture_tamper_fails_closed_before_review(self):
        self.handoff()
        self.step()
        (b.paths("proof", self.base)["repo"] / "app.py").write_text("# changed", encoding="utf8")
        self.assertEqual(self.step()["status"], "NEEDS_OPERATOR_RECOVERY")
        self.assertEqual(self.calls["C"], 0)

    def test_actual_subprocess_exit_37_and_recovery(self):
        # Recreate a v05a finished run in the CLI's normal relative paths.
        base = self.root / b.BASE
        qfile = self.root / a.BASE / "jobs.sqlite3"
        with a.Queue(qfile) as q:
            q.submit("restarted")
            for _ in range(3):
                a.advance(q, "restarted", base=base, locks=self.root / a.BASE / "locks",
                          provider_factory=self.provider)
            self.assertEqual(q.inspect("restarted")["job"]["status"], a.HANDOFF_COMPLETE)
        script = Path(w.__file__).resolve()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(script.parents[1])
        p = subprocess.run([sys.executable, str(script), "schedule-review", "--run-id", "restarted",
                            "--crash-after-review-schedule"], cwd=self.root,
                           env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 37, p.stderr)
        with a.Queue(qfile) as fresh:
            self.assertEqual(fresh.inspect("restarted")["job"]["phase"], w.REVIEW_PENDING)
            self.assertEqual(w.advance(fresh, "restarted", base=base,
                            locks=self.root / a.BASE / "locks",
                            review_provider_factory=self.review_provider)["status"], w.REVIEW_COMPLETED)
        self.assertEqual(self.calls["C"], 1)

    def test_second_schedule_cannot_change_input_digest(self):
        self.handoff()
        self.step()
        with w.ReviewRuntime(b.paths("proof", self.base)["db"]) as rt:
            with self.assertRaises(TransitionError):
                rt.schedule("proof", expected_input_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
