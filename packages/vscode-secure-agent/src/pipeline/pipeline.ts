import type { GovernedInvocationRequest } from "../../../../integrations/agent-system-fasttrack/runtime-adapter-ts/src/types.js";
import type { SecureAgentRuntime } from "../runtime/adapterBridge.js";
import {
  criticSystem,
  investigatorSystem,
  scoutSystem,
  synthesizerSystem,
} from "./prompts.js";
import { evaluateQualityGate } from "./qualityGate.js";
import type {
  PipelineEvent,
  PipelineResult,
  PipelineStageResult,
  StageId,
} from "./types.js";

interface StageDefinition {
  id: StageId;
  label: string;
  purpose: string;
  expectedRuntime: string;
  system: string;
}

const stages: StageDefinition[] = [
  {
    id: "security-scout",
    label: "Security Scout",
    purpose: "evidence_extraction",
    expectedRuntime: "runtime-antares-node-b",
    system: scoutSystem,
  },
  {
    id: "coding-investigator",
    label: "Coding Investigator",
    purpose: "code_reasoning",
    expectedRuntime: "runtime-gemma-node-a",
    system: investigatorSystem,
  },
  {
    id: "security-critic",
    label: "Security Critic",
    purpose: "independent_security_review",
    expectedRuntime: "runtime-foundation-node-c",
    system: criticSystem,
  },
  {
    id: "final-evidence-synthesizer",
    label: "Final Evidence Synthesizer",
    purpose: "evidence_synthesis",
    expectedRuntime: "runtime-gemma-node-a",
    system: synthesizerSystem,
  },
];

function priorTranscript(results: PipelineStageResult[]): string {
  if (!results.length) return "No prior agent output.";
  return results
    .map(
      (stage) =>
        `--- ${stage.label} (${stage.evidence.runtimeId}, ${stage.evidence.resolutionId}) ---\n${stage.content}`,
    )
    .join("\n\n");
}

export async function runSecurePipeline(
  runtime: SecureAgentRuntime,
  sourceLabel: string,
  source: string,
  truncated: boolean,
  options: {
    maxTokens: number;
    timeoutMs: number;
    onEvent?: (event: PipelineEvent) => void;
  },
): Promise<PipelineResult> {
  const results: PipelineStageResult[] = [];
  options.onEvent?.({ type: "pipeline-start", sourceLabel, truncated });

  for (const stage of stages) {
    options.onEvent?.({
      type: "stage-start",
      id: stage.id,
      label: stage.label,
      expectedRuntime: stage.expectedRuntime,
    });

    const userContent =
      stage.id === "security-scout"
        ? `SOURCE: ${sourceLabel}\n\n${source}`
        : `SOURCE: ${sourceLabel}\n\n${source}\n\nPRIOR GOVERNED OUTPUTS:\n${priorTranscript(results)}`;

    const request: GovernedInvocationRequest = {
      namespace: "axonvertex.secure",
      name: stage.id,
      purpose: stage.purpose,
      messages: [
        { role: "system", content: stage.system },
        { role: "user", content: userContent },
      ],
      temperature: 0,
      maxTokens: options.maxTokens,
      timeoutMs: options.timeoutMs,
    };

    const started = Date.now();
    const response = await runtime.invoke(request);
    const result: PipelineStageResult = {
      id: stage.id,
      label: stage.label,
      purpose: stage.purpose,
      expectedRuntime: stage.expectedRuntime,
      content: response.content,
      evidence: response.evidence,
      elapsedMs: Date.now() - started,
    };

    if (result.evidence.runtimeId !== stage.expectedRuntime) {
      throw new Error(
        `${stage.label}: Registry resolved ${result.evidence.runtimeId}; expected ${stage.expectedRuntime}`,
      );
    }

    results.push(result);
    options.onEvent?.({ type: "stage-complete", stage: result });
  }

  const gate = evaluateQualityGate(results);
  options.onEvent?.({ type: "gate", gate });

  return {
    sourceLabel,
    truncated,
    stages: results,
    gate,
    finalContent: results.at(-1)?.content ?? "",
  };
}
