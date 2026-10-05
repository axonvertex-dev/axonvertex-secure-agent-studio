#!/usr/bin/env python3

import json
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent),
)

from common import extract_json_candidates

if len(sys.argv) != 2:
    raise SystemExit(
        "usage: validate_existing_v2.py result.json"
    )

path = Path(sys.argv[1])
record = json.loads(path.read_text())

content = record["finalizer"]["content"]

candidates = extract_json_candidates(content)

required = {
    "verdict",
    "primary_finding",
    "validated_source_to_sink",
    "authentication",
    "authorization",
    "hypotheses",
    "positive_controls",
}

matches = [
    c for c in candidates
    if required.issubset(c.keys())
]

if not matches:
    raise SystemExit(
        "QUALITY_GATE_FAIL: no complete assessment JSON"
    )

final = matches[0]

errors = []

primary = final.get(
    "primary_finding",
    {},
)

cwe = primary.get("cwe")

if cwe != "CWE-78":
    errors.append(
        f"primary CWE must be CWE-78, got {cwe!r}"
    )

title = str(
    primary.get("title", "")
).lower()

for forbidden in (
    "unauthenticated",
    "authentication bypass",
    "auth bypass",
):
    if forbidden in title:
        errors.append(
            f"unsupported primary-title claim: {forbidden}"
        )

chain = final.get(
    "validated_source_to_sink"
)

chain_valid = False

if isinstance(chain, list) and chain:
    # Accept either:
    # 1. separate source/sink entries, or
    # 2. one explicit textual source -> sink path.
    if len(chain) >= 2:
        chain_valid = True
    elif len(chain) == 1:
        item = str(chain[0])
        chain_valid = "->" in item

if not chain_valid:
    errors.append(
        "source-to-sink chain incomplete"
    )

authn = final.get(
    "authentication",
    {},
)

if authn.get("status") not in (
    "partial",
    "not_demonstrated",
):
    errors.append(
        "authentication enforcement overclaimed"
    )

authz = final.get(
    "authorization",
    {},
)

if authz.get("status") != "not_demonstrated":
    errors.append(
        "authorization must be not_demonstrated"
    )

controls = final.get(
    "positive_controls",
    [],
)

if (
    not isinstance(controls, list)
    or len(controls) < 3
):
    errors.append(
        "positive controls missing"
    )

cluster = (
    final.get("hypotheses", {})
    .get("cluster_compromise", {})
)

if cluster.get("status") == "supported":
    errors.append(
        "cluster compromise unsupported"
    )

print("===== AUTHORITATIVE ASSESSMENT =====")
print(json.dumps(final, indent=2))

print()
print("===== QUALITY GATE =====")

if errors:
    print("QUALITY_GATE_FAIL")

    for error in errors:
        print(" -", error)

    raise SystemExit(2)

print("QUALITY_GATE_PASS")

record["final_assessment"] = final
record["quality_gate"] = {
    "status": "QUALITY_GATE_PASS",
    "errors": [],
}

out = path.with_name(
    path.stem + "-validated.json"
)

out.write_text(
    json.dumps(
        record,
        indent=2,
    )
)

print("VALIDATED RESULT:", out)
