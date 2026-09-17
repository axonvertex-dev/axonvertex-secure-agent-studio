from __future__ import annotations

from dataclasses import dataclass

from .distributed_suite_scenarios import (
    ReasoningScenario,
)
from .token_counter import TokenCounter


SYSTEM_PROMPT = """
You are an AXONVERTEX Secure Agent Studio security evidence reasoner.

Use only authoritative evidence records from the supplied corpus.

Rules:
- Determine the verdict from the complete evidence chain.
- Do not invent missing implementation details.
- Respect explicit precedence rules.
- Distinguish supporting evidence from counter-evidence.
- Distinguish uncertainty or missing-link evidence from both.
- Every authoritative COUNTER_EVIDENCE record that materially supports
  a different conclusion must appear in counter_evidence_ids, even when
  superseded by stronger or higher-precedence evidence.
- Records establishing that implementation behavior is unavailable,
  unknown, unverified, or merely required by policy rather than observed
  must appear in uncertainty_evidence_ids when they materially prevent
  a conclusion.
- If a necessary causal or authorization link is not established by
  authoritative evidence, return INSUFFICIENT_EVIDENCE.
- Do not infer implementation behavior from a design requirement.
- Do not convert unknown implementation behavior into an assumed
  vulnerable or secure behavior.

Return exactly one JSON object.
Do not use markdown or code fences.

Schema:
{
  "verdict": "VULNERABLE" | "NOT_VULNERABLE" | "INSUFFICIENT_EVIDENCE",
  "evidence_ids": ["..."],
  "counter_evidence_ids": ["..."],
  "uncertainty_evidence_ids": ["..."],
  "explanation": "..."
}
""".strip()


HEADER = """
SECURITY_INVESTIGATION_CORPUS_BEGIN

The corpus contains authoritative evidence, counter-evidence,
and unrelated synthetic distractor records.

""".lstrip()


@dataclass(frozen=True)
class GeneratedScenarioContext:
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
        "classification=synthetic-distractor"
    )


def build_user_prompt(
    *,
    scenario: ReasoningScenario,
    filler_records: int,
) -> str:
    insertions: dict[int, list[str]] = {}

    for record in scenario.records:
        index = round(
            filler_records * record.position
        )

        insertions.setdefault(
            index,
            [],
        ).append(record.text)

    records: list[str] = []

    for index in range(
        filler_records + 1
    ):
        for text in insertions.get(
            index,
            [],
        ):
            records.append(text)

        if index < filler_records:
            records.append(
                filler_record(index)
            )

    footer = f"""
SECURITY_INVESTIGATION_CORPUS_END

QUESTION:
{scenario.question}

Return only the required JSON object.
""".lstrip()

    return (
        HEADER
        + "\n".join(records)
        + "\n\n"
        + footer
    )


def count_prompt(
    *,
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


def generate_scenario_context(
    *,
    scenario: ReasoningScenario,
    counter: TokenCounter,
    target_prompt_tokens: int,
    tolerance_tokens: int,
) -> GeneratedScenarioContext:
    base_prompt = build_user_prompt(
        scenario=scenario,
        filler_records=0,
    )

    base_tokens = count_prompt(
        counter=counter,
        user_prompt=base_prompt,
    )

    sample_records = 100

    sample_prompt = build_user_prompt(
        scenario=scenario,
        filler_records=sample_records,
    )

    sample_tokens = count_prompt(
        counter=counter,
        user_prompt=sample_prompt,
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

    best_delta: int | None = None

    for iteration in range(1, 16):
        prompt = build_user_prompt(
            scenario=scenario,
            filler_records=record_count,
        )

        measured = count_prompt(
            counter=counter,
            user_prompt=prompt,
        )

        delta = (
            measured
            - target_prompt_tokens
        )

        if (
            best_delta is None
            or abs(delta) < abs(best_delta)
        ):
            best_delta = delta

        if abs(delta) <= tolerance_tokens:
            return GeneratedScenarioContext(
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
            adjustment = -1 if delta > 0 else 1

        record_count = max(
            0,
            record_count + adjustment,
        )

    raise RuntimeError(
        "Unable to construct context within tolerance; "
        f"best_delta={best_delta}"
    )
