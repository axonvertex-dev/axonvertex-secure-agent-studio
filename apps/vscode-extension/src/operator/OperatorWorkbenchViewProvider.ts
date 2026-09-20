import * as crypto from 'node:crypto';
import * as vscode from 'vscode';
import { ReadOnlyRunAdapter } from './ReadOnlyRunAdapter';

interface ViewMessage {
  type: 'ready' | 'refresh' | 'load';
  runId?: string;
}

export class OperatorWorkbenchViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'agentStudio.operatorWorkbench';
  private view: vscode.WebviewView | undefined;
  private selected = '';
  private sequence = 0;
  private readonly adapter = new ReadOnlyRunAdapter();

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      enableCommandUris: false,
      localResourceRoots: [],
    };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((raw: unknown) => {
      if (raw === null || typeof raw !== 'object') { return; }
      const message = raw as Partial<ViewMessage>;
      if (message.type === 'ready' || message.type === 'refresh') {
        void this.refresh();
      } else if (message.type === 'load' && typeof message.runId === 'string') {
        void this.load(message.runId);
      }
    });
  }

  public async refresh(): Promise<void> {
    const seq = ++this.sequence;
    try {
      const runs = await this.adapter.listRuns();
      if (seq !== this.sequence || !this.view) { return; }
      if (!runs.some(r => r.runId === this.selected)) {
        this.selected = runs.find(r => r.runId === 'v07c2-application-e2e-live-001')?.runId
          || runs[0]?.runId || '';
      }
      await this.view.webview.postMessage({ type: 'runs', runs, selected: this.selected });
      if (this.selected) { await this.load(this.selected); }
    } catch (error) {
      await this.problem(error);
    }
  }

  private async load(runId: string): Promise<void> {
    const seq = ++this.sequence;
    try {
      const list = await this.adapter.listRuns();
      if (!list.some(r => r.runId === runId)) {
        throw new Error('Run does not belong to the approved durable-live directory.');
      }
      this.selected = runId;
      const viewData = await this.adapter.loadRun(runId);
      if (seq === this.sequence && this.view) {
        await this.view.webview.postMessage({ type: 'run', run: viewData });
      }
    } catch (error) {
      if (seq === this.sequence) { await this.problem(error); }
    }
  }

  private async problem(error: unknown): Promise<void> {
    const msg = error instanceof Error ? error.message : 'Unknown inspection error';
    await this.view?.webview.postMessage({ type: 'error', message: msg.slice(0, 600) });
  }

  private html(webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(20).toString('hex');
    const csp = `default-src 'none'; img-src data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`;
    return `<!doctype html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operator Workbench</title>
<style nonce="${nonce}">
:root { color-scheme: light dark; }
body { padding: 12px; font: var(--vscode-font-size) var(--vscode-font-family); color: var(--vscode-foreground); }
header { display: grid; gap: 10px; margin-bottom: 14px; }
header strong { font-size: 1.15em; }
select,button { font: inherit; padding: 7px; color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border,var(--vscode-panel-border)); border-radius: 4px; }
button { cursor: pointer; color: var(--vscode-button-foreground); background: var(--vscode-button-background); }
fieldset { border: 1px solid var(--vscode-panel-border); margin: 0 0 10px; border-radius: 6px; min-width: 0; }
legend { font-weight: bold; padding: 0 5px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.9em; background: var(--vscode-textCodeBlock-background); padding: 8px; max-height: 340px; overflow-y: auto; }
small { color: var(--vscode-descriptionForeground); }
#status { padding: 7px 0; overflow-wrap: anywhere; }
.diff { max-height: 420px; }
</style></head><body>
<header><strong>AXONVERTEX · Operator Workbench</strong>
<small>Read-only · Node A · 0.7D1. No approvals, tool calls, model calls or source edits.</small>
<label for="runs">Durable investigation</label><select id="runs" aria-label="Durable investigation"></select>
<button id="refresh" type="button">Refresh evidence</button><div id="status" role="status" aria-live="polite">Loading…</div></header>
<main id="sections"></main>
<script nonce="${nonce}">
(() => {
'use strict';
const vscode = acquireVsCodeApi();
const select = document.getElementById('runs');
const status = document.getElementById('status');
const sections = document.getElementById('sections');
const refresh = document.getElementById('refresh');
function dump(label, data, css = '') {
  const fieldset = document.createElement('fieldset');
  const legend = document.createElement('legend'); legend.textContent = label;
  const pre = document.createElement('pre'); pre.className = css;
  pre.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  fieldset.append(legend, pre); sections.append(fieldset);
}
function show(run) {
  sections.replaceChildren();
  status.textContent = run.runId + ' · ' + (run.jobStatus || 'state not available');
  dump('Security review versions / quarantine', run.reviewVersions);
  dump('Accepted Foundation Sec reasoning', run.acceptedSecurityReview);
  dump('Candidate identity', {
    sourceSha256: run.candidate.sourceSha256,
    diffSha256: run.candidate.diffSha256,
    fixtureCommit: run.candidate.fixtureCommit,
    reviewArtifactId: run.candidate.reviewArtifactId,
  });
  dump('Candidate diff', run.candidate.unifiedDiff || '(not available from read-only review)', 'diff');
  dump('Sandbox verification', run.verification);
  dump('Recorded operator decision', run.decision);
  dump('Application result and Docker postcheck', {
    state: run.application.state,
    receiptSha256: run.application.receiptSha256,
    candidateSha256: run.application.candidateSha256,
    gitCommitCreated: run.application.gitCommitCreated,
    dockerCandidate: run.application.dockerCandidate,
  });
  dump('Application event sequence', run.application.events);
  dump('Evidence artifact references', run.artifacts);
}
window.addEventListener('message', (event) => {
  const message = event.data;
  if (!message || typeof message !== 'object') return;
  if (message.type === 'runs' && Array.isArray(message.runs)) {
    select.replaceChildren();
    for (const entry of message.runs) {
      if (!entry || typeof entry.runId !== 'string') continue;
      const option = document.createElement('option');
      option.value = entry.runId; option.textContent = entry.runId;
      select.append(option);
    }
    select.value = message.selected || '';
    status.textContent = message.runs.length ? 'Reading investigation…' : 'No local durable runs found.';
  } else if (message.type === 'run' && message.run) { show(message.run); }
  else if (message.type === 'error') { status.textContent = 'Read-only inspection failed: ' + String(message.message); }
});
select.addEventListener('change', () => {
  if (select.value) { status.textContent = 'Reading investigation…'; vscode.postMessage({ type: 'load', runId: select.value }); }
});
refresh.addEventListener('click', () => { status.textContent = 'Refreshing…'; vscode.postMessage({ type: 'refresh' }); });
vscode.postMessage({ type: 'ready' });
})();
</script></body></html>`;
  }
}
