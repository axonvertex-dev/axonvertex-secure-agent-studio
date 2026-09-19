# Checkpoint 2E-0.4D2 — Durable Agent Runtime through the resident Gemma Gateway

## Scope

Adds a new CLI `durable_gateway_bridge_v04d2.py`. It invokes existing `durable_live_bridge_v04b` with an injected provider that routes **every Gemma/Node A call** through `http://127.0.0.1:17712/v1/chat/completions`, with `X-Axonvertex-Lane: workflow`, using `GEMMA_GATEWAY_WORKFLOW_KEY` from the project `.env`. Antares/Node B retains its existing authenticated, read-only tool-loop adapter. It never calls direct Node A SGLang, and fails closed if the gateway is absent. The existing v04b runner is unchanged and remains a historical benchmark, but running it explicitly still bypasses the gateway; all production clients must eventually use the resident gateway route.

The bridge records a credential-free `gateway-calls.jsonl` metadata receipt with task/context IDs, request/response hashes, status, lane, queue time and inference time. The source/evidence/SQLite results remain in the original v04b-controlled synthetic fixture folder.

## Prerequisites

- Existing v0.1.7 workflow and 2E-0.4A/0.4B runner on Node A.
- Resident gateway running on loopback 17712 with `/health` status `ok` and existing workflow-lane credential in `.env`.
- Three-node config in project `.env`, with `GEMMA_MAX_OUTPUT_TOKENS` <=2048.
- Remain on `feat/checkpoint2e04-durable-agent-runtime`.

## Offline tests

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/durable_gateway_bridge_v04d2.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_durable_gateway_bridge_v04d2.py' -v
```

## Live proof — new run only

```bash
APP=services/benchmark-runner/src/benchmark_runner/durable_gateway_bridge_v04d2.py
RUN=v04d2-gateway-live-001

curl -fsS http://127.0.0.1:17712/health | jq .
python "$APP" prepare --run-id "$RUN" --crash-after-delegation
echo "Expected intentional exit code: $?"   # 37
python "$APP" inspect --run-id "$RUN" | jq '{status,tasks,outbox}'
python "$APP" scout --run-id "$RUN"
python "$APP" resume --run-id "$RUN"
python "$APP" inspect --run-id "$RUN" | jq '{status,tasks,outbox}'
python "$APP" resume --run-id "$RUN"   # no second Gemma request

cat "benchmarks/results/checkpoint2e/durable-live/$RUN/gateway-calls.jsonl" | jq .
```

Expected gateway receipts: exactly two workflow-lane entries with successful status 200, **different** task IDs, the same task-specific context ID, and queue/inference timing. `scout` uses Node B; no Gemma inference during waiting. `GEMMA_RESUMED` is only the resumed investigation, not end-to-end durable Foundation Sec, remediation, or approval.

## Boundaries

- Shared scheduling applies only to callers that use the resident gateway; the SGLang port remains technically reachable to trusted local processes. A network-level bypass prevention control is a separate deployment task.
- The gateway queue is resident but not itself crash-durable. The Python task store is durable; external model execution is at-least-once if the process crashes before committing its response.
- Gateway can return 503 on overload or 502 on inference failure. Failure leaves the durable task unacknowledged; the current lease may have to expire before retry. There is **no** silent direct-SGLang fallback.
- Node C/Foundation Sec and patch verification are *not* yet linked to this durable gateway bridge. The frozen 2E-0.3 runner demonstrates these separately.
- The bridge proof's `CandidateFinding` receipt is still the older reference-only marker; the independently verified source manifest is rechecked before each resumed Gemma call.
- The gateway must remain running in its dedicated terminal for the proof.
