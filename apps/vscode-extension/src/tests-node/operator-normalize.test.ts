import * as assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { normalizeOperatorRun } from '../operator/normalize';

describe('0.7D1 operator allowlist contract', () => {
  it('projects the live accepted review and applied result without exposing raw payloads', () => {
    const candidateSha = 'e352c81ce3fddda4e05ddbe88abc376f92803ea93edb96110f66d7b03f9a5073';
    const normalized = normalizeOperatorRun(
      'v07c2-application-e2e-live-001',
      {
        job: { status: 'VERIFIED_CANDIDATE_AWAITING_APPROVAL' },
        candidate_change: { source_sha256: candidateSha, unified_diff: '--- a/app.py\n+++ b/app.py', private_secret: 'MUST_NOT_LEAK' },
        security_review: { accepted_by_validator: true, model: 'foundation-sec-8b-reasoning', review: { source_pattern: 'unsafe_sql_concatenation' } },
        security_review_history: [
          { artifact_type: 'SecurityReview', accepted_by_validator: false, validation_errors: ['Invented evidence reference'] },
          { artifact_type: 'SecurityReviewRetry', accepted_by_validator: true },
        ],
        verification_result: { passed: true, original_fixture_unchanged: true, candidate: { normal_rows: 1, attack_rows: 0 } },
      },
      { decision: { decision: 'APPROVE', receipt_sha256: 'receipt', sensitive_justification: 'MUST_NOT_LEAK' } },
      { application: {
        state: 'APPLIED', candidate_sha256: candidateSha, result_sha256: 'application-receipt',
        result_json: JSON.stringify({ docker_candidate: { normal_rows: 1, nonexistent_rows: 0, attack_rows: 0 }, git_commit_created: false, token: 'MUST_NOT_LEAK' }),
        events: [{ kind: 'APPLY_COMPLETED', request_id: 'req' }],
      } },
      { artifacts: [{ artifact_type: 'CandidateChange', content_sha256: 'sha', payload: { secret: 'MUST_NOT_LEAK' } }] },
    );
    assert.equal(normalized.contractVersion, '0.7D1');
    assert.equal(normalized.candidate.sourceSha256, candidateSha);
    assert.equal(normalized.reviewVersions[0].accepted, false);
    assert.equal(normalized.reviewVersions[1].accepted, true);
    assert.equal(normalized.application.dockerCandidate.attack_rows, 0);
    assert.equal(normalized.application.gitCommitCreated, false);
    assert.equal(JSON.stringify(normalized).includes('MUST_NOT_LEAK'), false);
  });
  it('handles absent decision and application without inventing approval', () => {
    const data = normalizeOperatorRun('v1', {}, { decision: null }, { application: null }, {});
    assert.equal(data.decision.state, 'NOT_RECORDED');
    assert.equal(data.application.state, 'NOT_AUTHORIZED');
    assert.equal(data.verification.passed, false);
  });
});
