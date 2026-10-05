# AXONVERTEX REG-0.5 TypeScript Runtime Adapter

This package is the first TypeScript execution bridge between the AXONVERTEX Agent Registry and the real sovereign model runtimes.

The adapter does not choose a model itself. It requests a governed resolution for a logical agent and purpose. A model call is possible only when the Registry returns `ALLOW`. The adapter then verifies that the runtime identity, model ID, endpoint reference, credential reference and engine exactly match its local allowlisted runtime mapping before resolving a local secret and making an OpenAI-compatible `/chat/completions` call.

## Fail-closed properties

- A Registry `DENY` causes no runtime network call.
- Unknown runtime IDs are rejected.
- Runtime metadata mismatches are rejected.
- Expired resolutions are rejected.
- The Registry returns secret references only; real API keys are resolved locally.
- Evidence contains hashes and references, never API keys.
- REG-0.5 remains `LAB_ONLY`; it does not create production admission.

## Current runtime mappings

- `runtime-gemma-node-a` -> Node A / SGLang / `gemma-4-12b-it-qat`
- `runtime-antares-node-b` -> Node B / llama.cpp / `antares-1b`
- `runtime-foundation-node-c` -> Node C / llama.cpp / `foundation-sec-8b-reasoning`

## VS Code boundary

A future VS Code extension should import `GovernedRuntimeAdapter` and send logical `agent + purpose + messages`. It should never receive or store model API keys in webview state.
