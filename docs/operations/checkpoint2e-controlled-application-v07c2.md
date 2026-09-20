# AXONVERTEX Secure Agent Studio — 2E-0.7C2 controlled synthetic application

**Base:** `22ea84b` on `feat/checkpoint2e04-durable-agent-runtime`. 
**Dependency:** committed 0.7B decision ledger, 0.7C1 read-only gate.
**Trust boundary:** local Node A Unix principal, synthetic CWE-89 fixture only. No API approval, generic Git patching, production repositories, releases, deployment, or automatic Git commit.

## State machine and operations

```text
0.7B APPROVE (explicit, immutable decision)
    |
0.7C1 read-only preflight (exact evidence, target commit, owner, clean clone)
    |
0.7C2 authorize preview (NO file/ledger write)
    |
0.7C2 authorize --record-authorization (SQLite AUTHORIZED; NO app.py write)
    |
0.7C2 execute preview (NO source write)
    |
0.7C2 execute --apply (SQLite APPLYING first)
    |
atomic replacement of synthetic application_workspace/app.py ONLY
    |
Git diff, source SHA, unchanged other tracked files, unchanged original fixture,
Docker python:3.11-alpine UID65534 behavioral verification
    |
SQLite APPLIED + post-application receipt
```

- **Separation:** 0.7B `APPROVE` alone cannot execute. Authorization is recorded using its own request ID. Execution requires a *different explicit CLI operation*, `--apply`, and a separate request ID.
- **Binding:** authorizing/applying OS UID and username, full run-scoped target path, original fixture Git commit, verified candidate source SHA, verification artifact SHA, committed decision receipt, bounded synthetic scope.
- **Filesystem isolation:** exact `.../durable-live/<run>/application_workspace` independent Git clone; original `fixture_repo` and `candidate_workspace` refused. Only `app.py` may differ. `app.py` is replaced atomically via a target-relative directory FD. No Git commit created. Old Git HEAD remains the pinned synthetic fixture commit; working tree shows only modified `app.py`.
- **Verification:** generated code is *never executed on the host*: Docker `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534`, bounded resources, image `python:3.11-alpine`. Test measures normal=1, nonexistent=0, attack=0. Container image is tag-pinned rather than digest-pinned; do not characterize this as production-grade supply-chain assurance.
- **Integrity limits:** SHA receipts in local SQLite are tamper-evident against accidental edits, not signed, not protected from a privileged administrator able to rewrite ledger and hashes. The OS account alone is not individually attributable if shared. The entire target lifecycle does not yet provide an OS-enforced sandbox against malicious same-account processes racing pathname checks. Keep local-only.

## Interruption and controlled recovery

The applicator persists `APPLYING` *before* changing source. Failure caught after entering `APPLYING` marks `NEEDS_OPERATOR_RECOVERY`, leaves available evidence and target untouched by retry logic, and exits. A hard crash may leave `APPLYING`; restart never blindly rewrites source. `reconcile` **does not** write source. It only succeeds if the exact candidate was already written, only app.py differs, current approval/evidence/identity remain valid, and post-application Docker behavior passes. If crash was *before* the source swap, or the source is tampered, hold for manual review rather than automatic reset. A partially committed SQLite result must be inspected and investigated; no automatic rollback.

`inspect` does not create the ledger. `authorize` defaults to preview. `execute` defaults to preview. `reconcile` defaults to advisory preview. Only `--record-authorization` writes an application authorization; only `execute --apply` writes the target source; `reconcile --apply` runs Docker and marks an already-written candidate verified, never rewrites it.

## Development acceptance on Node A

From commit `22ea84b` after installing this additive 4-file overlay and retaining the separate one-line EOF cleanup from 0.7C1:

```bash
source services/benchmark-runner/.venv/bin/activate
python -m py_compile \
  services/benchmark-runner/src/benchmark_runner/application_execution_v07c2.py \
  scripts/ops/application_execute_v07c2.py
python -m unittest discover -s services/benchmark-runner/tests \
  -p test_application_execution_v07c2.py -v
python -m unittest discover -s services/benchmark-runner/tests \
  -p 'test_*.py'
python scripts/ops/application_execute_v07c2.py inspect \
  --run-id v06b-supervised-api-live-001
```

**DO NOT** generate an `APPROVE` decision for `v06b-supervised-api-live-001` merely to test the applicator. That recovered historical candidate is intentionally undecided. The new tests use temporary independent fixture repos, temporary decision/application SQLite ledgers and a **fake** Docker function; a future live validation requires a *new disposable synthetic run, its own explicitly authorized decision and real Docker check*. The code supports real Docker but an end-to-end live post-application test is not part of this overlay's offline acceptance.

### Conceptual CLI after a separate authorized synthetic test run exists

```bash
# All flags specify exact reviewed target/evidence; 'authorize' defaults to preview.
python scripts/ops/application_execute_v07c2.py authorize \
  --run-id "$RUN" --target "$TARGET" \
  --expected-candidate-sha256 "$CANDIDATE_SHA" \
  --expected-verification-sha256 "$VERIFICATION_SHA" \
  --expected-decision-receipt-sha256 "$DECISION_SHA" \
  --expected-target-commit "$TARGET_HEAD" \
  --request-id "$AUTH_REQUEST"

# On a separately reviewed test run only: repeat with --record-authorization.
# 'execute' with --apply is a second consequential action, not an implicit consequence.
# If interrupted, inspect before considering reconcile --apply.
```

No package files change `.env`, user-systemd units, gateway, model call paths, or existing historical run ledgers. This is not yet a VS Code UI or authenticated multi-user governance plane.
