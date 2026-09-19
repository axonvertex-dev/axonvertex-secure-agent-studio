# Checkpoint 2E-0.3 — Stateful three-node security investigation and verified candidate remediation

**Purpose:** Demonstrate actual delegation, software-managed wait/resume, read-only tool-backed scouting, source-backed specialist review, and an evidence-linked candidate patch checked in an isolated container. This is a deliberately narrow **pre-A2A** proof of concept for AXONVERTEX Secure Agent Studio.

## What is implemented

1. Node A Gemma drafts investigation plan and returns. The runtime persists a `WAITING` state while it delegates to Node B.
2. Antares receives a file manifest, **not the vulnerable source text**. It may use a function-called `terminal` read adapter for `ls`, `pwd`, `rg`, `grep`, `cat`, `head`, and bounded `sed` against one generated fixture Git worktree. No host shell or network command is executed.
3. Antares submits candidate repository-relative paths. The deterministic collector checks the immutable Git commit, resolves canonical paths, captures bytes/hashes/line numbers, and assigns IDs bound to commit, path and content.
4. Gemma resumes, analyzes exact source and caller observations, then enters another `WAITING` state while Foundation Sec receives a compact evidence-backed independent review task.
5. Foundation Sec returns constrained JSON. A fixture-specific validator checks evidence IDs and the distinction between observed SQL construction, observed request.args caller and *unproven deployed exploitability*. Disagreement quarantines the review and blocks patching in this version.
6. Gemma produces a complete replacement `app.py`; a narrow AST contract checks that it is only a SQLite parameterized `lookup_user(conn, username)` implementation. No hardcoded model substitute is silently installed on failure.
7. A Docker sandbox runs the same known-answer SQLite verification against the original and proposed file. Baseline must show normal=1, missing=0, attack=2; candidate must show normal=1, missing=0, attack=0. Docker is private/offline, read-only, unprivileged, resource-limited, and does not mount the Docker socket.
8. Gemma receives verification receipts, creates a final report; deterministic policy sets `AWAIT_HUMAN_APPROVAL`. **Neither the original generated fixture nor any user source tree is mutated.**

## Current architectural boundaries

- Implemented: single Python software coordinator, static model bindings from protected `.env`, task state machine, task wait/resume, bounded Antares tool loop, source receipts, verified candidate, append-oriented SHA-256 chained JSONL events, detailed trace/report.
- Not implemented: standard A2A protocol, persistent Agent Registry, MCP Gateway, authorization tokens/SPIFFE, production multi-repository Evidence Collector, graph store, RLM, GNN, learned decision router, generic code sandbox, human approval API or approved Git mutation.
- Test fixture is synthetic and intentionally vulnerable. A passing run **does not establish real-repository SAST accuracy or production exploitability**. The `request.args` caller is observed in a mock module, but no deployed HTTP route is demonstrated.
- The reference Python runner's task state is persisted in trace/events, but crash resumption and distributed durable queues are future work.

## Installation from Node B

Download the ZIP on Node B, and copy it to Node A:

```bash
scp ~/Downloads/AXONVERTEX_Checkpoint_2E03_Agentic_Workflow.zip \
  axonvertex@100.82.103.57:/tmp/
```

On Node A (from an active project shell):

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E03_Agentic_Workflow.zip -d .
source services/benchmark-runner/.venv/bin/activate
python -m py_compile services/benchmark-runner/src/benchmark_runner/agentic_workflow_v03.py
python -m unittest discover -s services/benchmark-runner/tests -p 'test_agentic_workflow_v03.py' -v
```

Install *only if not cached and you consent to pulling this public base image*:

```bash
docker image inspect python:3.11-alpine >/dev/null 2>&1 || docker pull python:3.11-alpine
```

Inspect `.env` safely without printing credentials:

```bash
python - <<'PY'
from dotenv import dotenv_values
c=dotenv_values('.env')
for p in ('GEMMA','NODE_B','NODE_C'):
    print(p, 'READY' if all(c.get(f'{p}_{v}') for v in ('BASE_URL','MODEL','API_KEY')) else 'MISSING')
PY
```

Execute a new measured **live** run from Node A:

```bash
python services/benchmark-runner/src/benchmark_runner/agentic_workflow_v03.py \
  --run-id checkpoint2e-three-node-agentic-v03-001
```

Inspect a concise summary without printing confidential inputs:

```bash
RUN=benchmarks/results/checkpoint2e/agentic-workflow/checkpoint2e-three-node-agentic-v03-001
jq '{status, fixture_commit, tasks, source_observations, review_validation,
      candidate, verification, decisions, failure}' "$RUN/trace.json"
sed -n '1,220p' "$RUN/report.md"
sed -n '1,180p' "$RUN/candidate.diff"
git -C "$RUN/fixture_repo" status --short
```

Expected success status: `verified_candidate_awaiting_approval`. Baseline/candidate attack result should be `2 → 0`. Original fixture Git `status --short` must be empty; candidate exists separately at `candidate_workspace/app.py`.

## Failure behavior and diagnostics

Every run ID is immutable. Retain the previous v1/v2 inference-chain traces. Never overwrite a failed integration run. A failed `v03-001` should be followed by a new ID `v03-002` after a small, evidenced fix.

- Scout produces text but no tool calls: recorded as a failed proof; do **not** claim tool-backed search.
- Scout submits before reading source: failure.
- Invalid file path or command: denied by the read adapter, receipt recorded; model may try a permitted command.
- Foundation Sec gives invented IDs, wrong classification or wrongly claims external exploitability: quarantined; no automatic patch.
- Gemma emits invalid patch: bounded retry, then failure; no hardcoded replacement.
- Docker is missing/inaccessible: fail before inference; no host execution fallback.
- Docker test fails or fixture changes: fail closed.
- A `</think>` formatting leak is flagged, and visible prefatory reasoning is not included in the saved final content. This is **not** a replacement for a robust Antares provider adapter.

Keep keys in Node A's existing ignored `.env` (mode 0600), never in this ZIP or debug output. Results contain generated source excerpts/model final answers, so apply repository-confidential retention controls before generalizing beyond the synthetic fixture.
