import * as vscode from "vscode";
import { createGovernedRuntime } from "../runtime/adapterBridge.js";
import { clearSecrets, configureSecrets } from "../runtime/secrets.js";
import { runSecurePipeline } from "../pipeline/pipeline.js";
import type { PipelineEvent } from "../pipeline/types.js";
import { dashboardHtml } from "./html.js";

export class SecureAgentDashboardProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "axonvertexSecureAgent.dashboard";
  private view?: vscode.WebviewView;
  private running = false;

  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = dashboardHtml(view.webview);

    view.webview.onDidReceiveMessage(async (message: { type?: string }) => {
      if (message.type === "configureSecrets") {
        await configureSecrets(this.context);
      } else if (message.type === "clearSecrets") {
        await clearSecrets(this.context);
      } else if (message.type === "run") {
        await this.runCurrent();
      }
    });
  }

  reveal(): void {
    void vscode.commands.executeCommand("workbench.view.extension.axonvertexSecureAgent");
  }

  async runCurrent(): Promise<void> {
    if (this.running) {
      vscode.window.showWarningMessage("AXONVERTEX Secure Agent pipeline is already running.");
      return;
    }

    this.reveal();
    this.running = true;

    try {
      const editor = vscode.window.activeTextEditor;
      if (!editor) throw new Error("No active text editor.");

      const selection = editor.selection;
      const hasSelection = !selection.isEmpty;
      const raw = hasSelection
        ? editor.document.getText(selection)
        : editor.document.getText();

      if (!raw.trim()) throw new Error("The current selection/file is empty.");

      const cfg = vscode.workspace.getConfiguration("axonvertexSecureAgent");
      const maxSourceChars = cfg.get<number>("maxSourceChars", 60000);
      const maxTokens = cfg.get<number>("maxTokensPerStage", 1400);
      const timeoutMs = cfg.get<number>("timeoutMs", 180000);

      const truncated = raw.length > maxSourceChars;
      const source = truncated ? raw.slice(0, maxSourceChars) : raw;
      const relative = vscode.workspace.asRelativePath(editor.document.uri, false);
      const sourceLabel = `${relative}${hasSelection ? " (selection)" : " (file)"}`;

      const runtime = await createGovernedRuntime(this.context);
      const send = (event: PipelineEvent) => {
        void this.view?.webview.postMessage(event);
      };

      await runSecurePipeline(runtime, sourceLabel, source, truncated, {
        maxTokens,
        timeoutMs,
        onEvent: send,
      });

      void this.view?.webview.postMessage({ type: "run-finished" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      void this.view?.webview.postMessage({ type: "pipeline-error", message });
      vscode.window.showErrorMessage(`AXONVERTEX Secure Agent: ${message}`);
    } finally {
      this.running = false;
    }
  }
}
