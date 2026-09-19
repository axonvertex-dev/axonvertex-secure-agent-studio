# Checkpoint 2E-0.4B/1 — Live Gemma → Antares → Gemma with durable handoff

## Scope

This deliberately narrow integration bridge combines the v0.1.7 controlled read-only Git-fixture scout with the checkpoint 2E-0.4A SQLite task/outbox store. It introduces no inference-service changes and does **not** overwrite either frozen source file. Execute only on Node A, in `feat/checkpoint2e04-durable-agent-runtime` with the configured project `.env`.

Three separate CLI invocations prove: (1) a **real Gemma plan** followed by persisted `WAITING_FOR_SCOUT` and an intentional process exit; (2) **real Antares** read-only tool calls and independent Git evidence collection, followed by a persisted scout receipt and `READY_TO_RESUME`; (3) **real Gemma** inference consumes exact source-backed evidence and the output is committed **in the same SQLite transaction** as `GEMMA_RESUMED`/outbox acknowledgment.

It does **not** yet execute a durable Foundation Sec review, remediation, Docker verification, or persistent human approval. The already-proven v0.1.7 runner remains the reference for those stages.

## Installation

Copy these three files into project paths:

- `services/benchmark-runner/src/benchmark_runner/durable_live_bridge_v04b.py`
- `services/benchmark-runner/tests/test_durable_live_bridge_v04b.py`
- `docs/benchmarks/checkpoint2e-durable-live-bridge-v04b.md`

No changes to `agentic_workflow_v03.py`, `durable_runtime_v04.py`, Node A/B/C inference images, `.env`, repository root README, or registry scaffolding.

## Test

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/durable_live_bridge_v04b.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_durable_live_bridge_v04b.py' -v
# Expected: 7 tests; OK
```

## Live proof, run these as separate commands (not in a `set -e` script)

```bash
APP=services/benchmark-runner/src/benchmark_runner/durable_live_bridge_v04b.py
RUN=v04b-live-001
python "$APP" prepare --run-id "$RUN" --crash-after-delegation
echo "Expected simulated crash exit code: $?"  # must be 37

python "$APP" inspect --run-id "$RUN" | jq '{status,context_snapshot_id,tasks,outbox}'
# WAITING_FOR_SCOUT; root WAITING, scout READY, DISPATCH_SCOUT PENDING

python "$APP" scout --run-id "$RUN"
# Actual Node B Antares tool calls; pinned evidence captured; READY_TO_RESUME

python "$APP" inspect --run-id "$RUN" | jq '{status,artifacts,outbox}'

python "$APP" resume --run-id "$RUN"
# Actual Node A Gemma response; inference output persisted atomically with resume acknowledgment

python "$APP" inspect --run-id "$RUN" | jq '{status,tasks,outbox,artifacts,events}'
# GEMMA_RESUMED, both jobs DONE; GemmaResumeOutput artifact

python "$APP" resume --run-id "$RUN"
# Reuses committed artifact; does NOT issue a second Gemma request
```

Artifacts are written under `benchmarks/results/checkpoint2e/durable-live/<RUN>/` (expected to be Git-ignored). The `scout-audit-001/events.jsonl` file preserves actual Node B tool results; `scout.json` preserves canonical `app.py` and `web.py` source and hashes; `plan.json`, `gemma-resume.json` contain only final normalized model content, **no private reasoning or API keys**. The authoritative resume artifact is committed in `runtime.sqlite3`; the JSON report is a derived convenience copy.

## Limits, recovery, and fail-closed behavior

- `prepare` calls Gemma **before** the durable delegation is committed; a failure during this preparation requires a fresh run ID. This checkpoint tests restart **after** the delegation commit.
- Antares model/tool attempts that fail before `scout.json` exists can be retried; up to ten separate `scout-audit-NNN` directories preserve attempts. A crash after Antares generated its candidate but before its manifest was written may require another inference. A crash after manifest write and before the SQLite scout acknowledgment reuses the verified manifest without another Antares request.
- The SQLite `CandidateFinding` artifact from v04A is labelled `reference_only_unverified` by design. The bridge independently verifies the `scout.json` contents against the pinned Git commit immediately before **every** resume and sends the canonical excerpts to Gemma; that is not yet a production typed `VerifiedEvidence` artifact.
- SQLite lease is 300 seconds. A transport failure after claiming a lease leaves it `LEASED`; wait for expiry before retrying. No double-claim while the lease is active. A failed network call may already have consumed inference tokens.
- Commit `GemmaResumeOutput` and acknowledgment in one SQLite transaction. If the process dies before commit, another inference may be required; if it dies after commit but before `gemma-resume.json` is written, `inspect` and repeated `resume` recover the **database** artifact without a new model request.
- This is **at-least-once external inference**, not exactly-once inference, and **single-controller proof**, not a distributed multiworker queue. Do not confuse `GEMMA_RESUMED` with the entire vulnerability-remediation workflow completed.
- This bridge does not modify the fixture repository, apply any generated patch, or authorize a user-repository mutation.
- SecurityScout's `format_leak_detected` warning from Node B remains tracked in `scout-audit-NNN/trace.json`; no changes to Node B provider templates are made here.

## Next

Extend the durable task contract with `SecurityReview`, `CandidateChange`, `VerificationResult` and `AwaitingHumanApproval`, then attach a permanent Agent Registry/A2A/MCP gateway. Repair model-authored attribution in the event-derived report before treating final narratives as provenance truth.
