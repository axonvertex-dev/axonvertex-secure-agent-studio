import * as crypto from 'node:crypto';
import * as vscode from 'vscode';
import { ReadOnlyRunAdapter } from './ReadOnlyRunAdapter';
import { operatorWorkbenchHtml } from './OperatorWorkbenchHtml';

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

  private html(_webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(20).toString('hex');
    return operatorWorkbenchHtml(nonce);
  }
}
