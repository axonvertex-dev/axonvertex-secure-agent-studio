# Checkpoint 2C — Context-Scale Reasoning Baseline v1

## Status

**BASELINE COMPLETE — 12/12 cases executed; 5 PASS, 7 FAIL.**

This result is intentionally preserved without changing prompts, graders,
evidence placement, context profiles, or reasoning settings.

## Profile Summary

| Profile | Passed | Failed |
|---|---:|---:|
| 32K | 3 | 0 |
| 64K | 1 | 2 |
| 96K | 1 | 2 |
| 128K | 0 | 3 |

## Detailed Matrix

| Profile | Scenario | Expected | Actual | Semantic | Provenance | Infrastructure | Prompt tokens | Latency ms | Result |
|---|---|---|---|---|---|---|---:|---:|---|
| 32k | A-vulnerable | VULNERABLE | VULNERABLE | PASS | PASS | PASS | 28167 | 39318 | PASS |
| 32k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | PASS | PASS | PASS | 28154 | 43630 | PASS |
| 32k | C-insufficient | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | PASS | PASS | PASS | 28175 | 42503 | PASS |
| 64k | A-vulnerable | VULNERABLE | VULNERABLE | PASS | PASS | PASS | 60912 | 110632 | PASS |
| 64k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | PASS | FAIL | PASS | 60936 | 110534 | FAIL |
| 64k | C-insufficient | INSUFFICIENT_EVIDENCE | VULNERABLE | FAIL | PASS | PASS | 60920 | 109271 | FAIL |
| 96k | A-vulnerable | VULNERABLE | VULNERABLE | PASS | PASS | PASS | 93694 | 206709 | PASS |
| 96k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | PASS | FAIL | PASS | 93681 | 437210 | FAIL |
| 96k | C-insufficient | INSUFFICIENT_EVIDENCE | VULNERABLE | FAIL | PASS | PASS | 93702 | 200353 | FAIL |
| 128k | A-vulnerable | VULNERABLE | VULNERABLE | PASS | FAIL | PASS | 126476 | 333186 | FAIL |
| 128k | B-not-vulnerable | NOT_VULNERABLE | NOT_VULNERABLE | PASS | FAIL | PASS | 126463 | 488967 | FAIL |
| 128k | C-insufficient | INSUFFICIENT_EVIDENCE | VULNERABLE | FAIL | PASS | PASS | 126447 | 330300 | FAIL |

## Principal Observation

The baseline does **not** support the assumption that increasing context
length monotonically improves reasoning quality.

At 32K all three scenarios passed.

At 64K and 96K:
- the vulnerable case remained successful;
- the not-vulnerable case retained the correct verdict but failed provenance;
- the insufficient-evidence case over-asserted `VULNERABLE`.

At 128K:
- semantic verdicts for the vulnerable and not-vulnerable cases remained correct,
  but provenance failed;
- the insufficient-evidence case again over-asserted `VULNERABLE`;
- no scenario satisfied the full benchmark contract.

Infrastructure validation passed throughout the matrix.

## Experimental Controls

- Model: Gemma 4 12B QAT
- Inference: SGLang / Node A
- Temperature: 0
- Explicit reasoning effort: default / not enabled
- Cache policy: cold-cache flush before every case
- Same evidence semantics across context profiles
- Same deterministic grader across profiles

## Interpretation

This is a baseline, not a final quality result.

It motivates empirical Context Budget Management, evidence-aware compaction,
uncertainty preservation, recursive retrieval, and model/reasoning routing
rather than automatically selecting the largest available context window.

Raw case results remain under:

`benchmarks/results/checkpoint2c/checkpoint2c-baseline-v1/`

and are intentionally excluded from normal Git tracking.
