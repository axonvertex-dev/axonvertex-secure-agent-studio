from __future__ import annotations

from dataclasses import dataclass

from .token_counter import TokenCounter


SYSTEM_PROMPT = """
You are an AXONVERTEX Secure Agent Studio long-context benchmark model.
The supplied corpus contains many distractor records and exactly one
authoritative SECURITY_KEY record.

Read the corpus carefully.

When asked for SECURITY_KEY, return only its value and no additional text.
""".strip()


EVIDENCE_VALUE = "AVX-7392-KAPPA"

EVIDENCE_RECORD = (
    "EVIDENCE_RECORD | "
    f"SECURITY_KEY={EVIDENCE_VALUE} | "
    "classification=authoritative | "
    "instruction=use-this-value-for-the-final-answer"
)


HEADER = """
SYNTHETIC_CORPUS_BEGIN

The records below are synthetic benchmark data.
Most records are irrelevant distractors.
Exactly one record contains SECURITY_KEY.

""".lstrip()


FOOTER = """
SYNTHETIC_CORPUS_END

QUESTION:
Return exactly the value assigned to SECURITY_KEY.
Return no explanation, punctuation, label, or additional text.
""".lstrip()


@dataclass(frozen=True)
class GeneratedLongContext:
    user_prompt: str
    requested_position: float
    insertion_index: int
    filler_records: int
    measured_prompt_tokens: int
    target_prompt_tokens: int
    token_delta: int
    generation_iterations: int


def filler_record(index: int) -> str:
    return (
        f"RECORD {index:07d} | "
        "service=benchmark-component | "
        "state=nominal | "
        "severity=none | "
        "finding=no-action-required | "
        "note=synthetic-distractor-record-without-security-key"
    )


def build_user_prompt(
    filler_records: int,
    evidence_position: float,
) -> tuple[str, int]:
    if not 0.0 <= evidence_position <= 1.0:
        raise ValueError(
            "evidence_position must be between 0.0 and 1.0"
        )

    insertion_index = round(
        filler_records * evidence_position
    )

    records: list[str] = []

    for index in range(filler_records):
        if index == insertion_index:
            records.append(EVIDENCE_RECORD)

        records.append(
            filler_record(index)
        )

    if insertion_index == filler_records:
        records.append(EVIDENCE_RECORD)

    body = "\n".join(records)

    prompt = (
        HEADER
        + body
        + "\n\n"
        + FOOTER
    )

    return prompt, insertion_index


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


def generate_long_context(
    *,
    counter: TokenCounter,
    target_prompt_tokens: int,
    evidence_position: float,
    tolerance_tokens: int,
) -> GeneratedLongContext:
    empty_prompt, _ = build_user_prompt(
        filler_records=0,
        evidence_position=evidence_position,
    )

    base_tokens = count_prompt(
        counter,
        empty_prompt,
    )

    sample_records = 100

    sample_prompt, _ = build_user_prompt(
        filler_records=sample_records,
        evidence_position=evidence_position,
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
            "Unable to estimate filler token density"
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

    best: GeneratedLongContext | None = None

    for iteration in range(1, 16):
        prompt, insertion_index = build_user_prompt(
            filler_records=record_count,
            evidence_position=evidence_position,
        )

        measured = count_prompt(
            counter,
            prompt,
        )

        delta = (
            measured
            - target_prompt_tokens
        )

        candidate = GeneratedLongContext(
            user_prompt=prompt,
            requested_position=evidence_position,
            insertion_index=insertion_index,
            filler_records=record_count,
            measured_prompt_tokens=measured,
            target_prompt_tokens=target_prompt_tokens,
            token_delta=delta,
            generation_iterations=iteration,
        )

        if (
            best is None
            or abs(delta) < abs(best.token_delta)
        ):
            best = candidate

        if abs(delta) <= tolerance_tokens:
            return candidate

        adjustment = round(
            (
                target_prompt_tokens
                - measured
            )
            / tokens_per_record
        )

        if adjustment == 0:
            adjustment = (
                -1
                if delta > 0
                else 1
            )

        record_count = max(
            0,
            record_count + adjustment,
        )

    assert best is not None

    if abs(best.token_delta) > tolerance_tokens:
        raise RuntimeError(
            "Could not construct prompt within token tolerance: "
            f"target={target_prompt_tokens}, "
            f"best={best.measured_prompt_tokens}, "
            f"delta={best.token_delta}"
        )

    return best
