# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.6B1

## Scope

Repairs a reproducible operator-recovery issue in the **synthetic CWE-89 fixture** under
Node A `systemd --user` supervision. `UMask=0077` correctly protects `.env`, SQLite
and evidence but makes the two Docker-bound test workspaces `700/600` when created.
The sandbox is deliberately unprivileged UID/GID `65534:65534`; it cannot read
those bind-mounted files. A fresh supervised job consequently reaches
`VERIFY_PENDING`/`WAITING_FOR_VERIFICATION`, then
`NEEDS_OPERATOR_RECOVERY` at the third bounded attempt.

This package replaces **only** `continuous_remediation_worker_v05c.py` with a
36-line fixture-scoped sandbox-access contract, and adds a separate operator
recovery script and tests. It does not modify the systemd unit, service-wide
umask, private state files, Git source contents, or approval policy.

Before invoking the sandbox, the existing worker now checks original Git
HEAD/clean status; checks the original source, deterministic verifier and
committed narrow candidate bytes; rejects symlinks; and only then changes
`fixture_repo` and `candidate_workspace` to `0755` and their `app.py` /
`verify.py` files to `0644`. The sandbox remains read-only, unprivileged,
network-disabled. Never set the parent run directory or database to 755/644.

## Recovery contract

`scripts/ops/recover_verification_v06b1.py` is offline and fixture-only.
It requires an explicit run ID, exact candidate **source** SHA-256,
reason `SANDBOX_INPUT_PERMISSIONS_REPAIRED`, and `--apply` to mutate state.
Dry-run is the default. It refuses a changed Git HEAD/working tree, tampered
candidate, missing review, any already-committed verification artifact,
non-READY verification task, active lease, wrong phase, wrong failure type,
any exhausted stage other than verification, or a second recovery authorization.

A run lock protects the transition. The durable per-run SQLite outbox and
worker queue live in different databases: reset durable verification attempts
transactionally and append a unique operator event first, then requeue the
worker transactionally. If interrupted **between** commits, run the same
`--apply` command once more: the unique event and outbox attempts=0 prove
that the first phase committed. It never requeues Gemma, Antares or Node C.
The supervised worker automatically picks up the verification job.

## Node A controlled installation

First inspect that there are no other `WORKING` jobs. Stop **only** the worker
systemd user service, leaving the Gemma Gateway and API active. Back up the
committed worker source, then overwrite it from this archive. Run focused and
full tests and dry-run recovery before `--apply`. Do not copy raw SQLite
files while the worker is running or delete any run directory.

Use the original ZIP baseline SHA-256 in the assistant's installation
instructions. If the baseline hash differs, investigate before overwriting.

Expected resumed run: `v06b-supervised-api-live-001`,
`VERIFIED_CANDIDATE_AWAITING_APPROVAL`, `VerificationResult.passed=true`,
`original_fixture_unchanged=true`. Three preexisting Gemma gateway receipts
remain three; previous review/remediation dispatch attempts remain unchanged.

Limitations: no general repository permissions model, no arbitrary task retry
API, no multi-host lease coordination, no automated approval or code mutation,
and the successful sandbox result is not a production security guarantee.
