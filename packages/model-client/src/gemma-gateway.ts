/** Checkpoint 2E-0.4D1: local, resident, single-process shared Gemma admission.
 * All consumer APIs MUST route through this service to share admission.
 * This is not itself a durable queue and cannot preempt a running inference.
 */
import {createServer, type IncomingMessage, type ServerResponse, type Server} from 'node:http';
import {timingSafeEqual} from 'node:crypto';
import {SharedInferenceScheduler, type InferenceLane} from './inference-scheduler.ts';
import {SharedGemmaClient, type GemmaMessage, type GemmaResult} from './shared-gemma-client.ts';

export interface GatewayConfig {
  model: string;
  chatKey: string;
  workflowKey: string;
  backgroundKey: string;
  upstreamKey?: string;
  maxQueued?: number;
  maxBodyBytes?: number;
  requestTimeoutMs?: number;
}
export interface GatewayModel {
  complete(messages: readonly GemmaMessage[], signal: AbortSignal, maxTokens: number): Promise<GemmaResult>;
}
export const DEFAULT_PORT = 17712;
const LANES: InferenceLane[] = ['chat', 'workflow', 'background'];
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;
const errorCodes = new Set(['INVALID_JSON','INVALID_REQUEST','UNAUTHORIZED','REQUEST_TOO_LARGE',
  'QUEUE_FULL','INFERENCE_ABORTED','MODEL_FAILED','METHOD_NOT_ALLOWED','NOT_FOUND']);

function equalKey(received: string, expected: string): boolean {
  // Require same length before timing-safe check. Tokens are opaque credentials.
  const a = Buffer.from(received); const b = Buffer.from(expected);
  return a.length === b.length && a.length > 0 && timingSafeEqual(a, b);
}
function send(res: ServerResponse, code: number, data: unknown, headers: Record<string,string> = {}): void {
  if (res.destroyed || res.writableEnded) return;
  res.writeHead(code, {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers});
  res.end(JSON.stringify(data));
}
function fail(res: ServerResponse, status: number, code: string): void {
  send(res, status, {error: {code: errorCodes.has(code) ? code : 'MODEL_FAILED'}});
}
function validMessages(messages: unknown): messages is GemmaMessage[] {
  return Array.isArray(messages) && messages.length > 0 && messages.length <= 32 &&
    messages.every(m => m && typeof m === 'object' &&
      ['system','user','assistant'].includes(m.role) &&
      typeof m.content === 'string' && m.content.length <= 64000);
}
async function readBody(req: IncomingMessage, maxBytes: number): Promise<string> {
  let count = 0; const chunks: Buffer[] = [];
  for await (const chunk of req) {
    const raw = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    count += raw.length;
    if (count > maxBytes) throw new Error('REQUEST_TOO_LARGE');
    chunks.push(raw);
  }
  return Buffer.concat(chunks).toString('utf8');
}
export function createGemmaGateway(config: GatewayConfig, model: GatewayModel): Server {
  if (!config.model || !config.chatKey || !config.workflowKey || !config.backgroundKey ||
    [config.chatKey,config.workflowKey,config.backgroundKey].some(k => k.length < 24) ||
    new Set([config.chatKey,config.workflowKey,config.backgroundKey]).size !== 3 ||
    (config.upstreamKey && [config.chatKey,config.workflowKey,config.backgroundKey].includes(config.upstreamKey))) {
    throw new Error('INVALID_GATEWAY_AUTH_CONFIG');
  }
  const auth: Record<InferenceLane,string> = {chat:config.chatKey,workflow:config.workflowKey,
    background:config.backgroundKey};
  const scheduler = new SharedInferenceScheduler({maxQueued:config.maxQueued ?? 32});
  const maxBytes = config.maxBodyBytes ?? 131072;
  const timeoutMs = config.requestTimeoutMs ?? 240000;
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1024 || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1000)
    throw new Error('INVALID_GATEWAY_LIMITS');
  const server = createServer(async (req, res) => {
    if (req.method === 'GET' && req.url === '/health') {
      send(res,200,{status:'ok',service:'axonvertex-gemma-gateway',scheduler:scheduler.snapshot()});
      return;
    }
    if (req.url !== '/v1/chat/completions') {fail(res,404,'NOT_FOUND');return;}
    if (req.method !== 'POST') {fail(res,405,'METHOD_NOT_ALLOWED');return;}
    const laneValue = req.headers['x-axonvertex-lane'];
    const lane = typeof laneValue === 'string' && LANES.includes(laneValue as InferenceLane)
      ? laneValue as InferenceLane : undefined;
    const token = req.headers.authorization;
    if (!lane || typeof token !== 'string' || !token.startsWith('Bearer ') ||
      !equalKey(token.slice(7), auth[lane])) {fail(res,401,'UNAUTHORIZED');return;}
    const taskId = req.headers['x-axonvertex-task-id'];
    const contextId = req.headers['x-axonvertex-context-id'];
    if (typeof taskId !== 'string' || !SAFE_ID.test(taskId) ||
      typeof contextId !== 'string' || !SAFE_ID.test(contextId) ||
      req.headers['content-type']?.split(';')[0]?.trim() !== 'application/json') {
      fail(res,400,'INVALID_REQUEST');return;
    }
    let raw = '';
    try {raw = await readBody(req,maxBytes);}
    catch {fail(res,413,'REQUEST_TOO_LARGE');return;}
    let body: unknown;
    try {body = JSON.parse(raw);} catch {fail(res,400,'INVALID_JSON');return;}
    if (!body || typeof body !== 'object' || Array.isArray(body)) {fail(res,400,'INVALID_REQUEST');return;}
    const b = body as Record<string,unknown>;
    // Fail closed on tool arguments, arbitrary server options, streaming or wrong model.
    const allowed = new Set(['model','messages','temperature','max_tokens','stream','chat_template_kwargs']);
    if (Object.keys(b).some(k => !allowed.has(k)) ||
      b.model !== config.model || !validMessages(b.messages) ||
      (b.temperature !== undefined && b.temperature !== 0) ||
      (b.stream !== undefined && b.stream !== false) ||
      (b.chat_template_kwargs !== undefined &&
       JSON.stringify(b.chat_template_kwargs) !== '{"enable_thinking":false}') ||
      !Number.isSafeInteger(b.max_tokens) || (b.max_tokens as number) < 1 || (b.max_tokens as number) > 2048) {
      fail(res,400,'INVALID_REQUEST');return;
    }
    const abort = new AbortController();
    res.on('close', () => {if (!res.writableEnded) abort.abort();});
    try {
      const output = await scheduler.schedule({taskId,contextId,lane,signal:abort.signal,
        timeoutMs,execute:signal => model.complete(b.messages as GemmaMessage[],signal,b.max_tokens as number)});
      send(res,200,{id:`chatcmpl-${taskId}`,object:'chat.completion',created:Math.floor(Date.now()/1000),
        model:config.model,choices:[{index:0,finish_reason:output.value.finishReason,
          message:{role:'assistant',content:output.value.content}}],usage:output.value.usage},
          {'X-Axonvertex-Queue-Ms':String(output.queuedMs),
            'X-Axonvertex-Inference-Ms':String(output.executionMs)});
    } catch (err) {
      const code = err instanceof Error ? err.message : 'MODEL_FAILED';
      fail(res,code === 'INFERENCE_QUEUE_FULL' ? 503 : code === 'ABORTED' ? 504 : 502,
        code === 'INFERENCE_QUEUE_FULL' ? 'QUEUE_FULL' : code === 'ABORTED' ? 'INFERENCE_ABORTED' : 'MODEL_FAILED');
    }
  });
  server.on('close',()=>scheduler.close());
  return server;
}
export function gatewayFromEnvironment(env: NodeJS.ProcessEnv = process.env): Server {
  if (!env.GEMMA_API_KEY || !env.GEMMA_MODEL || !env.GEMMA_BASE_URL) throw new Error('MISSING_UPSTREAM_CONFIG');
  if (!env.GEMMA_GATEWAY_CHAT_KEY || !env.GEMMA_GATEWAY_WORKFLOW_KEY || !env.GEMMA_GATEWAY_BACKGROUND_KEY)
    throw new Error('MISSING_GATEWAY_LANE_KEYS');
  const client = new SharedGemmaClient({baseUrl:env.GEMMA_BASE_URL,apiKey:env.GEMMA_API_KEY,model:env.GEMMA_MODEL});
  return createGemmaGateway({model:env.GEMMA_MODEL,chatKey:env.GEMMA_GATEWAY_CHAT_KEY,
    workflowKey:env.GEMMA_GATEWAY_WORKFLOW_KEY,backgroundKey:env.GEMMA_GATEWAY_BACKGROUND_KEY,
    upstreamKey:env.GEMMA_API_KEY},client);
}
