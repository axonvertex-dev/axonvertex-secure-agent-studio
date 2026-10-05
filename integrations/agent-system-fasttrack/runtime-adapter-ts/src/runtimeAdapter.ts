import { GovernanceDeniedError, RuntimeMappingError } from "./errors.js";
import { sha256Json } from "./digest.js";
import { invokeOpenAICompatible } from "./openaiCompat.js";
import type { RegistryClient } from "./registryClient.js";
import { materializeRuntime } from "./runtimeConfig.js";
import type {
  FetchLike,
  GovernedInvocationRequest,
  GovernedInvocationResult,
  InvocationEvidence,
  RuntimeTargetConfig,
} from "./types.js";

export class GovernedRuntimeAdapter {
  constructor(
    private readonly registry: RegistryClient,
    private readonly runtimeConfig: RuntimeTargetConfig,
    private readonly env: NodeJS.ProcessEnv = process.env,
    private readonly fetchImpl: FetchLike = fetch,
  ) {}

  async invoke(request: GovernedInvocationRequest): Promise<GovernedInvocationResult> {
    const resolution = await this.registry.resolve({
      namespace: request.namespace,
      name: request.name,
      purpose: request.purpose,
    });

    if (resolution.decision !== "ALLOW") {
      throw new GovernanceDeniedError(
        "DENY",
        resolution.reasons,
        resolution.resolutionId,
      );
    }

    if (
      resolution.scope !== "LAB_ONLY" ||
      !resolution.agentId ||
      resolution.agentRevision === undefined ||
      !resolution.revisionDigest ||
      !resolution.bindingId ||
      !resolution.admissionId ||
      !resolution.runtime ||
      !resolution.expiresAt
    ) {
      throw new RuntimeMappingError("Incomplete ALLOW resolution; refusing invocation");
    }

    const expiresAtMs = Date.parse(resolution.expiresAt);
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= Date.now()) {
      throw new RuntimeMappingError("Resolution has expired; refusing invocation");
    }

    const runtime = materializeRuntime(resolution, this.runtimeConfig, this.env);

    const modelRequest = {
      model: runtime.modelId,
      messages: request.messages,
      temperature: request.temperature ?? 0,
      max_tokens: request.maxTokens ?? 1024,
    };

    const requestDigest = sha256Json(modelRequest);

    const modelResult = await invokeOpenAICompatible(
      runtime,
      {
        messages: request.messages,
        temperature: request.temperature ?? 0,
        maxTokens: request.maxTokens ?? 1024,
        timeoutMs: request.timeoutMs ?? 180_000,
      },
      this.fetchImpl,
    );

    const responseDigest = sha256Json(modelResult.raw);

    const evidence: InvocationEvidence = {
      schemaVersion: "1.0",
      resolutionId: resolution.resolutionId,
      decision: "ALLOW",
      scope: "LAB_ONLY",
      agentId: resolution.agentId,
      agentRevision: resolution.agentRevision,
      revisionDigest: resolution.revisionDigest,
      bindingId: resolution.bindingId,
      admissionId: resolution.admissionId,
      namespace: request.namespace,
      agentName: request.name,
      purpose: request.purpose,
      runtimeId: runtime.id,
      modelId: runtime.modelId,
      engine: runtime.engine,
      nodeRef: runtime.nodeRef,
      endpointRef: runtime.endpointRef,
      requestDigest,
      responseDigest,
      issuedAt: resolution.issuedAt,
      resolutionExpiresAt: resolution.expiresAt,
      completedAt: new Date().toISOString(),
    };

    return {
      content: modelResult.content,
      ...(modelResult.reasoningContent
        ? { reasoningContent: modelResult.reasoningContent }
        : {}),
      ...(modelResult.finishReason
        ? { finishReason: modelResult.finishReason }
        : {}),
      ...(modelResult.raw.usage !== undefined
        ? { usage: modelResult.raw.usage }
        : {}),
      evidence,
    };
  }
}
