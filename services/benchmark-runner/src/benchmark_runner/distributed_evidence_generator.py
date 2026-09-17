from __future__ import annotations

from dataclasses import dataclass

from .token_counter import TokenCounter


SYSTEM_PROMPT = """
You are an AXONVERTEX Secure Agent Studio security evidence reasoner.

Use only the supplied authoritative evidence records when reaching the verdict.
Distractor records are not evidence.

When evidence conflicts:
- explicitly consider the counter-evidence;
- honor an explicitly stated precedence rule;
- do not invent implementation details;
- every authoritative record labeled COUNTER_EVIDENCE that materially
  supports a different conclusion MUST appear in counter_evidence_ids,
  even when it is superseded by a higher-precedence record;
- superseded counter-evidence must still be preserved in the evidence
  trace rather than silently discarded.

Return one JSON object only.
Do not use markdown or code fences.

Required schema:
{
  "verdict": "VULNERABLE" | "NOT_VULNERABLE" | "INSUFFICIENT_EVIDENCE",
  "evidence_ids": ["..."],
  "counter_evidence_ids": ["..."],
  "explanation": "..."
}
""".strip()


EVIDENCE_RECORDS = [
    (
        0.08,
        "E1",
        (
            "EVIDENCE E1 | "
            "route=/api/admin/export | "
            "authentication=middleware.jwt_required | "
            "authorization=authorize_role('admin') | "
            "classification=authoritative"
        ),
    ),
    (
        0.24,
        "C1",
        (
            "COUNTER_EVIDENCE C1 | "
            "component=jwt-library-default | "
            "JWT_VERIFY_SIGNATURE=true | "
            "scope=library-default | "
            "classification=authoritative"
        ),
    ),
    (
        0.48,
        "E3",
        (
            "EVIDENCE E3 | "
            "environment=production | "
            "JWT_VERIFY_SIGNATURE=false | "
            "precedence=runtime-production-override-supersedes-library-default | "
            "classification=authoritative"
        ),
    ),
    (
        0.64,
        "E4",
        (
            "EVIDENCE E4 | "
            "component=middleware.jwt_required | "
            "behavior=when-JWT_VERIFY_SIGNATURE-is-false-token-payload-is-decoded-and-claims-are-passed-downstream-without-cryptographic-signature-verification | "
            "classification=authoritative"
        ),
    ),
    (
        0.78,
        "E5",
        (
            "EVIDENCE E5 | "
            "component=authorize_role | "
            "behavior=authorization-allows-request-when-decoded-claims-role-equals-required-role | "
            "required_role=admin | "
            "classification=authoritative"
        ),
    ),
    (
        0.91,
        "E6",
        (
            "EVIDENCE E6 | "
            "route=/api/admin/export | "
            "additional-admin-verification=none | "
            "server-side-admin-directory-lookup=none | "
            "classification=authoritative"
        ),
    ),
]


EXPECTED_VERDICT = "VULNERABLE"

EXPECTED_EVIDENCE_IDS = {
    "E1",
    "E3",
    "E4",
    "E5",
    "E6",
}

EXPECTED_COUNTER_EVIDENCE_IDS = {
    "C1",
}


HEADER = """
SECURITY_INVESTIGATION_CORPUS_BEGIN

The corpus contains authoritative evidence, counter-evidence,
and synthetic distractor records.

Determine the security consequence only from the records.

""".lstrip()


FOOTER = """
SECURITY_INVESTIGATION_CORPUS_END

QUESTION:

Can an attacker submit a JWT whose signature is not cryptographically
verified, set role=admin in its claims, and thereby gain access to
/api/admin/export?

Return only the required JSON object.
""".lstrip()


@dataclass(frozen=True)
class GeneratedDistributedContext:
    user_prompt: str
    filler_records: int
    measured_prompt_tokens: int
    target_prompt_tokens: int
    token_delta: int
    generation_iterations: int


def filler_record(index: int) -> str:
    return (
        f"DISTRACTOR {index:07d} | "
        "component=unrelated-service | "
        "state=nominal | "
        "security_relevance=none | "
        "finding=no-action-required | "
        "classification=synthetic-distractor"
    )


def build_user_prompt(
    filler_records: int,
) -> str:
    insertions: dict[int, list[str]] = {}

    for position, _, record in EVIDENCE_RECORDS:
        index = round(
            filler_records * position
        )

        insertions.setdefault(
            index,
            [],
        ).append(record)

    records: list[str] = []

    for index in range(
        filler_records + 1
    ):
        for record in insertions.get(
            index,
            [],
        ):
            records.append(record)

        if index < filler_records:
            records.append(
                filler_record(index)
            )

    return (
        HEADER
        + "\n".join(records)
        + "\n\n"
        + FOOTER
    )


def count_prompt(
    counter: TokenCounter,
    user_prompt: str,
) -> int:
    return counter.count(
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
    )


def generate_distributed_context(
    *,
    counter: TokenCounter,
    target_prompt_tokens: int,
    tolerance_tokens: int,
) -> GeneratedDistributedContext:
    base_prompt = build_user_prompt(
        filler_records=0
    )

    base_tokens = count_prompt(
        counter,
        base_prompt,
    )

    sample_records = 100

    sample_prompt = build_user_prompt(
        filler_records=sample_records
    )

    sample_tokens = count_prompt(
        counter,
        sample_prompt,
    )

    tokens_per_record = (
        sample_tokens - base_tokens
    ) / sample_records

    if tokens_per_record <= 0:
        raise RuntimeError(
            "Invalid filler token density"
        )

    record_count = max(
        0,
        round(
            (
                target_prompt_tokens
                - base_tokens
            )
            / tokens_per_record
        ),
    )

    best = None

    for iteration in range(1, 16):
        prompt = build_user_prompt(
            filler_records=record_count
        )

        measured = count_prompt(
            counter,
            prompt,
        )

        delta = (
            measured
            - target_prompt_tokens
        )

        candidate = (
            prompt,
            record_count,
            measured,
            delta,
            iteration,
        )

        if (
            best is None
            or abs(delta) < abs(best[3])
        ):
            best = candidate

        if abs(delta) <= tolerance_tokens:
            return GeneratedDistributedContext(
                user_prompt=prompt,
                filler_records=record_count,
                measured_prompt_tokens=measured,
                target_prompt_tokens=target_prompt_tokens,
                token_delta=delta,
                generation_iterations=iteration,
            )

        adjustment = round(
            (
                target_prompt_tokens
                - measured
            )
            / tokens_per_record
        )

        if adjustment == 0:
            adjustment = (
                -1 if delta > 0 else 1
            )

        record_count = max(
            0,
            record_count + adjustment,
        )

    assert best is not None

    raise RuntimeError(
        "Unable to generate distributed context "
        f"within tolerance; best delta={best[3]}"
    )
