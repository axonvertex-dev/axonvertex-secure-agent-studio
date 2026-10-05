import assert from "node:assert/strict";
import test from "node:test";
import { GovernanceDeniedError, RuntimeMappingError } from "../src/errors.js";
import { GovernedRuntimeAdapter } from "../src/runtimeAdapter.js";
import type {
  FetchLike,
  InvocationResolution,
  RuntimeTargetConfig,
} from "../src/types.js";

const config: RuntimeTargetConfig = {
  schemaVersion: "1.0",
  runtimes: {
    "runtime-gemma-node-a": {
      endpointRef: "runtime://node-a:11433",
      credentialRef: "secret://node-a/gemma-api-key",
      modelId: "gemma-4-12b-it-qat",
      engine: "sglang",
      baseUrlEnv: "TEST_URL",
      defaultBaseUrl: "http://runtime.invalid/v1",
      apiKeyEnv: "TEST_KEY",
    },
  },
};

function registryReturning(resolution: InvocationResolution) {
  return {
    resolve: async () => resolution,
  };
}

test("DENY resolution prevents any runtime call", async () => {
  let runtimeCalled = false;
  const fetchImpl: FetchLike = async () => {
    runtimeCalled = true;
    throw new Error("runtime should not be called");
  };

  const adapter = new GovernedRuntimeAdapter(
    registryReturning({
      resolutionId: "res-denied",
      decision: "DENY",
      scope: "LAB_ONLY",
      reasons: ["LAB_ADMISSION_REQUIRED"],
      purpose: "code_reasoning",
      issuedAt: new Date().toISOString(),
    }) as never,
    config,
    { TEST_KEY: "not-used" },
    fetchImpl,
  );

  await assert.rejects(
    adapter.invoke({
      namespace: "axonvertex.secure",
      name: "coding-investigator",
      purpose: "code_reasoning",
      messages: [{ role: "user", content: "test" }],
    }),
    GovernanceDeniedError,
  );

  assert.equal(runtimeCalled, false);
});

test("ALLOW invokes exactly the Registry-selected runtime and emits no secret in evidence", async () => {
  let seenAuthorization = "";
  let seenUrl = "";
  const fetchImpl: FetchLike = async (input, init) => {
    seenUrl = String(input);
    seenAuthorization = new Headers(init?.headers).get("Authorization") ?? "";
    return new Response(
      JSON.stringify({
        choices: [{ finish_reason: "stop", message: { content: "MODEL_OK" } }],
        usage: { total_tokens: 5 },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  const future = new Date(Date.now() + 60_000).toISOString();
  const adapter = new GovernedRuntimeAdapter(
    registryReturning({
      resolutionId: "res-ok",
      decision: "ALLOW",
      scope: "LAB_ONLY",
      reasons: ["LAB_ADMISSION_VALID", "EVALUATION_PASS", "RUNTIME_AVAILABLE"],
      agentId: "agt-test",
      agentRevision: 1,
      revisionDigest: "sha256:abc",
      bindingId: "bnd-test",
      admissionId: "adm-test",
      purpose: "code_reasoning",
      runtime: {
        id: "runtime-gemma-node-a",
        modelId: "gemma-4-12b-it-qat",
        engine: "sglang",
        nodeRef: "node-a",
        endpointRef: "runtime://node-a:11433",
        credentialRef: "secret://node-a/gemma-api-key",
      },
      issuedAt: new Date().toISOString(),
      expiresAt: future,
    }) as never,
    config,
    { TEST_KEY: "super-secret", TEST_URL: "http://127.0.0.1:9999/v1" },
    fetchImpl,
  );

  const result = await adapter.invoke({
    namespace: "axonvertex.secure",
    name: "coding-investigator",
    purpose: "code_reasoning",
    messages: [{ role: "user", content: "test" }],
  });

  assert.equal(result.content, "MODEL_OK");
  assert.equal(seenUrl, "http://127.0.0.1:9999/v1/chat/completions");
  assert.equal(seenAuthorization, "Bearer super-secret");
  assert.equal(JSON.stringify(result.evidence).includes("super-secret"), false);
  assert.equal(result.evidence.runtimeId, "runtime-gemma-node-a");
});

test("runtime metadata mismatch fails closed before invocation", async () => {
  let runtimeCalled = false;
  const fetchImpl: FetchLike = async () => {
    runtimeCalled = true;
    throw new Error("must not call runtime");
  };

  const adapter = new GovernedRuntimeAdapter(
    registryReturning({
      resolutionId: "res-bad",
      decision: "ALLOW",
      scope: "LAB_ONLY",
      reasons: [],
      agentId: "agt-test",
      agentRevision: 1,
      revisionDigest: "sha256:abc",
      bindingId: "bnd-test",
      admissionId: "adm-test",
      purpose: "code_reasoning",
      runtime: {
        id: "runtime-gemma-node-a",
        modelId: "unexpected-model",
        engine: "sglang",
        nodeRef: "node-a",
        endpointRef: "runtime://node-a:11433",
        credentialRef: "secret://node-a/gemma-api-key",
      },
      issuedAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }) as never,
    config,
    { TEST_KEY: "secret" },
    fetchImpl,
  );

  await assert.rejects(
    adapter.invoke({
      namespace: "axonvertex.secure",
      name: "coding-investigator",
      purpose: "code_reasoning",
      messages: [{ role: "user", content: "test" }],
    }),
    RuntimeMappingError,
  );

  assert.equal(runtimeCalled, false);
});
