import test from 'node:test';
import assert from 'node:assert/strict';
import { SharedInferenceScheduler } from '../src/inference-scheduler.ts';
import { SharedGemmaClient } from '../src/shared-gemma-client.ts';
const tick = () => new Promise(r => setImmediate(r));
function deferred() {let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve};}

test('one active model request even with multiple queued callers', async () => {
  const scheduler = new SharedInferenceScheduler(); let count = 0, peak = 0;
  const requests = Array.from({length: 9}, (_, i) => scheduler.schedule({
    taskId: `job-${i}`, contextId: `context-${i}`, lane: i % 2 ? 'chat' : 'workflow',
    execute: async () => {count++; peak = Math.max(peak, count); await tick(); count--; return i;}
  }));
  assert.equal((await Promise.all(requests)).length, 9);
  assert.equal(peak, 1); assert.equal(scheduler.snapshot().active, 0);
});

test('weighted fairness: chat preferred, workflow and background not starved', async () => {
  const scheduler = new SharedInferenceScheduler(); const gate = deferred(); const started = [];
  const blocker = scheduler.schedule({taskId:'block', contextId:'b', lane:'background', execute: () => gate.promise});
  await tick();
  const input = [
    ['w1','workflow'],['b1','background'],['c1','chat'],['w2','workflow'],['c2','chat'],['c3','chat']
  ];
  const pending = input.map(([taskId,lane]) => scheduler.schedule({taskId,contextId:taskId,lane,
    execute: async () => {started.push(taskId); return taskId;}}));
  gate.resolve('done'); await Promise.all([blocker,...pending]);
  assert.deepEqual(started, ['c1','c2','w1','c3','w2','b1']);
});

test('queue capacity rejects overload without taking more requests', async () => {
  const s = new SharedInferenceScheduler({maxQueued:1}); const g = deferred();
  const active = s.schedule({taskId:'active',contextId:'ctx',lane:'chat',execute: () => g.promise});
  await tick(); const queued = s.schedule({taskId:'queued',contextId:'ctx',lane:'workflow',execute: async()=>1});
  await assert.rejects(s.schedule({taskId:'excess',contextId:'ctx',lane:'chat',execute:async()=>2}), /INFERENCE_QUEUE_FULL/);
  g.resolve(0); await Promise.all([active,queued]);
});

test('duplicate task IDs rejected until result settles', async () => {
  const s = new SharedInferenceScheduler(); const g = deferred();
  const first = s.schedule({taskId:'same',contextId:'A',lane:'chat',execute:()=>g.promise});
  await assert.rejects(s.schedule({taskId:'same',contextId:'B',lane:'workflow',execute:async()=>1}),/DUPLICATE/);
  g.resolve(1); await first;
  assert.equal((await s.schedule({taskId:'same',contextId:'C',lane:'chat',execute:async()=>2})).value,2);
});

test('queued abort prevents executing cancelled request', async () => {
  const s = new SharedInferenceScheduler(); const gate = deferred();
  const first=s.schedule({taskId:'first',contextId:'a',lane:'chat',execute:()=>gate.promise});
  await tick(); let ran=false; const aborter = new AbortController();
  const second=s.schedule({taskId:'second',contextId:'b',lane:'chat',signal:aborter.signal,
    execute:async()=>{ran=true;return 1;}});
  aborter.abort(); await assert.rejects(second,/ABORTED/);
  gate.resolve(0); await first; assert.equal(ran,false);
});

test('aborting an unresponsive active transport does NOT release GPU admission early', async () => {
  const s=new SharedInferenceScheduler(); const gate=deferred(); const aborter=new AbortController();
  const active=s.schedule({taskId:'active',contextId:'a',lane:'chat',signal:aborter.signal,
    execute:async()=>gate.promise}); await tick();
  let secondRan=false;
  const second=s.schedule({taskId:'second',contextId:'b',lane:'chat',
    execute:async()=>{secondRan=true;return 2;}});
  aborter.abort(); await tick();
  assert.equal(s.snapshot().active,1); assert.equal(secondRan,false);
  gate.resolve(1); await assert.rejects(active,/ABORTED/); await second;
  assert.equal(secondRan,true);
});

test('deadline signals transport and preserves admission until it settles', async () => {
  const s = new SharedInferenceScheduler(); let signalled=false;
  const active=s.schedule({taskId:'slow',contextId:'ctx',lane:'workflow',timeoutMs:5,
    execute:signal=>new Promise((_,reject)=>{
      if(signal.aborted){reject(new Error('stopped'));return;}
      signal.addEventListener('abort',()=>{signalled=true;reject(new Error('stopped'));},{once:true});
    })});
  await assert.rejects(active); assert.equal(signalled,true); assert.equal(s.snapshot().active,0);
});

test('close rejects queued items and allows active execution to settle', async () => {
  const s=new SharedInferenceScheduler();const gate=deferred();
  const active=s.schedule({taskId:'active',contextId:'ctx',lane:'chat',execute:()=>gate.promise});await tick();
  const queued=s.schedule({taskId:'queued',contextId:'ctx',lane:'workflow',execute:async()=>2});
  s.close();await assert.rejects(queued,/SCHEDULER_CLOSED/);gate.resolve(1);await active;
  await assert.rejects(s.schedule({taskId:'later',contextId:'ctx',lane:'chat',execute:async()=>3}),/SCHEDULER_CLOSED/);
});

test('scheduler emits metadata, not prompts or API keys', async () => {
  const events=[];const scheduler=new SharedInferenceScheduler({onEvent:e=>events.push(e)});
  await scheduler.schedule({taskId:'chat-1',contextId:'chat-context-1',lane:'chat',execute:async()=> 'PRIVATE_PAYLOAD'});
  assert.deepEqual(events.map(e=>e.type),['QUEUED','STARTED','FINISHED']);
  assert.doesNotMatch(JSON.stringify(events),/PRIVATE_PAYLOAD|Bearer|api.key/i);
});

test('stateless Gemma adapter sends distinct messages and no inherited context', async () => {
  const bodies=[]; const transport=async(_url,init)=>{
    bodies.push(JSON.parse(init.body));
    return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'OK'}}],usage:{prompt_tokens:3}}),{status:200});
  };
  const client=new SharedGemmaClient({baseUrl:'http://127.0.0.1:11433/v1',apiKey:'unit-test-key',model:'gemma-test',transport});
  const signal=new AbortController().signal;
  await client.complete([{role:'system',content:'CHAT_ONLY'},{role:'user',content:'hello'}],signal);
  await client.complete([{role:'system',content:'WORKFLOW_ONLY'},{role:'user',content:'evidence'}],signal);
  assert.match(JSON.stringify(bodies[0]),/CHAT_ONLY/);
  assert.doesNotMatch(JSON.stringify(bodies[1]),/CHAT_ONLY/);
  assert.match(JSON.stringify(bodies[1]),/WORKFLOW_ONLY/);
});

test('model transport refuses partial output and does not print raw error bodies', async()=>{
  const client=new SharedGemmaClient({baseUrl:'http://localhost:11433/v1',apiKey:'fake-key',model:'model',
    transport:async()=>new Response(JSON.stringify({choices:[{finish_reason:'length',message:{content:'partial'}}]}),{status:200})});
  await assert.rejects(client.complete([{role:'user',content:'test'}],new AbortController().signal),/GEMMA_INCOMPLETE_length/);
  const fail=new SharedGemmaClient({baseUrl:'http://localhost:11433/v1',apiKey:'fake-key',model:'model',
    transport:async()=>new Response('private backend text',{status:503})});
  await assert.rejects(fail.complete([{role:'user',content:'test'}],new AbortController().signal),error=>
    error.message==='GEMMA_HTTP_503');
});
