from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .schema import (
    BenchmarkResult,
    BenchmarkTask,
    UsageRecord,
)


TASK_PATH = (
    PROJECT_ROOT
    / "benchmarks"
    / "tasks"
    / "smoke"
    / "node-a-exact.yaml"
)

RESULT_DIR = (
    PROJECT_ROOT
    / "benchmarks"
    / "results"
    / "checkpoint1"
)


def load_task() -> BenchmarkTask:
    with TASK_PATH.open(
        "r",
        encoding="utf-8",
    ) as handle:
        payload = yaml.safe_load(handle)

    return BenchmarkTask.model_validate(payload)


def find_live_model(
    response: dict,
    model_id: str,
) -> dict | None:
    for model in response.get("data", []):
        if model.get("id") == model_id:
            return model

    return None


def main() -> None:
    print(
        "=============================================="
    )
    print(
        " AXONVERTEX Secure Agent Studio"
    )
    print(
        " Checkpoint 1 — Python Benchmark Foundation"
    )
    print(
        "=============================================="
    )

    task = load_task()
    endpoint = gemma_endpoint()

    print()
    print(f"Task     : {task.id}")
    print(f"Endpoint : {endpoint.base_url}")
    print(f"Model    : {endpoint.model}")

    client = OpenAICompatibleClient(
        endpoint
    )

    try:
        models_response = client.models()

        live_model = find_live_model(
            models_response,
            endpoint.model,
        )

        if live_model is None:
            raise RuntimeError(
                f"Model '{endpoint.model}' "
                "not advertised by endpoint"
            )

        max_model_len = live_model.get(
            "max_model_len"
        )

        print(
            f"Context  : {max_model_len}"
        )

        started = time.perf_counter()

        response = client.chat(
            messages=[
                {
                    "role": "system",
                    "content":
                        task.system_prompt,
                },
                {
                    "role": "user",
                    "content":
                        task.user_prompt,
                },
            ],
            temperature=task.temperature,
            max_tokens=task.max_output_tokens,
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000
        )

        choice = (
            response.get("choices", [{}])[0]
        )

        response_text = (
            choice
            .get("message", {})
            .get("content", "")
            .strip()
        )

        usage_raw = response.get(
            "usage",
            {},
        )

        prompt_details = usage_raw.get(
            "prompt_tokens_details",
            {},
        )

        expected = task.expected

        exact_match = (
            response_text
            == expected.exact_text
            if expected.exact_text
            is not None
            else None
        )

        substring_match = all(
            value in response_text
            for value
            in expected.required_substrings
        )

        passed = (
            exact_match is not False
            and substring_match
        )

        result = BenchmarkResult(
            task_id=task.id,

            endpoint_name=endpoint.name,
            endpoint_url=endpoint.base_url,
            model=endpoint.model,

            advertised_context_limit=
                max_model_len,

            status=(
                "PASS"
                if passed
                else "FAIL"
            ),

            response_text=response_text,

            exact_match=exact_match,

            required_substrings_match=
                substring_match,

            latency_ms=latency_ms,

            usage=UsageRecord(
                prompt_tokens=
                    usage_raw.get(
                        "prompt_tokens"
                    ),

                completion_tokens=
                    usage_raw.get(
                        "completion_tokens"
                    ),

                total_tokens=
                    usage_raw.get(
                        "total_tokens"
                    ),

                cached_tokens=
                    prompt_details.get(
                        "cached_tokens"
                    ),
            ),

            finish_reason=choice.get(
                "finish_reason"
            ),

            raw_metadata={
                "configured_context_limit":
                    endpoint
                    .configured_context_limit
            },
        )

    except Exception as exc:
        result = BenchmarkResult(
            task_id=task.id,

            endpoint_name=endpoint.name,
            endpoint_url=endpoint.base_url,
            model=endpoint.model,

            status="ERROR",

            error=str(exc),
        )

    finally:
        client.close()

    RESULT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )

    result_path = (
        RESULT_DIR
        / f"{task.id}-{timestamp}.json"
    )

    result_path.write_text(
        json.dumps(
            result.model_dump(),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("Result:")
    print(
        json.dumps(
            result.model_dump(),
            indent=2,
        )
    )

    print()
    print(
        f"Saved: {result_path}"
    )

    if result.status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
