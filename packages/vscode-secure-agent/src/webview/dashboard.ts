import * as vscode from "vscode";
import { createGovernedRuntime } from "../runtime/adapterBridge.js";
import { clearSecrets, configureSecrets } from "../runtime/secrets.js";
import { runSecurePipeline } from "../pipeline/pipeline.js";
import type { PipelineEvent, PipelineResult } from "../pipeline/types.js";
import {
  applyRemediation,
  prepareRemediation,
  showRemediationDiff,
  verifyCommandInjectionPatch,
  type RemediationProposal,
} from "../pipeline/remediation.js";
import { dashboardHtml } from "./html.js";

export class SecureAgentDashboardProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "axonvertexSecureAgent.dashboard";
  private view?: vscode.WebviewView;
  private running = false;
  private lastResult?: PipelineResult;
  private lastProposal?: RemediationProposal;

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
      } else if (message.type === "approvePatch") {
        await this.approvePatch();
      } else if (message.type === "denyPatch") {
        this.denyPatch();
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
    this.lastResult = undefined;
    this.lastProposal = undefined;

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

      const result = await runSecurePipeline(runtime, sourceLabel, source, truncated, {
        maxTokens,
        timeoutMs,
        onEvent: send,
      });
      this.lastResult = result;

      const proposal = await prepareRemediation(this.context, editor.document, result);
      this.lastProposal = proposal;

      if (proposal) {
        await showRemediationDiff(proposal);
        void this.view?.webview.postMessage({
          type: "approval-required",
          cwe: proposal.cwe,
          title: proposal.title,
          summary: proposal.summary,
        });
      } else {
        void this.view?.webview.postMessage({
          type: "approval-unavailable",
          message:
            result.gate.status !== "PASS"
              ? "Human approval is disabled because the deterministic quality gate did not pass."
              : "No deterministic remediation patch is available for this finding.",
        });
      }

      void this.view?.webview.postMessage({ type: "run-finished" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      void this.view?.webview.postMessage({ type: "pipeline-error", message });
      vscode.window.showErrorMessage(`AXONVERTEX Secure Agent: ${message}`);
    } finally {
      this.running = false;
    }
  }

  private async approvePatch(): Promise<void> {
    if (!this.lastProposal || !this.lastResult) {
      vscode.window.showWarningMessage("No AXONVERTEX patch is awaiting approval.");
      return;
    }

    await applyRemediation(this.lastProposal);
    const updated = await vscode.workspace.openTextDocument(this.lastProposal.sourceUri);
    const failures = verifyCommandInjectionPatch(updated.getText(), this.lastProposal.cwe);

    if (failures.length) {
      void this.view?.webview.postMessage({
        type: "approval-result",
        decision: "APPROVED_BUT_VERIFICATION_FAILED",
        detail: failures.join(" | "),
      });
      vscode.window.showErrorMessage(
        `AXONVERTEX remediation verification failed: ${failures.join(", ")}`,
      );
      return;
    }

    void this.view?.webview.postMessage({
      type: "approval-result",
      decision: "APPROVED_AND_VERIFIED",
      detail:
        `${this.lastProposal.cwe} fixed. Human-approved WorkspaceEdit applied and deterministic verification passed.`,
    });
    vscode.window.showInformationMessage(
      `AXONVERTEX: ${this.lastProposal.cwe} remediation approved and verified.`,
    );
    this.lastProposal = undefined;
  }

  private denyPatch(): void {
    if (!this.lastProposal) return;

    void this.view?.webview.postMessage({
      type: "approval-result",
      decision: "DENIED_BY_HUMAN",
      detail: "No workspace source was modified.",
    });
    vscode.window.showInformationMessage(
      "AXONVERTEX remediation denied. Source code was not modified.",
    );
    this.lastProposal = undefined;
  }
}
