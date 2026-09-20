/** 0.7D1 versioned, allowlisted, display-only operator contract.
 * Do not send raw durable artifacts, request headers, credentials, or tool payloads to Webviews.
 */
export interface OperatorArtifactRef {
  id: string;
  artifactType: string;
  contentSha256: string;
}
export interface OperatorReviewVersion {
  artifactType: string;
  accepted: boolean;
  contentSha256: string;
  validationErrors: string[];
}
export interface OperatorApplicationEvent {
  kind: string;
  createdAt: string;
  requestId: string;
}
export interface OperatorRunListItem {
  runId: string;
}
export interface OperatorRunView {
  contractVersion: '0.7D1';
  runId: string;
  jobStatus: string;
  reviewVersions: OperatorReviewVersion[];
  acceptedSecurityReview: {
    accepted: boolean;
    model: string;
    node: string;
    evidenceIds: string[];
    sourcePattern: string;
    externalExploitability: string;
    missingEvidence: string[];
  };
  candidate: {
    sourceSha256: string;
    diffSha256: string;
    fixtureCommit: string;
    unifiedDiff: string;
    reviewArtifactId: string;
  };
  verification: {
    passed: boolean;
    originalFixtureUnchanged: boolean;
    baseline: Record<string, number>;
    candidate: Record<string, number>;
  };
  decision: {
    state: string;
    reasonCode: string;
    identityAssurance: string;
    receiptSha256: string;
  };
  application: {
    state: string;
    receiptSha256: string;
    candidateSha256: string;
    gitCommitCreated: boolean | null;
    dockerCandidate: Record<string, number>;
    events: OperatorApplicationEvent[];
  };
  artifacts: OperatorArtifactRef[];
}
