#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env.runtime-adapter}"
test -f "$ENV_FILE" || {
  echo "MISSING $ENV_FILE"
  exit 2
}

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required=(
  AXV_REGISTRY_ADMIN_TOKEN
  AXV_RUNTIME_GEMMA_NODE_A_API_KEY
  AXV_RUNTIME_ANTARES_NODE_B_API_KEY
  AXV_RUNTIME_FOUNDATION_NODE_C_API_KEY
)

bad=0
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "MISSING $name"
    bad=1
  else
    echo "OK $name"
  fi
done

if [ "$bad" -ne 0 ]; then
  exit 3
fi

echo "REG-0.5 ENV CHECK PASS"
