import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import * as vscode from 'vscode';
import type { OperatorRunListItem, OperatorRunView } from '../../../../packages/shared-types/operator-view';
import { normalizeOperatorRun } from './normalize';

const execFileAsync = promisify(execFile);
const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const RESULTS = ['benchmarks', 'results', 'checkpoint2e', 'durable-live'];

async function existingDirectory(value: string): Promise<string> {
  const actual = await fs.realpath(value);
  if (!(await fs.stat(actual)).isDirectory()) {
    throw new Error('Operator repository root is not a directory.');
  }
  return actual;
}

export class ReadOnlyRunAdapter {
  private async root(): Promise<string> {
    if (!vscode.workspace.isTrusted) {
      throw new Error('Open this repository in a trusted Remote SSH workspace to inspect its local operator records.');
    }
    if (vscode.env.remoteName !== 'ssh-remote') {
      throw new Error('0.7D1 requires the extension host on Node A through VS Code Remote SSH.');
    }
    const configured = vscode.workspace.getConfiguration('agentStudio.operator')
      .get<string>('repositoryRoot', '').trim();
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const selected = configured || folder;
    if (!selected || !path.isAbsolute(selected)) {
      throw new Error('Open the Node A Agent Studio repository or configure its absolute operator.repositoryRoot.');
    }
    const resolved = await existingDirectory(selected);
    await fs.access(path.join(resolved, 'scripts', 'ops', 'review_run_v07a.py'));
    await fs.access(path.join(resolved, 'scripts', 'ops', 'operator_decision_v07b.py'));
    await fs.access(path.join(resolved, 'scripts', 'ops', 'application_execute_v07c2.py'));
    return resolved;
  }

  private async resultDirectory(repository: string): Promise<string> {
    const expected = path.join(repository, ...RESULTS);
    const actual = await existingDirectory(expected);
    if (actual !== expected) {
      throw new Error('The durable-live result directory must not be a symlink.');
    }
    return actual;
  }

  public async listRuns(): Promise<OperatorRunListItem[]> {
    const base = await this.resultDirectory(await this.root());
    const dirs = await fs.readdir(base, { withFileTypes: true });
    const result: OperatorRunListItem[] = [];
    for (const entry of dirs) {
      if (!RUN_ID.test(entry.name) || !entry.isDirectory() || entry.isSymbolicLink()) {
        continue;
      }
      result.push({ runId: entry.name });
    }
    return result.sort((a, b) => b.runId.localeCompare(a.runId)).slice(0, 200);
  }

  private async readCli(repository: string, script: string, args: string[]): Promise<unknown> {
    const venvPython = path.join(repository, 'services', 'benchmark-runner', '.venv', 'bin', 'python');
    const python = await fs.access(venvPython).then(() => venvPython, () => 'python3');
    // Do not forward raw stderr/stdout from an operator CLI to the Webview.
    let stdout: string;
    try {
      ({ stdout } = await execFileAsync(
        python,
        [path.join(repository, script), ...args],
        {
          cwd: repository,
          timeout: 30_000,
          maxBuffer: 8 * 1024 * 1024,
          windowsHide: true,
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
        },
      ));
      return JSON.parse(stdout) as unknown;
    } catch {
      throw new Error('Read-only investigation inspection failed. Check Node A CLI health locally.');
    }
  }

  public async loadRun(runId: string): Promise<OperatorRunView> {
    if (!RUN_ID.test(runId)) {
      throw new Error('Invalid run ID.');
    }
    const repository = await this.root();
    const base = await this.resultDirectory(repository);
    const runPath = path.join(base, runId);
    const stat = await fs.lstat(runPath);
    if (!stat.isDirectory() || stat.isSymbolicLink() || await fs.realpath(runPath) !== runPath) {
      throw new Error('Run must be a real directory under durable-live.');
    }
    // A Webview must not be able to request arbitrary filesystem paths or CLI arguments.
    // Scripts below are the existing read-only operator inspect commands, not decision/apply commands.
    const review = await this.readCli(repository, 'scripts/ops/review_run_v07a.py', [
      '--run-id', runId, '--include-content',
    ]);
    const decision = await this.readCli(repository, 'scripts/ops/operator_decision_v07b.py', [
      'inspect', '--run-id', runId,
    ]);
    const application = await this.readCli(repository, 'scripts/ops/application_execute_v07c2.py', [
      'inspect', '--run-id', runId,
    ]);
    const bridge = await this.readCli(
      repository,
      'services/benchmark-runner/src/benchmark_runner/durable_gateway_bridge_v04d2.py',
      ['inspect', '--run-id', runId],
    );
    return normalizeOperatorRun(runId, review, decision, application, bridge);
  }
}
