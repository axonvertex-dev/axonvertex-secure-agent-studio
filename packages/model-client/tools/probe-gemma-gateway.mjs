/** Live proof of resident HTTP gateway with both authenticated lanes. */
import {randomUUID} from 'node:crypto';
const model=process.env.GEMMA_MODEL;
if(!model) throw new Error('MISSING_GEMMA_MODEL');
const root='http://127.0.0.1:17712';
const health=await fetch(root+'/health').then(r=>r.json());
if(health.status!=='ok') throw new Error('GATEWAY_UNHEALTHY');
async function probe(lane, expected){
  const token=process.env[`GEMMA_GATEWAY_${lane.toUpperCase()}_KEY`];
  if(!token) throw new Error('MISSING_GATEWAY_LANE_KEY');
  const taskId=`gateway-${lane}-${randomUUID()}`;
  const r=await fetch(root+'/v1/chat/completions',{
    method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json',
      'X-Axonvertex-Lane':lane,'X-Axonvertex-Task-Id':taskId,
      'X-Axonvertex-Context-Id':`${lane}:checkpoint-2e04d1`},
    body:JSON.stringify({model,messages:[{role:'system',content:`Return exactly ${expected}.`},
      {role:'user',content:`Return exactly ${expected} and nothing else.`}],
      temperature:0,max_tokens:64,stream:false,chat_template_kwargs:{enable_thinking:false}})});
  if(!r.ok) throw new Error(`GATEWAY_${lane}_HTTP_${r.status}`);
  const body=await r.json();
  const content=body.choices?.[0]?.message?.content?.trim();
  return {lane,status:r.status,pass:content===expected,output:content,
    queuedMs:Number(r.headers.get('x-axonvertex-queue-ms')),
    inferenceMs:Number(r.headers.get('x-axonvertex-inference-ms'))};
}
const result=await Promise.all([probe('chat','CHAT_GATEWAY_OK'),probe('workflow','WORKFLOW_GATEWAY_OK')]);
console.log(JSON.stringify({health,results:result},null,2));
if(result.some(r=>!r.pass)) process.exitCode=2;
