import * as vscode from "vscode";
import { SecureAgentDashboardProvider } from "./webview/dashboard.js";
import { clearSecrets, configureSecrets } from "./runtime/secrets.js";

export function activate(context: vscode.ExtensionContext): void {
  const provider = new SecureAgentDashboardProvider(context);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SecureAgentDashboardProvider.viewType,
      provider,
      { webviewOptions: { retainContextWhenHidden: true } },
    ),
    vscode.commands.registerCommand(
      "axonvertexSecureAgent.openDashboard",
      () => provider.reveal(),
    ),
    vscode.commands.registerCommand(
      "axonvertexSecureAgent.runCurrent",
      () => provider.runCurrent(),
    ),
    vscode.commands.registerCommand(
      "axonvertexSecureAgent.configureSecrets",
      () => configureSecrets(context),
    ),
    vscode.commands.registerCommand(
      "axonvertexSecureAgent.clearSecrets",
      () => clearSecrets(context),
    ),
  );
}

export function deactivate(): void {
  // No background worker or persistent model connection is retained.
}
