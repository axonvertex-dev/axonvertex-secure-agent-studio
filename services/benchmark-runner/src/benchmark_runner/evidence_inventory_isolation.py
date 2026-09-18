from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .context_profiles import load_context_profiles
from .distributed_reasoning_smoke import (
    normalize_id_set,
    parse_json_response,
)
from .distributed_suite_scenarios import (
    SCENARIOS,
    ReasoningScenario,
)
from .long_context_matrix import (
    flush_sglang_cache,
)
from .token_counter import TokenCounter


TOLERANCE_TOKENS = 128
MAX_OUTPUT_TOKENS = 512


SYSTEM_PROMPT = """
You are an evidence inventory engine.

Your task is NOT to decide whether a system is vulnerable,
safe, exploitable, or non-exploitable.

Do NOT return a security verdict.

Inspect the complete supplied corpus and enumerate every
authoritative record exactly once.

Classify every authoritative record relative to the question as:

support:
  evidence that directly contributes toward establishing
  the primary causal or security proposition.

counter:
  authoritative evidence that materially supports an
  alternative or opposing conclusion.

uncertainty:
  authoritative evidence whose primary significance is that
  implementation behavior, conformance, a causal link, or
  another decision-critical fact is unavailable or unknown.

Rules:

- Every authoritative evidence record must appear exactly once.
- Synthetic DISTRACTOR records must never appear.
- Do not omit evidence because it appears redundant.
- Do not omit corroborating evidence.
- Do not infer facts that are not explicitly present.
- A policy or architecture requirement with unknown
  implementation conformance is uncertainty evidence,
  not proof that the implementation follows the requirement.
- Do not generate a verdict.

Return exactly one JSON object:

{
  "support": ["..."],
  "counter": ["..."],
  "uncertainty": ["..."]
}
""".strip()


HEADER = """
SECURITY_INVESTIGATION_CORPUS_BEGIN

The corpus contains authoritative evidence records and
synthetic distractor records.

Inventory every authoritative record.

""".lstrip()


EXPECTED_INVENTORY: dict[str, dict[str, set[str]]] = {
    "A-vulnerable": {
        "support": {
            "A1",
            "A3",
            "A4",
            "A5",
            "A6",
        },
        "counter": {
            "AC1",
        },
        "uncertainty": set(),
    },

    "B-not-vulnerable": {
        "support": {
            "B1",
            "B3",
            "B4",
            "B5",
            "B6",
        },
        "counter": {
            "BC1",
        },
        "uncertainty": set(),
    },

    "C-insufficient": {
        "support": {
            "C1",
            "C2",
            "C3",
        },
        "counter": set(),
        "uncertainty": {
            "CC1",
            "C4",
        },
    },
}


DEFAULT_CASES = [
    ("64k", "B-not-vulnerable"),
    ("64k", "C-insufficient"),

    ("96k", "B-not-vulnerable"),
    ("96k", "C-insufficient"),

    ("128k", "A-vulnerable"),
    ("128k", "B-not-vulnerable"),
    ("128k", "C-insufficient"),
]


@dataclass(frozen=True)
class GeneratedInventoryContext:
    user_prompt: str
    filler_records: int
    measured_prompt_tokens: int
    target_prompt_tokens: int
    token_delta: int


def filler_record(index: int) -> str:
    return (
        f"DISTRACTOR {index:07d} | "
        "component=unrelated-service | "
        "state=nominal | "
        "security_relevance=none | "
        "classification=synthetic-distractor"
    )


def build_prompt(
    *,
    scenario: ReasoningScenario,
    filler_records: int,
) -> str:
    insertions: dict[int, list[str]] = {}

    for record in scenario.records:
        index = round(
            filler_records
            * record.position
        )

        insertions.setdefault(
            index,
            [],
        ).append(
            record.text
        )

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

REFERENCE QUESTION:
{scenario.question}

Do not answer the question.

Inventory and classify every authoritative evidence record.
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


def generate_context(
    *,
    scenario: ReasoningScenario,
    counter: TokenCounter,
    target_prompt_tokens: int,
) -> GeneratedInventoryContext:
    base_prompt = build_prompt(
        scenario=scenario,
        filler_records=0,
    )

    base_tokens = count_prompt(
        counter=counter,
        user_prompt=base_prompt,
    )

    sample_count = 100

    sample_prompt = build_prompt(
        scenario=scenario,
        filler_records=sample_count,
    )

    sample_tokens = count_prompt(
        counter=counter,
        user_prompt=sample_prompt,
    )

    tokens_per_record = (
        sample_tokens - base_tokens
    ) / sample_count

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

    best: tuple[
        str,
        int,
        int,
        int,
    ] | None = None

    for _ in range(20):
        prompt = build_prompt(
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

        candidate = (
            prompt,
            record_count,
            measured,
            delta,
        )

        if (
            best is None
            or abs(delta)
            < abs(best[3])
        ):
            best = candidate

        if abs(delta) <= TOLERANCE_TOKENS:
            return GeneratedInventoryContext(
                user_prompt=prompt,
                filler_records=record_count,
                measured_prompt_tokens=measured,
                target_prompt_tokens=
                    target_prompt_tokens,
                token_delta=delta,
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
                -1
                if delta > 0
                else 1
            )

        record_count = max(
            0,
            record_count + adjustment,
        )

    assert best is not None

    raise RuntimeError(
        "Unable to construct inventory context "
        f"within tolerance; best_delta={best[3]}"
    )


def measure_positions(
    *,
    counter: TokenCounter,
    scenario: ReasoningScenario,
    user_prompt: str,
    full_prompt_tokens: int,
) -> dict[str, float]:
    empty_tokens = counter.count(
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": "",
            }
        ],
    )

    payload_tokens = max(
        1,
        full_prompt_tokens
        - empty_tokens,
    )

    result: dict[str, float] = {}

    for record in scenario.records:
        offset = user_prompt.index(
            record.text
        )

        prefix = user_prompt[:offset]

        prefix_tokens = counter.count(
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": prefix,
                }
            ],
        )

        result[
            record.evidence_id
        ] = round(
            max(
                0,
                prefix_tokens
                - empty_tokens,
            )
            / payload_tokens,
            4,
        )

    return result


def execute_case(
    *,
    profile_name: str,
    scenario_name: str,
    counter: TokenCounter,
    client: OpenAICompatibleClient,
) -> dict[str, Any]:
    scenario = SCENARIOS[
        scenario_name
    ]

    profile = load_context_profiles()[
        profile_name
    ]

    endpoint = gemma_endpoint()

    generated = generate_context(
        scenario=scenario,
        counter=counter,
        target_prompt_tokens=
            profile.target_prompt_tokens,
    )

    positions = measure_positions(
        counter=counter,
        scenario=scenario,
        user_prompt=
            generated.user_prompt,
        full_prompt_tokens=
            generated.measured_prompt_tokens,
    )

    flush_sglang_cache(
        endpoint_url=
            endpoint.base_url,
    )

    started = time.perf_counter()

    response = client.chat(
        messages=[
            {
                "role": "system",
                "content":
                    SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content":
                    generated.user_prompt,
            },
        ],
        temperature=0.0,
        max_tokens=
            MAX_OUTPUT_TOKENS,
    )

    latency_ms = round(
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    choice = response.get(
        "choices",
        [{}],
    )[0]

    raw_response = (
        choice
        .get("message", {})
        .get("content", "")
        .strip()
    )

    usage = response.get(
        "usage",
        {},
    )

    actual_prompt_tokens = (
        usage.get(
            "prompt_tokens"
        )
    )

    completion_tokens = (
        usage.get(
            "completion_tokens"
        )
    )

    parsed = None
    parse_error = None

    try:
        parsed = parse_json_response(
            raw_response
        )
    except Exception as exc:
        parse_error = str(exc)

    support = normalize_id_set(
        parsed.get("support")
        if parsed
        else None
    )

    counter_ids = normalize_id_set(
        parsed.get("counter")
        if parsed
        else None
    )

    uncertainty = normalize_id_set(
        parsed.get("uncertainty")
        if parsed
        else None
    )

    expected = EXPECTED_INVENTORY[
        scenario_name
    ]

    expected_support = set(
        expected["support"]
    )

    expected_counter = set(
        expected["counter"]
    )

    expected_uncertainty = set(
        expected["uncertainty"]
    )

    all_expected = (
        expected_support
        | expected_counter
        | expected_uncertainty
    )

    all_actual = (
        support
        | counter_ids
        | uncertainty
    )

    missing_ids = (
        all_expected
        - all_actual
    )

    unsupported_ids = (
        all_actual
        - all_expected
    )

    duplicated_between_categories = (
        (support & counter_ids)
        | (support & uncertainty)
        | (counter_ids & uncertainty)
    )

    support_exact = (
        support
        == expected_support
    )

    counter_exact = (
        counter_ids
        == expected_counter
    )

    uncertainty_exact = (
        uncertainty
        == expected_uncertainty
    )

    exhaustive_recovery = (
        all_actual
        == all_expected
    )

    classification_exact = all([
        support_exact,
        counter_exact,
        uncertainty_exact,
    ])

    token_counter_match = (
        actual_prompt_tokens
        == generated.measured_prompt_tokens
    )

    reservation_contract_safe = (
        isinstance(
            actual_prompt_tokens,
            int,
        )
        and actual_prompt_tokens
        <= profile.hard_prompt_limit
    )

    passed = all([
        parsed is not None,
        exhaustive_recovery,
        classification_exact,
        len(unsupported_ids) == 0,
        len(
            duplicated_between_categories
        ) == 0,
        token_counter_match,
        reservation_contract_safe,
    ])

    return {
        "schema_version":
            "evidence-inventory-isolation.v1",

        "checkpoint":
            "2C.2",

        "status":
            "PASS"
            if passed
            else "FAIL",

        "profile":
            profile_name,

        "scenario_id":
            scenario_name,

        "target_prompt_tokens":
            profile.target_prompt_tokens,

        "actual_prompt_tokens":
            actual_prompt_tokens,

        "completion_tokens":
            completion_tokens,

        "token_delta":
            (
                actual_prompt_tokens
                - profile.target_prompt_tokens
                if isinstance(
                    actual_prompt_tokens,
                    int,
                )
                else None
            ),

        "token_counter_match":
            token_counter_match,

        "reservation_contract_safe":
            reservation_contract_safe,

        "evidence_positions":
            positions,

        "expected_support":
            sorted(
                expected_support
            ),

        "actual_support":
            sorted(
                support
            ),

        "expected_counter":
            sorted(
                expected_counter
            ),

        "actual_counter":
            sorted(
                counter_ids
            ),

        "expected_uncertainty":
            sorted(
                expected_uncertainty
            ),

        "actual_uncertainty":
            sorted(
                uncertainty
            ),

        "missing_ids":
            sorted(
                missing_ids
            ),

        "unsupported_ids":
            sorted(
                unsupported_ids
            ),

        "duplicated_between_categories":
            sorted(
                duplicated_between_categories
            ),

        "exhaustive_recovery":
            exhaustive_recovery,

        "classification_exact":
            classification_exact,

        "support_exact":
            support_exact,

        "counter_exact":
            counter_exact,

        "uncertainty_exact":
            uncertainty_exact,

        "latency_ms":
            latency_ms,

        "parse_error":
            parse_error,

        "raw_response":
            raw_response,
    }


def parse_case(
    value: str,
) -> tuple[str, str]:
    try:
        profile, scenario = (
            value.split(
                ":",
                1,
            )
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Case must be PROFILE:SCENARIO"
        ) from exc

    if profile not in {
        "32k",
        "64k",
        "96k",
        "128k",
    }:
        raise argparse.ArgumentTypeError(
            f"Unknown profile: {profile}"
        )

    if scenario not in SCENARIOS:
        raise argparse.ArgumentTypeError(
            f"Unknown scenario: {scenario}"
        )

    return profile, scenario


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--case",
        action="append",
        type=parse_case,
        dest="cases",
        help=(
            "PROFILE:SCENARIO. "
            "May be specified multiple times."
        ),
    )

    parser.add_argument(
        "--run-id",
        default=None,
    )

    args = parser.parse_args()

    cases = (
        args.cases
        if args.cases
        else DEFAULT_CASES
    )

    run_id = (
        args.run_id
        or datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%dT%H%M%SZ"
        )
    )

    result_dir = (
        PROJECT_ROOT
        / "benchmarks"
        / "results"
        / "checkpoint2c2"
        / run_id
    )

    result_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    endpoint = gemma_endpoint()

    counter = TokenCounter(endpoint)
    client = OpenAICompatibleClient(
        endpoint
    )

    results: list[
        dict[str, Any]
    ] = []

    try:
        print(
            "=========================================================="
        )
        print(
            " AXONVERTEX Secure Agent Studio"
        )
        print(
            " Checkpoint 2C.2 — Evidence Inventory Isolation"
        )
        print(
            "=========================================================="
        )

        for index, (
            profile,
            scenario,
        ) in enumerate(
            cases,
            start=1,
        ):
            print()
            print("=" * 76)

            print(
                f"CASE {index}/{len(cases)}"
            )

            print(
                f"PROFILE  : {profile}"
            )

            print(
                f"SCENARIO : {scenario}"
            )

            print("=" * 76)

            result = execute_case(
                profile_name=profile,
                scenario_name=scenario,
                counter=counter,
                client=client,
            )

            results.append(result)

            case_path = (
                result_dir
                / (
                    f"{profile}__"
                    f"{scenario}.json"
                )
            )

            case_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            print(
                json.dumps(
                    {
                        "status":
                            result["status"],

                        "prompt_tokens":
                            result[
                                "actual_prompt_tokens"
                            ],

                        "support":
                            result[
                                "actual_support"
                            ],

                        "counter":
                            result[
                                "actual_counter"
                            ],

                        "uncertainty":
                            result[
                                "actual_uncertainty"
                            ],

                        "missing_ids":
                            result[
                                "missing_ids"
                            ],

                        "exhaustive_recovery":
                            result[
                                "exhaustive_recovery"
                            ],

                        "classification_exact":
                            result[
                                "classification_exact"
                            ],

                        "latency_ms":
                            result[
                                "latency_ms"
                            ],
                    },
                    indent=2,
                )
            )

        passed = sum(
            r["status"] == "PASS"
            for r in results
        )

        summary = {
            "schema_version":
                "evidence-inventory-isolation-summary.v1",

            "checkpoint":
                "2C.2",

            "run_id":
                run_id,

            "total_cases":
                len(results),

            "passed":
                passed,

            "failed":
                len(results)
                - passed,

            "all_passed":
                passed
                == len(results),

            "results":
                results,
        }

        (
            result_dir
            / "inventory-summary.json"
        ).write_text(
            json.dumps(
                summary,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print()
        print("=" * 76)
        print(
            "CHECKPOINT 2C.2 SUMMARY"
        )
        print("=" * 76)

        print(
            json.dumps(
                {
                    "run_id":
                        run_id,

                    "total":
                        len(results),

                    "passed":
                        passed,

                    "failed":
                        len(results)
                        - passed,

                    "all_passed":
                        passed
                        == len(results),

                    "results":
                        str(result_dir),
                },
                indent=2,
            )
        )

    finally:
        counter.close()
        client.close()


if __name__ == "__main__":
    main()
