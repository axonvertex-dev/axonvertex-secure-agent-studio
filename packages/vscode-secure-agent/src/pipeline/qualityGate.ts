import type { GateResult, PipelineStageResult } from "./types.js";

function jsonCandidates(text: string): unknown[] {
  const out: unknown[] = [];
  const trimmed = text.trim();

  try {
    out.push(JSON.parse(trimmed));
  } catch {
    // Continue with fenced/balanced candidates.
  }

  const fence = /```(?:json)?\s*([\s\S]*?)```/gi;
  for (const match of trimmed.matchAll(fence)) {
    try {
      out.push(JSON.parse(match[1]!.trim()));
    } catch {
      // Ignore malformed fenced candidate.
    }
  }

  for (let start = 0; start < trimmed.length; start++) {
    if (trimmed[start] !== "{") continue;
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = start; i < trimmed.length; i++) {
      const ch = trimmed[i]!;
      if (inString) {
        if (escaped) escaped = false;
        else if (ch === "\\") escaped = true;
        else if (ch === '"') inString = false;
        continue;
      }
      if (ch === '"') inString = true;
      else if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) {
          try {
            out.push(JSON.parse(trimmed.slice(start, i + 1)));
          } catch {
            // Ignore candidate.
          }
          break;
        }
      }
    }
  }

  return out;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function evaluateQualityGate(stages: PipelineStageResult[]): GateResult {
  const reasons: string[] = [];

  if (stages.length !== 4) {
    reasons.push(`expected 4 governed stages, received ${stages.length}`);
  }

  for (const stage of stages) {
    if (stage.evidence.decision !== "ALLOW") {
      reasons.push(`${stage.label}: Registry decision was not ALLOW`);
    }
    if (stage.evidence.scope !== "LAB_ONLY") {
      reasons.push(`${stage.label}: unexpected governance scope`);
    }
    if (!stage.evidence.resolutionId.startsWith("res_")) {
      reasons.push(`${stage.label}: missing governed resolution ID`);
    }
    if (!stage.evidence.requestDigest.startsWith("sha256:")) {
      reasons.push(`${stage.label}: missing request digest`);
    }
    if (!stage.evidence.responseDigest.startsWith("sha256:")) {
      reasons.push(`${stage.label}: missing response digest`);
    }
  }

  const finalStage = stages.find((s) => s.id === "final-evidence-synthesizer");
  if (!finalStage) {
    reasons.push("final evidence synthesizer did not complete");
    return { status: "FAIL", reasons };
  }

  const candidate = jsonCandidates(finalStage.content)
    .map(asRecord)
    .find((v) =>
      v &&
      "verdict" in v &&
      "primary_finding" in v &&
      "validated_source_to_sink" in v &&
      "authentication" in v &&
      "authorization" in v,
    );

  if (!candidate) {
    reasons.push("final synthesizer did not produce the required assessment object");
    return { status: "FAIL", reasons };
  }

  const verdict = typeof candidate.verdict === "string" ? candidate.verdict : "";
  if (!["ACCEPT", "ACCEPT_WITH_CORRECTIONS", "REJECT"].includes(verdict)) {
    reasons.push("final verdict is outside the allowed deterministic schema");
  }

  const finding = asRecord(candidate.primary_finding);
  const title = typeof finding?.title === "string" ? finding.title.trim() : "";
  const cwe = typeof finding?.cwe === "string" ? finding.cwe.trim() : "";

  if (!title) reasons.push("primary finding title is missing");
  if (!/^CWE-\d+$/.test(cwe)) reasons.push("primary finding CWE is missing or malformed");

  const sourceToSink = Array.isArray(candidate.validated_source_to_sink)
    ? candidate.validated_source_to_sink.filter((v) => typeof v === "string" && v.trim())
    : [];

  if (sourceToSink.length === 0) {
    reasons.push("validated source-to-sink evidence is empty");
  }

  for (const field of ["authentication", "authorization"] as const) {
    const block = asRecord(candidate[field]);
    if (!block || typeof block.status !== "string" || !block.status.trim()) {
      reasons.push(`${field} status is missing`);
    }
  }

  const remediation = Array.isArray(candidate.approved_remediation)
    ? candidate.approved_remediation.filter((v) => typeof v === "string" && v.trim())
    : [];
  const tests = Array.isArray(candidate.regression_tests)
    ? candidate.regression_tests.filter((v) => typeof v === "string" && v.trim())
    : [];

  if (remediation.length === 0) reasons.push("approved remediation is empty");
  if (tests.length === 0) reasons.push("regression tests are empty");

  return {
    status: reasons.length ? "FAIL" : "PASS",
    reasons,
    assessment: {
      verdict,
      primaryFinding: title,
      cwe,
    },
  };
}
