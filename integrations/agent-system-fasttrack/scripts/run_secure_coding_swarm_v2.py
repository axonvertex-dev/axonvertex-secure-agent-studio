#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

from common import (
    call,
    extract_json_candidates,
    load_env,
    save,
)

ROOT = Path(__file__).resolve().parents[1]

load_env()

CASE_PATH = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else ROOT / "cases/security_case.json"
)

case = json.loads(CASE_PATH.read_text())
case_text = json.dumps(case, indent=2)


def invoke(
    node,
    system,
    user,
    max_tokens,
    timeout=1200,
):
    return call(
        os.environ[f"NODE_{node}_URL"],
        os.environ[f"NODE_{node}_API_KEY"],
        os.environ[f"NODE_{node}_MODEL"],
        [
            {
                "role": "system",
                "content": system,
            },
            {
                "role": "user",
                "content": user,
            },
        ],
        max_tokens=max_tokens,
        temperature=0,
        timeout=timeout,
    )


print("===== 1/4 SECURITY SCOUT / ANTARES =====", flush=True)

scout = invoke(
    "B",
    """
You are AXONVERTEX Security Scout.

Your job is fast evidence extraction only.

You MAY:
- identify files and functions
- identify candidate source/sink relationships
- identify candidate security concerns
- list missing evidence

You MUST NOT:
- issue the final vulnerability verdict
- approve remediation
- claim exploit impact not supported by evidence
- convert recommendations into existing controls
- claim cluster compromise
- invent network reachability

Treat every conclusion as a candidate for later verification.
""",
    f"""
Extract evidence from this case.

Return concise JSON with:
- observed_files
- observed_data_flows
- candidate_findings
- positive_controls_observed
- missing_evidence

CASE:

{case_text}
""",
    1200,
)

print(
    "finish:",
    scout["finish_reason"],
    "elapsed:",
    scout["elapsed_seconds"],
)


print()
print("===== 2/4 CODING INVESTIGATOR / GEMMA =====", flush=True)

investigator = invoke(
    "A",
    """
You are AXONVERTEX Coding Investigator.

Perform deep application-security and code reasoning.

The Security Scout output is UNTRUSTED supporting material.
Verify every scout claim against the supplied case.

Critical reasoning rules:

1. Authentication and authorization are different.
2. Existence of authentication middleware does not prove that
   route-specific authorization exists.
3. Do not infer public exploitability merely from a dangerous sink.
4. Do not infer cluster compromise from command execution.
5. Only describe controls actually present in supplied evidence.
6. Distinguish observation from inference.
7. Refuse unsupported conclusions.
""",
    f"""
CASE:

{case_text}


UNTRUSTED SECURITY SCOUT OUTPUT:

{scout["content"]}


Produce an evidence-grounded candidate security assessment covering:

- strongest directly supported vulnerability
- CWE
- source-to-sink path
- authentication
- authorization
- SSRF hypothesis
- XSS hypothesis
- cluster-compromise hypothesis
- security-positive controls actually observed
- missing evidence
- remediation
- regression tests
- conclusions that must be refused
""",
    5000,
)

print(
    "finish:",
    investigator["finish_reason"],
    "elapsed:",
    investigator["elapsed_seconds"],
)


print()
print("===== 3/4 SECURITY CRITIC / FOUNDATION SEC =====", flush=True)

critic = invoke(
    "C",
    """
You are AXONVERTEX Security Critic.

You are NOT the final decision maker.

Review the Coding Investigator's assessment against the original evidence.

Look specifically for:

- unsupported exploitability claims
- authentication/authorization confusion
- incorrect CWE selection
- invented controls
- invented source-to-sink steps
- unsupported SSRF claims
- unsupported XSS claims
- unsupported cluster-compromise claims
- missing positive controls
- missing evidence requirements

Authentication proves identity.
Authorization determines whether that identity may perform the operation.
Never treat these concepts as equivalent.

Return concise JSON only.
""",
    f"""
ORIGINAL CASE:

{case_text}


CODING INVESTIGATOR CANDIDATE:

{investigator["content"]}


Return:

{{
  "candidate_quality": "PASS|PASS_WITH_CORRECTIONS|FAIL",
  "supported_claims": [],
  "unsupported_claims": [],
  "missing_controls_from_assessment": [],
  "authentication_review": "",
  "authorization_review": "",
  "cwe_review": "",
  "required_corrections": []
}}
""",
    2200,
)

print(
    "finish:",
    critic["finish_reason"],
    "elapsed:",
    critic["elapsed_seconds"],
)


print()
print("===== 4/4 FINAL EVIDENCE SYNTHESIZER / GEMMA =====", flush=True)

finalizer = invoke(
    "A",
    """
You are the AXONVERTEX Final Evidence Synthesizer.

You receive:
1. original evidence,
2. an investigator assessment,
3. an independent security critic.

Produce the authoritative assessment.

EVIDENCE DISCIPLINE:

- The primary directly supported weakness is OS command injection
  if untrusted command data reaches subprocess.run(..., shell=True).

- Do NOT call the finding "unauthenticated RCE" unless the supplied
  evidence actually proves absence or bypass of authentication.

- Authentication middleware code exists, but the supplied evidence
  does not show middleware registration or prove its enforcement on
  this route. Therefore authentication enforcement is PARTIAL /
  NOT FULLY DEMONSTRATED.

- No route-specific role, scope, permission, ownership or authorization
  check is demonstrated. Authorization must therefore be
  NOT_DEMONSTRATED, not "bypassed".

- Command execution does NOT prove Kubernetes or cluster compromise.

- Existing worker controls must not disappear:
  uid 10001;
  filesystem read-only except /tmp;
  no Kubernetes API token;
  environment only REDIS_URL and LOG_LEVEL;
  no supplied evidence of cloud credentials.

- The architecture states that the webhook contacts merchant-supplied
  callback URLs. That creates an SSRF-relevant sink, but exploitability,
  URL validation and network reachability are not sufficiently shown.

- The report template alone is insufficient to prove XSS because the
  rendering engine and escaping behavior are not supplied.

Return exactly one JSON object.
No markdown.
No text outside the JSON object.
""",
    f"""
ORIGINAL CASE:

{case_text}


INVESTIGATOR:

{investigator["content"]}


SECURITY CRITIC:

{critic["content"]}


Return exactly:

{{
  "verdict": "ACCEPT|ACCEPT_WITH_CORRECTIONS|REJECT|NEEDS_EVIDENCE",

  "primary_finding": {{
    "title": "string",
    "cwe": "CWE-78",
    "confidence": "high|medium|low",
    "assessment": "string"
  }},

  "validated_source_to_sink": [
    "string"
  ],

  "authentication": {{
    "status": "partial|not_demonstrated|demonstrated",
    "assessment": "string"
  }},

  "authorization": {{
    "status": "not_demonstrated|partial|demonstrated",
    "assessment": "string"
  }},

  "hypotheses": {{
    "ssrf": {{
      "status": "supported|weak|insufficient_evidence",
      "assessment": "string"
    }},
    "xss": {{
      "status": "supported|weak|insufficient_evidence",
      "assessment": "string"
    }},
    "cluster_compromise": {{
      "status": "supported|weak|insufficient_evidence",
      "assessment": "string"
    }}
  }},

  "positive_controls": [
    "string"
  ],

  "missing_evidence": [
    "string"
  ],

  "unsupported_claims_rejected": [
    "string"
  ],

  "approved_remediation": [
    "string"
  ],

  "regression_tests": [
    "string"
  ]
}}
""",
    2600,
)

print(
    "finish:",
    finalizer["finish_reason"],
    "elapsed:",
    finalizer["elapsed_seconds"],
)


# -------------------------------------------------
# Deterministic quality gate
# -------------------------------------------------

candidates = extract_json_candidates(
    finalizer["content"]
)

required_final_keys = {
    "verdict",
    "primary_finding",
    "validated_source_to_sink",
    "authentication",
    "authorization",
    "hypotheses",
    "positive_controls",
}

final_candidates = [
    candidate
    for candidate in candidates
    if required_final_keys.issubset(candidate.keys())
]

final = final_candidates[0] if final_candidates else None

errors = []

if not isinstance(final, dict):
    errors.append(
        "final output is not a JSON object"
    )

if isinstance(final, dict):

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

    forbidden_title_terms = (
        "unauthenticated",
        "authentication bypass",
        "auth bypass",
    )

    for term in forbidden_title_terms:
        if term in title:
            errors.append(
                f"unsupported title claim: {term}"
            )

    chain = final.get(
        "validated_source_to_sink"
    )

    chain_valid = False

    if isinstance(chain, list) and chain:
        if len(chain) >= 2:
            chain_valid = True

        elif len(chain) == 1:
            item = str(chain[0])
            chain_valid = "->" in item

    if not chain_valid:
        errors.append(
            "validated_source_to_sink is incomplete"
        )

    authentication = final.get(
        "authentication",
        {},
    )

    if authentication.get("status") not in (
        "partial",
        "not_demonstrated",
    ):
        errors.append(
            "authentication enforcement was overclaimed"
        )

    authorization = final.get(
        "authorization",
        {},
    )

    if authorization.get("status") != (
        "not_demonstrated"
    ):
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
            "positive controls are missing"
        )

    hypotheses = final.get(
        "hypotheses",
        {},
    )

    cluster = hypotheses.get(
        "cluster_compromise",
        {},
    )

    if cluster.get("status") == "supported":
        errors.append(
            "cluster compromise is unsupported"
        )


quality_status = (
    "QUALITY_GATE_PASS"
    if not errors
    else "QUALITY_GATE_FAIL"
)


record = {
    "case": case["name"],
    "pipeline": [
        "security-scout/antares-node-b",
        "coding-investigator/gemma-node-a",
        "security-critic/foundation-node-c",
        "final-evidence-synthesizer/gemma-node-a",
        "deterministic-quality-gate",
    ],
    "scout": scout,
    "investigator": investigator,
    "critic": critic,
    "finalizer": finalizer,
    "final_assessment": final,
    "quality_gate": {
        "status": quality_status,
        "errors": errors,
    },
}

result_path = save(
    "secure-coding-swarm-v2",
    record,
)

print()
print("======================================")
print("AXONVERTEX AGENT SYSTEM")
print("======================================")
print("RESULT:", result_path)
print("QUALITY:", quality_status)

if errors:
    print()
    print("QUALITY GATE ERRORS:")

    for error in errors:
        print(" -", error)

print()
print("===== AUTHORITATIVE ASSESSMENT =====")

print(
    json.dumps(
        final,
        indent=2,
    )
    if final
    else finalizer["content"]
)

if errors:
    raise SystemExit(2)
