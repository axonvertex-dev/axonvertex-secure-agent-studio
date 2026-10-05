#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

umask 077

echo "===== NODE A / GEMMA CREDENTIAL ====="
echo "You may be prompted for the Node A SSH password."

NODE_A_KEY="$(
  ssh \
    -o ConnectTimeout=15 \
    -o StrictHostKeyChecking=accept-new \
    axonvertex@100.82.103.57 \
    'cd /mnt/axonvertexstorage/development/projects/axonvertex-ai-sglang-service &&
     sed -n "s/^API_KEY=//p" .env | head -n1'
)"

echo "Node A credential retrieved."

echo
echo "===== NODE B / ANTARES CREDENTIAL ====="

NODE_B_KEY="$(
  cd /mnt/axonvertexstorage/inference/llama-cpp-inference-service
  sed -n 's/^API_KEY=//p' .env | head -n1
)"

echo "Node B credential retrieved."

echo
echo "===== NODE C / FOUNDATION SEC CREDENTIAL ====="
echo "You may be prompted for the Node C SSH password."

NODE_C_KEY="$(
  ssh \
    -o ConnectTimeout=15 \
    -o StrictHostKeyChecking=accept-new \
    rentorzo@100.76.212.84 \
    'cd "$HOME/axonvertexstorage/inference/llama-cpp-inference/profiles/foundation-sec-8b-reasoning" &&
     sed -n "s/^API_KEY=//p" .env | head -n1'
)"

echo "Node C credential retrieved."

test -n "$NODE_A_KEY" || {
  echo "ERROR: Node A API key is empty."
  exit 1
}

test -n "$NODE_B_KEY" || {
  echo "ERROR: Node B API key is empty."
  exit 1
}

test -n "$NODE_C_KEY" || {
  echo "ERROR: Node C API key is empty."
  exit 1
}

cat > .env.agent-system <<EOF2
NODE_A_URL=http://100.82.103.57:11433/v1
NODE_A_MODEL=gemma-4-12b-it-qat
NODE_A_API_KEY=$NODE_A_KEY

NODE_B_URL=http://127.0.0.1:18184/v1
NODE_B_MODEL=antares-1b
NODE_B_API_KEY=$NODE_B_KEY

NODE_C_URL=http://100.76.212.84:18183/v1
NODE_C_MODEL=foundation-sec-8b-reasoning
NODE_C_API_KEY=$NODE_C_KEY
EOF2

chmod 600 .env.agent-system

echo
echo "===== CREATED ====="
ls -l .env.agent-system

echo
echo "===== CREDENTIAL CHECK — VALUES HIDDEN ====="

grep '_API_KEY=' .env.agent-system |
awk -F= '{
  printf "%-20s loaded=%-3s length=%d\n",
         $1,
         (length($2) > 0 ? "yes" : "no"),
         length($2)
}'

echo
echo "Agent-system environment ready."
