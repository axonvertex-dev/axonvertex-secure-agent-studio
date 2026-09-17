from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .context_profiles import load_context_profiles
from .distributed_evidence_generator import (
    EVIDENCE_RECORDS,
    EXPECTED_COUNTER_EVIDENCE_IDS,
    EXPECTED_EVIDENCE_IDS,
    EXPECTED_VERDICT,
    SYSTEM_PROMPT,
    generate_distributed_context,
)
from .long_context_matrix import (
    flush_sglang_cache,
)
from .token_counter import TokenCounter


PROFILE_NAME = "32k"
TOLERANCE_TOKENS = 128
MAX_OUTPUT_TOKENS = 512


def parse_json_response(
    text: str,
) -> dict[str, Any]:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        )

    try:
        value = json.loads(cleaned)

        if not isinstance(value, dict):
            raise ValueError(
                "Response JSON is not an object"
            )

        return value

    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end == -1:
            raise

        value = json.loads(
            cleaned[start:end + 1]
        )

        if not isinstance(value, dict):
            raise ValueError(
                "Response JSON is not an object"
            )

        return value


def measure_evidence_positions(
    *,
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

    for _, evidence_id, record in EVIDENCE_RECORDS:
        offset = user_prompt.index(record)

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

        result[evidence_id] = round(
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


def normalize_id_set(
    value: Any,
) -> set[str]:
    if not isinstance(value, list):
        return set()

    return {
        str(item).strip()
        for item in value
        if str(item).strip()
    }


def main() -> None:
    endpoint = gemma_endpoint()

    profile = load_context_profiles()[
        PROFILE_NAME
    ]

    counter = TokenCounter(endpoint)
    client = OpenAICompatibleClient(endpoint)

    try:
        print(
            "======================================================="
        )
        print(
            " AXONVERTEX Secure Agent Studio"
        )
        print(
            " Checkpoint 2B — Distributed Evidence Reasoning"
        )
        print(
            "======================================================="
        )

        generated = generate_distributed_context(
            counter=counter,
            target_prompt_tokens=
                profile.target_prompt_tokens,
            tolerance_tokens=
                TOLERANCE_TOKENS,
        )

        positions = measure_evidence_positions(
            counter=counter,
            user_prompt=
                generated.user_prompt,
            full_prompt_tokens=
                generated.measured_prompt_tokens,
        )

        print()
        print(
            f"Profile          : {PROFILE_NAME}"
        )
        print(
            f"Target prompt    : "
            f"{profile.target_prompt_tokens}"
        )
        print(
            f"Measured prompt  : "
            f"{generated.measured_prompt_tokens}"
        )
        print(
            f"Token delta      : "
            f"{generated.token_delta:+d}"
        )
        print(
            f"Filler records   : "
            f"{generated.filler_records}"
        )
        print(
            f"Evidence positions: "
            f"{positions}"
        )

        print()
        print(
            "Flushing SGLang radix cache..."
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

        verdict_correct = (
            verdict
            == EXPECTED_VERDICT
        )

        required_evidence_present = (
            EXPECTED_EVIDENCE_IDS
            <= evidence_ids
        )

        evidence_exact = (
            evidence_ids
            == EXPECTED_EVIDENCE_IDS
        )

        counter_evidence_exact = (
            counter_ids
            == EXPECTED_COUNTER_EVIDENCE_IDS
        )

        known_ids = (
            EXPECTED_EVIDENCE_IDS
            | EXPECTED_COUNTER_EVIDENCE_IDS
        )

        unsupported_ids = (
            evidence_ids
            | counter_ids
        ) - known_ids

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

        semantic_reasoning_pass = all(
            [
                parsed is not None,
                verdict_correct,
                required_evidence_present,
                no_unsupported_ids,
            ]
        )

        provenance_contract_pass = all(
            [
                parsed is not None,
                evidence_exact,
                counter_evidence_exact,
                no_unsupported_ids,
            ]
        )

        infrastructure_contract_pass = all(
            [
                token_counter_match,
                reservation_contract_safe,
            ]
        )

        passed = all(
            [
                semantic_reasoning_pass,
                provenance_contract_pass,
                infrastructure_contract_pass,
            ]
        )

        result = {
            "schema_version":
                "distributed-reasoning-result.v1",

            "status":
                "PASS"
                if passed
                else "FAIL",

            "profile":
                PROFILE_NAME,

            "target_prompt_tokens":
                profile.target_prompt_tokens,

            "counted_prompt_tokens":
                generated.measured_prompt_tokens,

            "actual_prompt_tokens":
                actual_prompt_tokens,

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

            "evidence_positions":
                positions,

            "expected_verdict":
                EXPECTED_VERDICT,

            "actual_verdict":
                verdict,

            "verdict_correct":
                verdict_correct,

            "semantic_reasoning_pass":
                semantic_reasoning_pass,

            "provenance_contract_pass":
                provenance_contract_pass,

            "infrastructure_contract_pass":
                infrastructure_contract_pass,

            "expected_evidence_ids":
                sorted(
                    EXPECTED_EVIDENCE_IDS
                ),

            "actual_evidence_ids":
                sorted(
                    evidence_ids
                ),

            "evidence_exact":
                evidence_exact,

            "expected_counter_evidence_ids":
                sorted(
                    EXPECTED_COUNTER_EVIDENCE_IDS
                ),

            "actual_counter_evidence_ids":
                sorted(
                    counter_ids
                ),

            "counter_evidence_exact":
                counter_evidence_exact,

            "unsupported_ids":
                sorted(
                    unsupported_ids
                ),

            "no_unsupported_ids":
                no_unsupported_ids,

            "reservation_contract_safe":
                reservation_contract_safe,

            "latency_ms":
                latency_ms,

            "finish_reason":
                choice.get(
                    "finish_reason"
                ),

            "parse_error":
                parse_error,

            "raw_response":
                raw_response,
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
            / "checkpoint2b"
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
                "distributed-security-"
                f"32k-{timestamp}.json"
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
