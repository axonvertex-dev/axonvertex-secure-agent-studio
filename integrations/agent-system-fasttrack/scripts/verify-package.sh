#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m py_compile scripts/common.py scripts/check_models.py scripts/run_common_benchmark.py scripts/run_secure_coding_swarm.py
python3 - <<'PY2'
import json
for p in ('config/runtime_bindings.json','cases/security_case.json'): json.load(open(p))
print('PASS: package syntax and JSON validated')
PY2
