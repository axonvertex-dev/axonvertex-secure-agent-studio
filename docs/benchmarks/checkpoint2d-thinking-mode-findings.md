# Checkpoint 2D — Thinking Mode Findings

## 2D-B: Native Gemma 4 Thinking-Mode Probe

Model:

- `gemma-4-12b-it-qat`
- SGLang patched v0.5.17
- Gemma 4 reasoning parser
- Native template control: `enable_thinking`
- Generation ceiling: 8192 tokens

## Serving behavior

The deployed Gemma 4 chat template exposes a binary reasoning control:

- `enable_thinking=false` — thinking disabled
- `enable_thinking=true` — thinking enabled

The template does not expose distinct low/medium/high reasoning budgets.

Earlier experiments using `reasoning_effort=low|medium|high`
produced identical reasoning-token usage for completed cases.
Native-toggle testing confirms that `reasoning_effort=low`
corresponds behaviorally to enabling Gemma thinking.

## MATH-500 Level-5 hard3 probe

Three deterministic Level-5 examples were evaluated:

1. Algebra
2. Counting & Probability
3. Geometry

### Thinking OFF

- Cases: 3
- Generation completed: 3/3
- Budget exhaustion: 0/3
- Correct: 3/3
- Overall task success: 100%
- Mean reasoning tokens: 0
- Mean latency: 30.0 seconds

### Thinking ON

- Cases: 3
- Generation completed: 1/3
- Budget exhaustion: 2/3
- Correct completed answers: 1/1
- Overall task success: 33.3%
- Mean reasoning tokens: 5875.7
- Mean latency: 212.7 seconds

Thinking ON was approximately 7.1x slower on this probe.

The two unsuccessful Thinking-ON cases are classified as
generation-budget exhaustion rather than mathematical-answer
failures:

- reasoning_tokens = 8192
- completion_tokens = 8192
- finish_reason = length
- final content = empty

## Interpretation

This probe does not establish that thinking reduces mathematical
accuracy. The sample is too small for that claim.

It establishes a concrete execution failure mode:

> Enabling Gemma 4 thinking can consume the entire generation budget
> before the model transitions from reasoning to final-answer output.

Therefore task success, reasoning termination, token budget, and
latency must be treated separately from answer accuracy.

## Architectural implication

Thinking should be controlled by the Decision Control Runtime rather
than enabled indiscriminately.

The runtime should support:

- thinking OFF / ON routing
- reasoning-token budgets
- wall-clock budgets
- termination detection
- budget-exhaustion classification
- fallback execution
- retry after context compaction
- structured evidence capture without persisting private reasoning

## Next experiment: Checkpoint 2D-A

Compare Thinking ON against the existing long-context evidence
reasoning baseline:

- C-insufficient / 64K
- C-insufficient / 96K
- C-insufficient / 128K

The key research question is:

> Can increased reasoning compute recover decisions from noisy long
> context, or does evidence-preserving context compaction provide the
> stronger intervention?

Existing deterministic compaction already recovered all three
C-insufficient long-context failures.
