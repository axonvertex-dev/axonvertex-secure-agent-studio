import type {
  OperatorRunView,
  OperatorArtifactRef,
  OperatorReviewVersion,
  OperatorApplicationEvent,
} from '../../../../packages/shared-types/operator-view';

type Dict = Record<string, unknown>;

function obj(value: unknown): Dict {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Dict : {};
}
function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
function bool(value: unknown): boolean {
  return value === true;
}
function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').slice(0, 100) : [];
}
function counts(value: unknown): Record<string, number> {
  const input = obj(value);
  const result: Record<string, number> = {};
  for (const key of ['normal_rows', 'nonexistent_rows', 'attack_rows']) {
    if (typeof input[key] === 'number' && Number.isFinite(input[key])) {
      result[key] = input[key];
    }
  }
  return result;
}
function parseResult(value: unknown): Dict {
  if (typeof value !== 'string') { return {}; }
  try { return obj(JSON.parse(value)); } catch { return {}; }
}

/** The only backend-to-Webview projection: no raw payloads or CLI output. */
export function normalizeOperatorRun(
  runId: string,
  reviewResponse: unknown,
  decisionResponse: unknown,
  applicationResponse: unknown,
  bridgeResponse: unknown,
): OperatorRunView {
  const review = obj(reviewResponse);
  const decision = obj(obj(decisionResponse).decision);
  const application = obj(obj(applicationResponse).application);
  const bridge = obj(bridgeResponse);
  const job = obj(review.job);
  const accepted = obj(review.security_review);
  const reviewer = obj(accepted.review);
  const candidate = obj(review.candidate_change);
  const verification = obj(review.verification_result);
  const result = parseResult(application.result_json);

  const reviewVersions: OperatorReviewVersion[] = Array.isArray(review.security_review_history)
    ? review.security_review_history.slice(0, 100).map((entry: unknown) => {
      const version = obj(entry);
      return {
        artifactType: str(version.artifact_type),
        accepted: bool(version.accepted_by_validator),
        contentSha256: str(version.content_sha256),
        validationErrors: strings(version.validation_errors),
      };
    }) : [];
  const events: OperatorApplicationEvent[] = Array.isArray(application.events)
    ? application.events.slice(0, 200).map((entry: unknown) => {
      const event = obj(entry);
      return {
        kind: str(event.kind),
        createdAt: str(event.created_at),
        requestId: str(event.request_id),
      };
    }) : [];
  const artifacts: OperatorArtifactRef[] = Array.isArray(bridge.artifacts)
    ? bridge.artifacts.slice(0, 200).map((entry: unknown) => {
      const artifact = obj(entry);
      return {
        id: str(artifact.artifact_id ?? artifact.id),
        artifactType: str(artifact.artifact_type),
        contentSha256: str(artifact.content_sha256),
      };
    }) : [];
  return {
    contractVersion: '0.7D1', runId,
    jobStatus: str(job.status ?? bridge.status),
    reviewVersions,
    acceptedSecurityReview: {
      accepted: bool(accepted.accepted_by_validator),
      model: str(accepted.model),
      node: str(accepted.node),
      evidenceIds: strings(accepted.evidence_ids),
      sourcePattern: str(reviewer.source_pattern),
      externalExploitability: str(reviewer.external_exploitability),
      missingEvidence: strings(reviewer.missing_evidence),
    },
    candidate: {
      sourceSha256: str(candidate.source_sha256),
      diffSha256: str(candidate.diff_sha256),
      fixtureCommit: str(candidate.fixture_commit),
      unifiedDiff: str(candidate.unified_diff).slice(0, 200_000),
      reviewArtifactId: str(candidate.review_artifact_id),
    },
    verification: {
      passed: bool(verification.passed),
      originalFixtureUnchanged: bool(verification.original_fixture_unchanged),
      baseline: counts(verification.baseline),
      candidate: counts(verification.candidate),
    },
    decision: {
      state: str(decision.decision) || 'NOT_RECORDED',
      reasonCode: str(decision.reason_code),
      identityAssurance: str(decision.identity_assurance),
      receiptSha256: str(decision.receipt_sha256),
    },
    application: {
      state: str(application.state) || 'NOT_AUTHORIZED',
      receiptSha256: str(application.result_sha256),
      candidateSha256: str(application.candidate_sha256),
      gitCommitCreated: typeof result.git_commit_created === 'boolean' ? result.git_commit_created : null,
      dockerCandidate: counts(result.docker_candidate),
      events,
    },
    artifacts,
  };
}
