# Checkpoint 2E-0.7D2 — Visual Operator Workbench

This is a **presentation-only** patch on top of committed 0.7D1 (`be0329bd765b6b70f245240268360cff0359e66b`).

The 0.7D1 allowlisted backend-to-Webview contract and read-only `ReadOnlyRunAdapter` remain unchanged. The existing Coding Agent remains untouched. The extension still runs in the Node A Remote SSH extension host, not through a new exposed API port.

## Visual features

- Separates recorded *investigation*, *operator decision*, and *application* state instead of treating the investigation's retained `VERIFIED_CANDIDATE_AWAITING_APPROVAL` as the final application state.
- Preserves rejected and accepted Foundation Sec review versions with exact validation errors and hashes.
- Displays accepted model evidence with external exploitability limitations.
- Displays line-classified remediation diff using `textContent`, never executable HTML.
- Compares baseline and candidate fixture counts; absent results display `Not measured`, never an invented zero.
- Shows separate operator decision, application receipt and UTC application-event timeline.
- Shows only allowlisted artifact IDs and content hashes.

## Security boundary

The Webview CSP forbids connections, forms, frames and external resources. There are no decision, application or model-message controls. No raw CLI output, raw artifact payloads, credentials or application-result JSON is sent into the Webview. Rendering is DOM/text-only; source diff text is never parsed as HTML.

## Acceptance procedure

1. Confirm Git HEAD is 0.7D1 (`be0329b`) before extracting the patch and preserve unrelated files.
2. Apply patch using `unzip -o` after confirming the expected 0.7D1 provider SHA-256 and compile from monorepo root with `npm run compile --workspace agent-studio-coding-agent`.
3. Run `node --test apps/vscode-extension/out/tests-node/operator-*.test.js` and `npm run lint --workspace agent-studio-coding-agent`.
4. Inspect changes before committing; package via the previously validated isolated `/tmp` method, **not** from the hoisted workspace.
5. Install the new VSIX into the Node A Remote SSH extension host; load `v07c2-application-e2e-live-001`. Validate three state cards, rejected→accepted review history, diff, baseline 2→candidate 0 attack rows, APPROVE and APPLIED receipts.
6. Before and after UI inspection verify immutable acceptance snapshot SHA-256 `e72dbc4334644939e25501aa1682e87f0b77abaf7c53d3da65146693e91251d0`, and that the original fixture remains clean and only `app.py` is modified in the independent application workspace.

The Node A Agent Studio backend, durable decisions, application engine and synthetic acceptance run must not be edited or rerun for this UI checkpoint.
