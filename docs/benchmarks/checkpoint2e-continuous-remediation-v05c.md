# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.5C

## Scope and dependencies

Additive worker `continuous_remediation_worker_v05c.py` extends v05B on branch
`feat/checkpoint2e04-durable-agent-runtime`, currently committed through `8f403a2`.
The frozen v0.1.7 proof, v04B, v04D2, v05A and v05B sources are **not replaced**.
The original, deliberately vulnerable **synthetic CWE-89 Git fixture only** is in scope.

A single submitted run can advance A (Gemma via resident gateway) → B (Antares)
→ A (Gemma analysis via gateway) → C (Foundation Sec review) → A (Gemma
candidate via gateway) → isolated Docker baseline/candidate comparison →
`VERIFIED_CANDIDATE_AWAITING_APPROVAL`.

This proof does NOT implement a general-purpose code fixer, Agent Registry,
MCP/A2A, approval UI, production deployment assurance, or patch application.
No generated source executes directly on the host. No model gains permission to
modify the original fixture repository.

## Reused components

- `continuous_review_worker_v05b`: already committed reviewed artifact, queue and task handoff.
- `durable_runtime_v04`: existing per-run SQLite `runs`, `tasks`, `artifacts`, `events`, `outbox` tables.
- `durable_gateway_bridge_v04d2.GatewayProvider`: mandatory Node A workflow lane at `127.0.0.1:17712`.
- `agentic_workflow_v03`: `extract_code`, narrow fixture `validate_patch`, `docker_check`, known-answer fixture and verification script.
- `continuous_worker_v05a.run_lock`: local single-worker-per-run; NOT distributed locking.

## Durable states

`REVIEW_COMPLETED` → `REMEDIATION_PENDING` / `WAITING_FOR_REMEDIATION`
→ `CANDIDATE_READY` → `VERIFY_PENDING` / `WAITING_FOR_VERIFICATION`
→ `VERIFIED_CANDIDATE_AWAITING_APPROVAL`, or `VERIFICATION_REJECTED`.
Two invalid Gemma patch outputs produce `REMEDIATION_REJECTED`; network and
sandbox infrastructure failures are bounded retries, then
`NEEDS_OPERATOR_RECOVERY`. Tampered pinned Git or candidate workspace fails closed.

The accepted Foundation Sec review is referenced, **not rerun**. Only the
verified Git source is authoritative. A generated `CandidateChange` artifact
contains source and source, prompt, response and diff hashes; the
`VerificationResult` records both baseline/candidate observed row counts,
Docker image and original fixture immutability. Only an isolated candidate
workspace and `candidate.diff` are written. Original Git status/HEAD are
rechecked before and after verification.

## On Node A: install and offline tests

From Node B, `scp ~/Downloads/AXONVERTEX_Checkpoint_2E05C_Durable_Remediation.zip axonvertex@100.82.103.57:/tmp/`.

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E05C_Durable_Remediation.zip -d .
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/continuous_remediation_worker_v05c.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_continuous_remediation_worker_v05c.py' -v
```

Run full Python regression suite before committing. Existing regression
harness deliberately prints `FAILED at gemma_remediation` and
`FAILED at antares_scout` while testing bounded failure; the unittest final
result (`OK` vs `FAILED`) is authoritative.

## Live acceptance on same reviewed run, without rerunning A-B-A-C

Requires resident gateway healthy at loopback `:17712`, Docker daemon active,
Docker image `python:3.11-alpine` already available. Check image; pull only
intentionally if missing. Never fall back to running candidate on host.

```bash
curl --noproxy '*' -fsS http://127.0.0.1:17712/health | jq .
docker image inspect python:3.11-alpine >/dev/null && echo SANDBOX_IMAGE_OK
APP=services/benchmark-runner/src/benchmark_runner/continuous_remediation_worker_v05c.py
RUN=v05a-auto-handoff-live-001
python "$APP" schedule-remediation --run-id "$RUN" --crash-after-remediation-schedule
echo "Process exit code: $?"  # deliberate 37
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status}'
```

Expected persisted state after process restart: queue `REMEDIATION_PENDING`,
run `WAITING_FOR_REMEDIATION`, no new Gemma invocation yet. Then execute one
bounded step, inspect and **pause to review the candidate before Docker**:

```bash
python "$APP" step --run-id "$RUN"  # Gemma candidate through gateway
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status,artifacts}'
python "$APP" step --run-id "$RUN"  # persist verification delegation
cat "benchmarks/results/checkpoint2e/durable-live/$RUN/candidate.diff"  # may not exist until verification step
```

`candidate.diff` and `candidate_workspace/app.py` materialize at verification.
To run verification, ensure the image exists, then:

```bash
python "$APP" step --run-id "$RUN"  # Docker baseline + candidate, no network
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status,artifacts}'
python "$APP" step --run-id "$RUN"  # idempotent, NO new Gemma or Docker
jq -s '{call_count:length, statuses:map(.status),lanes:map(.lane)}' \
  "benchmarks/results/checkpoint2e/durable-live/$RUN/gateway-calls.jsonl"
```

A successful accepted prior A-B-A-C run should show **3 Gemma gateway calls**:
planning, source analysis, patch generation (or 4 if patch-contract correction
needed), and one committed verification artifact. Node C remains one committed
review dispatch. The final state is not authorization to apply the patch.

`python "$APP" serve --stop-when-idle` advances all pending stages automatically;
`python "$APP" serve` remains a polling process until stopped. This CLI is
not a supervised production service.

## Crash boundary and security caveats

Database stage commits and outbox acknowledgments are atomic within the per-run
SQLite database. Worker queue reconciliation is explicit after interruptions
between the two independent database commits. Model requests interrupted after
remote execution but BEFORE durable commit may be repeated. After candidate
or verification commit, the worker skips repeat inference/execution; **not
exactly-once remote inference**. Do not run different versions of the worker
against the same live run. Keep gateway process running while Node A calls run.

The Docker verifier inherits v0.3 restrictions: `--network none`, `--read-only`,
`--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 64`,
256 MiB, 1 CPU, non-root UID, and read-only candidate mount. Compare known
fixture baseline `normal_rows=1, nonexistent_rows=0, attack_rows=2` against
candidate `1,0,0`. This does **not** prove real-world production exploitability.
