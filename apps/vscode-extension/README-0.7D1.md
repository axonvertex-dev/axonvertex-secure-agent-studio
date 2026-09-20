# AXONVERTEX VS Code: 0.7D1 read-only Operator Workbench

This folder selectively imports the original `agent-studio-coding-agent.zip` **TypeScript source**, runtime dependency manifest, media icon, original README/CHANGELOG and lockfile. Original Coding Agent commands, UI, tool implementations and approval logic are retained. A separate Operator Workbench view is newly added. The original archive's old .vsix and compiled JS are **not** installed; compile this source instead.

## Scope / boundary

- First test target: `v07c2-application-e2e-live-001` in Node A's durable-live results.
- User opens VS Code on Node C and connects using **Remote SSH** to Node A; install this extension in the SSH remote environment (not only locally on macOS).
- Open `/mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio` as the remote workspace root, or configure `agentStudio.operator.repositoryRoot` as that absolute Node A path.
- Operator view reads only `review_run_v07a.py --include-content`, `operator_decision_v07b.py inspect`, `application_execute_v07c2.py inspect`, and `durable_gateway_bridge_v04d2.py inspect` using child-process argument arrays, not a shell. These are executed with Node A's benchmark runner .venv Python if present.
- Webview receives an **allowlisted display-only projection** from `packages/shared-types/operator-view.d.ts`, never raw logs or SQLite rows. It uses CSP and textContent; no API keys enter the operator view.
- This iteration does **not** add new backend APIs, source mutations, approval endpoints or individual identity claims. The existing Coding Agent is still capable of editing code in its own view; the **Operator Workbench view only** is read-only. The two must not be mistaken for the same security boundary.
- Remote SSH and VS Code workspace trust are required; this is not a security boundary against a compromised Node A account or modified Python operator scripts. Existing receipt and audit limitations remain.

## Node A build

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio/apps/vscode-extension
npm ci
npm run compile
node --test out/tests-node/operator-normalize.test.js
npm run lint
npm exec -- vsce package                  # Only when ready to install
```

**Do not use `--no-dependencies` when packaging.** The original Coding Agent requires `markdown-it` and `sanitize-html` at runtime. `npm run compile` does not require an inference server.

## Initial UI acceptance

1. Open Remote SSH workspace on Node A in VS Code on Node C.
2. Open Agent Studio > Operator Workbench (Read-only).
3. Select `v07c2-application-e2e-live-001` and inspect the two reviewer versions, current candidate SHA, diff, Docker verification, `APPROVE` and `APPLIED` receipts.
4. Capture original snapshot SHA-256 `e72dbc4334644939e25501aa1682e87f0b77abaf7c53d3da65146693e91251d0`, `git status --short` in the target, and original fixture hash **before and after** browsing. Expect no changes.
5. Check supervisor logs for zero extra inference requests during UI inspection. Do not claim that merely running the compile demonstrates UI activation; actual Remote SSH UI acceptance is a separate step.

Original ZIP contained VSIX binaries and generated JS. They are deliberately excluded from this source-import checkpoint.
