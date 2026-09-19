/** Live acceptance: one Node process, two real Gemma lanes and concurrent real Antares scout.
 * Controlled fixture only. Does NOT route durable_live_bridge.py resume through this scheduler.
 */
import {spawn, spawnSync} from 'node:child_process';
import {SharedInferenceScheduler} from '../src/inference-scheduler.ts';
import {SharedGemmaClient} from '../src/shared-gemma-client.ts';

const runId = process.argv[2];
if (!runId || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/.test(runId)) {
  console.error('Usage: node --env-file=.env --experimental-strip-types packages/model-client/tools/prove-chat-while-scout.mjs <prepared-run-id>');
  process.exit(2);
}
const python= 'services/benchmark-runner/.venv/bin/python';
const bridge='services/benchmark-runner/src/benchmark_runner/durable_live_bridge_v04b.py';
function inspect() {
  const r=spawnSync(python,[bridge,'inspect','--run-id',runId],{encoding:'utf8',timeout:15000});
  if (r.status!==0) throw new Error('DURABLE_INSPECT_FAILED: '+(r.stderr??'').slice(-300));
  return JSON.parse(r.stdout);
}
const initial=inspect();
if (initial.status!=='WAITING_FOR_SCOUT') throw new Error('RUN_MUST_BE_WAITING_FOR_SCOUT: '+initial.status);
for(const key of ['GEMMA_API_KEY','GEMMA_BASE_URL','GEMMA_MODEL']) {
  if(!process.env[key]) throw new Error('MISSING_CONFIG_'+key);
}
const model=new SharedGemmaClient({baseUrl:process.env.GEMMA_BASE_URL,
  apiKey:process.env.GEMMA_API_KEY,model:process.env.GEMMA_MODEL});
const events=[];
const scheduler=new SharedInferenceScheduler({onEvent:event=>events.push(event)});
const scoutStarted=Date.now();
const scout=spawn(python,[bridge,'scout','--run-id',runId],{stdio:['ignore','pipe','pipe']});
let scoutOut='',scoutErr='';
scout.stdout.setEncoding('utf8'); scout.stderr.setEncoding('utf8');
scout.stdout.on('data',chunk=>{scoutOut=(scoutOut+chunk).slice(-10000);});
scout.stderr.on('data',chunk=>{scoutErr=(scoutErr+chunk).slice(-1000);});
const scoutDone=new Promise((resolve,reject)=>{
  scout.on('error',reject);
  scout.on('close',code=>resolve({code,finishedMs:Date.now()}));
});
const chat=scheduler.schedule({taskId:`${runId}:chat-smoke`,contextId:`chat:${runId}`,
  lane:'chat',timeoutMs:120000,
  execute:signal=>model.complete([
    {role:'system',content:'You are the interactive AXONVERTEX chat lane. Follow exact-output requests. Do not add other task context.'},
    {role:'user',content:'Return exactly CHAT_LANE_OK and nothing else.'}
  ],signal,64)});
const workflow=scheduler.schedule({taskId:`${runId}:workflow-smoke`,contextId:`workflow:${runId}`,
  lane:'workflow',timeoutMs:120000,
  execute:signal=>model.complete([
    {role:'system',content:'You are an isolated AXONVERTEX workflow inference lane. Follow exact-output requests. Do not add chat context.'},
    {role:'user',content:'Return exactly WORKFLOW_LANE_OK and nothing else.'}
  ],signal,64)});
const settled=await Promise.allSettled([chat,workflow,scoutDone]);
const [c,w,s]=settled;
const final=inspect();
const chatStarted=events.find(e=>e.taskId===`${runId}:chat-smoke`&&e.type==='STARTED')?.timestampMs;
const chatFinished=events.find(e=>e.taskId===`${runId}:chat-smoke`&&e.type==='FINISHED')?.timestampMs;
const scoutEnd=s.status==='fulfilled'?s.value.finishedMs:null;
const summary={runId,scoutStarted,scoutEnd,
  initialState:initial.status, finalState:final.status,
  chat:c.status==='fulfilled'?{content:c.value.value.content.trim(),queueMs:c.value.queuedMs,
    inferenceMs:c.value.executionMs}:{error:c.reason?.message??'unknown'},
  workflow:w.status==='fulfilled'?{content:w.value.value.content.trim(),queueMs:w.value.queuedMs,
    inferenceMs:w.value.executionMs}:{error:w.reason?.message??'unknown'},
  scoutExit:s.status==='fulfilled'?s.value.code:null,
  scoutError:s.status==='rejected'?s.reason.message:(s.value.code===0?null:scoutErr),
  chatOverlappedScout:Boolean(chatStarted&&chatFinished&&scoutEnd&&chatStarted<scoutEnd&&scoutStarted<chatFinished),
  schedulerEvents:events};
console.log(JSON.stringify(summary,null,2));
if (final.status!=='READY_TO_RESUME'|| s.status!=='fulfilled'||s.value.code!==0 ||
  c.status!=='fulfilled'||w.status!=='fulfilled'||
  c.value.value.content.trim()!=='CHAT_LANE_OK'||w.value.value.content.trim()!=='WORKFLOW_LANE_OK'||
  !summary.chatOverlappedScout) process.exitCode=2;
