import type { InvocationEvidence } from "../../../../integrations/agent-system-fasttrack/runtime-adapter-ts/src/types.js";

export type StageId =
  | "security-scout"
  | "coding-investigator"
  | "security-critic"
  | "final-evidence-synthesizer";

export interface PipelineStageResult {
  id: StageId;
  label: string;
  purpose: string;
  expectedRuntime: string;
  content: string;
  evidence: InvocationEvidence;
  elapsedMs: number;
}

export interface GateResult {
  status: "PASS" | "FAIL";
  reasons: string[];
  assessment?: {
    verdict: string;
    primaryFinding: string;
    cwe: string;
  };
}

export interface PipelineResult {
  sourceLabel: string;
  truncated: boolean;
  stages: PipelineStageResult[];
  gate: GateResult;
  finalContent: string;
}

export type PipelineEvent =
  | { type: "pipeline-start"; sourceLabel: string; truncated: boolean }
  | { type: "stage-start"; id: StageId; label: string; expectedRuntime: string }
  | { type: "stage-complete"; stage: PipelineStageResult }
  | { type: "gate"; gate: GateResult }
  | { type: "pipeline-error"; message: string };
