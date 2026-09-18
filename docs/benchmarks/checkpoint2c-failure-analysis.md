# Checkpoint 2C.1 — Failure Characterization

## Baseline

- Total cases: 12
- PASS: 5
- FAIL: 7

## Failure classes

- `MISSING_REQUIRED_PROVENANCE`: 4
- `PROVENANCE_CONTRACT_FAILURE`: 4
- `SEMANTIC_VERDICT_FAILURE`: 3
- `TRACE_VERDICT_CONTRADICTION`: 3

## Missing required evidence

- `A6` omitted in 1 failed case(s)
- `B6` omitted in 3 failed case(s)

## Failed cases

| Profile | Scenario | Expected | Actual | Failure classes | Missing required evidence |
|---|---|---|---|---|---|
| 128k | A-vulnerable | VULNERABLE | VULNERABLE | MISSING_REQUIRED_PROVENANCE, PROVENANCE_CONTRACT_FAILURE | A6 |
| 128k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | MISSING_REQUIRED_PROVENANCE, PROVENANCE_CONTRACT_FAILURE | B6 |
| 128k | C-insufficient | INSUFFICIENT_EVIDENCE | VULNERABLE | SEMANTIC_VERDICT_FAILURE, TRACE_VERDICT_CONTRADICTION | — |
| 64k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | MISSING_REQUIRED_PROVENANCE, PROVENANCE_CONTRACT_FAILURE | B6 |
| 64k | C-insufficient | INSUFFICIENT_EVIDENCE | VULNERABLE | SEMANTIC_VERDICT_FAILURE, TRACE_VERDICT_CONTRADICTION | — |
| 96k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | MISSING_REQUIRED_PROVENANCE, PROVENANCE_CONTRACT_FAILURE | B6 |
| 96k | C-insufficient | INSUFFICIENT_EVIDENCE | VULNERABLE | SEMANTIC_VERDICT_FAILURE, TRACE_VERDICT_CONTRADICTION | — |

## Interpretation

The baseline exposes two distinct long-context degradation modes:

1. **Provenance coverage degradation.** The verdict remains semantically correct, but required corroborating evidence is omitted.

2. **Trace/verdict inconsistency.** The model explicitly surfaces uncertainty evidence but reaches a verdict that assumes the unresolved causal link is known.

These modes should be evaluated separately before changing reasoning effort, compaction, or routing.

