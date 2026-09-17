from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .context_profiles import load_context_profiles
from .long_context_generator import (
    EVIDENCE_VALUE,
    SYSTEM_PROMPT,
    generate_long_context,
)
from .token_counter import TokenCounter


PROFILE_NAME = "32k"
EVIDENCE_POSITION = 0.50
TOLERANCE_TOKENS = 128
MAX_OUTPUT_TOKENS = 32


def main() -> None:
    print(
        "======================================================"
    )
    print(
        " AXONVERTEX Secure Agent Studio"
    )
    print(
        " Checkpoint 2 — 32K Long-Context Retrieval Smoke Test"
    )
    print(
        "======================================================"
    )

    endpoint = gemma_endpoint()
    profiles = load_context_profiles()

    profile = profiles[PROFILE_NAME]

    counter = TokenCounter(endpoint)
    client = OpenAICompatibleClient(endpoint)

    try:
        print()
        print(
            f"Profile            : {profile.name}"
        )
        print(
            f"Context ceiling    : {profile.context_ceiling}"
        )
        print(
            f"Target prompt      : {profile.target_prompt_tokens}"
        )
        print(
            f"Output reserve     : {profile.output_reserve}"
        )
        print(
            f"Evidence position  : {EVIDENCE_POSITION:.0%}"
        )

        print()
        print(
            "Generating deterministic synthetic context..."
        )

        generated = generate_long_context(
            counter=counter,
            target_prompt_tokens=
                profile.target_prompt_tokens,
            evidence_position=
                EVIDENCE_POSITION,
            tolerance_tokens=
                TOLERANCE_TOKENS,
        )

        print(
            f"Filler records     : {generated.filler_records}"
        )
        print(
            f"Insertion index    : {generated.insertion_index}"
        )
        print(
            f"Measured prompt    : "
            f"{generated.measured_prompt_tokens}"
        )
        print(
            f"Target delta       : "
            f"{generated.token_delta:+d}"
        )
        print(
            f"Generator passes   : "
            f"{generated.generation_iterations}"
        )

        print()
        print("Executing inference...")

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

        cached_tokens = (
            usage
            .get(
                "prompt_tokens_details",
                {},
            )
            .get(
                "cached_tokens",
                0,
            )
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

        passed = all(
            [
                token_counter_match,
                within_target_tolerance,
                answer_correct,
                context_ceiling_safe,
            ]
        )

        cache_hit_ratio = None

        if (
            isinstance(actual_prompt_tokens, int)
            and actual_prompt_tokens > 0
            and isinstance(cached_tokens, int)
        ):
            cache_hit_ratio = (
                cached_tokens
                / actual_prompt_tokens
            )

        result = {
            "schema_version":
                "long-context-result.v1",

            "status":
                "PASS"
                if passed
                else "FAIL",

            "profile":
                profile.name,

            "model":
                endpoint.model,

            "endpoint":
                endpoint.base_url,

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
                EVIDENCE_POSITION,

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

            "cached_tokens":
                cached_tokens,

            "cache_hit_ratio":
                cache_hit_ratio,

            "context_ceiling_safe":
                context_ceiling_safe,

            "finish_reason":
                choice.get(
                    "finish_reason"
                ),

            "latency_ms":
                latency_ms,
        }

        print()
        print("===== RESULT =====")
        print(
            json.dumps(
                result,
                indent=2,
            )
        )

        result_dir = (
            PROJECT_ROOT
            / "benchmarks"
            / "results"
            / "checkpoint2"
        )

        result_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        timestamp = (
            datetime.now(timezone.utc)
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )

        result_path = (
            result_dir
            / (
                "long-context-32k-pos50-"
                f"{timestamp}.json"
            )
        )

        result_path.write_text(
            json.dumps(
                result,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print()
        print(
            f"Saved: {result_path}"
        )

        if not passed:
            raise SystemExit(1)

    finally:
        counter.close()
        client.close()


if __name__ == "__main__":
    main()
