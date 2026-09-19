# Checkpoint 2E-0.4D1 — Resident Gemma Gateway

## Why
The v04C scheduler is per-process. The Python durable bridge bypasses it. This additive checkpoint creates a loopback-only HTTP gateway with exactly one `SharedInferenceScheduler` instance. It reuses `SharedGemmaClient` and the frozen Node A SGLang backend. It does not modify the backend or the v0.1.7 workflow.

## Contracts
- Binds only `127.0.0.1:17712`; do not proxy it onto public interfaces.
- Distinct secret bearer token for each lane (`chat`, `workflow`, `background`), all different from `GEMMA_API_KEY`; no token is logged.
- Header `X-Axonvertex-Lane` must match the provided lane token. `X-Axonvertex-Task-Id` and `X-Axonvertex-Context-Id` are required.
- `POST /v1/chat/completions` accepts only validated non-streaming, temperature-zero, thinking-off Gemma requests. Tools, schemas, alternate models, unknown options are rejected. Output cap: 2048 tokens. Request body cap: 128KiB.
- `GET /health` exposes scheduler queue sizes, not prompts or credentials.
- Response compatible with basic OpenAI chat completion envelopes. HTTP headers contain queue/inference milliseconds.
- Queue admission is process-wide **only for requests sent to this gateway**. Do not claim global admission while clients still use direct SGLang.
- This is a prototype resident process. Gateway queue is volatile. Durable jobs belong in the SQLite Agent Runtime; reconnect/retry and at-least-once inference semantics remain necessary.
- Priority pertains to queue order **between** inferences, not mid-inference preemption. Model execution timeout is not a guarantee a disconnected backend has stopped.
- Lane tokens provide capability to choose the queue; protect them independently. Loopback binding prevents external access but any local user knowing a lane key may call it. Add process isolation/service ACLs later.

## Install
Unzip into repo, run scheduler and gateway unit tests, populate distinct `GEMMA_GATEWAY_{CHAT,WORKFLOW,BACKGROUND}_KEY` in ignored .env (do not display values), run `node --env-file=.env --experimental-strip-types packages/model-client/tools/start-gemma-gateway.mjs` in a **dedicated** Node A terminal.

Second Node A terminal: `node --env-file=.env --experimental-strip-types packages/model-client/tools/probe-gemma-gateway.mjs`. Success requires CHAT_GATEWAY_OK and WORKFLOW_GATEWAY_OK.

## Next checkpoint
v04D2 modifies only the feature-branch Python bridge to opt in to `GEMMA_GATEWAY_BASE_URL=http://127.0.0.1:17712/v1` and its workflow token, adds task/context headers, and verifies a real durable `resume` call and live interactive chat both reach this one gateway. No direct fallback if gateway is down. Do not mark v04D global until that is observed.
