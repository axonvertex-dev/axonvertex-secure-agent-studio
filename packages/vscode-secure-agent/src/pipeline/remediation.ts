import * as vscode from "vscode";
import type { PipelineResult } from "./types.js";

export interface RemediationProposal {
  sourceUri: vscode.Uri;
  previewUri: vscode.Uri;
  originalText: string;
  patchedText: string;
  cwe: string;
  title: string;
  summary: string;
}

function buildCommandInjectionPatch(
  source: string,
  cwe: string,
): string | undefined {
  if (!source.includes("shell=True")) return undefined;
  if (!source.includes("subprocess.run(")) return undefined;

  let patched = source;

  // Remove the shell-command construction line.
  patched = patched.replace(
    /^\s*command\s*=\s*f["']ping -c 1 \{host\}["']\s*\r?\n(?:\s*\r?\n)?/m,
    "",
  );

  // Replace subprocess.run(command, shell=True, ...) with argv + shell=False.
  const before = patched;

  patched = patched.replace(
    /^(\s*)command,\r?\n(\s*)shell=True,/m,
    (_match, argIndent: string, shellIndent: string) =>
      `${argIndent}["ping", "-c", "1", host],\n${shellIndent}shell=False,`,
  );

  if (patched === before) {
    return undefined;
  }

  // Add security provenance directly above the remediated call.
  patched = patched.replace(
    /^(\s*)result\s*=\s*subprocess\.run\(/m,
    (_match, indent: string) =>
      `${indent}# AXONVERTEX SECURITY REMEDIATION\n` +
      `${indent}# Finding: ${cwe} - Command Injection\n` +
      `${indent}# CVE: N/A - local source finding; no CVE has been assigned.\n` +
      `${indent}# Reason: remove shell interpretation of the user-controlled host value.\n` +
      `${indent}result = subprocess.run(`,
  );

  return patched;
}

export async function prepareRemediation(
  context: vscode.ExtensionContext,
  document: vscode.TextDocument,
  result: PipelineResult,
): Promise<RemediationProposal | undefined> {
  if (result.gate.status !== "PASS") return undefined;

  const cwe = result.gate.assessment?.cwe;

  if (
    typeof cwe !== "string" ||
    !["CWE-77", "CWE-78"].includes(cwe)
  ) {
    return undefined;
  }

  const originalText = document.getText();
  const patchedText = buildCommandInjectionPatch(originalText, cwe);

  if (!patchedText || patchedText === originalText) {
    return undefined;
  }

  await vscode.workspace.fs.createDirectory(context.globalStorageUri);

  const filename =
    document.uri.path.split("/").pop() ?? "proposed-patch.py";

  const previewUri = vscode.Uri.joinPath(
    context.globalStorageUri,
    `proposed-${Date.now()}-${filename}`,
  );

  await vscode.workspace.fs.writeFile(
    previewUri,
    Buffer.from(patchedText, "utf8"),
  );

  return {
    sourceUri: document.uri,
    previewUri,
    originalText,
    patchedText,
    cwe,
    title: `${cwe} Command Injection remediation`,
    summary:
      "Remove shell execution and invoke ping with a direct argument vector.",
  };
}

export async function showRemediationDiff(
  proposal: RemediationProposal,
): Promise<void> {
  await vscode.commands.executeCommand(
    "vscode.diff",
    proposal.sourceUri,
    proposal.previewUri,
    `AXONVERTEX Proposed Patch • ${proposal.cwe}`,
    { preview: true },
  );
}

export async function applyRemediation(
  proposal: RemediationProposal,
): Promise<void> {
  const document =
    await vscode.workspace.openTextDocument(proposal.sourceUri);

  const end =
    document.lineAt(document.lineCount - 1).range.end;

  const edit = new vscode.WorkspaceEdit();

  edit.replace(
    proposal.sourceUri,
    new vscode.Range(
      new vscode.Position(0, 0),
      end,
    ),
    proposal.patchedText,
  );

  const applied =
    await vscode.workspace.applyEdit(edit);

  if (!applied) {
    throw new Error(
      "VS Code rejected the remediation WorkspaceEdit.",
    );
  }

  const updated =
    await vscode.workspace.openTextDocument(proposal.sourceUri);

  await updated.save();
  await vscode.window.showTextDocument(updated);
}

export function verifyCommandInjectionPatch(
  text: string,
  cwe: string,
): string[] {
  const failures: string[] = [];

  if (text.includes("shell=True")) {
    failures.push("shell=True remains");
  }

  if (!text.includes('["ping", "-c", "1", host]')) {
    failures.push("direct argv invocation is missing");
  }

  if (!text.includes(`Finding: ${cwe}`)) {
    failures.push(`${cwe} provenance comment is missing`);
  }

  if (!text.includes("CVE: N/A")) {
    failures.push("CVE status comment is missing");
  }

  if (!text.includes("# Reason:")) {
    failures.push("remediation reason comment is missing");
  }

  return failures;
}
