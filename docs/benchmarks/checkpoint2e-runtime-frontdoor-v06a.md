# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.6A

## Baseline

Feature branch `feat/checkpoint2e04-durable-agent-runtime` at `bfeb332` proves the
single-submission synthetic CWE-89 live A→B→A→C→A→Docker workflow. The known
successful run is `v05c-full-auto-live-001`, ending
`VERIFIED_CANDIDATE_AWAITING_APPROVAL`. The 0.5C implementation and its SQLite
state are preserved. This package installs **three new files** and changes no
older worker, model-client, API key or database.

## What is added

- Stable Python entry point: `agent_studio_runtime_v06a.py`.
- `submit`, `inspect`, `events`, and `serve` route to the existing v05C `Queue`,
  `RemediationRuntime`, and `continuous_remediation_worker_v05c.serve` without
  inventing a new state machine or migrating a database.
- An **optional separate** local HTTP API on `127.0.0.1:17713` for submitting
  controlled fixture jobs, listing and inspecting job/task/outbox/artifact
  metadata, and polling cursor-based worker/runtime events. No raw artifact
  payloads, code, model output, reasoning, credentials, prompts or error bodies
  are served. Committed artifact digests are checked before returning metadata.
- Tests exercise bearer auth, reject duplicate run submissions, invalid JSON,
  oversized requests, paths and unknown operations, protect provenance metadata,
  and assert the service delegates to the existing v05C worker.

**Intentionally not part of 0.6A:** general repository ingestion, Agent Registry,
MCP, A2A, approvals, applying patches, distributed locks, streaming, UI,
production authentication or process supervision. `/health` means only that the
API responds; it explicitly does **not** certify that the worker, Gemma gateway,
Node B or Node C is alive. One host, one trusted administrator, synthetic fixture.

## Security boundaries

- API binds ONLY loopback `127.0.0.1`; do not port-forward/reverse-proxy publicly.
- Every API operation other than `GET /health` needs `AGENT_STUDIO_API_KEY`,
  independently generated, at least 32 characters and distinct from Gemma lane
  keys and upstream key. Missing/reused keys prevent API startup.
- No API route for stage stepping, model calls, repo mutation, approving,
  applying or running arbitrary commands. POST body accepts **only** `run_id`,
  validated by the existing bridge safe-ID contract; max JSON body 4096 bytes.
- Read responses expose only metadata, and events deliberately discard
  `details` / `payload_json` values. JSON results use `Cache-Control: no-store`.
- The API and worker use different SQLite connections to the existing WAL
  queue. The worker is a **separate process**; do not launch two different worker
  versions against the same run. A second worker process uses the existing
  per-run `flock` on Node A, not distributed mutual exclusion.
- Existing execution retains its known semantics: durable committed stages,
  at-least-once remote inference if terminated before a commit, no direct
  fallback from the Gemma gateway, sandbox-only generated code, original
  fixture unchanged and human approval required.

## Install: from Node B, then Node A

Node B:

```bash
scp ~/Downloads/AXONVERTEX_Checkpoint_2E06A_Runtime_Front_Door.zip \
  axonvertex@100.82.103.57:/tmp/
```

Node A:

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E06A_Runtime_Front_Door.zip -d .
source services/benchmark-runner/.venv/bin/activate
APP=services/benchmark-runner/src/benchmark_runner/agent_studio_runtime_v06a.py
python -m py_compile "$APP"
python -m unittest discover -s services/benchmark-runner/tests \
  -p 'test_agent_studio_runtime_v06a.py' -v
python -m unittest discover -s services/benchmark-runner/tests -p 'test_*.py'
```

There were 11 focused offline tests, 75 tests in the locally assembled source
snapshot used to build this ZIP; Node A previously reported 66 tests before
install, so its test count may be 77 after adding 11 if all other test files
are unchanged. Confirm the final unittest `OK` rather than relying on count.

## First use — read-only inspection, no new inference

```bash
APP=services/benchmark-runner/src/benchmark_runner/agent_studio_runtime_v06a.py
RUN=v05c-full-auto-live-001
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status,tasks,outbox,artifacts}'
python "$APP" events --run-id "$RUN" --limit 5 \
  | jq '{worker_events,runtime_events,next_worker_after,next_runtime_after}'
```

The previously verified run must remain untouched; no new model or Docker call
is made for inspection. This new entry point may also process new synthetic
fixture jobs:

```bash
RUN=v06a-cli-auto-live-001
python "$APP" submit --run-id "$RUN"
python "$APP" serve --stop-when-idle  # uses existing v05C stage engine
python "$APP" inspect --run-id "$RUN" | jq '{job,bridge_status}'
```

Do not run this live new-job check until the read-only checks pass and the
existing Gemma gateway, Node B/C, and Docker are healthy.

## Optional API — separate terminal, no keys printed

Once, add `AGENT_STUDIO_API_KEY` to the existing ignored `.env`. Generate a new
key; do not reuse any inference credential, commit `.env`, or show key values in
terminal output. Example **only if the key has not yet been configured**:

```bash
python - <<'PY'
from pathlib import Path
import os, secrets
p = Path('.env')
if not p.is_file():
    raise SystemExit('Existing ignored .env is required')
if any(line.strip().startswith('AGENT_STUDIO_API_KEY=') for line in p.read_text().splitlines()):
    raise SystemExit('API key already exists: do not append a duplicate')
with p.open('a', encoding='utf-8') as out:
    out.write('\nAGENT_STUDIO_API_KEY=' + secrets.token_urlsafe(36) + '\n')
os.chmod(p, 0o600)
print('Independent Agent Studio API credential configured (value hidden)')
PY
```

Terminal 1: keep resident Gemma gateway as previously started, e.g.
`node --env-file=.env --experimental-strip-types packages/model-client/tools/start-gemma-gateway.mjs`.

Terminal 2: start optional API. No worker is started by this command.

```bash
python "$APP" api
# AGENT_STUDIO_API_READY http://127.0.0.1:17713
```

Terminal 3: safely inspect the prior run through the API without printing the
credential. Python sends it in an HTTP header, not a shell command argument:

```bash
python - <<'PY'
import json, urllib.request
from dotenv import dotenv_values
key = dotenv_values('.env')['AGENT_STUDIO_API_KEY']
req = urllib.request.Request(
    'http://127.0.0.1:17713/v1/runs/v05c-full-auto-live-001',
    headers={'Authorization': 'Bearer ' + key})
with urllib.request.urlopen(req, timeout=10) as response:
    data = json.load(response)
print(json.dumps({'job':data['job'], 'bridge_status':data['bridge_status'],
                  'artifact_types':[a['artifact_type'] for a in data['artifacts']]}, indent=2))
PY
```

API endpoints: `GET /health` (no auth); bearer-protected `POST /v1/runs` with
body `{"run_id":"..."}`, `GET /v1/runs`, `GET /v1/runs/{run_id}`,
`GET /v1/runs/{run_id}/events?worker_after=0&runtime_after=0&limit=100`.
The last route returns independent cursors for worker and runtime ledgers.

## Commit gate

Stage only the new three files. Preserve the untracked root README and backup
file unchanged. Test v06A before starting any new live run.

```bash
git add -- \
  docs/benchmarks/checkpoint2e-runtime-frontdoor-v06a.md \
  services/benchmark-runner/src/benchmark_runner/agent_studio_runtime_v06a.py \
  services/benchmark-runner/tests/test_agent_studio_runtime_v06a.py
git diff --cached --check
git diff --cached --stat
# Commit and push only after Node A tests and first read-only inspection succeed.
```

## Subsequent 0.6B / 0.6C work

0.6B: supervised, isolated resident Gemma Gateway, worker and API processes
(on Node A); explicit startup dependencies, service credentials and health
checks, restart/stop procedures and a durable golden-run preservation step.
0.6C: lightweight provenance viewer consuming the sanitized API, preserving
artifact/content hash relationships without serving raw prompts or patches.
Approval action stays separate until its authorization and exact-snapshot
policy are specified and tested.
