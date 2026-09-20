# AXONVERTEX Secure Agent Studio — Checkpoint 2E-0.7B

**Base commit:** `d7f18f0` (`feat/checkpoint2e04-durable-agent-runtime`).

## Scope and trust

This checkpoint adds a **local, fixture-scoped operator decision ledger**. It does not alter the existing Agent Studio API, queue, worker, inference Gateway, durable task state, target repository, or sandbox verification. `APPROVE` means the local OS principal accepts this verified synthetic candidate for a future **separate** application review; it is NOT application or production deployment authorization. `REJECT` records a local decision but does not mutate the existing durable run status. The 0.7C application gate MUST consult the independent ledger, authenticate its actual requester, recheck target/candidate source/commit and security policy, and refuse a rejected or missing decision. No `--apply` invocation in this checkpoint applies code; it applies the *decision record* only.

The single shared `AGENT_STUDIO_API_KEY` is intentionally not used for human attribution. The CLI binds decisions to UID and OS account name determined by the kernel (`getuid/geteuid` and `pwd.getpwuid`), refuses root/setuid and requires a local interactive terminal for justification. **Shared Unix accounts are not individual human identities.** If more than one human can log in as `axonvertex`, this is a single-account development audit only; OIDC/WebAuthn or separately authenticated named Unix logins are needed for individual attribution before exposing approval in VS Code or a network API. This version has no remote approval endpoint and no cryptographic signature. A SHA-256 receipt detects inadvertent/noncoherent ledger edits; an actor with write control can rewrite DB and recompute digest, so this is **not tamper-evident against an administrator or compromised account**.

## Decision prerequisites

`operator_review_v07a.project` revalidates all persisted artifact payload digests, source/diff SHA-256, verification-to-candidate binding and approval boundary. Both worker and durable runtime status must be `VERIFIED_CANDIDATE_AWAITING_APPROVAL`, the root task `AWAITING_APPROVAL`, verification outbox `DONE`, Foundation Sec review accepted by its schema validator and Docker verification `passed:true` and `original_fixture_unchanged:true`. External exploitability may remain `insufficient_evidence` and must not be implicitly upgraded. Explicit expected candidate **source SHA-256** and expected **VerificationResult artifact content SHA-256** must match a review inspected by the operator. No user repository changes are supported.

Decisions are stored in `benchmarks/results/checkpoint2e/operator-decisions-v07b/decisions.sqlite3` with directory mode 0700, DB mode 0600. The separate DB uses `UNIQUE(run_id)` and `UNIQUE(request_id)` and SQLite `BEGIN IMMEDIATE`; exact requests replay idempotently, conflicting decisions/reused IDs fail. Triggers reject UPDATE/DELETE through normal SQL clients; root or database owner can still bypass them. The worker's existing per-run `flock` is held during decision writing. Local state remains in its original `VERIFIED_CANDIDATE_AWAITING_APPROVAL` state and is interpreted with the separate decision view.

## Review on Node A (no decision mutation)

Transfer ZIP from Node C `~/Downloads` to `axonvertex@100.82.103.57:/tmp/`, check its SHA-256 as provided in chat, `unzip -n ZIP -d .`, source the benchmark-runner venv and run:

```bash
python -m unittest discover -s services/benchmark-runner/tests -p 'test_operator_decisions_v07b.py' -v
python -m unittest discover -s services/benchmark-runner/tests -p 'test_*.py'

RUN=v06b-supervised-api-live-001
python scripts/ops/operator_decision_v07b.py inspect --run-id "$RUN"
python scripts/ops/review_run_v07a.py --run-id "$RUN" | jq '{job,candidate_change,verification_result,artifacts}'
```

`inspect` must print `"decision":null` for an undecided run and must not create the ledger. There is no need to restart the supervised services; this is a separate local CLI. On first acceptance, **do not decide the live run**; run focused/full tests and read-only inspect first. The operator can choose a decision in a subsequent step.

## Decision options

`decide --run-id RUN --decision APPROVE|REJECT --reason-code REASON --expected-candidate-sha256 HEX --expected-verification-sha256 HEX --request-id UUID [--apply]`.

- `APPROVE`: `VERIFIED_SYNTHETIC_FIX_ACCEPTED`
- `REJECT`: `FIX_NOT_ACCEPTED`, `INSUFFICIENT_REVIEW_EVIDENCE`, `UNACCEPTABLE_FUNCTIONAL_CHANGE`, `OTHER_REVIEW_REASON`

The terminal prompts for a 12–1024 character justification, to avoid placing the rationale in shell history. Without `--apply`, result `DECISION_ELIGIBLE_DRY_RUN` leaves all files unchanged. With `--apply`, it writes the decision ledger only; an exact retry returns `DECISION_ALREADY_COMMITTED`. `inspect` returns a `local_digest_not_signed` integrity label. Do not enter private credentials, prompt contents or protected health data in the justification. Do not use model-authored suggestions as authority to approve.

## Constraints for future 0.7C

This decision is scoped strictly to `synthetic_CWE-89_fixture_only`. No application, external filesystem write, production target, MTA, MCP, A2A, VS Code decision endpoint, human-identity federation, signatures, or remote approval is provided. The future apply gate must never interpret current worker `AWAITING_APPROVAL` or this ledger's `APPROVE` as sufficient authorization to mutate a target; a fresh separate target-bound authorization is required.
