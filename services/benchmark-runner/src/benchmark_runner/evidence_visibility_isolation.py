from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
from .long_context_matrix import flush_sglang_cache
from .token_counter import TokenCounter


TOLERANCE_TOKENS = 128
MAX_OUTPUT_TOKENS = 256


SYSTEM_PROMPT = """
You are an evidence record inventory engine.

This is a retrieval task only.

Do NOT:
- decide whether the system is vulnerable;
- reason about security consequences;
- classify evidence as support, counter, or uncertainty;
- summarize evidence;
- reproduce evidence record text.

Inspect the entire corpus and return the ID of every authoritative
evidence record exactly once.

An evidence ID is the short identifier immediately following the
record marker EVIDENCE or COUNTER_EVIDENCE.

Examples of valid IDs:
E1
C4
BC1

Synthetic DISTRACTOR records are not authoritative evidence and must
never be returned.

Return exactly one JSON object:

{
  "record_ids": ["ID1", "ID2"]
}

The array must contain IDs only.
Do not return record contents.
Do not return a verdict.
Do not use markdown.
""".strip()


HEADER = """
SECURITY_INVESTIGATION_CORPUS_BEGIN

Inventory every authoritative evidence record in this corpus.

""".lstrip()


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
class GeneratedContext:
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


def expected_ids(
    scenario: ReasoningScenario,
) -> set[str]:
    return {
        record.evidence_id
        for record in scenario.records
    }


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

    footer = """
SECURITY_INVESTIGATION_CORPUS_END

Return the ID of every authoritative evidence record.
Return IDs only in the required JSON object.
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
) -> GeneratedContext:
    base = build_prompt(
        scenario=scenario,
        filler_records=0,
    )

    base_tokens = count_prompt(
        counter=counter,
        user_prompt=base,
    )

    sample_records = 100

    sample = build_prompt(
        scenario=scenario,
        filler_records=sample_records,
    )

    sample_tokens = count_prompt(
        counter=counter,
        user_prompt=sample,
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

    best_delta = None

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

        if (
            best_delta is None
            or abs(delta) < abs(best_delta)
        ):
            best_delta = delta

        if abs(delta) <= TOLERANCE_TOKENS:
            return GeneratedContext(
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

    raise RuntimeError(
        "Unable to construct context "
        f"within tolerance; best_delta={best_delta}"
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
                "content": SYSTEM_PROMPT,
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

    actual_prompt_tokens = usage.get(
        "prompt_tokens"
    )

    completion_tokens = usage.get(
        "completion_tokens"
    )

    parsed = None
    parse_error = None

    try:
        parsed = parse_json_response(
            raw_response
        )
    except Exception as exc:
        parse_error = str(exc)

    actual_ids = normalize_id_set(
        parsed.get("record_ids")
        if parsed
        else None
    )

    expected = expected_ids(
        scenario
    )

    missing = (
        expected
        - actual_ids
    )

    unsupported = (
        actual_ids
        - expected
    )

    exact_recovery = (
        actual_ids
        == expected
    )

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
        exact_recovery,
        len(missing) == 0,
        len(unsupported) == 0,
        token_counter_match,
        reservation_contract_safe,
    ])

    return {
        "schema_version":
            "evidence-visibility-isolation.v1",

        "checkpoint":
            "2C.2a",

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

        "expected_ids":
            sorted(expected),

        "actual_ids":
            sorted(actual_ids),

        "missing_ids":
            sorted(missing),

        "unsupported_ids":
            sorted(unsupported),

        "exact_recovery":
            exact_recovery,

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
        / "checkpoint2c2a"
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
            " Checkpoint 2C.2a — Evidence Visibility Isolation"
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

            (
                result_dir
                / (
                    f"{profile}__"
                    f"{scenario}.json"
                )
            ).write_text(
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

                        "expected_ids":
                            result[
                                "expected_ids"
                            ],

                        "actual_ids":
                            result[
                                "actual_ids"
                            ],

                        "missing_ids":
                            result[
                                "missing_ids"
                            ],

                        "unsupported_ids":
                            result[
                                "unsupported_ids"
                            ],

                        "exact_recovery":
                            result[
                                "exact_recovery"
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
                "evidence-visibility-isolation-summary.v1",

            "checkpoint":
                "2C.2a",

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
            / "visibility-summary.json"
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
            "CHECKPOINT 2C.2a SUMMARY"
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
