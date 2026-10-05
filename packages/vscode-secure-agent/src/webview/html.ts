import * as vscode from "vscode";
import { randomBytes } from "node:crypto";

export function dashboardHtml(webview: vscode.Webview): string {
  const nonce = randomBytes(16).toString("hex");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta
  http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"
/>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AXONVERTEX Secure Agent</title>
<style>
  :root {
    color-scheme: light dark;
    --border: var(--vscode-panel-border);
    --muted: var(--vscode-descriptionForeground);
    --ok: var(--vscode-testing-iconPassed);
    --bad: var(--vscode-testing-iconFailed);
    --warn: var(--vscode-editorWarning-foreground);
  }
  body { margin: 0; padding: 14px; font-family: var(--vscode-font-family); color: var(--vscode-foreground); }
  h2 { margin: 0 0 4px; font-size: 16px; }
  .sub { color: var(--muted); font-size: 11px; margin-bottom: 12px; }
  .actions { display: grid; grid-template-columns: 1fr; gap: 6px; margin-bottom: 14px; }
  button { border: 0; padding: 8px 10px; cursor: pointer; color: var(--vscode-button-foreground); background: var(--vscode-button-background); }
  button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
  button:disabled { opacity: .55; cursor: default; }
  .source, .gate, .error { border: 1px solid var(--border); padding: 9px; margin: 8px 0; border-radius: 4px; }
  .stage { border: 1px solid var(--border); border-left-width: 3px; padding: 9px; margin: 7px 0; border-radius: 4px; }
  .stage.running { border-left-color: var(--warn); }
  .stage.done { border-left-color: var(--ok); }
  .stage.error { border-left-color: var(--bad); }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .name { font-weight: 600; font-size: 12px; }
  .meta, .evidence { color: var(--muted); font-size: 10px; overflow-wrap: anywhere; margin-top: 4px; }
  .status { font-size: 10px; text-transform: uppercase; }
  .output { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--vscode-editor-font-family); font-size: 10px; max-height: 160px; overflow: auto; margin-top: 7px; }
  .gate.pass { border-color: var(--ok); }
  .gate.fail, .error { border-color: var(--bad); }
  .hidden { display: none; }
</style>
</head>
<body>
  <h2>AXONVERTEX Secure Agent</h2>
  <div class="sub">Registry-governed sovereign secure coding pipeline · LAB_ONLY</div>

  <div class="actions">
    <button id="run">Run Current Selection / File</button>
    <button id="configure" class="secondary">Configure Lab Secrets</button>
    <button id="clear" class="secondary">Clear Lab Secrets</button>
  </div>

  <div id="source" class="source">No run started.</div>
  <div id="error" class="error hidden"></div>

  <div id="security-scout" class="stage">
    <div class="row"><span class="name">1 · Security Scout</span><span class="status">idle</span></div>
    <div class="meta">Antares · Node B · evidence_extraction</div>
    <div class="evidence"></div><div class="output"></div>
  </div>

  <div id="coding-investigator" class="stage">
    <div class="row"><span class="name">2 · Coding Investigator</span><span class="status">idle</span></div>
    <div class="meta">Gemma · Node A · code_reasoning</div>
    <div class="evidence"></div><div class="output"></div>
  </div>

  <div id="security-critic" class="stage">
    <div class="row"><span class="name">3 · Security Critic</span><span class="status">idle</span></div>
    <div class="meta">Foundation Sec · Node C · independent_security_review</div>
    <div class="evidence"></div><div class="output"></div>
  </div>

  <div id="final-evidence-synthesizer" class="stage">
    <div class="row"><span class="name">4 · Final Evidence Synthesizer</span><span class="status">idle</span></div>
    <div class="meta">Gemma · Node A · evidence_synthesis</div>
    <div class="evidence"></div><div class="output"></div>
  </div>

  <div id="gate" class="gate">
    <div class="row"><span class="name">5 · Deterministic Quality Gate</span><span id="gateStatus" class="status">idle</span></div>
    <div id="gateText" class="meta">No model can approve itself.</div>
  </div>

<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const run = document.getElementById('run');
  const configure = document.getElementById('configure');
  const clear = document.getElementById('clear');
  const source = document.getElementById('source');
  const error = document.getElementById('error');
  const gate = document.getElementById('gate');
  const gateStatus = document.getElementById('gateStatus');
  const gateText = document.getElementById('gateText');

  const stageIds = [
    'security-scout',
    'coding-investigator',
    'security-critic',
    'final-evidence-synthesizer'
  ];

  function reset() {
    error.classList.add('hidden');
    error.textContent = '';
    gate.className = 'gate';
    gateStatus.textContent = 'idle';
    gateText.textContent = 'No model can approve itself.';
    for (const id of stageIds) {
      const el = document.getElementById(id);
      el.className = 'stage';
      el.querySelector('.status').textContent = 'idle';
      el.querySelector('.evidence').textContent = '';
      el.querySelector('.output').textContent = '';
    }
  }

  function setBusy(busy) {
    run.disabled = busy;
    configure.disabled = busy;
    clear.disabled = busy;
  }

  run.addEventListener('click', () => { reset(); setBusy(true); vscode.postMessage({ type: 'run' }); });
  configure.addEventListener('click', () => vscode.postMessage({ type: 'configureSecrets' }));
  clear.addEventListener('click', () => vscode.postMessage({ type: 'clearSecrets' }));

  window.addEventListener('message', (event) => {
    const m = event.data;
    if (m.type === 'pipeline-start') {
      source.textContent = 'Source: ' + m.sourceLabel + (m.truncated ? ' · truncated by policy' : '');
    } else if (m.type === 'stage-start') {
      const el = document.getElementById(m.id);
      el.className = 'stage running';
      el.querySelector('.status').textContent = 'running';
    } else if (m.type === 'stage-complete') {
      const s = m.stage;
      const el = document.getElementById(s.id);
      el.className = 'stage done';
      el.querySelector('.status').textContent = 'allowed';
      el.querySelector('.evidence').textContent =
        s.evidence.runtimeId + ' · ' + s.evidence.modelId + ' · ' +
        s.evidence.resolutionId + ' · ' + s.elapsedMs + 'ms';
      el.querySelector('.output').textContent = s.content;
    } else if (m.type === 'gate') {
      gateStatus.textContent = m.gate.status;
      gate.className = 'gate ' + (m.gate.status === 'PASS' ? 'pass' : 'fail');
      const assessment = m.gate.assessment
        ? m.gate.assessment.verdict + ' · ' + m.gate.assessment.cwe + ' · ' + m.gate.assessment.primaryFinding
        : '';
      gateText.textContent = [assessment, ...(m.gate.reasons || [])].filter(Boolean).join(' | ') || 'All deterministic checks passed.';
      setBusy(false);
    } else if (m.type === 'pipeline-error') {
      error.textContent = m.message;
      error.classList.remove('hidden');
      setBusy(false);
    } else if (m.type === 'run-finished') {
      setBusy(false);
    }
  });
</script>
</body>
</html>`;
}
