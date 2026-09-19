# Checkpoint 2E-0.4C/1: Shared Gemma chat/workflow scheduling

## Purpose and architecture

`packages/model-client/src/inference-scheduler.ts` is a single-process, shared inference admission controller with weighted chat/workflow/background lanes (3/2/1), concurrency=1 and bounded queues. `shared-gemma-client.ts` provides stateless OpenAI-compatible authenticated Node A transport: every request carries an explicit context package; the adapter does not cache user messages. The scheduler records **only** task/context IDs, state and times, not prompts, credentials or private reasoning. It does not keep Gemma generating while a durable agent task waits for Antares.

This is not a production singleton across many API processes. All Node A Gemma callers must route through the same resident scheduler process/service for the cap and priority behavior to apply globally. The existing Python `durable_live_bridge_v04b.py` directly calls Gemma and therefore still **bypasses** this scheduler; a later integration must route it through the same scheduler host. The test below proves independent real chat and workflow inference scheduled while a real Node B scout works, not a production API, streaming, persistent chat history, or multi-user authentication.

One active request remains admitted until the underlying HTTP transport settles, including after timeout/abort; we do not release the GPU slot merely because a callback raised a cancellation signal. Cancellation and fairness behavior are tested offline. Weighted queue order may be affected by already-running work, and a long active model generation is not preempted. The scheduler queue itself is not persisted; durable Agent Runtime retains workflow tasks across restarts.

## Install (additive)

Unzip into repository root while on `feat/checkpoint2e04-durable-agent-runtime`. Adds five files in `packages/model-client/{src,tests,tools}` and `docs/benchmarks`. Does not overwrite `probe.ts`, `.env`, root README or any inference service. Requires project Node.js 22 and the existing Python benchmark-runner venv.

## Offline tests

```bash
node --experimental-strip-types --test \
  packages/model-client/tests/inference-scheduler.test.mjs
```

Expected: 11 tests, 11 pass. This uses Node 22's native TypeScript type-stripping for the new `.ts` modules; it does not require new npm dependencies or change `packages/model-client/package.json`.

## Live proof (use a NEW run ID; 2E-0.4B still preserved)

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
source services/benchmark-runner/.venv/bin/activate
APP=services/benchmark-runner/src/benchmark_runner/durable_live_bridge_v04b.py
RUN=v04c-chat-scout-live-001
python "$APP" prepare --run-id "$RUN" --crash-after-delegation
# Intentional exit 37; do not use set -e
python "$APP" inspect --run-id "$RUN" | jq '{status,tasks,outbox}'
# WAITING_FOR_SCOUT
node --env-file=.env --experimental-strip-types \
  packages/model-client/tools/prove-chat-while-scout.mjs "$RUN"
# Expected: chat CHAT_LANE_OK; workflow WORKFLOW_LANE_OK;
# scoutExit 0; finalState READY_TO_RESUME; chatOverlappedScout true
python "$APP" resume --run-id "$RUN"
python "$APP" inspect --run-id "$RUN" | jq '{status,tasks,outbox}'
# GEMMA_RESUMED, idempotency still available
```

**Important:** The Node script launches real Antares (`scout`) in a child process. It routes only its *own* two Gemma inference calls through its one scheduler instance. The follow-on Python `resume` remains outside the scheduler and is executed only after the proof script ends. Do not run other independent Gemma workloads concurrently and assume they are governed by this new in-process scheduler. Do not claim zero queue latency, preemption, globally enforced single concurrency, or durable chat sessions from this checkpoint.

## Acceptance

- Offline: serialized admission, fair lane selection, bounded queues, safe timeout handling, queued cancellation, close, metadata-only auditing, no cross-context messages, rejection of incomplete model responses.
- Live: persisted `WAITING_FOR_SCOUT` after Gemma plan and intentional crash; Antares real read-only Git scout in a separate process; real Gemma chat and workflow requests through one shared single-slot scheduler while scout is active; `READY_TO_RESUME` after scout; manual real Gemma durable resume through frozen v04B bridge.
- If exact outputs are not returned or the overlap observation is false, treat the proof as inconclusive/fail; do not change the inference node configurations to force success.
