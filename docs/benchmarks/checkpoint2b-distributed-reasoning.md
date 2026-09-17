# Checkpoint 2B — Distributed Evidence Reasoning

## Status

**PASS — 3/3 scenarios at the 32K context profile.**

The benchmark validates three distinct reasoning outcomes:

- `VULNERABLE`
- `NOT_VULNERABLE`
- `INSUFFICIENT_EVIDENCE`

The suite requires semantic correctness, evidence provenance, counter-evidence preservation, uncertainty evidence handling, and infrastructure/token-budget correctness.

## Results

| Scenario | Verdict | Prompt Tokens | Latency ms | Status |
|---|---|---:|---:|---|
| A-vulnerable | VULNERABLE | 28167 | 38127 | PASS |
| B-not-vulnerable | NOT_VULNERABLE | 28154 | 40444 | PASS |
| C-insufficient | INSUFFICIENT_EVIDENCE | 28175 | 41911 | PASS |

## Evidence Contract

The Checkpoint 2B evidence model distinguishes:

- required supporting evidence
- allowed supporting evidence
- required counter-evidence
- allowed counter-evidence
- required uncertainty evidence
- allowed uncertainty evidence
- unsupported evidence

A correct verdict alone is insufficient for PASS.

## Important finding

During development, the model initially over-asserted vulnerability when a critical authorization implementation link was missing. The final benchmark explicitly tests uncertainty handling and requires `INSUFFICIENT_EVIDENCE` when the causal chain cannot be established from authoritative evidence.

## Scope limitation

Checkpoint 2B validates distributed synthetic security evidence reasoning at the 32K profile. It does not yet establish performance at 64K/96K/128K, repository-shaped evidence reasoning, recursive retrieval, RLM behavior, or learned context routing.

