import assert from "node:assert/strict";
import test from "node:test";
import { evaluateQualityGate } from "../src/pipeline/qualityGate.js";
import type { PipelineStageResult, StageId } from "../src/pipeline/types.js";

function stage(id: StageId, runtimeId: string, content = "{}"): PipelineStageResult {
  return {
    id,
    label: id,
    purpose: "test",
    expectedRuntime: runtimeId,
    content,
    elapsedMs: 1,
    evidence: {
      schemaVersion: "1.0",
      resolutionId: `res_${id}`,
      decision: "ALLOW",
      scope: "LAB_ONLY",
      agentId: `agt_${id}`,
      agentRevision: 1,
      revisionDigest: "sha256:rev",
      bindingId: `bnd_${id}`,
      admissionId: `adm_${id}`,
      namespace: "axonvertex.secure",
      agentName: id,
      purpose: "test",
      runtimeId,
      modelId: "test-model",
      engine: "test",
      nodeRef: "node-test",
      endpointRef: "runtime://test",
      requestDigest: "sha256:req",
      responseDigest: "sha256:resp",
      issuedAt: new Date().toISOString(),
      resolutionExpiresAt: new Date(Date.now() + 60_000).toISOString(),
      completedAt: new Date().toISOString(),
    },
  };
}

test("gate passes only a structurally complete governed final assessment", () => {
  const final = JSON.stringify({
    verdict: "ACCEPT_WITH_CORRECTIONS",
    primary_finding: {
      title: "OS Command Injection",
      cwe: "CWE-78",
      confidence: "high",
      assessment: "evidence",
    },
    validated_source_to_sink: ["source -> sink"],
    authentication: { status: "partial", assessment: "evidence" },
    authorization: { status: "not_demonstrated", assessment: "evidence" },
    approved_remediation: ["remove shell execution"],
    regression_tests: ["metacharacters cannot execute"],
  });

  const result = evaluateQualityGate([
    stage("security-scout", "runtime-antares-node-b"),
    stage("coding-investigator", "runtime-gemma-node-a"),
    stage("security-critic", "runtime-foundation-node-c"),
    stage("final-evidence-synthesizer", "runtime-gemma-node-a", final),
  ]);

  assert.equal(result.status, "PASS");
  assert.equal(result.assessment?.cwe, "CWE-78");
});

test("gate fails if the final assessment omits source-to-sink evidence", () => {
  const final = JSON.stringify({
    verdict: "ACCEPT",
    primary_finding: { title: "Finding", cwe: "CWE-78" },
    validated_source_to_sink: [],
    authentication: { status: "partial" },
    authorization: { status: "unknown" },
    approved_remediation: ["fix"],
    regression_tests: ["test"],
  });

  const result = evaluateQualityGate([
    stage("security-scout", "runtime-antares-node-b"),
    stage("coding-investigator", "runtime-gemma-node-a"),
    stage("security-critic", "runtime-foundation-node-c"),
    stage("final-evidence-synthesizer", "runtime-gemma-node-a", final),
  ]);

  assert.equal(result.status, "FAIL");
  assert.ok(result.reasons.some((r) => r.includes("source-to-sink")));
});

test("gate fails if any stage lacks governed ALLOW evidence", () => {
  const stages = [
    stage("security-scout", "runtime-antares-node-b"),
    stage("coding-investigator", "runtime-gemma-node-a"),
    stage("security-critic", "runtime-foundation-node-c"),
    stage(
      "final-evidence-synthesizer",
      "runtime-gemma-node-a",
      JSON.stringify({
        verdict: "REJECT",
        primary_finding: { title: "Finding", cwe: "CWE-78" },
        validated_source_to_sink: ["a -> b"],
        authentication: { status: "partial" },
        authorization: { status: "unknown" },
        approved_remediation: ["fix"],
        regression_tests: ["test"],
      }),
    ),
  ];

  stages[2]!.evidence.decision = "ALLOW";
  stages[2]!.evidence.resolutionId = "invalid";

  const result = evaluateQualityGate(stages);
  assert.equal(result.status, "FAIL");
  assert.ok(result.reasons.some((r) => r.includes("resolution ID")));
});
