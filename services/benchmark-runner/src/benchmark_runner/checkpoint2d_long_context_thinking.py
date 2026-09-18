from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .distributed_reasoning_suite import execute_scenario
from .distributed_suite_scenarios import SCENARIOS
from .token_counter import TokenCounter


SCENARIO_ID = "C-insufficient"

PROFILES = (
    "64k",
    "96k",
    "128k",
)

OUTPUT_BUDGET = 4096

RESULT_ROOT = (
    PROJECT_ROOT
    / "benchmarks/results/checkpoint2d/"
      "long-context-thinking"
)


def summarize(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = []

    for result in results:
        rows.append(
            {
                "profile":
                    result.get("profile_name"),

                "expected_verdict":
                    result.get("expected_verdict"),

                "actual_verdict":
                    result.get("actual_verdict"),

                "verdict_correct":
                    result.get("verdict_correct"),

                "semantic_reasoning_pass":
                    result.get(
                        "semantic_reasoning_pass"
                    ),

                "provenance_contract_pass":
                    result.get(
                        "provenance_contract_pass"
                    ),

                "infrastructure_contract_pass":
                    result.get(
                        "infrastructure_contract_pass"
                    ),

                "generation_complete":
                    result.get(
                        "generation_complete"
                    ),

                "finish_reason":
                    result.get(
                        "finish_reason"
                    ),

                "actual_prompt_tokens":
                    result.get(
                        "actual_prompt_tokens"
                    ),

                "completion_tokens":
                    result.get(
                        "completion_tokens"
                    ),

                "reasoning_tokens":
                    result.get(
                        "reasoning_tokens"
                    ),

                "cached_tokens":
                    result.get(
                        "cached_tokens"
                    ),

                "latency_ms":
                    result.get(
                        "latency_ms"
                    ),

                "actual_uncertainty_evidence_ids":
                    result.get(
                        "actual_uncertainty_evidence_ids"
                    ),

                "parse_error":
                    result.get(
                        "parse_error"
                    ),
            }
        )

    completed = sum(
        bool(r.get("generation_complete"))
        for r in results
    )

    verdict_correct = sum(
        bool(r.get("verdict_correct"))
        for r in results
    )

    semantic_pass = sum(
        bool(r.get("semantic_reasoning_pass"))
        for r in results
    )

    return {
        "checkpoint": "2D-A",
        "experiment":
            "raw-long-context-thinking-on",

        "scenario":
            SCENARIO_ID,

        "thinking_mode":
            "on",

        "enable_thinking":
            True,

        "max_output_tokens":
            OUTPUT_BUDGET,

        "cases":
            len(results),

        "generation_completed":
            completed,

        "verdict_correct":
            verdict_correct,

        "semantic_reasoning_passed":
            semantic_pass,

        "profiles":
            rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-id",
        required=True,
    )

    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=PROFILES,
        default=list(PROFILES),
    )

    args = parser.parse_args()

    run_dir = (
        RESULT_ROOT
        / args.run_id
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    endpoint = gemma_endpoint()

    client = OpenAICompatibleClient(
        endpoint
    )

    counter = TokenCounter(
        endpoint
    )

    scenario = SCENARIOS[
        SCENARIO_ID
    ]

    try:
        total = len(args.profiles)

        for index, profile in enumerate(
            args.profiles,
            start=1,
        ):
            result_path = (
                run_dir
                / f"{profile}.json"
            )

            if result_path.exists():
                print(
                    f"[{index}/{total}] "
                    f"SKIP {profile}"
                )
                continue

            print()
            print("=" * 76)
            print(
                f"[{index}/{total}] "
                f"{SCENARIO_ID} "
                f"{profile.upper()} "
                f"THINKING ON"
            )
            print("=" * 76)

            result = execute_scenario(
                scenario=scenario,
                counter=counter,
                client=client,
                profile_name=profile,
                enable_thinking=True,
                max_output_tokens=
                    OUTPUT_BUDGET,
            )

            # Explicit experiment metadata.
            result["checkpoint"] = "2D-A"
            result["run_id"] = args.run_id
            result["experiment"] = (
                "raw-long-context-thinking-on"
            )
            result["profile_name"] = profile

            # Never persist private reasoning text.
            result.pop(
                "reasoning_content",
                None,
            )

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
                        "profile":
                            profile,

                        "expected_verdict":
                            result.get(
                                "expected_verdict"
                            ),

                        "actual_verdict":
                            result.get(
                                "actual_verdict"
                            ),

                        "verdict_correct":
                            result.get(
                                "verdict_correct"
                            ),

                        "semantic_reasoning_pass":
                            result.get(
                                "semantic_reasoning_pass"
                            ),

                        "provenance_contract_pass":
                            result.get(
                                "provenance_contract_pass"
                            ),

                        "generation_complete":
                            result.get(
                                "generation_complete"
                            ),

                        "finish_reason":
                            result.get(
                                "finish_reason"
                            ),

                        "actual_prompt_tokens":
                            result.get(
                                "actual_prompt_tokens"
                            ),

                        "completion_tokens":
                            result.get(
                                "completion_tokens"
                            ),

                        "reasoning_tokens":
                            result.get(
                                "reasoning_tokens"
                            ),

                        "latency_ms":
                            result.get(
                                "latency_ms"
                            ),

                        "uncertainty_ids":
                            result.get(
                                "actual_uncertainty_evidence_ids"
                            ),

                        "parse_error":
                            result.get(
                                "parse_error"
                            ),
                    },
                    indent=2,
                )
            )

            # Rebuild summary after every
            # completed profile.
            results = []

            for path in sorted(
                run_dir.glob("*.json")
            ):
                if path.name == "summary.json":
                    continue

                results.append(
                    json.loads(
                        path.read_text(
                            encoding="utf-8"
                        )
                    )
                )

            (
                run_dir
                / "summary.json"
            ).write_text(
                json.dumps(
                    summarize(results),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        results = []

        for path in sorted(
            run_dir.glob("*.json")
        ):
            if path.name == "summary.json":
                continue

            results.append(
                json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )
            )

        summary = summarize(
            results
        )

        print()
        print("=" * 76)
        print(
            "CHECKPOINT 2D-A "
            "LONG-CONTEXT THINKING SUMMARY"
        )
        print("=" * 76)
        print(
            json.dumps(
                summary,
                indent=2,
            )
        )

    finally:
        counter.close()
        client.close()


if __name__ == "__main__":
    main()
