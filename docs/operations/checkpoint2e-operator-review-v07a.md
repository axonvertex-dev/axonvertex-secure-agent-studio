# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.7A

**Base commit:** `27bff64` on `feat/checkpoint2e04-durable-agent-runtime`.

## 0.7 delivery sequence

| Stage | Deliverable | Mutation allowed? |
|---|---|---|
| **0.7A** | Local read-only case projection, source diff, Foundation Sec review, Docker behavior receipt, event timeline | **No** |
| 0.7B | Separate operator authentication and RBAC; single immutable decision bound to run + candidate source SHA-256 + verification artifact digest, with explicit reject/approve reasons and append-only audit | Decision ledger only |
| 0.7C | Separate **approved candidate** application gate with trusted target/commit allowlist, expiry, compare-and-swap, re-verification and rollback plan; no implicit execution by approve | Scoped Git mutation only after fresh checks |
| 0.7D | VS Code review presentation and API integration after operator access control, pagination, redaction, CSRF/local binding and origin rules are designed and tested | Respect stage-specific permissions |

0.7A **does not** add a browser endpoint. The existing single `AGENT_STUDIO_API_KEY`
proves access to the loopback API, **not individual reviewer identity**. It must
not be used to impersonate an operator for approval. CLI operates locally as the
OS account with access to the durable evidence; do not share the machine account
for multi-user attribution. Model-authored review summaries are untrusted text.

## Review projection contract

`operator_review_v07a.project(...)` opens both SQLite ledgers with `mode=ro`
and `PRAGMA query_only=ON`; it never invokes the worker, provider, Docker,
`git`, or an approving method. It verifies each persisted artifact's canonical
SHA-256 and independently checks candidate source/diff hashes and candidate
SHA in the verification result. It refuses inconsistent approval-boundary state.
Read-only inspection does **not** validate the *current* workspace contents;
`original_fixture_unchanged` is the recorded observation from the prior
sandbox verification. A future apply operation must recheck source and target.

The default projection contains run/task/outbox statuses, artifact IDs/hashes,
Foundation Sec structured findings (including `external_exploitability`),
controlled fixture baseline/candidate observations, source SHA and diff SHA,
event timeline and only allowlisted Gemma Gateway receipt fields. It never
includes raw prompts, tool output, review free text, response content, API keys,
lease tokens, source code or patch by default. Receipts are **local operational
logs**, not an exhaustive or cryptographically authenticated inference audit.

`--include-content` deliberately emits the candidate source, unified diff and
model-authored review summary to **local stdout**. Treat the model summary and
source as untrusted content; do not pipe it to automation that follows model
instructions, and do not paste confidential content into chat accidentally.
The tool has no approve/reject/apply/write flags.

## Install from Node C (Mac) to Node A

On Node C after saving the ZIP into `~/Downloads`:

```bash
scp ~/Downloads/AXONVERTEX_Checkpoint_2E07A_Operator_Review.zip \
  axonvertex@100.82.103.57:/tmp/
```

On Node A, from the repository root, on the exact expected base commit:

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio
unzip -n /tmp/AXONVERTEX_Checkpoint_2E07A_Operator_Review.zip -d .
source services/benchmark-runner/.venv/bin/activate
python -m unittest discover -s services/benchmark-runner/tests \
  -p 'test_operator_review_v07a.py' -v
python -m unittest discover -s services/benchmark-runner/tests -p 'test_*.py'
```

Review the **existing** investigation; do not resubmit or re-run the models:

```bash
python scripts/ops/review_run_v07a.py --run-id v06b-supervised-api-live-001 \
  | jq '{run_id,job,runtime_status,security_review,candidate_change,verification_result,gateway_receipts}'
```

To review the patch and free-text review explicitly on your own terminal:

```bash
python scripts/ops/review_run_v07a.py --run-id v06b-supervised-api-live-001 \
  --include-content | jq '{security_review,candidate_change}'
```

Only stage these four new files for 0.7A; leave unrelated untracked files alone.
Do not push or enable any approval feature until the live review results are
inspected. Nothing here changes existing `systemd` units or requires a restart.
