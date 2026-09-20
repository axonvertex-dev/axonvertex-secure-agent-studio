# Installing the 0.7D1 source-only integration into the Node A monorepo

Download this zip on Node C (macOS), transfer to Node A, and extract in the monorepo. Before extraction **confirm both target directories are empty**. This package has no Git root files, no compiled artifacts, no VSIX and no durable run data.

## Node C

```bash
scp ~/Downloads/axonvertex-operator-workbench-v07d1-source.zip \
  axonvertex@100.82.103.57:/tmp/
```

## Node A

```bash
cd /mnt/axonvertexstorage/development/projects/axonvertex-secure-agent-studio

if [ -n "$(ls -A apps/vscode-extension)" ] || [ -n "$(ls -A packages/shared-types)" ]; then
  echo 'DESTINATION_NONEMPTY — STOP AND INSPECT; DO NOT UNZIP'
else
  unzip -n /tmp/axonvertex-operator-workbench-v07d1-source.zip -d .
fi

cd apps/vscode-extension
npm ci
npm run compile
node --test out/tests-node/operator-normalize.test.js
npm run lint
```

If either directory is not empty, stop and compare its contents rather than overwriting existing work. Run the subsequent build commands only after successful extraction.

The source archive does not change any running service. Confirm the acceptance snapshot remains `600` and SHA-256 `e72dbc4334644939e25501aa1682e87f0b77abaf7c53d3da65146693e91251d0`.

Only after Node A compile and tests pass should you package/install the VSIX, or run the extension in an Extension Development Host on the SSH remote.
