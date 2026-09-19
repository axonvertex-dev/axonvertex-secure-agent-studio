# Checkpoint 2E-0.5B — Continuous durable Foundation Sec review

## Scope

Additive `continuous_review_worker_v05b.py` is a **successor CLI** for v05a, reusing its `Queue`, stage execution, Node A gateway provider, run locking, existing synthetic fixture, v04b manifest verification, and v04 durable SQLite runtime. Invoke the v05b CLI (not the v05a CLI) for A→B→A→C automation. Neither the frozen v0.1.7 workflow nor v05a code is modified.

Node A planning + resumption exclusively use authenticated resident Gemma gateway `127.0.0.1:17712` through the v04d2 `GatewayProvider`. Node B Antares uses existing read-only scout. Node C Foundation Sec uses **only** `NODE_C_BASE_URL`, `NODE_C_MODEL`, `NODE_C_API_KEY` for structured JSON via `old.Provider({'C':...})`; the proof restricts C URL to `http://100.76.212.84:18183/v1`. No Node C traffic is routed to the Gemma gateway; this does not grant Node C tool calls. The existing root worker process is on Node A.

## Persisted new states

`GEMMA_RESUMED` → `WAITING_FOR_REVIEW` (review task `READY`; root `WAITING`; `DISPATCH_REVIEW PENDING`) → review outbox `LEASED` → `REVIEW_COMPLETED` (review artifact committed, outbox `DONE`, root `READY` for future remediation) **or** `REVIEW_QUARANTINED` (review artifact captured, root `BLOCKED`; no remediation).

`ReviewRuntime` appends transactional rows to existing `runs`, `tasks`, `outbox`, `artifacts`, `events` in the per-run v04 database; v05b reuses v05a `jobs.sqlite3` and kernel flock. The review input is freshly reconstructed from the verified pinned Git manifest and committed Gemma final-content artifact. The scheduled outbox binds to the review input SHA-256; the accepted review must cite both known evidence IDs, agree with deterministic AST fixture observations, and avoid unsupported external exploitability claims. Rejected model claims are quarantined, not remediated. Only final structured review JSON is persisted, not model private reasoning, remote error bodies or keys.

The v05a `HANDOFF_COMPLETED` state is an intermediate status in v05b. **v05b terminates at `REVIEW_COMPLETED`, not `VERIFIED_CANDIDATE_AWAITING_APPROVAL`.** Remediation, sandbox verification, approval, production persistence, multi-host leases, A2A/MCP, and full policy engine remain future work. It is not exactly-once inference: a crash after Node C returns but before a durable review commit may cause a new inference after lease expiration. An already committed review cannot be re-inferred by this worker. One worker per run on the same Node A host is enforced with flock only.

## Install, test, first live run

The ZIP contains only three new files. From Node B transfer it to Node A `/tmp`, then on Node A:

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E05B_Continuous_Foundation_Review.zip -d .
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/continuous_review_worker_v05b.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_continuous_review_worker_v05b.py' -v
```

Keep resident gateway running. From Node A verify `curl --noproxy '*' -fsS http://127.0.0.1:17712/health` and `curl --noproxy '*' -fsS http://100.76.212.84:18183/health` without printing credentials.

### Deliberate crash / recovery on completed v05a run

Use an existing *completed* v05a job, e.g. `v05a-auto-handoff-live-001`, if that run is present and not previously scheduled for review. The `schedule-review` command atomically schedules Node C in the existing per-run DB and then updates the shared worker queue; deliberate exit 37 occurs **after both commits**.

```bash
APP=services/benchmark-runner/src/benchmark_runner/continuous_review_worker_v05b.py
RUN=v05a-auto-handoff-live-001
python "$APP" schedule-review --run-id "$RUN" --crash-after-review-schedule
echo "Intentional process exit code: $?"  # expect 37
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status}'
python "$APP" step --run-id "$RUN"    # real Node C, no repeated Gemma or Antares
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status}'
```

Underlying task/outbox/evidence:

```bash
python services/benchmark-runner/src/benchmark_runner/durable_gateway_bridge_v04d2.py \
  inspect --run-id "$RUN" | jq '{status,tasks,outbox,artifacts: [.artifacts[]|{artifact_id,artifact_type,content_sha256}]}'
```

Re-running `python "$APP" step --run-id "$RUN"` must return `REVIEW_COMPLETED` or `REVIEW_QUARANTINED` without a repeat Node C call. **Only `REVIEW_COMPLETED` is an accepted source-grounded security review.** If Node C returns contradictory review JSON, `REVIEW_QUARANTINED` is expected fail-closed behavior. A transport failure may queue a bounded retry. If operator recovery is requested, stop; preserve evidence and logs.

### Full one-submission A→B→A→C

```bash
RUN=v05b-auto-foundation-live-001
python "$APP" submit --run-id "$RUN"
python "$APP" serve --stop-when-idle
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status,events}'
```

For a resident worker use `python "$APP" serve` in a supervised terminal. `--stop-when-idle` is only for bounded demos and can exit if another process holds an unexpired review lease; relaunch later. Do not run separate v05a/v05b worker services simultaneously when using the same shared queue.

## Live acceptance

1. Offline test suite passes; no source code from user repositories is used.
2. Crash after review scheduling returns code 37 and leaves `WAITING_FOR_REVIEW` with Node C task `READY`, `DISPATCH_REVIEW PENDING`.
3. Fresh v05b process calls real Foundation Sec 8B on C with JSON schema, and persisted review is either validated or quarantined with evidence refs and deployment uncertainty.
4. Accepted review advances root from `WAITING` to `READY` and commits `SecurityReview`; repeated `step` does not re-infer.
5. `gateway-calls.jsonl` remains two A workflow calls for a previously completed A→B→A run; Node C never goes through the Gemma gateway.
