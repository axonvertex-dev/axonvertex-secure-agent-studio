"""Offline contract tests. Never connect to any inference endpoint or execute Docker."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from benchmark_runner import agentic_workflow_v03 as w


class FakeProvider:
    def __init__(self, bad_review=False, bad_candidate=False):
        self.nodes = {n: {'model': {'A': 'gemma-4-12b-it-qat', 'B': 'antares-1b',
                                   'C': 'foundation-sec-8b-reasoning'}[n]}
                      for n in 'ABC'}
        self.b = 0
        self.a = 0
        self.bad_review = bad_review
        self.bad_candidate = bad_candidate

    def call(self, node, messages, *, tools=None, schema=None):
        result = {
            'node': node, 'model': self.nodes[node]['model'],
            'finish_reason': 'stop', 'content': 'Acknowledged. Missing deployed route proof.',
            'format_leak_detected': False, 'tool_calls': [],
            'raw_content_sha256': w.sha('synthetic'), 'prompt_tokens': 200,
            'completion_tokens': 80, 'reasoning_tokens': None, 'latency_ms': 1,
            'request_sha256': w.sha('fake request')
        }
        if node == 'B':
            self.b += 1
            result['finish_reason'] = 'tool_calls'
            if self.b == 1:
                result['tool_calls'] = [{'id': 't1', 'function': {'name': 'terminal',
                                           'arguments': json.dumps({'command': 'rg -n username app.py'})}}]
            elif self.b == 2:
                result['tool_calls'] = [{'id': 't2', 'function': {'name': 'terminal',
                                           'arguments': json.dumps({'command': 'cat app.py'})}}]
            elif self.b == 3:
                result['tool_calls'] = [{'id': 't3', 'function': {'name': 'submit_vulnerable_files',
                                           'arguments': json.dumps({'file_paths': ['app.py'],
                                                                    'reason': 'unsafe SQL string'})}}]
            else:
                raise AssertionError('unexpected Antares call')
        elif node == 'C':
            ids = []
            # Exact IDs are available in canonical evidence serialized to the C review prompt.
            prompt = messages[-1]['content']
            ids = sorted(set(__import__('re').findall(r'ev-git-[a-f0-9]{20}', prompt)))
            result['content'] = json.dumps({
                'source_pattern': 'not_observed' if self.bad_review else 'unsafe_sql_concatenation',
                'caller_path': 'request_args_observed',
                'external_exploitability': 'insufficient_evidence',
                'supporting_evidence_ids': ids,
                'missing_evidence': ['deployed_route', 'authentication', 'external_exploit'],
                'review_summary': 'Unsafe construction observed; external reachability unproven',
            })
        elif node == 'A':
            self.a += 1
            if 'Generate a complete replacement app.py file' in messages[-1]['content']:
                result['content'] = '```python\n' + (
                    w.APP_VULNERABLE if self.bad_candidate else w.SAFE_EXAMPLE) + '```'
        return result


def fake_sandbox(path):
    src = (Path(path) / 'app.py').read_text()
    return {'normal_rows': 1, 'nonexistent_rows': 0,
            'attack_rows': 2 if w.sha(src) == w.sha(w.APP_VULNERABLE) else 0}


class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_results = w.RESULTS
        w.RESULTS = Path(self.tmp.name) / 'results'

    def tearDown(self):
        w.RESULTS = self.original_results
        self.tmp.cleanup()

    def test_git_collector_and_scope(self):
        repo, commit = w.make_fixture(Path(self.tmp.name))
        evidence = w.capture(repo, commit, 'app.py')
        self.assertEqual(evidence['source_sha256'], w.sha(w.APP_VULNERABLE))
        self.assertTrue(evidence['verified_against_git'])
        for path in ['../app.py', '/etc/passwd', '.git/config', 'other.py']:
            with self.assertRaises(ValueError):
                w.canonical_file(repo, path)
        self.assertTrue(w.inspect_source([evidence, w.capture(repo, commit, 'web.py')])
                        ['unsafe_sql_string_construction_observed'])

    def test_collector_rejects_mutated_commit_worktree(self):
        repo, commit = w.make_fixture(Path(self.tmp.name))
        (repo / 'app.py').write_text(w.SAFE_EXAMPLE)
        with self.assertRaises(RuntimeError):
            w.capture(repo, commit, 'app.py')

    def test_review_rejects_invented_id(self):
        repo, commit = w.make_fixture(Path(self.tmp.name))
        evidence = [w.capture(repo, commit, 'app.py'), w.capture(repo, commit, 'web.py')]
        facts = w.inspect_source(evidence)
        review = {
            'source_pattern': 'unsafe_sql_concatenation',
            'caller_path': 'request_args_observed',
            'external_exploitability': 'insufficient_evidence',
            'supporting_evidence_ids': [e['evidence_id'] for e in evidence] + ['ev-invented'],
            'missing_evidence': ['deployed_route'],
            'review_summary': 'Source-backed, but invented extra ID',
        }
        self.assertIn('Invented evidence reference', w.validate_review(review, evidence, facts))

    def test_tool_allowlist(self):
        repo, _ = w.make_fixture(Path(self.tmp.name))
        self.assertIn('app.py:', w.tool_terminal(repo, 'rg -n username app.py'))
        self.assertIn('return', w.tool_terminal(repo, 'cat app.py'))
        for command in ['python -c "print(1)"', 'cat ../.env', 'rm -rf .',
                        'cat /etc/passwd', 'ls ; cat /etc/passwd']:
            with self.assertRaises(ValueError):
                w.tool_terminal(repo, command)

    def test_patch_contract(self):
        self.assertEqual(w.validate_patch(w.SAFE_EXAMPLE), [])
        self.assertTrue(w.validate_patch(w.APP_VULNERABLE))
        self.assertTrue(w.validate_patch('''def lookup_user(conn, username):\n    return conn.execute("DROP TABLE users; SELECT * FROM users WHERE username = ?", (username,)).fetchall()\n'''))
        self.assertTrue(w.validate_patch('''def lookup_user(conn, username):\n    import os\n    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchall()\n'''))

    def test_redaction(self):
        content, leak = w.normalize('private scratchpad</think>Final only')
        self.assertEqual(content, 'Final only')
        self.assertTrue(leak)
        content, leak = w.normalize('<think>unclosed private scratchpad')
        self.assertEqual(content, '')
        self.assertTrue(leak)

    def test_full_offline_contract_without_node_access(self):
        code, out = w.workflow('offline-pass', FakeProvider(), verify=fake_sandbox)
        self.assertEqual(code, 0)
        t = json.loads((out / 'trace.json').read_text())
        self.assertEqual(t['status'], 'verified_candidate_awaiting_approval')
        self.assertEqual(t['tasks']['root']['state'], 'COMPLETED')
        self.assertEqual(t['verification']['baseline']['attack_rows'], 2)
        self.assertEqual(t['verification']['candidate']['attack_rows'], 0)
        self.assertEqual((out / 'fixture_repo/app.py').read_text(), w.APP_VULNERABLE)
        self.assertNotEqual((out / 'candidate_workspace/app.py').read_text(), w.APP_VULNERABLE)
        events = [json.loads(line) for line in (out / 'events.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['event_type'] == 'TOOL_COMPLETED' for e in events))
        self.assertTrue(any(e['event_type'] == 'AGENT_RESUMED' for e in events))
        self.assertTrue(any(e['event_type'] == 'APPROVAL_GATE' for e in events))
        self.assertEqual(events[0]['previous_hash'], '0'*64)
        self.assertEqual(events[-1]['event_sha256'], w.sha(w.jdump({k:v for k,v in events[-1].items()
                                                                   if k != 'event_sha256'})))
        self.assertIn('Who did what and why', (out / 'report.md').read_text())

    def test_review_disagreement_quarantines_before_patch(self):
        code, out = w.workflow('offline-disagree', FakeProvider(bad_review=True), verify=fake_sandbox)
        self.assertEqual(code, 2)
        t = json.loads((out / 'trace.json').read_text())
        self.assertFalse(t['review_validation']['accepted'])
        self.assertIsNone(t['candidate'])
        self.assertEqual((out / 'fixture_repo/app.py').read_text(), w.APP_VULNERABLE)

    def test_invalid_patch_fails_closed(self):
        code, out = w.workflow('offline-badpatch', FakeProvider(bad_candidate=True), verify=fake_sandbox)
        self.assertEqual(code, 1)
        t = json.loads((out / 'trace.json').read_text())
        self.assertEqual(t['status'], 'failed')
        self.assertIsNone(t['candidate'])
        self.assertEqual((out / 'fixture_repo/app.py').read_text(), w.APP_VULNERABLE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
