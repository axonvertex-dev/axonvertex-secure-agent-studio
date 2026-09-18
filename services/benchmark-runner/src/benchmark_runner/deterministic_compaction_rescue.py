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
from .distributed_suite_generator import SYSTEM_PROMPT
from .distributed_suite_scenarios import (
    SCENARIOS,
    ReasoningScenario,
)
from .evidence_visibility_isolation import (
    generate_context,
)
from .long_context_matrix import flush_sglang_cache
from .token_counter import TokenCounter


MAX_OUTPUT_TOKENS = 512


DEFAULT_CASES = [
    ("64k", "A-vulnerable"),
    ("64k", "B-not-vulnerable"),
    ("64k", "C-insufficient"),

    ("96k", "A-vulnerable"),
    ("96k", "B-not-vulnerable"),
    ("96k", "C-insufficient"),

    ("128k", "A-vulnerable"),
    ("128k", "B-not-vulnerable"),
    ("128k", "C-insufficient"),
]


def extract_authoritative_records(
    user_prompt: str,
) -> list[str]:
    """
    Deterministic fast compaction.

    Preserve every authoritative record verbatim.
    Remove synthetic distractors and long-context filler.

    This intentionally performs no LLM summarization.
    """
    records = []

    for line in user_prompt.splitlines():
        stripped = line.strip()

        if (
            stripped.startswith("EVIDENCE ")
            or stripped.startswith(
                "COUNTER_EVIDENCE "
            )
        ):
            records.append(stripped)

    return records


def build_compact_prompt(
    *,
    scenario: ReasoningScenario,
    authoritative_records: list[str],
) -> str:
    return (
        "COMPACT_EVIDENCE_BUNDLE_BEGIN\n\n"
        + "\n".join(
            authoritative_records
        )
        + "\n\n"
        + "COMPACT_EVIDENCE_BUNDLE_END\n\n"
        + "QUESTION:\n"
        + scenario.question
        + "\n\n"
        + "Return only the required JSON object."
    )


def execute_case(
    *,
    source_profile_name: str,
    scenario_name: str,
    counter: TokenCounter,
    client: OpenAICompatibleClient,
) -> dict[str, Any]:
    scenario = SCENARIOS[
        scenario_name
    ]

    profile = load_context_profiles()[
        source_profile_name
    ]

    endpoint = gemma_endpoint()

    # Build the original long-context source.
    generated = generate_context(
        scenario=scenario,
        counter=counter,
        target_prompt_tokens=
            profile.target_prompt_tokens,
    )

    source_prompt_tokens = (
        generated.measured_prompt_tokens
    )

    # Deterministic compaction.
    authoritative_records = (
        extract_authoritative_records(
            generated.user_prompt
        )
    )

    expected_record_ids = {
        record.evidence_id
        for record in scenario.records
    }

    extracted_record_ids = set()

    for record in scenario.records:
        if record.text in authoritative_records:
            extracted_record_ids.add(
                record.evidence_id
            )

    extraction_complete = (
        extracted_record_ids
        == expected_record_ids
    )

    missing_after_compaction = (
        expected_record_ids
        - extracted_record_ids
    )

    compact_prompt = build_compact_prompt(
        scenario=scenario,
        authoritative_records=
            authoritative_records,
    )

    compact_prompt_tokens = counter.count(
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": compact_prompt,
            }
        ],
    )

    compaction_ratio = round(
        compact_prompt_tokens
        / source_prompt_tokens,
        6,
    )

    token_reduction_percent = round(
        (
            1
            - (
                compact_prompt_tokens
                / source_prompt_tokens
            )
        )
        * 100,
        3,
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
                "content": compact_prompt,
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

    required_evidence = set(
        scenario.expected_evidence_ids
    )

    allowed_evidence = set(
        scenario.allowed_evidence_ids
    )

    required_counter = set(
        scenario.expected_counter_evidence_ids
    )

    allowed_counter = set(
        scenario.allowed_counter_evidence_ids
    )

    required_uncertainty = set(
        scenario.expected_uncertainty_evidence_ids
    )

    allowed_uncertainty = set(
        scenario.allowed_uncertainty_evidence_ids
    )

    verdict_correct = (
        verdict
        == scenario.expected_verdict
    )

    evidence_required_present = (
        required_evidence
        <= evidence_ids
    )

    evidence_allowed_only = (
        evidence_ids
        <= allowed_evidence
    )

    counter_required_present = (
        required_counter
        <= counter_ids
    )

    counter_allowed_only = (
        counter_ids
        <= allowed_counter
    )

    uncertainty_required_present = (
        required_uncertainty
        <= uncertainty_ids
    )

    uncertainty_allowed_only = (
        uncertainty_ids
        <= allowed_uncertainty
    )

    categories_disjoint = (
        evidence_ids.isdisjoint(
            counter_ids
        )
        and evidence_ids.isdisjoint(
            uncertainty_ids
        )
        and counter_ids.isdisjoint(
            uncertainty_ids
        )
    )

    all_allowed = (
        allowed_evidence
        | allowed_counter
        | allowed_uncertainty
    )

    actual_ids = (
        evidence_ids
        | counter_ids
        | uncertainty_ids
    )

    unsupported_ids = (
        actual_ids
        - all_allowed
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

        categories_disjoint,
        len(unsupported_ids) == 0,
    ])

    infrastructure_contract_pass = all([
        extraction_complete,
        actual_prompt_tokens
        == compact_prompt_tokens,
    ])

    passed = all([
        semantic_reasoning_pass,
        provenance_contract_pass,
        infrastructure_contract_pass,
    ])

    return {
        "schema_version":
            "deterministic-compaction-rescue.v1",

        "checkpoint":
            "2C.3",

        "status":
            "PASS"
            if passed
            else "FAIL",

        "source_profile":
            source_profile_name,

        "scenario_id":
            scenario_name,

        "expected_verdict":
            scenario.expected_verdict,

        "actual_verdict":
            verdict,

        "verdict_correct":
            verdict_correct,

        "source_prompt_tokens":
            source_prompt_tokens,

        "compact_prompt_tokens":
            compact_prompt_tokens,

        "actual_prompt_tokens":
            actual_prompt_tokens,

        "completion_tokens":
            completion_tokens,

        "compaction_ratio":
            compaction_ratio,

        "token_reduction_percent":
            token_reduction_percent,

        "source_record_ids":
            sorted(
                expected_record_ids
            ),

        "compacted_record_ids":
            sorted(
                extracted_record_ids
            ),

        "missing_after_compaction":
            sorted(
                missing_after_compaction
            ),

        "extraction_complete":
            extraction_complete,

        "actual_evidence_ids":
            sorted(
                evidence_ids
            ),

        "actual_counter_evidence_ids":
            sorted(
                counter_ids
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
        "64k",
        "96k",
        "128k",
    }:
        raise argparse.ArgumentTypeError(
            "Compaction rescue profile must "
            "be 64k, 96k or 128k"
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
        / "checkpoint2c3"
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
            " Checkpoint 2C.3 — Deterministic Compaction Rescue"
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
                f"SOURCE PROFILE : {profile}"
            )

            print(
                f"SCENARIO       : {scenario}"
            )

            print("=" * 76)

            result = execute_case(
                source_profile_name=
                    profile,
                scenario_name=
                    scenario,
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

                        "expected_verdict":
                            result[
                                "expected_verdict"
                            ],

                        "actual_verdict":
                            result[
                                "actual_verdict"
                            ],

                        "source_prompt_tokens":
                            result[
                                "source_prompt_tokens"
                            ],

                        "compact_prompt_tokens":
                            result[
                                "compact_prompt_tokens"
                            ],

                        "token_reduction_percent":
                            result[
                                "token_reduction_percent"
                            ],

                        "extraction_complete":
                            result[
                                "extraction_complete"
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
                "deterministic-compaction-rescue-summary.v1",

            "checkpoint":
                "2C.3",

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
            / "compaction-summary.json"
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
            "CHECKPOINT 2C.3 SUMMARY"
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
