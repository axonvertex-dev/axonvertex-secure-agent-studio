from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .context_profiles import load_context_profiles
from .long_context_generator import (
    EVIDENCE_RECORD,
    EVIDENCE_VALUE,
    SYSTEM_PROMPT,
    generate_long_context,
)
from .token_counter import TokenCounter


POSITIONS = [
    0.05,
    0.25,
    0.50,
    0.75,
    0.95,
]

TOLERANCE_TOKENS = 128
MAX_OUTPUT_TOKENS = 32


def measure_evidence_position(
    *,
    counter: TokenCounter,
    user_prompt: str,
    full_prompt_tokens: int,
) -> dict[str, Any]:
    marker_offset = user_prompt.index(
        EVIDENCE_RECORD
    )

    prefix = user_prompt[:marker_offset]

    framing_tokens = counter.count(
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": "",
            }
        ],
    )

    prefix_prompt_tokens = counter.count(
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": prefix,
            }
        ],
    )

    evidence_payload_offset = max(
        0,
        prefix_prompt_tokens - framing_tokens,
    )

    payload_tokens = max(
        1,
        full_prompt_tokens - framing_tokens,
    )

    measured_position = (
        evidence_payload_offset
        / payload_tokens
    )

    return {
        "framing_tokens": framing_tokens,
        "prefix_prompt_tokens":
            prefix_prompt_tokens,
        "evidence_payload_token_offset":
            evidence_payload_offset,
        "payload_tokens":
            payload_tokens,
        "measured_evidence_position":
            measured_position,
    }



def flush_sglang_cache(
    *,
    endpoint_url: str,
) -> None:
    admin_key = os.environ.get(
        "BENCHMARK_SGLANG_ADMIN_API_KEY",
        "",
    ).strip()

    if not admin_key:
        raise RuntimeError(
            "BENCHMARK_SGLANG_ADMIN_API_KEY is required "
            "for --cold-cache"
        )

    import httpx

    response = httpx.post(
        endpoint_url.rstrip("/")
        .removesuffix("/v1")
        + "/flush_cache",
        params={
            "timeout": 60,
        },
        headers={
            "Authorization":
                f"Bearer {admin_key}",
        },
        timeout=90.0,
    )

    response.raise_for_status()

    body = response.text.strip()

    if "Cache flushed" not in body:
        raise RuntimeError(
            "Unexpected flush_cache response: "
            f"{body!r}"
        )


def run_case(
    *,
    profile_name: str,
    evidence_position: float,
    counter: TokenCounter,
    client: OpenAICompatibleClient,
) -> dict[str, Any]:
    profiles = load_context_profiles()
    profile = profiles[profile_name]

    generated = generate_long_context(
        counter=counter,
        target_prompt_tokens=
            profile.target_prompt_tokens,
        evidence_position=
            evidence_position,
        tolerance_tokens=
            TOLERANCE_TOKENS,
    )

    position_measurement = (
        measure_evidence_position(
            counter=counter,
            user_prompt=
                generated.user_prompt,
            full_prompt_tokens=
                generated.measured_prompt_tokens,
        )
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
        max_tokens=MAX_OUTPUT_TOKENS,
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

    response_text = (
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

    total_tokens = usage.get(
        "total_tokens"
    )

    prompt_token_details_raw = (
        usage.get("prompt_tokens_details")
    )

    cache_metrics_available = isinstance(
        prompt_token_details_raw,
        dict,
    )

    prompt_token_details = (
        prompt_token_details_raw
        or {}
    )

    cached_tokens = (
        prompt_token_details.get(
            "cached_tokens",
            0,
        )
        or 0
    )

    token_counter_match = (
        actual_prompt_tokens
        == generated.measured_prompt_tokens
    )

    within_target_tolerance = (
        isinstance(
            actual_prompt_tokens,
            int,
        )
        and abs(
            actual_prompt_tokens
            - profile.target_prompt_tokens
        )
        <= TOLERANCE_TOKENS
    )

    answer_correct = (
        response_text
        == EVIDENCE_VALUE
    )

    context_ceiling_safe = (
        isinstance(
            actual_prompt_tokens,
            int,
        )
        and isinstance(
            completion_tokens,
            int,
        )
        and (
            actual_prompt_tokens
            + completion_tokens
        )
        <= profile.context_ceiling
    )

    reservation_contract_safe = (
        isinstance(
            actual_prompt_tokens,
            int,
        )
        and (
            actual_prompt_tokens
            <= (
                profile.context_ceiling
                - profile.output_reserve
            )
        )
    )

    passed = all(
        [
            token_counter_match,
            within_target_tolerance,
            answer_correct,
            context_ceiling_safe,
            reservation_contract_safe,
        ]
    )

    cache_hit_ratio = None

    if (
        isinstance(
            actual_prompt_tokens,
            int,
        )
        and actual_prompt_tokens > 0
        and isinstance(
            cached_tokens,
            int,
        )
    ):
        cache_hit_ratio = (
            cached_tokens
            / actual_prompt_tokens
        )

    return {
        "schema_version":
            "long-context-result.v2",

        "status":
            "PASS"
            if passed
            else "FAIL",

        "profile":
            profile.name,

        "context_ceiling":
            profile.context_ceiling,

        "output_reserve":
            profile.output_reserve,

        "target_prompt_tokens":
            profile.target_prompt_tokens,

        "counted_prompt_tokens":
            generated.measured_prompt_tokens,

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

        "token_counter_match":
            token_counter_match,

        "within_target_tolerance":
            within_target_tolerance,

        "requested_evidence_position":
            evidence_position,

        **position_measurement,

        "evidence_position_error":
            (
                position_measurement[
                    "measured_evidence_position"
                ]
                - evidence_position
            ),

        "filler_records":
            generated.filler_records,

        "evidence_insertion_index":
            generated.insertion_index,

        "generator_iterations":
            generated.generation_iterations,

        "expected":
            EVIDENCE_VALUE,

        "response":
            response_text,

        "answer_correct":
            answer_correct,

        "completion_tokens":
            completion_tokens,

        "total_tokens":
            total_tokens,

        "cache_metrics_available":
            cache_metrics_available,

        "cached_tokens":
            cached_tokens,

        "cache_hit_ratio":
            cache_hit_ratio,

        "context_ceiling_safe":
            context_ceiling_safe,

        "reservation_contract_safe":
            reservation_contract_safe,

        "finish_reason":
            choice.get(
                "finish_reason"
            ),

        "latency_ms":
            latency_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--profiles",
        nargs="+",
        default=["32k"],
    )

    parser.add_argument(
        "--cold-cache",
        action="store_true",
        help=(
            "Flush the SGLang radix cache "
            "before every benchmark case."
        ),
    )

    parser.add_argument(
        "--positions",
        nargs="+",
        type=float,
        default=POSITIONS,
        help=(
            "Evidence positions expressed as fractions, "
            "for example: --positions 0.50"
        ),
    )

    args = parser.parse_args()

    for position in args.positions:
        if not 0.0 <= position <= 1.0:
            raise SystemExit(
                f"Invalid evidence position: {position}"
            )

    profiles = load_context_profiles()

    for name in args.profiles:
        if name not in profiles:
            raise SystemExit(
                f"Unknown profile: {name}"
            )

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
        / "checkpoint2"
        / timestamp
    )

    result_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_results: list[
        dict[str, Any]
    ] = []

    try:
        for profile_name in args.profiles:
            print()
            print(
                "=" * 72
            )
            print(
                f"PROFILE: {profile_name}"
            )
            print(
                "=" * 72
            )

            for position in args.positions:
                print()
                print(
                    f"Running "
                    f"{profile_name} "
                    f"@ {position:.0%}..."
                )

                if args.cold_cache:
                    print(
                        "Flushing SGLang radix cache..."
                    )

                    flush_sglang_cache(
                        endpoint_url=
                            endpoint.base_url,
                    )

                result = run_case(
                    profile_name=
                        profile_name,
                    evidence_position=
                        position,
                    counter=counter,
                    client=client,
                )

                all_results.append(
                    result
                )

                case_name = (
                    f"{profile_name}-"
                    f"pos{round(position * 100):02d}"
                )

                case_path = (
                    result_dir
                    / f"{case_name}.json"
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
                                result[
                                    "status"
                                ],

                            "target":
                                result[
                                    "target_prompt_tokens"
                                ],

                            "actual":
                                result[
                                    "actual_prompt_tokens"
                                ],

                            "requested_position":
                                result[
                                    "requested_evidence_position"
                                ],

                            "measured_position":
                                round(
                                    result[
                                        "measured_evidence_position"
                                    ],
                                    4,
                                ),

                            "response":
                                result[
                                    "response"
                                ],

                            "cached_tokens":
                                result[
                                    "cached_tokens"
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
            1
            for result in all_results
            if result["status"]
            == "PASS"
        )

        failed = (
            len(all_results)
            - passed
        )

        summary = {
            "schema_version":
                "long-context-matrix.v1",

            "model":
                endpoint.model,

            "endpoint":
                endpoint.base_url,

            "profiles":
                args.profiles,

            "positions":
                args.positions,

            "cold_cache":
                args.cold_cache,

            "total_cases":
                len(all_results),

            "passed":
                passed,

            "failed":
                failed,

            "all_passed":
                failed == 0,

            "latency_interpretation":
                (
                    "informational-only; "
                    "prefix cache not controlled"
                ),

            "results":
                all_results,
        }

        summary_path = (
            result_dir
            / "matrix-summary.json"
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
            "MATRIX SUMMARY"
        )
        print(
            "=" * 72
        )

        print(
            json.dumps(
                {
                    "total_cases":
                        len(all_results),
                    "passed":
                        passed,
                    "failed":
                        failed,
                    "all_passed":
                        failed == 0,
                    "results":
                        str(result_dir),
                },
                indent=2,
            )
        )

        if failed:
            raise SystemExit(1)

    finally:
        counter.close()
        client.close()


if __name__ == "__main__":
    main()
