# AXONVERTEX Secure Agent — VS Code

STUDIO-0.1 is the first UI-driven VS Code surface for the governed sovereign secure-coding agent chain.

Pipeline:

1. Security Scout → Antares / Node B → `evidence_extraction`
2. Coding Investigator → Gemma / Node A → `code_reasoning`
3. Security Critic → Foundation Sec / Node C → `independent_security_review`
4. Final Evidence Synthesizer → Gemma / Node A → `evidence_synthesis`
5. Deterministic quality gate → no model self-approval

The extension reuses the REG-0.5 `GovernedRuntimeAdapter` source at build time. It does not duplicate Registry resolution logic and does not choose a physical model independently.

## Security boundaries

- Registry resolution occurs before every model invocation.
- Registry `DENY` stops the pipeline.
- Runtime/model/credential-reference mismatches fail closed inside REG-0.5.
- Model API keys and the lab Registry token are stored only in VS Code `SecretStorage`.
- Model output is rendered with `textContent`, not injected as HTML.
- No model can make the deterministic quality gate pass by merely emitting `ACCEPT`.
- STUDIO-0.1 remains a LAB_ONLY workflow until production identity and authorization replace the development admin-token path.

## Source context

The current editor selection is used when non-empty; otherwise the current file is used. `axonvertexSecureAgent.maxSourceChars` caps source sent to the model chain.
