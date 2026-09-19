# Checkpoint 2E-0.5A — Continuous dispatcher for durable A→B→A handoff

## Proven dependencies

- 2E-0.3: fixed synthetic Git-fixture Gemma/Antares/Foundation Sec remediation and sandbox checks.
- 2E-0.4A–D2: SQLite durability and the **resident Gemma Gateway** on `127.0.0.1:17712`.
- `a481413` feature branch baseline.

This package adds **three files only**, does not replace any older module, and does not touch model inference deployments or `.env`. Run on Node A from the Secure Agent Studio repo root, with the resident Gemma gateway already running and the benchmark runner virtual environment active.

## Exact goal and stopping boundary

Submit one **synthetic** investigation; an always-running local worker automatically advances:

1. Gemma planning through the shared gateway.
2. Persist root `WAITING_FOR_SCOUT` and Antares `READY` task.
3. Antares read-only tools on the generated pinned Git fixture and deterministic source manifest.
4. Persist scout finding and resume job.
5. Gemma resumed analysis through the shared gateway and atomic output/ack transaction.
6. Stop at queue status **`HANDOFF_COMPLETED`** (underlying durable state `GEMMA_RESUMED`).

**Do not confuse `HANDOFF_COMPLETED` with security-remediation completion.** Foundation Sec, patch, Docker checks, approval and authorized Git mutation are not integrated into the durable continuous worker yet. The earlier v0.1.7 runner proves a separate non-durable full flow. Do not merge or label this checkpoint as an end-to-end durable remediation proof.

## Installation and local tests

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E05A_Continuous_Worker.zip -d .
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/continuous_worker_v05a.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_continuous_worker_v05a.py' -v
curl -fsS http://127.0.0.1:17712/health | jq .
```

## Live task: one submission, worker runs remaining handoff automatically

Terminal 1: keep the existing gateway running. Terminal 2:

```bash
APP=services/benchmark-runner/src/benchmark_runner/continuous_worker_v05a.py
RUN=v05a-auto-handoff-live-001
python "$APP" submit --run-id "$RUN"
python "$APP" serve --stop-when-idle
```

`--stop-when-idle` is for the initial proof: the worker exits after it finishes all runnable jobs. For a continuously running worker, use `python "$APP" serve --poll-seconds 2` without the flag in a dedicated terminal. Only the running process advances tasks; this package does **not** install systemd/Docker service management or an HTTP Chat API.

Terminal 3 can inspect while the worker is busy:

```bash
python "$APP" inspect --run-id "$RUN" | jq '{job,events}'
python services/benchmark-runner/src/benchmark_runner/durable_gateway_bridge_v04d2.py inspect --run-id "$RUN" | jq '{status,tasks,outbox}'
```

Expected queue status: `HANDOFF_COMPLETED`, bridge state: `GEMMA_RESUMED`, two gateway workflow-lane receipts, Antares scout completion, persisted Gemma result. No Foundation Sec/remediation claim.

```bash
RUN_DIR="benchmarks/results/checkpoint2e/durable-live/$RUN"
jq -s '{count:length, statuses:map(.status), lanes:map(.lane), transports:map(.transport)}' "$RUN_DIR/gateway-calls.jsonl"
```

## Recovery and safety rules

- Queue database: `benchmarks/results/checkpoint2e/continuous-worker-v05a/jobs.sqlite3` (mode 0600). It persists stage receipts, state and sanitized error **types**, not API keys, raw reasoning or prompts.
- One Node A `flock` per run prevents concurrent local workers from dispatching the same run. After a process crashes, the kernel unlocks the file; the next worker reconciles the authoritative bridge SQLite state. **This is not a distributed lock across hosts.**
- If the worker crashes after the bridge has committed a stage but before its queue receipt, the next process detects the committed stage and advances without rerunning that stage. If it crashes while external inference is in flight and *before* persistence, the inference may occur again: at-least-once external calls, NOT exactly-once.
- If initial preparation leaves a partial folder before writing a plan and SQLite state, the job is quarantined as `NEEDS_OPERATOR_RECOVERY` rather than blindly repeating Gemma planning. Do not delete or overwrite forensic traces to hide ambiguity.
- Errors are retried at most three times for a recoverable unchanged persisted stage, then quarantined. No fallback to direct SGLang from gateway failure.
- Model output and source evidence are retained by the existing bridge in its synthetic fixture results. The generic queue is not a replacement for a governed evidence store, multi-tenant isolation, A2A, MCP or Agent Registry.
- Gateway is only globally enforced for clients that actually use it; legacy scripts can still address local SGLang.

## Further checkpoints

2E-0.5B: durable task contracts/worker integration for Node C review, Gemma remediation, Docker verification and approval with restart test at EACH dependency. 2E-0.5C: authenticated API and UI, real Agent Registry and A2A/MCP governance. Later: EDG, context/RLM and learned decision control.
