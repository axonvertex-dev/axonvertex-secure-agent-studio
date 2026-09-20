"""2E-0.7A: isolated read-only operator projection; no inference, Docker or Git mutation."""
import hashlib
import json
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from benchmark_runner import agentic_workflow_v03 as fixture
from benchmark_runner import continuous_remediation_worker_v05c as remediation
from benchmark_runner import operator_review_v07a as view
from benchmark_runner.durable_runtime_v04 import TransitionError, artifact_digest

RUN = "review-v07a-unit"


@contextmanager
def write_db(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class OperatorReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.queue = self.base / "jobs.sqlite3"
        self.run_base = self.base / "durable-live"
        self.folder = self.run_base / RUN
        self.folder.mkdir(parents=True)
        self.runtime = self.folder / "runtime.sqlite3"
        with write_db(self.queue) as db:
            db.executescript("""
            CREATE TABLE jobs(run_id TEXT,status TEXT,phase TEXT,attempts INTEGER,
                              last_error_type TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE worker_events(seq INTEGER PRIMARY KEY,run_id TEXT,kind TEXT,
              reason_code TEXT,phase TEXT,created_at TEXT);
            """)
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                       (RUN,"VERIFIED_CANDIDATE_AWAITING_APPROVAL",
                        "VERIFIED_CANDIDATE_AWAITING_APPROVAL",0,None,"2026-09-19T00:00:00Z",
                        "2026-09-19T00:10:00Z"))
            db.execute("INSERT INTO worker_events VALUES(?,?,?,?,?,?)",
                       (1,RUN,"TASK_SUBMITTED","USER_SUBMITTED","PREPARE","2026-09-19T00:00:00Z"))
        with write_db(self.runtime) as db:
            db.executescript("""
            CREATE TABLE runs(run_id TEXT,status TEXT);
            CREATE TABLE tasks(task_id TEXT,run_id TEXT,owner TEXT,purpose TEXT,
              state TEXT,dependency_task_id TEXT);
            CREATE TABLE outbox(job_id TEXT,run_id TEXT,kind TEXT,status TEXT,attempts INTEGER);
            CREATE TABLE artifacts(artifact_id TEXT,run_id TEXT,artifact_type TEXT,
              producer_task_id TEXT,content_sha256 TEXT,payload_json TEXT,created_at TEXT);
            CREATE TABLE events(seq INTEGER PRIMARY KEY,run_id TEXT,event_type TEXT,
              actor TEXT,reason_code TEXT,task_id TEXT,created_at TEXT);
            """)
            db.execute("INSERT INTO runs VALUES (?,?)", (RUN,remediation.APPROVAL_PENDING))
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                       (RUN+":root",RUN,"AgentRuntime/Gemma","Resume","AWAITING_APPROVAL",None))
            db.execute("INSERT INTO outbox VALUES(?,?,?,?,?)",
                       (RUN+":dispatch-verification",RUN,"DISPATCH_VERIFICATION","DONE",1))
            db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                       (1,RUN,"APPROVAL_GATE","Policy","HUMAN_APPROVAL_REQUIRED",RUN+":root",
                        "2026-09-19T00:10:00Z"))
        self.source = fixture.APP_VULNERABLE + "# candidate\n"
        self.delta = "".join(__import__('difflib').unified_diff(
            fixture.APP_VULNERABLE.splitlines(keepends=True),
            self.source.splitlines(keepends=True), fromfile="a/app.py", tofile="b/app.py"))
        self.review = {"accepted": True, "validation_errors": [],"node":"C", "model":"foundation",
            "evidence_ids":["e-app","e-web"],
            "review": {"source_pattern":"unsafe_sql_concatenation",
                "caller_path":"request_args_observed", "external_exploitability":"insufficient_evidence",
                "supporting_evidence_ids":["e-app","e-web"], "missing_evidence":["deployment"],
                "review_summary":"MODEL_UNTRUSTED_TEXT"}}
        self.candidate = {"source":self.source,"source_sha256":fixture.sha(self.source),
           "diff_sha256":fixture.sha(self.delta),"fixture_commit":"fixture-commit",
           "review_artifact_id":RUN+":foundation-review", "evidence_ids":["e-app","e-web"],
           "node":"A", "model":"gemma"}
        self.verify = {"source_artifact_id": RUN+":candidate-change",
            "candidate_sha256":self.candidate["source_sha256"],
            "baseline":remediation.BASELINE_EXPECTED,"candidate":remediation.CANDIDATE_EXPECTED,
            "passed":True,"original_fixture_unchanged":True,"sandbox_image":"python:3.11-alpine"}
        self.save("SecurityReview",self.review)
        self.save("CandidateChange",self.candidate)
        self.save("VerificationResult",self.verify)

    def save(self, kind, payload):
        ids={"SecurityReview":"foundation-review", "CandidateChange":"candidate-change",
             "VerificationResult":"verification-result"}
        with write_db(self.runtime) as db:
            db.execute("DELETE FROM artifacts WHERE artifact_type=?", (kind,))
            db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
                       (RUN+":"+ids[kind], RUN,kind,RUN+":root",artifact_digest(payload),
                        json.dumps(payload),"2026-09-19T00:09:00Z"))

    def read(self, **kwargs):
        return view.project(RUN,queue_db=self.queue,run_base=self.run_base,**kwargs)

    def test_full_projection_is_evidence_complete_and_redacted(self):
        result=self.read()
        self.assertEqual(result["runtime_status"], remediation.APPROVAL_PENDING)
        self.assertTrue(result["verification_result"]["passed"])
        self.assertTrue(result["verification_result"]["original_fixture_unchanged"])
        self.assertEqual(len(result["artifacts"]),3)
        self.assertEqual([e["ledger"] for e in result["timeline"]],["worker","runtime"])
        self.assertEqual(result["security_review"]["review"]["external_exploitability"],
                         "insufficient_evidence")
        self.assertNotIn(self.source, json.dumps(result))
        self.assertNotIn("MODEL_UNTRUSTED_TEXT", json.dumps(result))
        self.assertNotIn("payload_json",json.dumps(result))

    def test_explicit_include_content_reveals_only_review_summary_source_diff(self):
        result=self.read(include_content=True)
        self.assertEqual(result["candidate_change"]["source"], self.source)
        self.assertEqual(result["candidate_change"]["unified_diff"],self.delta)
        self.assertEqual(result["security_review"]["review"]["review_summary"],
                         "MODEL_UNTRUSTED_TEXT")

    def test_read_only_proof_no_database_file_changes(self):
        files=[self.queue,self.runtime]
        before=[hashlib.sha256(f.read_bytes()).hexdigest() for f in files]
        self.read()
        self.read(include_content=True)
        self.assertEqual(before,[hashlib.sha256(f.read_bytes()).hexdigest() for f in files])

    def test_tampered_review_refuses_complete_projection(self):
        with write_db(self.runtime) as db:
            db.execute("UPDATE artifacts SET payload_json=? WHERE artifact_type='SecurityReview'",
                       (json.dumps({"secret":"UNTRUSTED"}),))
        with self.assertRaisesRegex(TransitionError,"integrity mismatch"):
            self.read()

    def test_tampered_candidate_source_and_diff_refuse(self):
        self.candidate["source"]="modified!"
        self.save("CandidateChange",self.candidate)
        with self.assertRaisesRegex(TransitionError,"source identity mismatch"):
            self.read()
        self.candidate["source"]=self.source
        self.candidate["diff_sha256"]="0"*64
        self.save("CandidateChange",self.candidate)
        with self.assertRaisesRegex(TransitionError,"diff identity mismatch"):
            self.read()

    def test_verification_candidate_mismatch_refuses(self):
        self.verify["candidate_sha256"]="0"*64
        self.save("VerificationResult",self.verify)
        with self.assertRaisesRegex(TransitionError,"candidate identity mismatch"):
            self.read()

    def test_inconsistent_verification_refuses(self):
        self.verify["passed"]=False
        self.save("VerificationResult",self.verify)
        with self.assertRaisesRegex(TransitionError,"receipt inconsistent"):
            self.read()

    def test_missing_verification_in_approval_state_refuses(self):
        with write_db(self.runtime) as db:
            db.execute("DELETE FROM artifacts WHERE artifact_type='VerificationResult'")
        with self.assertRaisesRegex(TransitionError,"Inconsistent approval boundary"):
            self.read()

    def test_missing_run_does_not_create_ledger(self):
        other=self.base/"nonexistent.sqlite3"
        with self.assertRaises(TransitionError):
            view.project("missing",queue_db=other,run_base=self.run_base)
        self.assertFalse(other.exists())
        with self.assertRaises(ValueError):
            view.project("../bad",queue_db=self.queue,run_base=self.run_base)

    def test_gateway_receipts_allowlist_never_echoes_prompts(self):
        p=self.folder/"gateway-calls.jsonl"
        p.write_text(json.dumps({"status":200,"lane":"workflow",
          "transport":"gemma_gateway_loopback","inference_ms":18510,
          "messages":"SENSITIVE_PROMPT","authorization":"SECRET"})+"\n")
        result=self.read()
        self.assertEqual(result["gateway_receipts"]["call_count"],1)
        self.assertEqual(result["gateway_receipts"]["entries"][0]["status"],200)
        self.assertNotIn("SENSITIVE_PROMPT",json.dumps(result))
        self.assertNotIn("SECRET",json.dumps(result))
        self.assertEqual(result["gateway_receipts"]["integrity"],
                         "not_cryptographically_authenticated")

    def test_reject_symlinked_receipts(self):
        secret=self.base/"private"
        secret.write_text("private")
        (self.folder/"gateway-calls.jsonl").symlink_to(secret)
        with self.assertRaisesRegex(TransitionError,"receipt file invalid"):
            self.read()

    def test_preparation_does_not_require_durable_db_or_create_one(self):
        with write_db(self.queue) as db:
            db.execute("UPDATE jobs SET phase='PREPARE',status='WORKING' WHERE run_id=?",(RUN,))
        self.runtime.unlink()
        result=self.read()
        self.assertEqual(result["runtime_status"],"NOT_PREPARED")
        self.assertEqual(result["artifacts"],[])
        self.assertFalse(self.runtime.exists())


if __name__ == "__main__":
    unittest.main()
