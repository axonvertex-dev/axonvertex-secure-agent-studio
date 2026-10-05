import * as vscode from "vscode";
import {
  GovernedRuntimeAdapter,
  RegistryClient,
  loadRuntimeConfig,
} from "../../../../integrations/agent-system-fasttrack/runtime-adapter-ts/src/index.js";
import type {
  GovernedInvocationRequest,
  GovernedInvocationResult,
} from "../../../../integrations/agent-system-fasttrack/runtime-adapter-ts/src/types.js";
import { requireSecrets } from "./secrets.js";

export interface SecureAgentRuntime {
  invoke(request: GovernedInvocationRequest): Promise<GovernedInvocationResult>;
}

export async function createGovernedRuntime(
  context: vscode.ExtensionContext,
): Promise<SecureAgentRuntime> {
  const secrets = await requireSecrets(context);
  const cfg = vscode.workspace.getConfiguration("axonvertexSecureAgent");

  const registryUrl = cfg.get<string>("registryUrl", "http://127.0.0.1:18781");
  const runtimeConfigPath = context.asAbsolutePath("dist/runtime-targets.json");
  const runtimeConfig = loadRuntimeConfig(runtimeConfigPath);

  const runtimeEnv: NodeJS.ProcessEnv = {
    AXV_RUNTIME_GEMMA_NODE_A_URL: cfg.get<string>(
      "gemmaUrl",
      "http://100.82.103.57:11433/v1",
    ),
    AXV_RUNTIME_GEMMA_NODE_A_API_KEY: secrets.gemmaApiKey,
    AXV_RUNTIME_ANTARES_NODE_B_URL: cfg.get<string>(
      "antaresUrl",
      "http://127.0.0.1:18184/v1",
    ),
    AXV_RUNTIME_ANTARES_NODE_B_API_KEY: secrets.antaresApiKey,
    AXV_RUNTIME_FOUNDATION_NODE_C_URL: cfg.get<string>(
      "foundationUrl",
      "http://100.76.212.84:18183/v1",
    ),
    AXV_RUNTIME_FOUNDATION_NODE_C_API_KEY: secrets.foundationApiKey,
  };

  const registry = new RegistryClient(registryUrl, secrets.registryAdminToken);
  return new GovernedRuntimeAdapter(registry, runtimeConfig, runtimeEnv);
}
