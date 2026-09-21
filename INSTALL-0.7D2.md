# Install 0.7D2 visual-only source patch

Apply only to the committed 0.7D1 Agent Studio monorepo checkout at `be0329b`. This ZIP contains **two new files and one replacement file** in `apps/vscode-extension`, plus this document and a docs page. It contains no Python, backend, lockfile, artifact, fixture or Git metadata changes.

Node C: download ZIP and `scp ~/Downloads/axonvertex-operator-workbench-v07d2-visual-patch.zip axonvertex@100.82.103.57:/tmp/`.

Node A: from `/mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio`, run `git log -1 --oneline` and `git status --short`; do not overwrite if the operator provider differs from committed 0.7D1. Inspect `unzip -Z1` before extraction. Use `unzip -o /tmp/axonvertex-operator-workbench-v07d2-visual-patch.zip -d .` only after checking the targeted files, never run `git clean`.

Compile and test:

```bash
npm run compile --workspace agent-studio-coding-agent && \
node --test apps/vscode-extension/out/tests-node/operator-*.test.js && \
npm run lint --workspace agent-studio-coding-agent
```

The VSIX needs the **isolated package staging method** verified in 0.7D1. Do not package from the workspace directly (VSCE traversed hoisted `../../node_modules` and failed secret scanning). Do not disable secret scanning. Before any Git commit, check `git diff --check` and ensure the two pre-existing unrelated untracked files remain excluded.
