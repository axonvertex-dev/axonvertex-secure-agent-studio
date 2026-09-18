from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from math_verify import parse, verify

from .config import PROJECT_ROOT
from .long_context_matrix import flush_sglang_cache


RAW_DATA = (
    PROJECT_ROOT
    / "benchmarks/datasets/math500/raw/test.jsonl"
)

MANIFEST = (
    PROJECT_ROOT
    / "benchmarks/datasets/math500/manifests/"
    "reasoning-effort-pilot-v1.json"
)

RESULT_ROOT = (
    PROJECT_ROOT
    / "benchmarks/results/checkpoint2d/math500"
)

MODES = ("off", "on")

SYSTEM_PROMPT = (
    "Solve the mathematics problem carefully. "
    "Return only the final answer enclosed in \\\\boxed{...}. "
    "Do not include an explanation in the final response."
)


def load_rows() -> dict[str, dict[str, Any]]:
    rows = {}

    for line in RAW_DATA.read_text(
        encoding="utf-8"
    ).splitlines():
        row = json.loads(line)
        rows[row["unique_id"]] = row

    return rows


def load_manifest_ids(
    limit: int,
    min_level: int | None = None,
) -> list[str]:
    data = json.loads(
        MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    examples = data["examples"]

    if min_level is not None:
        examples = [
            x
            for x in examples
            if int(x["level"]) >= min_level
        ]

    return [
        x["unique_id"]
        for x in examples[:limit]
    ]


def safe_id(
    unique_id: str,
) -> str:
    digest = hashlib.sha256(
        unique_id.encode()
    ).hexdigest()[:10]

    stem = (
        unique_id
        .replace("/", "__")
        .replace(".", "_")
    )

    return f"{stem}__{digest}"


def score_answer(
    *,
    reference_answer: str,
    model_response: str,
) -> tuple[bool, str | None]:
    try:
        gold = parse(
            f"${reference_answer}$"
        )

        prediction = parse(
            model_response
        )

        return (
            bool(verify(gold, prediction)),
            None,
        )

    except Exception as exc:
        return False, str(exc)


def make_summary(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    by_mode = {}

    for mode in MODES:
        subset = [
            r for r in results
            if r["thinking_mode"] == mode
        ]

        correct = sum(
            bool(r["correct"])
            for r in subset
        )

        completed = sum(
            bool(r["generation_complete"])
            for r in subset
        )

        truncated = sum(
            not bool(r["generation_complete"])
            for r in subset
        )

        reasoning = [
            r["reasoning_tokens"]
            for r in subset
            if isinstance(
                r["reasoning_tokens"],
                int,
            )
        ]

        latency = [
            r["latency_ms"]
            for r in subset
        ]

        completed_subset = [
            r for r in subset
            if r["generation_complete"]
        ]

        correct_completed = sum(
            bool(r["correct"])
            for r in completed_subset
        )

        by_mode[mode] = {
            "cases": len(subset),
            "generation_completed": completed,
            "generation_truncated": truncated,
            "correct": correct,
            "overall_success_rate": (
                correct / len(subset)
                if subset
                else None
            ),
            "accuracy_on_completed": (
                correct_completed
                / len(completed_subset)
                if completed_subset
                else None
            ),
            "mean_reasoning_tokens": (
                sum(reasoning) / len(reasoning)
                if reasoning
                else None
            ),
            "mean_latency_ms": (
                sum(latency) / len(latency)
                if latency
                else None
            ),
        }

    return {
        "checkpoint": "2D-B",
        "benchmark": "MATH-500",
        "experiment": "thinking-off-vs-on",
        "completed_cases": len(results),
        "by_mode": by_mode,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-id",
        required=True,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--min-level",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--modes",
        nargs="+",
        choices=MODES,
        default=list(MODES),
    )

    args = parser.parse_args()

    base = os.environ[
        "GEMMA_BASE_URL"
    ].rstrip("/")

    api_key = os.environ[
        "GEMMA_API_KEY"
    ]

    model = os.environ[
        "GEMMA_MODEL"
    ]

    rows = load_rows()
    selected_ids = load_manifest_ids(
        args.limit,
        min_level=args.min_level,
    )

    run_dir = (
        RESULT_ROOT
        / args.run_id
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timeout = float(
        os.environ.get(
            "BENCHMARK_HTTP_READ_TIMEOUT_SECONDS",
            "1800",
        )
    )

    client = httpx.Client(
        timeout=httpx.Timeout(
            timeout,
            connect=30,
        )
    )

    try:
        selected_modes = tuple(
            args.modes
        )

        total_expected = (
            len(selected_ids)
            * len(selected_modes)
        )

        completed = 0

        for unique_id in selected_ids:
            row = rows[unique_id]

            for mode in selected_modes:
                completed += 1

                filename = (
                    f"{safe_id(unique_id)}"
                    f"__{mode}.json"
                )

                result_path = (
                    run_dir / filename
                )

                if result_path.exists():
                    print(
                        f"[{completed}/{total_expected}] "
                        f"SKIP {mode:3s} "
                        f"{unique_id}"
                    )
                    continue

                print()
                print("=" * 76)
                print(
                    f"[{completed}/{total_expected}] "
                    f"{mode.upper()} "
                    f"{unique_id}"
                )
                print(
                    "subject:",
                    row["subject"],
                    "| level:",
                    row["level"],
                )
                print("=" * 76)

                flush_sglang_cache(
                    endpoint_url=base,
                )

                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content":
                                SYSTEM_PROMPT,
                        },
                        {
                            "role": "user",
                            "content":
                                row["problem"],
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 8192,
                    "chat_template_kwargs": {
                        "enable_thinking":
                            mode == "on",
                    },
                }

                started = (
                    time.perf_counter()
                )

                response = client.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization":
                            f"Bearer {api_key}",
                        "Content-Type":
                            "application/json",
                    },
                    json=payload,
                )

                latency_ms = round(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000
                )

                response.raise_for_status()

                data = response.json()

                choice = data["choices"][0]

                message = choice["message"]

                finish_reason = choice.get(
                    "finish_reason"
                )

                final_response = (
                    message
                    .get("content", "")
                    .strip()
                )

                usage = data.get(
                    "usage",
                    {},
                )

                prompt_details = (
                    usage.get(
                        "prompt_tokens_details"
                    )
                    or {}
                )

                completion_details = (
                    usage.get(
                        "completion_tokens_details"
                    )
                    or {}
                )

                reasoning_tokens = (
                    usage.get(
                        "reasoning_tokens"
                    )
                )

                if reasoning_tokens is None:
                    reasoning_tokens = (
                        completion_details.get(
                            "reasoning_tokens"
                        )
                    )

                correct, scoring_error = (
                    score_answer(
                        reference_answer=
                            row["answer"],
                        model_response=
                            final_response,
                    )
                )

                result = {
                    "schema_version":
                        "math500-thinking-mode.v1",

                    "checkpoint":
                        "2D-B",

                    "run_id":
                        args.run_id,

                    "unique_id":
                        unique_id,

                    "subject":
                        row["subject"],

                    "level":
                        row["level"],

                    "thinking_mode":
                        mode,

                    "enable_thinking":
                        mode == "on",

                    "correct":
                        correct,

                    "reference_answer":
                        row["answer"],

                    "model_final_response":
                        final_response,

                    "prompt_tokens":
                        usage.get(
                            "prompt_tokens"
                        ),

                    "completion_tokens":
                        usage.get(
                            "completion_tokens"
                        ),

                    "total_tokens":
                        usage.get(
                            "total_tokens"
                        ),

                    "reasoning_tokens":
                        reasoning_tokens,

                    "cached_tokens":
                        prompt_details.get(
                            "cached_tokens"
                        ),

                    "latency_ms":
                        latency_ms,

                    "finish_reason":
                        finish_reason,

                    "generation_complete":
                        (
                            finish_reason != "length"
                            and bool(final_response)
                        ),

                    "cold_cache":
                        True,

                    "scoring_error":
                        scoring_error,

                    "reasoning_content_present":
                        bool(
                            message.get(
                                "reasoning_content"
                            )
                            or message.get(
                                "reasoning"
                            )
                        )
                }

                result_path.write_text(
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
                            "correct":
                                correct,

                            "answer":
                                row["answer"],

                            "response":
                                final_response,

                            "reasoning_tokens":
                                reasoning_tokens,

                            "completion_tokens":
                                result[
                                    "completion_tokens"
                                ],

                            "cached_tokens":
                                result[
                                    "cached_tokens"
                                ],

                            "latency_ms":
                                latency_ms,

                            "finish_reason":
                                finish_reason,

                            "generation_complete":
                                result[
                                    "generation_complete"
                                ],

                            "scoring_error":
                                scoring_error,
                        },
                        indent=2,
                    )
                )

                # Rebuild summary after every case
                # so interrupted runs are resumable.
                results = []

                for p in sorted(
                    run_dir.glob(
                        "*.json"
                    )
                ):
                    if (
                        p.name
                        == "summary.json"
                    ):
                        continue

                    results.append(
                        json.loads(
                            p.read_text(
                                encoding="utf-8"
                            )
                        )
                    )

                (
                    run_dir
                    / "summary.json"
                ).write_text(
                    json.dumps(
                        make_summary(
                            results
                        ),
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

        results = []

        for p in sorted(
            run_dir.glob("*.json")
        ):
            if p.name == "summary.json":
                continue

            results.append(
                json.loads(
                    p.read_text(
                        encoding="utf-8"
                    )
                )
            )

        summary = make_summary(
            results
        )

        print()
        print("=" * 76)
        print(
            "CHECKPOINT 2D-B "
            "MATH-500 SUMMARY"
        )
        print("=" * 76)

        print(
            json.dumps(
                summary,
                indent=2,
            )
        )

    finally:
        client.close()


if __name__ == "__main__":
    main()
