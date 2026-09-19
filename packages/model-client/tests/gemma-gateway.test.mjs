import test from 'node:test';
import assert from 'node:assert/strict';
import {createGemmaGateway} from '../src/gemma-gateway.ts';
const chatKey = 'C'.repeat(48), workflowKey='W'.repeat(48), backgroundKey='B'.repeat(48);
const cfg={model:'gemma-4-12b-it-qat',chatKey,workflowKey,backgroundKey};
function defer(){let release; const promise=new Promise(resolve=>release=resolve);return {promise,release};}
let seq=0;
async function withServer(provider,run,cfgOverride={}){
 const server=createGemmaGateway({...cfg,...cfgOverride},provider);
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{return await run(`http://127.0.0.1:${server.address().port}`);}finally{await new Promise(resolve=>server.close(resolve));}
}
const provider={complete: async messages=>({content:messages.at(-1).content,finishReason:'stop',usage:{prompt_tokens:4,completion_tokens:4}})};
function opts(lane='chat',overrides={}){
 return {method:'POST',headers:{Authorization:`Bearer ${{chat:chatKey,workflow:workflowKey,background:backgroundKey}[lane]}`,
 'Content-Type':'application/json','X-Axonvertex-Lane':lane,
 'X-Axonvertex-Task-Id':`test-${++seq}`,'X-Axonvertex-Context-Id':`ctx:${lane}`},
 body:JSON.stringify({model:cfg.model,messages:[{role:'user',content:'private-'+lane}],temperature:0,max_tokens:50,stream:false,
 chat_template_kwargs:{enable_thinking:false},...overrides})};
}
test('health exposes queue metadata but not credentials or prompts',async()=>{
 await withServer(provider,async url=>{const result=await fetch(url+'/health');const text=await result.text();
 assert.equal(result.status,200);assert.equal(JSON.parse(text).scheduler.active,0);
 for(const value of [chatKey,workflowKey,backgroundKey,'private-chat']) assert.ok(!text.includes(value));});
});
test('separate authenticated chat/workflow lanes and stateless messages',async()=>{
 await withServer(provider,async url=>{const a=await fetch(url+'/v1/chat/completions',opts());
 const b=await fetch(url+'/v1/chat/completions',opts('workflow'));
 assert.equal((await a.json()).choices[0].message.content,'private-chat');
 assert.equal((await b.json()).choices[0].message.content,'private-workflow');
 assert.ok(Number(b.headers.get('x-axonvertex-queue-ms'))>=0);});
});
test('lane credentials cannot self-promote to another lane',async()=>{
 await withServer(provider,async url=>{const o=opts('workflow');o.headers['X-Axonvertex-Lane']='chat';
 const r=await fetch(url+'/v1/chat/completions',o);assert.equal(r.status,401);});
});
test('unauthenticated request denied before model call',async()=>{
 let calls=0;await withServer({complete:async()=>{calls++;throw Error('private');}},async url=>{
 const o=opts();delete o.headers.Authorization;const r=await fetch(url+'/v1/chat/completions',o);
 assert.equal(r.status,401);assert.equal(calls,0);});
});
test('rejects tools and unsupported inference parameters',async()=>{
 await withServer(provider,async url=>{for(const invalid of [{tools:[]},{temperature:1},{stream:true},
 {model:'other'},{max_tokens:2049},{chat_template_kwargs:{enable_thinking:true}}]){
 const r=await fetch(url+'/v1/chat/completions',opts('workflow',invalid));assert.equal(r.status,400);
 }});
});
test('global admission across independent callers is single-inference',async()=>{
 let active=0,peak=0;const barrier=defer();
 const gateProvider={complete:async messages=>{active++;peak=Math.max(peak,active);
 await barrier.promise;active--;return {content:messages[0].content,finishReason:'stop',usage:{}};}};
 await withServer(gateProvider,async url=>{
 const requests=[opts(),opts('workflow'),opts('chat')];
 const calls=requests.map(o=>fetch(url+'/v1/chat/completions',o));
 await new Promise(resolve=>setTimeout(resolve,20));assert.equal(peak,1);
 barrier.release();const results=await Promise.all(calls);
 assert.deepEqual(results.map(r=>r.status),[200,200,200]);assert.equal(peak,1);
 });
});
test('full queue refuses overload while preserving active task',async()=>{
 const barrier=defer(),started=defer();let calls=0;
 const gateProvider={complete:async()=>{calls++;started.release();await barrier.promise;
 return {content:'ok',finishReason:'stop',usage:{}};}};
 await withServer(gateProvider,async url=>{
 const first=fetch(url+'/v1/chat/completions',opts());await started.promise;
 const second=fetch(url+'/v1/chat/completions',opts('workflow'));
 await new Promise(resolve=>setTimeout(resolve,25));
 const third=await fetch(url+'/v1/chat/completions',opts());
 assert.equal(third.status,503);assert.equal((await third.json()).error.code,'QUEUE_FULL');
 barrier.release();await Promise.all([first,second]);assert.equal(calls,2);
 },{maxQueued:1});
});
test('model failures never expose backend error text',async()=>{
 await withServer({complete:async()=>{throw Error('private-user-prompt internal token');}},async url=>{
 const r=await fetch(url+'/v1/chat/completions',opts());const text=await r.text();
 assert.equal(r.status,502);assert.ok(!text.includes('private-user-prompt'));assert.ok(!text.includes('token'));
 });
});
test('rejects insecure config',()=>{
 assert.throws(()=>createGemmaGateway({...cfg,workflowKey:chatKey},provider),/INVALID_GATEWAY_AUTH_CONFIG/);
 assert.throws(()=>createGemmaGateway({...cfg,upstreamKey:workflowKey},provider),/INVALID_GATEWAY_AUTH_CONFIG/);
});
