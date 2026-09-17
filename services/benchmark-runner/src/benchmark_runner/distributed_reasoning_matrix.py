from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import OpenAICompatibleClient
from .config import PROJECT_ROOT, gemma_endpoint
from .distributed_reasoning_suite import execute_scenario
from .distributed_suite_scenarios import SCENARIOS
from .token_counter import TokenCounter


DEFAULT_PROFILES = [
    "32k",
    "64k",
    "96k",
    "128k",
]


def write_summary(
    *,
    result_dir: Path,
    profiles: list[str],
    scenarios: list[str],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = sum(
        r["status"] == "PASS"
        for r in results
    )

    failed = sum(
        r["status"] != "PASS"
        for r in results
    )

    profile_summary: dict[str, Any] = {}

    for profile in profiles:
        subset = [
            r
            for r in results
            if r["profile"] == profile
        ]

        profile_summary[profile] = {
            "completed": len(subset),
            "passed": sum(
                r["status"] == "PASS"
                for r in subset
            ),
            "failed": sum(
                r["status"] != "PASS"
                for r in subset
            ),
        }

    scenario_summary: dict[str, Any] = {}

    for scenario in scenarios:
        subset = [
            r
            for r in results
            if r["scenario_id"] == scenario
        ]

        scenario_summary[scenario] = {
            "completed": len(subset),
            "passed": sum(
                r["status"] == "PASS"
                for r in subset
            ),
            "failed": sum(
                r["status"] != "PASS"
                for r in subset
            ),
        }

    expected_cases = (
        len(profiles) * len(scenarios)
    )

    summary = {
        "schema_version":
            "distributed-reasoning-matrix.v1",

        "checkpoint":
            "2C",

        "reasoning_effort":
            "default",

        "cache_policy":
            "cold-before-each-case",

        "profiles":
            profiles,

        "scenarios":
            scenarios,

        "expected_cases":
            expected_cases,

        "completed_cases":
            len(results),

        "passed":
            passed,

        "failed":
            failed,

        "complete":
            len(results) == expected_cases,

        "all_passed":
            (
                len(results) == expected_cases
                and failed == 0
            ),

        "profile_summary":
            profile_summary,

        "scenario_summary":
            scenario_summary,

        "results":
            results,
    }

    (
        result_dir
        / "matrix-summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=DEFAULT_PROFILES,
        default=DEFAULT_PROFILES,
    )

    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=sorted(SCENARIOS),
        default=list(SCENARIOS),
    )

    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Stable run directory name. "
            "Reuse it to resume an interrupted matrix."
        ),
    )

    args = parser.parse_args()

    run_id = (
        args.run_id
        or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
    )

    result_dir = (
        PROJECT_ROOT
        / "benchmarks"
        / "results"
        / "checkpoint2c"
        / run_id
    )

    result_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    endpoint = gemma_endpoint()

    counter = TokenCounter(endpoint)
    client = OpenAICompatibleClient(endpoint)

    results: list[dict[str, Any]] = []

    try:
        print(
            "=========================================================="
        )
        print(
            " AXONVERTEX Secure Agent Studio"
        )
        print(
            " Checkpoint 2C — Context-Scale Reasoning Matrix"
        )
        print(
            "=========================================================="
        )

        expected_cases = (
            len(args.profiles)
            * len(args.scenarios)
        )

        case_no = 0

        for profile in args.profiles:
            for scenario_name in args.scenarios:
                case_no += 1

                scenario = SCENARIOS[
                    scenario_name
                ]

                case_path = (
                    result_dir
                    / (
                        f"{profile}__"
                        f"{scenario_name}.json"
                    )
                )

                print()
                print("=" * 76)
                print(
                    f"CASE {case_no}/{expected_cases}"
                )
                print(
                    f"PROFILE  : {profile}"
                )
                print(
                    f"SCENARIO : {scenario_name}"
                )
                print(
                    f"EXPECTED : "
                    f"{scenario.expected_verdict}"
                )
                print("=" * 76)

                if case_path.exists():
                    result = json.loads(
                        case_path.read_text(
                            encoding="utf-8"
                        )
                    )

                    results.append(result)

                    print(
                        "RESUME: existing case result loaded"
                    )

                    print(
                        json.dumps(
                            {
                                "status":
                                    result["status"],
                                "profile":
                                    result["profile"],
                                "scenario":
                                    result["scenario_id"],
                            },
                            indent=2,
                        )
                    )

                    continue

                result = execute_scenario(
                    scenario=scenario,
                    counter=counter,
                    client=client,
                    profile_name=profile,
                )

                case_path.write_text(
                    json.dumps(
                        result,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                results.append(result)

                write_summary(
                    result_dir=result_dir,
                    profiles=args.profiles,
                    scenarios=args.scenarios,
                    results=results,
                )

                print(
                    json.dumps(
                        {
                            "status":
                                result["status"],

                            "profile":
                                result["profile"],

                            "scenario":
                                result["scenario_id"],

                            "expected_verdict":
                                result["expected_verdict"],

                            "actual_verdict":
                                result["actual_verdict"],

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

                            "prompt_tokens":
                                result[
                                    "actual_prompt_tokens"
                                ],

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
                                result["latency_ms"],
                        },
                        indent=2,
                    )
                )

        summary = write_summary(
            result_dir=result_dir,
            profiles=args.profiles,
            scenarios=args.scenarios,
            results=results,
        )

        print()
        print("=" * 76)
        print("CHECKPOINT 2C MATRIX SUMMARY")
        print("=" * 76)

        print(
            json.dumps(
                {
                    "run_id":
                        run_id,

                    "expected_cases":
                        summary["expected_cases"],

                    "completed_cases":
                        summary["completed_cases"],

                    "passed":
                        summary["passed"],

                    "failed":
                        summary["failed"],

                    "complete":
                        summary["complete"],

                    "all_passed":
                        summary["all_passed"],

                    "profile_summary":
                        summary[
                            "profile_summary"
                        ],

                    "results":
                        str(result_dir),
                },
                indent=2,
            )
        )

        if not summary["all_passed"]:
            raise SystemExit(1)

    finally:
        counter.close()
        client.close()


if __name__ == "__main__":
    main()
