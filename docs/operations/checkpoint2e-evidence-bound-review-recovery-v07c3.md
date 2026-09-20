# AXONVERTEX 2E-0.7C3 — Evidence-bound versioned Node C review recovery

Base: `ac62a8c` on `feat/checkpoint2e04-durable-agent-runtime`. Scope is the controlled **synthetic CWE-89 fixture only**. This patch modifies no existing record in the 0.7B decision ledger or 0.7C2 application ledger, and never directly applies generated code.

## Why

`v07c2-application-e2e-live-001` ended `REVIEW_QUARANTINED` because the generated `review.supporting_evidence_ids` added characters to the first source ID. The immutable `GemmaResumeOutput.evidence_ids` and `SecurityReview.evidence_ids` contained the two correct IDs. Correctness of the *finding* is not enough to waive the deterministic citation validator.

## State machine

```text
REVIEW_QUARANTINED (original SecurityReview kept, root BLOCKED)
    | local OS operator, explicit rejected-artifact SHA256, known validation errors,
    | intact fixture, no decision/candidate/previous retry
    v
WAITING_FOR_REVIEW_RETRY / REVIEW_RETRY_PENDING
    | new versioned task :review-retry-1 and outbox :dispatch-review-retry-1
    | exact prompt SHA256, local operator UID and account audit event
    v
Node C strict structured re-review with exact allowlisted canonical IDs
    | no citation rewriting, no cross-node source-analysis replay
    +-- valid --> SecurityReviewRetry accepted, root READY, REVIEW_COMPLETED
    |                 --> existing Gemma remediation and Docker verification
    +-- invalid -> SecurityReviewRetry rejected, root BLOCKED, REVIEW_QUARANTINED
                     (no automatic second recovery)
```

The original `:foundation-review` artifact is NEVER updated or deleted. The new `:foundation-review-retry-1` uses artifact type `SecurityReviewRetry` and must bind to the same pinned Git source and committed Gemma source analysis. `CandidateChange.review_artifact_id` must point to the accepted review, and downstream 0.7A, 0.7B, 0.7C1 and 0.7C2 read the accepted version and its hash while retaining a redacted list of rejected review attempts.

A bounded inference transport failure uses the existing lease budget (maximum three transport attempts), then enters `NEEDS_OPERATOR_RECOVERY`. A completed invalid *review* is not retried again. This patch does not implement a second operator retry policy.

## Installation and verification

Stop **only** `axonvertex-agent-runtime-worker.service` before installing changed Python modules. The Gateway and API may stay online, but do not submit another run during installation. Check the Git base and the package SHA256; install only if they match. Run `py_compile`, eight new focused offline tests, then the full `test_*.py` suite. Existing untracked `README.md`, `.pre-scout-recovery` and `.env` must remain untouched. Never `git add .`.

## Recovery preflight (read-only)

```bash
RUN=v07c2-application-e2e-live-001
BRIDGE=services/benchmark-runner/src/benchmark_runner/durable_gateway_bridge_v04d2.py
REJECTED_SHA="$(python "$BRIDGE" inspect --run-id "$RUN" | jq -r '.artifacts[] | select(.artifact_type == "SecurityReview") | .content_sha256')"
python scripts/ops/recover_review_v07c3.py --run-id "$RUN" \
  --expected-rejected-review-sha256 "$REJECTED_SHA" \
  --reason-code FOUNDATION_REVIEW_CITATION_MISMATCH
```

Expected: `REVIEW_RECOVERY_ELIGIBLE_DRY_RUN`, with zero new artifacts, model calls, decisions or application records. **Stop here for operator review before `--apply`.** The action applies no code, but `--apply` authorizes a new model call and new durable artifacts. Do not run it until tests and the live quarantine have been reviewed.

When explicitly authorized, rerun the identical command with `--apply` while the worker is stopped; then start the supervised worker. If a crash occurs after durable retry authorization but before the queue update, the identical apply command reconciles that half-complete local transaction with the same local account. Once the queue is updated, the command refuses a second authorization. A crash after a committed review receipt but before the worker queue update reconciles without calling Node C again.

## Boundaries and limits

- Never silently rewrite invented IDs; a model-produced review must validate independently.
- Only one review retry for the specific pair of errors `Invented evidence reference` + `Required source evidence ID omitted`. Other quarantines are not recovered by this command.
- No arbitrary workspace, production target, internet fallback, approval or code application.
- Unix UID/account gives *local account attribution*, not proof of an individual human when accounts are shared. Gateway receipts are operational and not cryptographically authenticated.
- This release's local offline tests fake model and Docker behavior; live Node C response and Docker-backed verification must be independently observed on Node A before acceptance and Git commit.
