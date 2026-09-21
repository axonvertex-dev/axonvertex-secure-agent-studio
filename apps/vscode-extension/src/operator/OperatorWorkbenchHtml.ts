/**
 * 0.7D2 display-only HTML. All backend values arrive through the 0.7D1
 * allowlisted projection and are rendered via textContent, never as HTML.
 */
export function operatorWorkbenchHtml(nonce: string): string {
  const csp = `default-src 'none'; img-src data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`;
  return `<!doctype html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AXONVERTEX Operator Workbench</title>
<style nonce="${nonce}">
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 14px; font: var(--vscode-font-size) var(--vscode-font-family); color: var(--vscode-foreground); }
header { display: grid; gap: 10px; padding-bottom: 16px; border-bottom: 1px solid var(--vscode-panel-border); }
h1 { font-size: 1.15rem; margin: 0; font-weight: 650; }
h2 { font-size: 1rem; margin: 0; }
h3 { font-size: .95rem; margin: 0 0 5px; }
p { line-height: 1.5; margin: 4px 0 8px; }
small, .muted { color: var(--vscode-descriptionForeground); }
code, .hash, .mono { font-family: var(--vscode-editor-font-family,monospace); overflow-wrap: anywhere; }
label { font-weight: 600; }
select, button { font: inherit; min-width: 0; padding: 8px; color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border,var(--vscode-panel-border)); border-radius: 5px; }
button { cursor: pointer; color: var(--vscode-button-foreground); background: var(--vscode-button-background); }
button:hover { background: var(--vscode-button-hoverBackground); }
button:focus-visible, select:focus-visible { outline: 2px solid var(--vscode-focusBorder); outline-offset: 2px; }
#status { overflow-wrap: anywhere; font-size: .9em; color: var(--vscode-descriptionForeground); }
#sections { display: grid; gap: 12px; padding: 14px 0 30px; }
.panel { border: 1px solid var(--vscode-panel-border); border-radius: 8px; overflow: hidden; min-width: 0; }
.panel-head { padding: 11px 12px; border-bottom: 1px solid var(--vscode-panel-border); background: var(--vscode-sideBarSectionHeader-background); }
.panel-body { padding: 12px; display: grid; gap: 9px; }
.header-sub { font-size: .88em; margin-top: 4px; }
.state-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,150px),1fr)); gap: 9px; }
.state { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 11px; min-width: 0; }
.state-label { font-size: .81em; color: var(--vscode-descriptionForeground); }
.state-value { font-size: 1.05em; font-weight: 650; overflow-wrap: anywhere; margin-top: 6px; }
.pill { display: inline-flex; align-items: center; max-width: 100%; padding: 3px 8px; border-radius: 100px; border: 1px solid var(--vscode-panel-border); font-size: .82em; overflow-wrap: anywhere; }
.good { border-left: 3px solid var(--vscode-testing-iconPassed,#3c9c67); }
.warn { border-left: 3px solid var(--vscode-editorWarning-foreground,#cca700); }
.bad { border-left: 3px solid var(--vscode-testing-iconFailed,#d84948); }
.neutral { border-left: 3px solid var(--vscode-panel-border); }
.timeline { list-style: none; margin: 0; padding: 0 0 0 10px; display: grid; gap: 12px; }
.timeline li { border-left: 2px solid var(--vscode-panel-border); padding: 0 0 1px 13px; position: relative; min-width: 0; }
.timeline li::before { content: ''; position: absolute; left: -5px; top: 3px; width: 8px; height: 8px; border-radius: 50%; background: var(--vscode-descriptionForeground); }
.timeline li.good::before { background: var(--vscode-testing-iconPassed,#3c9c67); }
.timeline li.bad::before { background: var(--vscode-testing-iconFailed,#d84948); }
.timeline li.warn::before { background: var(--vscode-editorWarning-foreground,#cca700); }
.timeline li.good,.timeline li.bad,.timeline li.warn { border-left-width: 2px; }
.kv { display: grid; grid-template-columns: minmax(95px, 1fr) minmax(0,2fr); gap: 6px 12px; margin: 0; }
.kv dt { color: var(--vscode-descriptionForeground); }
.kv dd { margin: 0; overflow-wrap: anywhere; }
.hash { font-size: .82em; }
.diff { margin: 0; overflow-x: auto; max-height: 580px; background: var(--vscode-editor-background); border: 1px solid var(--vscode-panel-border); padding: 5px 0; font: .9em/1.55 var(--vscode-editor-font-family,monospace); }
.diff-line { display: block; white-space: pre; min-width: max-content; padding: 0 10px; }
.diff-add { background: var(--vscode-diffEditor-insertedLineBackground,rgba(35,134,54,.19)); }
.diff-remove { background: var(--vscode-diffEditor-removedLineBackground,rgba(248,81,73,.16)); }
.diff-meta { color: var(--vscode-descriptionForeground); }
.diff-hunk { color: var(--vscode-textLink-foreground); }
.compare { width: 100%; border-collapse: collapse; table-layout: fixed; }
.compare th,.compare td { padding: 7px 5px; border-bottom: 1px solid var(--vscode-panel-border); text-align: left; overflow-wrap: anywhere; }
.compare th { font-size: .85em; color: var(--vscode-descriptionForeground); }
.compare .num { font-variant-numeric: tabular-nums; }
.artifact { border: 1px solid var(--vscode-panel-border); border-radius: 5px; padding: 9px; min-width: 0; }
.artifact .hash { display: block; padding-top: 5px; }
.empty { padding: 12px; color: var(--vscode-descriptionForeground); border: 1px dashed var(--vscode-panel-border); border-radius: 5px; }
@media (max-width: 370px) { body { padding: 9px; } .kv { grid-template-columns: 1fr; gap: 3px; } .kv dd { padding-bottom: 9px; } }
</style></head><body>
<header>
<h1>AXONVERTEX · Operator Workbench</h1>
<small>Read-only · Node A · 0.7D2. No approval, application, model or tool execution controls.</small>
<label for="runs">Durable investigation</label>
<select id="runs" aria-label="Durable investigation"></select>
<button id="refresh" type="button">Refresh evidence</button>
<div id="status" role="status" aria-live="polite">Loading…</div>
</header>
<main id="sections"></main>
<script nonce="${nonce}">
(() => {
'use strict';
const vscode = acquireVsCodeApi();
const select = document.getElementById('runs');
const status = document.getElementById('status');
const sections = document.getElementById('sections');
const refresh = document.getElementById('refresh');
const create = (tag, cls, value) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
};
const text = (value, fallback = 'Not recorded') => value === '' || value === null || value === undefined ? fallback : String(value);
function panel(title, note) {
  const parent = create('section','panel');
  const head = create('div','panel-head');
  head.append(create('h2','',title));
  if (note) head.append(create('div','header-sub muted',note));
  const body = create('div','panel-body');
  parent.append(head,body); sections.append(parent);
  return body;
}
function empty(body, message) { body.append(create('div','empty',message)); }
function kv(body, entries) {
  const dl = create('dl','kv');
  for (const [key,value,mono] of entries) {
    dl.append(create('dt','',key),create('dd',mono ? 'hash' : '',text(value)));
  }
  body.append(dl);
}
function tone(state) {
  if (['APPLIED','APPROVE','VERIFIED','PASS','ACCEPTED','APPLY_COMPLETED'].includes(state)) return 'good';
  if (['REJECT','REJECTED','FAIL','FAILED','QUARANTINED'].includes(state)) return 'bad';
  if (['AUTHORIZED','APPLY_STARTED','PENDING'].includes(state)) return 'warn';
  return 'neutral';
}
function statusCard(label, value, sub, state) {
  const card = create('div','state ' + tone(state));
  card.append(create('div','state-label',label),create('div','state-value',text(value)));
  if (sub) card.append(create('div','muted header-sub',sub));
  return card;
}
function timeline(body, items) {
  if (!items.length) { empty(body,'No events recorded.'); return; }
  const list = create('ol','timeline');
  for (const item of items) {
    const row = create('li',item.tone || 'neutral');
    row.append(create('h3','',item.title));
    if (item.detail) row.append(create('p','',item.detail));
    if (item.id) row.append(create('div','hash muted',item.id));
    if (item.time) row.append(create('small','',item.time));
    list.append(row);
  }
  body.append(list);
}
function verification(body, baseline, candidate) {
  const table = create('table','compare');
  const caption = create('caption','muted','Observed fixture test counts; no production exploitability claim.');
  const head = create('thead');
  const headRow = create('tr');
  ['Test','Baseline','Candidate'].forEach(x => headRow.append(create('th','',x)));
  head.append(headRow);
  const rows = create('tbody');
  for (const [key,label] of [['normal_rows','Normal lookup'],['nonexistent_rows','Nonexistent lookup'],['attack_rows','Controlled injection']]) {
    const row = create('tr');
    row.append(create('td','',label));
    for (const values of [baseline,candidate]) {
      const value = values && Object.prototype.hasOwnProperty.call(values,key) ? values[key] : null;
      row.append(create('td','num',value === null || value === undefined ? 'Not measured' : value));
    }
    rows.append(row);
  }
  table.append(caption,head,rows); body.append(table);
}
function diff(body, unifiedDiff) {
  if (!unifiedDiff) { empty(body,'No candidate diff available from the inspection record.'); return; }
  const block = create('pre','diff');
  const lines = unifiedDiff.split('\\n');
  if (lines[lines.length - 1] === '') lines.pop();
  for (const line of lines) {
    let cls = 'diff-line';
    if (line.startsWith('+++ ') || line.startsWith('--- ')) cls += ' diff-meta';
    else if (line.startsWith('+')) cls += ' diff-add';
    else if (line.startsWith('-')) cls += ' diff-remove';
    else if (line.startsWith('@@')) cls += ' diff-hunk';
    block.append(create('span',cls,line || ' '));
  }
  body.append(block);
}
function show(run) {
  sections.replaceChildren();
  status.textContent = text(run.runId,'Unknown run') + ' · Read-only evidence loaded';
  const decision = run.decision || {};
  const application = run.application || {};
  const verificationData = run.verification || {};
  const review = run.acceptedSecurityReview || {};
  const candidate = run.candidate || {};
  const versions = Array.isArray(run.reviewVersions) ? run.reviewVersions : [];
  const events = Array.isArray(application.events) ? application.events : [];
  const artifacts = Array.isArray(run.artifacts) ? run.artifacts : [];
  let body = panel('Recorded lifecycle states','Separate ledgers: the investigation status is not rewritten after approval or application.');
  const cards = create('div','state-grid');
  cards.append(
    statusCard('Investigation',run.jobStatus || 'NOT_RECORDED','Workflow status',run.jobStatus === 'VERIFIED_CANDIDATE_AWAITING_APPROVAL' ? 'VERIFIED' : run.jobStatus),
    statusCard('Operator decision',decision.state || 'NOT_RECORDED',text(decision.reasonCode,'No decision receipt'),decision.state),
    statusCard('Application',application.state || 'NOT_AUTHORIZED','Separate application ledger',application.state)
  );
  body.append(cards);
  body = panel('Security review and recovery','Versioned review history retained; invalid references are not silently repaired.');
  timeline(body, versions.map((v,i) => ({
    title: (i + 1) + '. ' + text(v.artifactType,'Review') + (v.accepted ? ' · Accepted' : ' · Not accepted'),
    detail: Array.isArray(v.validationErrors) && v.validationErrors.length ? v.validationErrors.join(' · ') : 'No validator errors recorded',
    id: 'SHA-256: ' + text(v.contentSha256),
    tone: v.accepted ? 'good' : 'bad',
  })));
  body = panel('Accepted Foundation Sec reasoning','Model assessment grounded in the cited evidence; deployment claims are not inferred.');
  kv(body,[
    ['Review accepted',review.accepted ? 'Yes' : 'No'],
    ['Reviewer model',review.model],['Node',review.node],
    ['Source pattern',review.sourcePattern],['External exploitability',review.externalExploitability],
    ['Missing evidence',Array.isArray(review.missingEvidence) ? review.missingEvidence.join(' · ') : ''],
    ['Evidence IDs',Array.isArray(review.evidenceIds) ? review.evidenceIds.join(' · ') : '',true],
  ]);
  body = panel('Candidate and remediation','Exact candidate identity and the proposed source change.');
  kv(body,[
    ['Source SHA-256',candidate.sourceSha256,true],['Diff SHA-256',candidate.diffSha256,true],
    ['Fixture commit',candidate.fixtureCommit,true],['Accepted review artifact',candidate.reviewArtifactId,true],
  ]);
  diff(body,candidate.unifiedDiff);
  body = panel('Sandbox verification','Baseline and candidate counts from the same synthetic fixture.');
  body.append(create('span','pill ' + (verificationData.passed ? 'good' : 'neutral'),verificationData.passed ? 'Verification passed' : 'Verification not confirmed'));
  body.append(create('small','',verificationData.originalFixtureUnchanged ? 'Original fixture unchanged' : 'Original fixture unchanged: not confirmed'));
  verification(body,verificationData.baseline,verificationData.candidate);
  body = panel('Operator decision','Recorded by the existing local operator decision ledger; this view cannot approve.');
  kv(body,[['Decision',decision.state],['Reason code',decision.reasonCode],
    ['Identity assurance',decision.identityAssurance],['Decision receipt SHA-256',decision.receiptSha256,true]]);
  body = panel('Application and postcheck','Separate authorization, execution and Docker-backed result; no Git commit is implied.');
  kv(body,[['Application state',application.state],['Application receipt SHA-256',application.receiptSha256,true],
    ['Applied candidate SHA-256',application.candidateSha256,true],
    ['Git commit created',application.gitCommitCreated === null || application.gitCommitCreated === undefined ? 'Not recorded' : application.gitCommitCreated ? 'Yes' : 'No']]);
  verification(body,{},application.dockerCandidate);
  body = panel('Application event timeline','Event timestamps are displayed in UTC as recorded.');
  timeline(body, events.map(e => ({title: text(e.kind),time: text(e.createdAt,''),id:'Request ID: ' + text(e.requestId),tone: tone(e.kind)})));
  body = panel('Evidence artifact references','Allowlisted IDs and content hashes only; raw artifact payloads are not rendered.');
  if (!artifacts.length) empty(body,'No artifact references in this investigation.');
  for (const artifact of artifacts) {
    const card = create('div','artifact');
    card.append(create('strong','',text(artifact.artifactType)));
    card.append(create('div','hash',text(artifact.id)));
    card.append(create('small','hash muted','SHA-256: ' + text(artifact.contentSha256)));
    body.append(card);
  }
}
window.addEventListener('message', event => {
  const message = event.data;
  if (!message || typeof message !== 'object') return;
  if (message.type === 'runs' && Array.isArray(message.runs)) {
    select.replaceChildren();
    for (const entry of message.runs) {
      if (!entry || typeof entry.runId !== 'string') continue;
      const option = create('option','',entry.runId); option.value = entry.runId;
      select.append(option);
    }
    select.value = message.selected || '';
    status.textContent = message.runs.length ? 'Reading investigation…' : 'No local durable runs found.';
  } else if (message.type === 'run' && message.run && message.run.contractVersion === '0.7D1') {
    show(message.run);
  } else if (message.type === 'error') {
    status.textContent = 'Read-only inspection failed: ' + String(message.message).slice(0,600);
  }
});
select.addEventListener('change', () => {
  if (select.value) { status.textContent = 'Reading investigation…'; vscode.postMessage({ type: 'load', runId: select.value }); }
});
refresh.addEventListener('click', () => { status.textContent = 'Refreshing…'; vscode.postMessage({ type: 'refresh' }); });
vscode.postMessage({ type: 'ready' });
})();
</script></body></html>`;
}
