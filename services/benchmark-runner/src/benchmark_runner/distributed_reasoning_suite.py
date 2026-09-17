from __future__ import annotations

import argparse

import json
import time
from datetime import datetime, timezone
from typing import Any

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .context_profiles import load_context_profiles
from .distributed_reasoning_smoke import (
    normalize_id_set,
    parse_json_response,
)
from .distributed_suite_generator import (
    SYSTEM_PROMPT,
    generate_scenario_context,
)
from .distributed_suite_scenarios import (
    SCENARIOS,
    ReasoningScenario,
)
from .long_context_matrix import (
    flush_sglang_cache,
)
from .token_counter import TokenCounter


PROFILE_NAME = "32k"
TOLERANCE_TOKENS = 128
MAX_OUTPUT_TOKENS = 512


def measure_positions(
    *,
    scenario: ReasoningScenario,
    counter: TokenCounter,
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
        full_prompt_tokens - empty_tokens,
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

        result[record.evidence_id] = round(
            (
                max(
                    0,
                    prefix_tokens - empty_tokens,
                )
                / payload_tokens
            ),
            4,
        )

    return result


def execute_scenario(
    *,
    scenario: ReasoningScenario,
    counter: TokenCounter,
    client: OpenAICompatibleClient,
) -> dict[str, Any]:
    endpoint = gemma_endpoint()

    profile = load_context_profiles()[
        PROFILE_NAME
    ]

    generated = generate_scenario_context(
        scenario=scenario,
        counter=counter,
        target_prompt_tokens=
            profile.target_prompt_tokens,
        tolerance_tokens=
            TOLERANCE_TOKENS,
    )

    positions = measure_positions(
        scenario=scenario,
        counter=counter,
        user_prompt=
            generated.user_prompt,
        full_prompt_tokens=
            generated.measured_prompt_tokens,
    )

    flush_sglang_cache(
        endpoint_url=endpoint.base_url,
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

    parsed = None
    parse_error = None

    try:
        parsed = parse_json_response(
            raw_response
        )
    except Exception as exc:
        parse_error = str(exc)

    verdict = (
        parsed.get("verdict")
        if parsed
        else None
    )

    evidence_ids = normalize_id_set(
        parsed.get("evidence_ids")
        if parsed
        else None
    )

    counter_ids = normalize_id_set(
        parsed.get(
            "counter_evidence_ids"
        )
        if parsed
        else None
    )

    uncertainty_ids = normalize_id_set(
        parsed.get(
            "uncertainty_evidence_ids"
        )
        if parsed
        else None
    )

    expected_evidence = set(
        scenario.expected_evidence_ids
    )

    allowed_evidence = set(
        scenario.allowed_evidence_ids
    )

    expected_counter = set(
        scenario.expected_counter_evidence_ids
    )

    allowed_counter = set(
        scenario.allowed_counter_evidence_ids
    )

    expected_uncertainty = set(
        scenario.expected_uncertainty_evidence_ids
    )

    allowed_uncertainty = set(
        scenario.allowed_uncertainty_evidence_ids
    )

    known_ids = (
        allowed_evidence
        | allowed_counter
        | allowed_uncertainty
    )

    unsupported_ids = (
        evidence_ids
        | counter_ids
        | uncertainty_ids
    ) - known_ids

    verdict_correct = (
        verdict
        == scenario.expected_verdict
    )

    evidence_required_present = (
        expected_evidence
        <= evidence_ids
    )

    evidence_allowed_only = (
        evidence_ids
        <= allowed_evidence
    )

    counter_required_present = (
        expected_counter
        <= counter_ids
    )

    counter_allowed_only = (
        counter_ids
        <= allowed_counter
    )

    uncertainty_required_present = (
        expected_uncertainty
        <= uncertainty_ids
    )

    uncertainty_allowed_only = (
        uncertainty_ids
        <= allowed_uncertainty
    )

    evidence_categories_disjoint = (
        evidence_ids.isdisjoint(counter_ids)
        and evidence_ids.isdisjoint(
            uncertainty_ids
        )
        and counter_ids.isdisjoint(
            uncertainty_ids
        )
    )

    no_unsupported_ids = (
        len(unsupported_ids) == 0
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

    semantic_reasoning_pass = all([
        parsed is not None,
        verdict_correct,
    ])

    provenance_contract_pass = all([
        parsed is not None,

        evidence_required_present,
        evidence_allowed_only,

        counter_required_present,
        counter_allowed_only,

        uncertainty_required_present,
        uncertainty_allowed_only,

        evidence_categories_disjoint,
        no_unsupported_ids,
    ])

    infrastructure_contract_pass = all([
        token_counter_match,
        reservation_contract_safe,
    ])

    passed = all([
        semantic_reasoning_pass,
        provenance_contract_pass,
        infrastructure_contract_pass,
    ])

    return {
        "schema_version":
            "distributed-reasoning-suite-result.v1",

        "scenario_id":
            scenario.scenario_id,

        "status":
            "PASS"
            if passed
            else "FAIL",

        "profile":
            PROFILE_NAME,

        "target_prompt_tokens":
            profile.target_prompt_tokens,

        "actual_prompt_tokens":
            actual_prompt_tokens,

        "prompt_token_delta":
            (
                actual_prompt_tokens
                - profile.target_prompt_tokens
                if isinstance(
                    actual_prompt_tokens,
                    int,
                )
                else None
            ),

        "evidence_positions":
            positions,

        "expected_verdict":
            scenario.expected_verdict,

        "actual_verdict":
            verdict,

        "verdict_correct":
            verdict_correct,

        "expected_evidence_ids":
            sorted(
                expected_evidence
            ),

        "actual_evidence_ids":
            sorted(
                evidence_ids
            ),

        "expected_counter_evidence_ids":
            sorted(
                expected_counter
            ),

        "actual_counter_evidence_ids":
            sorted(
                counter_ids
            ),

        "expected_uncertainty_evidence_ids":
            sorted(
                expected_uncertainty
            ),

        "actual_uncertainty_evidence_ids":
            sorted(
                uncertainty_ids
            ),

        "unsupported_ids":
            sorted(
                unsupported_ids
            ),

        "semantic_reasoning_pass":
            semantic_reasoning_pass,

        "provenance_contract_pass":
            provenance_contract_pass,

        "infrastructure_contract_pass":
            infrastructure_contract_pass,

        "token_counter_match":
            token_counter_match,

        "reservation_contract_safe":
            reservation_contract_safe,

        "latency_ms":
            latency_ms,

        "parse_error":
            parse_error,

        "raw_response":
            raw_response,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=sorted(SCENARIOS),
        default=list(SCENARIOS),
    )

    args = parser.parse_args()

    selected_scenarios = [
        SCENARIOS[name]
        for name in args.scenarios
    ]

    endpoint = gemma_endpoint()

    counter = TokenCounter(endpoint)
    client = OpenAICompatibleClient(endpoint)

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )

    result_dir = (
        PROJECT_ROOT
        / "benchmarks"
        / "results"
        / "checkpoint2b"
        / timestamp
    )

    result_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    results: list[dict[str, Any]] = []

    try:
        print(
            "========================================================"
        )
        print(
            " AXONVERTEX Secure Agent Studio"
        )
        print(
            " Checkpoint 2B — 32K Reasoning Suite v1"
        )
        print(
            "========================================================"
        )

        for scenario in selected_scenarios:
            print()
            print(
                "=" * 72
            )
            print(
                f"SCENARIO: {scenario.scenario_id}"
            )
            print(
                f"EXPECTED: {scenario.expected_verdict}"
            )
            print(
                "=" * 72
            )

            result = execute_scenario(
                scenario=scenario,
                counter=counter,
                client=client,
            )

            results.append(result)

            path = (
                result_dir
                / f"{scenario.scenario_id}.json"
            )

            path.write_text(
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
                        "actual_prompt_tokens":
                            result[
                                "actual_prompt_tokens"
                            ],
                        "expected_verdict":
                            result[
                                "expected_verdict"
                            ],
                        "actual_verdict":
                            result[
                                "actual_verdict"
                            ],
                        "semantic":
                            result[
                                "semantic_reasoning_pass"
                            ],
                        "provenance":
                            result[
                                "provenance_contract_pass"
                            ],
                        "infrastructure":
                            result[
                                "infrastructure_contract_pass"
                            ],
                        "evidence":
                            result[
                                "actual_evidence_ids"
                            ],
                        "counter_evidence":
                            result[
                                "actual_counter_evidence_ids"
                            ],
                        "uncertainty_evidence":
                            result[
                                "actual_uncertainty_evidence_ids"
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
            result["status"] == "PASS"
            for result in results
        )

        summary = {
            "schema_version":
                "distributed-reasoning-suite.v1",

            "profile":
                PROFILE_NAME,

            "total_scenarios":
                len(results),

            "passed":
                passed,

            "failed":
                len(results) - passed,

            "all_passed":
                passed == len(results),

            "results":
                results,
        }

        summary_path = (
            result_dir
            / "suite-summary.json"
        )

        summary_path.write_text(
            json.dumps(
                summary,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print()
        print(
            "=" * 72
        )
        print(
            "SUITE SUMMARY"
        )
        print(
            "=" * 72
        )

        print(
            json.dumps(
                {
                    "total":
                        len(results),
                    "passed":
                        passed,
                    "failed":
                        len(results) - passed,
                    "all_passed":
                        passed == len(results),
                    "results":
                        str(result_dir),
                },
                indent=2,
            )
        )

        if passed != len(results):
            raise SystemExit(1)

    finally:
        counter.close()
        client.close()


if __name__ == "__main__":
    main()
