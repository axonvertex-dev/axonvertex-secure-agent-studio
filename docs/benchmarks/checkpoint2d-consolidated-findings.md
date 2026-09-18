# Checkpoint 2D — Thinking Mode vs Context Quality

## Objective

Checkpoint 2D evaluates whether additional model reasoning compute can
recover failures caused by noisy long context, and compares that intervention
against deterministic evidence-preserving context compaction.

The experiment builds directly on Checkpoint 2C.

## Native Gemma 4 reasoning control

The deployed Gemma 4 chat template exposes a binary reasoning control:

- `enable_thinking=false` — Thinking OFF
- `enable_thinking=true` — Thinking ON

The deployed template does not expose independent low, medium and high
reasoning budgets.

Earlier experiments using the generic OpenAI-compatible
`reasoning_effort=low|medium|high` interface produced identical reasoning-token
usage for completed cases.

Inspection of the deployed SGLang/template path confirmed that Gemma 4 uses the
native `enable_thinking` boolean.

Therefore Checkpoint 2D uses:

- Thinking OFF
- Thinking ON

rather than treating low/medium/high as distinct Gemma 4 capabilities.

---

## 2D-B — MATH-500 native thinking-mode probe

Three deterministic Level-5 MATH-500 examples were evaluated.

### Thinking OFF

- Cases: 3
- Generation completed: 3/3
- Correct: 3/3
- Generation truncations: 0/3
- Mean reasoning tokens: 0
- Mean latency: approximately 30.0 seconds

### Thinking ON

- Cases: 3
- Generation completed: 1/3
- Correct completed responses: 1/1
- Generation truncations: 2/3
- Mean reasoning tokens: approximately 5875.7
- Mean latency: approximately 212.7 seconds

The two unsuccessful Thinking-ON executions consumed the entire 8192-token
generation budget inside the reasoning channel:

- `reasoning_tokens = 8192`
- `completion_tokens = 8192`
- `finish_reason = length`
- no final answer emitted

These are classified as reasoning/generation-budget exhaustion failures, not
mathematical-answer errors.

This establishes that enabling model thinking can introduce substantial latency
and termination risk and therefore should not be enabled indiscriminately.

---

## 2D-A — Long-context distributed evidence reasoning

Scenario:

- `C-insufficient`
- Expected verdict: `INSUFFICIENT_EVIDENCE`
- Decision-critical uncertainty: `C4`

Profiles tested:

- 64K
- 96K
- 128K

Generation budget:

- 4096 tokens

### Previous Checkpoint 2C raw-context baseline

| Profile | Thinking | Verdict result |
|---|---|---|
| 64K | OFF | FAIL |
| 96K | OFF | FAIL |
| 128K | OFF | FAIL |

In each raw long-context failure the model had access to the decision-critical
uncertainty evidence but incorrectly produced a definitive `VULNERABLE`
verdict.

### Checkpoint 2D-A — Raw context + Thinking ON

| Profile | Verdict | Reasoning tokens | Latency |
|---|---|---:|---:|
| 64K | INSUFFICIENT_EVIDENCE | 584 | 118.0 s |
| 96K | INSUFFICIENT_EVIDENCE | 1619 | 274.6 s |
| 128K | INSUFFICIENT_EVIDENCE | 1808 | 427.0 s |

Results:

- Decision sufficiency: 3/3 PASS
- Generation reliability: 3/3 PASS
- Context-profile reservation contract: 3/3 PASS
- Decision-critical uncertainty `C4`: recovered in all 3 cases
- Finish reason: `stop` in all 3 cases

Prompt measurements:

| Profile | Target | Actual | Delta |
|---|---:|---:|---:|
| 64K | 60928 | 60918 | -10 |
| 96K | 93696 | 93700 | +4 |
| 128K | 126464 | 126445 | -19 |

All are inside the ±128-token profile tolerance.

---

## Comparison with deterministic compaction

Checkpoint 2C deterministic evidence-preserving compaction had already recovered
the same three semantic failures:

| Scenario | 64K | 96K | 128K |
|---|---|---|---|
| Raw + Thinking OFF | FAIL | FAIL | FAIL |
| Raw + Thinking ON | PASS | PASS | PASS |
| Compacted + Thinking OFF | PASS | PASS | PASS |

The compacted C-insufficient executions completed in approximately 7–8 seconds,
while raw-context Thinking-ON executions required approximately:

- 118 seconds at 64K
- 275 seconds at 96K
- 427 seconds at 128K

Therefore both interventions can recover the semantic decision, but
evidence-preserving context compaction is dramatically more compute-efficient
for this task family.

---

## Decision Contract v2 interpretation

For scenario C:

Decision-required evidence:

- C1
- C2
- C3

Decision-required uncertainty:

- C4

Closure/audit evidence:

- CC1

The Thinking-ON runs included the full decision-required support and `C4`,
therefore all three satisfy Decision Contract v2 for decision sufficiency.

The legacy strict provenance contract remains incomplete because CC1 is not
consistently cited by the model.

This reinforces the distinction between:

1. decision sufficiency;
2. model citation completeness;
3. system-held audit provenance.

The Evidence Decision Graph/control plane should retain the full evidence
inventory independently of the model's selected citation subset.

---

## Infrastructure telemetry note

The historical infrastructure rubric reports failure because the
OpenAI-compatible usage response did not populate its expected API-side prompt
token field.

This is not a context-budget failure.

The benchmark's authoritative token counter measured:

- 60918 tokens at 64K
- 93700 tokens at 96K
- 126445 tokens at 128K

and all three remained within their profile contracts.

No frozen inference result is modified to correct this telemetry mismatch.
Derived assessments are stored separately.

---

## Architectural conclusion

Checkpoint 2D demonstrates that increased reasoning compute can recover semantic
decisions from noisy long context.

However, structured evidence-preserving context compaction can recover the same
decision using substantially less inference time and reasoning compute.

The emerging runtime policy is therefore:

1. retrieve and structure relevant evidence;
2. preserve contradiction, uncertainty and provenance;
3. compact noisy or oversized context;
4. attempt bounded Thinking-OFF inference;
5. escalate to Thinking ON only when decision uncertainty remains;
6. enforce reasoning-token and wall-clock budgets;
7. classify reasoning-budget exhaustion separately from answer correctness;
8. fall back, recompact or escalate to another reasoning specialist when needed.

This supports the Context Intelligence Gateway thesis:

> Context quality and evidence structure are first-class inference controls.
> Additional reasoning compute is an escalation mechanism, not a substitute for
> well-constructed context.

---

## Next checkpoint

Checkpoint 2E should convert these findings into an explicit Decision Control
Runtime policy:

- context-quality assessment;
- compaction trigger;
- Thinking OFF / ON routing;
- reasoning budget enforcement;
- termination monitoring;
- fallback execution;
- evidence graph integration;
- structured decision trace;
- later learned routing/classification experiments.

