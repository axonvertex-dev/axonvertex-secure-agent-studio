# Checkpoint 2E-0.7D1: Operator Workbench integration

## Objective

Import the v0.3.0 Coding Agent source selectively into `apps/vscode-extension`, retain its existing capabilities, and add a separate operator display for the verified synthetic run. The `packages/shared-types/operator-view.d.ts` contract is deliberately projection-only.

## Architectural boundaries

| Component | Place | Responsibility |
|---|---|---|
| VS Code desktop | Node C macOS | Displays Remote SSH view |
| Extension host | Node A Ubuntu | Runs read-only operator adapters and existing Coding Agent |
| CLI scripts | Node A repository | Read existing review, decision, application and artifact records |
| Durable run | `benchmarks/results/checkpoint2e/durable-live/v07c2-application-e2e-live-001` | Remains intact, Git-ignored, not copied into source package |
| Operator Webview | Node C rendering | Only receives allowed fields; refresh/select only |

0.7D1 does **not** expose API `:17713`, use any model, approve, reject, authorize or apply code in its operator view. The Coding Agent is a separate existing surface and retains its governance controls; it is not made read-only by this feature.

## Release gate

`npm ci`, `npm run compile`, contract tests and `npm run lint` on Node A; actual Remote SSH display against the preserved run; before/after fixture SHA, target SHA, decision receipt, application receipt and baseline snapshot SHA. No model inference needed. Do not delete or clean the accepted application workspace.

## Implementation notes

- Python operator scripts are invoked by `execFile` with fixed filenames and vetted run IDs; no shell and no Webview-controlled command names.
- Reject symbolic-link run directories and require trusted SSH remote workspace.
- Existing CLI output is normalized into an allowlisted display contract; UI creates nodes with `textContent`, uses restrictive CSP, no external libraries loaded into Operator Webview.
- The read-only CLI outputs may include sensitive evidence; the Webview can display the approved candidate diff. Access follows the Node A Unix account and VS Code Remote SSH session, **not** per-person authorization.
- The display contract currently projects validation and event metadata; cryptographic identity, signed receipts, fine-grained access control and user-mediated write operations are follow-up checkpoints.
