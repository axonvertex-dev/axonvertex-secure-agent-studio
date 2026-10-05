import * as vscode from "vscode";

export const SecretKeys = {
  registryAdminToken: "axonvertex.registry.adminToken",
  gemmaApiKey: "axonvertex.runtime.gemma.apiKey",
  antaresApiKey: "axonvertex.runtime.antares.apiKey",
  foundationApiKey: "axonvertex.runtime.foundation.apiKey",
} as const;

const labels: Array<[keyof typeof SecretKeys, string]> = [
  ["registryAdminToken", "Agent Registry lab admin token"],
  ["gemmaApiKey", "Node A Gemma API key"],
  ["antaresApiKey", "Node B Antares API key"],
  ["foundationApiKey", "Node C Foundation Sec API key"],
];

export async function configureSecrets(context: vscode.ExtensionContext): Promise<boolean> {
  for (const [name, label] of labels) {
    const existing = await context.secrets.get(SecretKeys[name]);
    const value = await vscode.window.showInputBox({
      title: "AXONVERTEX Secure Agent — Lab Secret",
      prompt: label,
      password: true,
      ignoreFocusOut: true,
      placeHolder: existing ? "Stored — enter a replacement, or press Escape to keep it" : "Required",
    });

    if (value === undefined) {
      if (existing) {
        continue;
      }
      vscode.window.showWarningMessage(`Configuration stopped: ${label} is not stored.`);
      return false;
    }

    if (!value.trim()) {
      vscode.window.showWarningMessage(`Empty value rejected: ${label}.`);
      return false;
    }

    await context.secrets.store(SecretKeys[name], value.trim());
  }

  vscode.window.showInformationMessage("AXONVERTEX lab secrets stored in VS Code SecretStorage.");
  return true;
}

export async function clearSecrets(context: vscode.ExtensionContext): Promise<void> {
  await Promise.all(Object.values(SecretKeys).map((key) => context.secrets.delete(key)));
  vscode.window.showInformationMessage("AXONVERTEX lab secrets cleared from VS Code SecretStorage.");
}

export async function requireSecrets(context: vscode.ExtensionContext): Promise<{
  registryAdminToken: string;
  gemmaApiKey: string;
  antaresApiKey: string;
  foundationApiKey: string;
}> {
  const registryAdminToken = await context.secrets.get(SecretKeys.registryAdminToken);
  const gemmaApiKey = await context.secrets.get(SecretKeys.gemmaApiKey);
  const antaresApiKey = await context.secrets.get(SecretKeys.antaresApiKey);
  const foundationApiKey = await context.secrets.get(SecretKeys.foundationApiKey);

  const missing = [
    !registryAdminToken && "Registry admin token",
    !gemmaApiKey && "Gemma API key",
    !antaresApiKey && "Antares API key",
    !foundationApiKey && "Foundation Sec API key",
  ].filter(Boolean);

  if (missing.length) {
    throw new Error(`Missing SecretStorage values: ${missing.join(", ")}`);
  }

  return {
    registryAdminToken: registryAdminToken!,
    gemmaApiKey: gemmaApiKey!,
    antaresApiKey: antaresApiKey!,
    foundationApiKey: foundationApiKey!,
  };
}
