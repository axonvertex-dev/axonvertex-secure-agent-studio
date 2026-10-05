#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env.runtime-adapter}"
EVIDENCE_FILE="${2:-../results/runtime-adapter/reg-0.5-evidence.jsonl}"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

node dist/src/cli.js \
  --env "$ENV_FILE" \
  --agent coding-investigator \
  --purpose code_reasoning \
  --system "You are the AXONVERTEX Coding Investigator. Follow the supplied instruction precisely and do not claim actions you did not perform." \
  --prompt "Return exactly: REG_0_5_GEMMA_RUNTIME_OK" \
  --temperature 0 \
  --max-tokens 80 \
  --evidence "$EVIDENCE_FILE"
