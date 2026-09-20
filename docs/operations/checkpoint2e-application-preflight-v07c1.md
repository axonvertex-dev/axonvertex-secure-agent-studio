# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.7C1

**Base:** commit `42422b2` on `feat/checkpoint2e04-durable-agent-runtime`.

## Scope

0.7C1 introduces the *read-only preflight* for later policy-gated application. This is intentionally **not** an applicator and supplies no `--apply` flag, no HTTP endpoint, no application grant, no Git writes, no model calls and no Docker invocation. Application implementation is a separate 0.7C2 change after 0.7C1 testing. A 0.7B APPROVE decision does not itself authorize or perform application.

Only the controlled synthetic CWE-89 run is supported; the sole accepted application target is an independently provisioned Git clone in `benchmarks/results/checkpoint2e/durable-live/<RUN>/application_workspace` with exactly the original fixture commit and tracked files. The original `fixture_repo` and `candidate_workspace` are NEVER accepted as application targets. No arbitrary, private, external or production Git repository may be supplied. Target is *explicitly provided* to the CLI and never inferred from the operator's current working directory.

## Read-only policy checks

1. Validate run ID and three expected digests: candidate source SHA-256, VerificationResult artifact digest and 0.7B decision receipt digest.
2. Require an actual committed local `APPROVE` in the separate decision ledger; refuse `REJECT`, missing decision, changed receipt, changed Unix account. Local Unix account is **not a separately authenticated human identity** on shared accounts.
3. Revalidate current worker/durable runtime states, all artifact digests, Foundation Sec accepted review, verified Docker behavior, unchanged fixture receipt, and exact evidence identities. External exploitability remains unestablished.
4. Require a precise pre-provisioned `application_workspace`; refuse symlinks, traversal, incorrect owner, missing Git root, target nested in another repo, wrong original commit, modified/untracked files, unexpected tracked file inventory and non-original `app.py`.
5. Return an allowlisted summary only, with `application_authorized:false` and `applies_code:false`. Do not output source, model review text, prompts, rationale or credentials. Git uses optional locking disabled during inspection.

The file/commit checks reduce mistakes but are **not** production-grade atomic path isolation against another process deliberately swapping paths during inspection; that requires directory-fd/openat and a scoped sandbox in 0.7C2. The ledger SHA receipt is local and unsigned; it is not evidence against an administrator with file write access. Do not expose this on a network API or infer independent human attribution.

## Node C to Node A installation

From Apple Silicon Node C, download package ZIP to `~/Downloads` and run:

```bash
scp ~/Downloads/AXONVERTEX_Checkpoint_2E07C1_Application_Preflight.zip \
  axonvertex@100.82.103.57:/tmp/
```

On Node A from repo root, verify the ZIP SHA provided separately, run `unzip -n` and Python venv focused/full tests. Current real investigation `v06b-supervised-api-live-001` intentionally has **no recorded approval**. Do not create an approval just to pass a live preflight. The 15 tests use isolated synthetic fixtures, temporary local Git clones and temporary decision ledgers, not the real run. Baseline Node A suite 123 -> 138 tests if no extra changes.

The CLI is available only as a preview after a decision exists and an isolated target has been provisioned:

```bash
python scripts/ops/application_gate_v07c1.py \
  --run-id RUN \
  --target benchmarks/results/checkpoint2e/durable-live/RUN/application_workspace \
  --expected-candidate-sha256 CANDIDATE_SOURCE_SHA256 \
  --expected-verification-sha256 VERIFICATION_ARTIFACT_SHA256 \
  --expected-decision-receipt-sha256 DECISION_RECEIPT_SHA256
```

Only `APPLICATION_PREFLIGHT_ELIGIBLE` means all *read-only* 0.7C1 checks passed. It does **not** grant permission to apply code or promise a later application will succeed. No approval decision, clone or source mutation is required to accept 0.7C1 on Node A.
