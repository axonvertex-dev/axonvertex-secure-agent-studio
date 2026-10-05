import { readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import type { InvocationResolution, RuntimeTarget, RuntimeTargetConfig } from "./types.js";
import { RuntimeMappingError, SecretResolutionError } from "./errors.js";

export interface MaterializedRuntime {
  id: string;
  modelId: string;
  engine: string;
  nodeRef: string;
  endpointRef: string;
  baseUrl: string;
  apiKey: string;
}

export function loadRuntimeConfig(path = "config/runtime-targets.json"): RuntimeTargetConfig {
  const absolute = resolvePath(path);
  const config = JSON.parse(readFileSync(absolute, "utf8")) as RuntimeTargetConfig;
  if (config.schemaVersion !== "1.0" || !config.runtimes) {
    throw new RuntimeMappingError("Unsupported or incomplete runtime-target configuration");
  }
  return config;
}

function getRequiredSecret(envName: string, env: NodeJS.ProcessEnv): string {
  const value = env[envName]?.trim();
  if (!value) {
    throw new SecretResolutionError(`Missing local secret environment variable ${envName}`);
  }
  return value;
}

export function materializeRuntime(
  resolution: InvocationResolution,
  config: RuntimeTargetConfig,
  env: NodeJS.ProcessEnv = process.env,
): MaterializedRuntime {
  const runtime = resolution.runtime;
  if (!runtime) {
    throw new RuntimeMappingError("ALLOW resolution did not include a runtime");
  }

  const target: RuntimeTarget | undefined = config.runtimes[runtime.id];
  if (!target) {
    throw new RuntimeMappingError(`Runtime ${runtime.id} has no local adapter mapping`);
  }

  const expected: Array<[string, string, string]> = [
    ["endpointRef", runtime.endpointRef, target.endpointRef],
    ["credentialRef", runtime.credentialRef, target.credentialRef],
    ["modelId", runtime.modelId, target.modelId],
    ["engine", runtime.engine, target.engine],
  ];

  for (const [field, actual, wanted] of expected) {
    if (actual !== wanted) {
      throw new RuntimeMappingError(
        `Fail-closed runtime mapping mismatch for ${runtime.id}: ${field}`,
      );
    }
  }

  const baseUrl = (env[target.baseUrlEnv] ?? target.defaultBaseUrl).trim();
  if (!baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
    throw new RuntimeMappingError(`Invalid base URL for runtime ${runtime.id}`);
  }

  return {
    id: runtime.id,
    modelId: runtime.modelId,
    engine: runtime.engine,
    nodeRef: runtime.nodeRef,
    endpointRef: runtime.endpointRef,
    baseUrl: baseUrl.replace(/\/$/, ""),
    apiKey: getRequiredSecret(target.apiKeyEnv, env),
  };
}
