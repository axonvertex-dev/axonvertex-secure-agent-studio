# AXONVERTEX Checkpoint 2E-0.4A — Durable task/runtime contract

**Source checkpoint:** `v0.1.7-checkpoint2e-three-node-agentic` (commit `3ba65a6`).  **Working branch:** `feat/checkpoint2e04-durable-agent-runtime`.

## Scope: deliberately narrow first proof

The working v0.3 harness demonstrated in-process `WAITING → RUNNING` and verified a candidate remediation in a controlled Git fixture. This new module is an **additive, stdlib-only persistence prototype** under `services/benchmark-runner`, not the final `packages/agent-runtime` library and not an actual live Gemma/Antares invocation.

It proves all of the following for one synthetic delegation:

- An SQLite database with durable run, agent-task, source-reference artifact, event, and outbox records (WAL, full synchronous mode, foreign keys).
- `Gemma WAITING`, `Antares READY` and a scout dispatch receipt are committed in **one transaction**.
- A different process can inspect these records after the first process intentionally terminates with `os._exit(37)`.
- A bounded scout-result reference is committed atomically with `Antares COMPLETED`, `Gemma READY`, and a resume outbox message.
- An outbox worker obtains an expiring resume lease; only a holder with a current lease can mark Gemma's task `RUNNING`.
- Duplicate starts/results do not duplicate events, artifacts or dispatches. Conflicting artifact content and stale lease tokens are rejected.
- An expired lease may be reclaimed. **This is at-least-once dispatch with idempotent state transitions, not exactly-once remote model execution.** Workers must use persisted invocation IDs and reconciliation before retrying a real inference call.

**Not proved yet:** executing Antares/Gemma through this store, general evidence authentication/verification, production agent registration, standard A2A/MCP transport, post-crash recovery of an in-flight remote model request, final remediation approval, distributed leadership, or a multi-node persistent runtime. `complete-scout` accepts *reference-only unverified* synthetic evidence IDs. Never present its artifact receipt as source verification.

## Install

The ZIP contains only three additive paths: `durable_runtime_v04.py`, `test_durable_runtime_v04.py`, and this document. It does not replace the existing v0.3 workflow, project README or protected `.env`.

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E04A_Durable_Runtime.zip -d .
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/durable_runtime_v04.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_durable_runtime_v04.py' -v
```

## Manual crash/restart exercise: each line invokes a **separate process**

Use one new run ID per proof. DB stays in ignored benchmark output; it has no API keys or private reasoning.

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
APP=services/benchmark-runner/src/benchmark_runner/durable_runtime_v04.py
DB=benchmarks/results/checkpoint2e/durable-runtime/v04a-proof-001/runtime.sqlite3
RUN=v04a-proof-001

python "$APP" crash-after-start --db "$DB" --run-id "$RUN"
echo "EXPECTED DELIBERATE PROCESS EXIT CODE: $? (37)"

python "$APP" inspect --db "$DB" --run-id "$RUN" \
  | jq '{status, context_snapshot_id, tasks, outbox, events}'

python "$APP" complete-scout --db "$DB" --run-id "$RUN" \
  --artifact-id scout-artifact-synthetic-001 \
  --evidence-id ev-synthetic-001 \
  | jq '{status, artifacts, outbox}'

LEASE=$(python "$APP" claim-resume --db "$DB" --run-id "$RUN" \
  --worker node-a-demo-worker | jq -r '.lease_token')

python "$APP" ack-resume --db "$DB" --run-id "$RUN" \
  --lease-token "$LEASE" | jq '{status, tasks, events}'

python "$APP" inspect --db "$DB" --run-id "$RUN" \
  | jq '{status, task_events: [.events[].event_type], outbox}'
```

The final state should read `GEMMA_RESUMED` with exactly one `TASK_DELEGATED`, one `ARTIFACT_RECEIVED`, one `AGENT_RESUME_READY` and one `AGENT_RESUMED`. This is the **runtime state-machine's resume acknowledgement**, *not* proof that Gemma has performed a fresh inference after restarting.

## Next integration milestone (2E-0.4B)

Refactor the v0.3 workflow's task transitions through this persistence interface. Store task/invocation IDs before calls; persist exact tool receipts and source evidence only after independent collector validation; resume Gemma by consuming the outbox task. Add an interruption test with the process terminated while waiting for an actual Antares result; on restart, reconcile the remote work instead of issuing it twice. Do not allow the model to decide authority/policy or assign its own evidence IDs. After proof, choose the permanent package language/transport based on the repository's root `package.json` and existing model-client contracts; keep the Python harness as a regression oracle.
