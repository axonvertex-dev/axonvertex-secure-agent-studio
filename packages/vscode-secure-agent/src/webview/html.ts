import * as vscode from "vscode";
import { randomBytes } from "node:crypto";

export function dashboardHtml(webview: vscode.Webview): string {
  const nonce = randomBytes(16).toString("hex");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AXONVERTEX Secure Agent</title>
<style>
:root{color-scheme:light dark;--border:var(--vscode-panel-border);--muted:var(--vscode-descriptionForeground);--ok:var(--vscode-testing-iconPassed);--bad:var(--vscode-testing-iconFailed);--warn:var(--vscode-editorWarning-foreground)}
body{margin:0;padding:14px;font-family:var(--vscode-font-family);color:var(--vscode-foreground)}
h2{margin:0 0 4px;font-size:16px}.sub,.meta,.evidence{color:var(--muted);font-size:10px}.actions{display:grid;gap:6px;margin:12px 0}
button{border:0;padding:8px 10px;cursor:pointer;color:var(--vscode-button-foreground);background:var(--vscode-button-background)}
button.secondary{color:var(--vscode-button-secondaryForeground);background:var(--vscode-button-secondaryBackground)}
button.deny{border:1px solid var(--bad);color:var(--vscode-foreground);background:transparent}
button:disabled{opacity:.55}.box,.stage{border:1px solid var(--border);padding:9px;margin:7px 0;border-radius:4px}
.stage{border-left-width:3px}.stage.running{border-left-color:var(--warn)}.stage.done{border-left-color:var(--ok)}
.row{display:flex;justify-content:space-between;gap:8px}.name{font-weight:600;font-size:12px}.status{font-size:10px;text-transform:uppercase}
.output{white-space:pre-wrap;overflow-wrap:anywhere;font-family:var(--vscode-editor-font-family);font-size:10px;max-height:145px;overflow:auto;margin-top:6px}
.gate.pass,.approval.approved{border-color:var(--ok)}.gate.fail,.error,.approval.denied{border-color:var(--bad)}
.approval.ready{border-color:var(--warn)}.approval-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}.hidden{display:none}
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
<div id="source" class="box">No run started.</div>
<div id="error" class="box error hidden"></div>

${[
  ["security-scout","1 · Security Scout","Antares · Node B · evidence_extraction"],
  ["coding-investigator","2 · Coding Investigator","Gemma · Node A · code_reasoning"],
  ["security-critic","3 · Security Critic","Foundation Sec · Node C · independent_security_review"],
  ["final-evidence-synthesizer","4 · Final Evidence Synthesizer","Gemma · Node A · evidence_synthesis"]
].map(([id,name,meta])=>`
<div id="${id}" class="stage">
<div class="row"><span class="name">${name}</span><span class="status">idle</span></div>
<div class="meta">${meta}</div><div class="evidence"></div><div class="output"></div>
</div>`).join("")}

<div id="gate" class="box gate">
<div class="row"><span class="name">5 · Deterministic Quality Gate</span><span id="gateStatus" class="status">idle</span></div>
<div id="gateText" class="meta">No model can approve itself.</div>
</div>

<div id="approval" class="box approval hidden">
<div class="row"><span class="name">6 · Human Remediation Gate</span><span id="approvalStatus" class="status">waiting</span></div>
<div id="approvalText" class="meta"></div>
<div id="approvalActions" class="approval-actions hidden">
<button id="approvePatch">APPROVE PATCH</button>
<button id="denyPatch" class="deny">DENY</button>
</div>
</div>

<script nonce="${nonce}">
const vscode=acquireVsCodeApi();
const run=document.getElementById('run'),configure=document.getElementById('configure'),clear=document.getElementById('clear');
const source=document.getElementById('source'),error=document.getElementById('error'),gate=document.getElementById('gate'),gateStatus=document.getElementById('gateStatus'),gateText=document.getElementById('gateText');
const approval=document.getElementById('approval'),approvalStatus=document.getElementById('approvalStatus'),approvalText=document.getElementById('approvalText'),approvalActions=document.getElementById('approvalActions');
const ids=['security-scout','coding-investigator','security-critic','final-evidence-synthesizer'];
function reset(){error.classList.add('hidden');gate.className='box gate';gateStatus.textContent='idle';gateText.textContent='No model can approve itself.';approval.className='box approval hidden';approvalActions.classList.add('hidden');ids.forEach(id=>{const e=document.getElementById(id);e.className='stage';e.querySelector('.status').textContent='idle';e.querySelector('.evidence').textContent='';e.querySelector('.output').textContent=''})}
function busy(v){run.disabled=v;configure.disabled=v;clear.disabled=v}
run.onclick=()=>{reset();busy(true);vscode.postMessage({type:'run'})};
configure.onclick=()=>vscode.postMessage({type:'configureSecrets'});
clear.onclick=()=>vscode.postMessage({type:'clearSecrets'});
document.getElementById('approvePatch').onclick=()=>vscode.postMessage({type:'approvePatch'});
document.getElementById('denyPatch').onclick=()=>vscode.postMessage({type:'denyPatch'});
window.addEventListener('message',event=>{
 const m=event.data;
 if(m.type==='pipeline-start') source.textContent='Source: '+m.sourceLabel+(m.truncated?' · truncated by policy':'');
 else if(m.type==='stage-start'){const e=document.getElementById(m.id);e.className='stage running';e.querySelector('.status').textContent='running'}
 else if(m.type==='stage-complete'){const s=m.stage,e=document.getElementById(s.id);e.className='stage done';e.querySelector('.status').textContent='allowed';e.querySelector('.evidence').textContent=s.evidence.runtimeId+' · '+s.evidence.modelId+' · '+s.evidence.resolutionId+' · '+s.elapsedMs+'ms';e.querySelector('.output').textContent=s.content}
 else if(m.type==='gate'){gateStatus.textContent=m.gate.status;gate.className='box gate '+(m.gate.status==='PASS'?'pass':'fail');const a=m.gate.assessment?m.gate.assessment.verdict+' · '+m.gate.assessment.cwe+' · '+m.gate.assessment.primaryFinding:'';gateText.textContent=[a,...(m.gate.reasons||[])].filter(Boolean).join(' | ')||'All deterministic checks passed.';busy(false)}
 else if(m.type==='approval-required'){approval.className='box approval ready';approvalStatus.textContent='HUMAN DECISION REQUIRED';approvalText.textContent=m.cwe+' · '+m.title+' · '+m.summary+' · Review the red/green VS Code diff before deciding.';approvalActions.classList.remove('hidden')}
 else if(m.type==='approval-unavailable'){approval.className='box approval';approvalStatus.textContent='NOT AVAILABLE';approvalText.textContent=m.message}
 else if(m.type==='approval-result'){approvalActions.classList.add('hidden');approvalStatus.textContent=m.decision;approvalText.textContent=m.detail;approval.className='box approval '+(m.decision==='APPROVED_AND_VERIFIED'?'approved':'denied')}
 else if(m.type==='pipeline-error'){error.textContent=m.message;error.classList.remove('hidden');busy(false)}
 else if(m.type==='run-finished')busy(false);
});
</script>
</body></html>`;
}
