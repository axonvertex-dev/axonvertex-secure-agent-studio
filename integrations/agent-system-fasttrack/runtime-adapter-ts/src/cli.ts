import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import { GovernanceDeniedError } from "./errors.js";
import { loadEnvFile } from "./env.js";
import { RegistryClient } from "./registryClient.js";
import { loadRuntimeConfig } from "./runtimeConfig.js";
import { GovernedRuntimeAdapter } from "./runtimeAdapter.js";
import type { ChatMessage } from "./types.js";

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const envFile = arg("env") ?? ".env.runtime-adapter";
loadEnvFile(envFile);

const registryUrl = process.env.AXV_REGISTRY_URL ?? "http://127.0.0.1:18781";
const registryToken = process.env.AXV_REGISTRY_ADMIN_TOKEN?.trim();
if (!registryToken) {
  throw new Error("AXV_REGISTRY_ADMIN_TOKEN is required");
}

const namespace = arg("namespace") ?? "axonvertex.secure";
const name = arg("agent");
const purpose = arg("purpose");
const prompt = arg("prompt");
const system = arg("system");
const evidencePath = arg("evidence");

if (!name || !purpose || !prompt) {
  throw new Error(
    "Usage: --agent NAME --purpose PURPOSE --prompt TEXT [--system TEXT] [--env FILE] [--evidence FILE]",
  );
}

const messages: ChatMessage[] = [];
if (system) messages.push({ role: "system", content: system });
messages.push({ role: "user", content: prompt });

const registry = new RegistryClient(registryUrl, registryToken);
const config = loadRuntimeConfig("config/runtime-targets.json");
const adapter = new GovernedRuntimeAdapter(registry, config);

try {
  const result = await adapter.invoke({
    namespace,
    name,
    purpose,
    messages,
    temperature: Number(arg("temperature") ?? "0"),
    maxTokens: Number(arg("max-tokens") ?? "512"),
    timeoutMs: Number(arg("timeout-ms") ?? "180000"),
  });

  console.log(result.content);
  if (result.reasoningContent) {
    console.error("[reasoning_content present]");
  }
  console.error(
    `[governance] resolution=${result.evidence.resolutionId} runtime=${result.evidence.runtimeId} request=${result.evidence.requestDigest} response=${result.evidence.responseDigest}`,
  );

  if (evidencePath) {
    const path = resolvePath(evidencePath);
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, JSON.stringify(result.evidence) + "\n", { encoding: "utf8", mode: 0o600 });
  }
} catch (error) {
  if (error instanceof GovernanceDeniedError) {
    console.error(
      `[governance-deny] resolution=${error.resolutionId} reasons=${error.reasons.join(",")}`,
    );
    process.exitCode = 23;
  } else {
    throw error;
  }
}
