from __future__ import annotations

import json
import statistics
from pathlib import Path

from .config import PROJECT_ROOT


RUNS = {
    "32k": "20260917T193027Z",
    "64k": "20260917T193631Z",
    "96k": "20260917T195236Z",
    "128k": "20260917T185728Z",
}


def main() -> None:
    root = (
        PROJECT_ROOT
        / "benchmarks"
        / "results"
        / "checkpoint2"
    )

    rows = []
    all_cases = []

    for profile, run_id in RUNS.items():
        run_dir = root / run_id

        summary_path = (
            run_dir
            / "matrix-summary.json"
        )

        if not summary_path.exists():
            raise SystemExit(
                f"Missing summary: {summary_path}"
            )

        summary = json.loads(
            summary_path.read_text(
                encoding="utf-8"
            )
        )

        cases = summary["results"]

        if len(cases) != 5:
            raise RuntimeError(
                f"{profile}: expected 5 cases, "
                f"found {len(cases)}"
            )

        latencies = [
            case["latency_ms"]
            for case in cases
        ]

        passed = sum(
            case["status"] == "PASS"
            for case in cases
        )

        actual_prompts = sorted(
            {
                case["actual_prompt_tokens"]
                for case in cases
            }
        )

        cached = [
            case["cached_tokens"]
            for case in cases
        ]

        row = {
            "profile": profile,
            "run_id": run_id,
            "cases": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "actual_prompt_tokens":
                actual_prompts,
            "mean_latency_ms":
                round(
                    statistics.mean(
                        latencies
                    ),
                    1,
                ),
            "min_latency_ms":
                min(latencies),
            "max_latency_ms":
                max(latencies),
            "cached_tokens_total":
                sum(cached),
        }

        rows.append(row)

        for case in cases:
            all_cases.append(
                {
                    "profile": profile,
                    **case,
                }
            )

    total = len(all_cases)

    passed = sum(
        case["status"] == "PASS"
        for case in all_cases
    )

    aggregate = {
        "schema_version":
            "checkpoint2a-summary.v1",

        "benchmark":
            "single-fact-positional-retrieval",

        "protocol": {
            "cold_cache_before_every_case":
                True,
            "evidence_positions": [
                0.05,
                0.25,
                0.50,
                0.75,
                0.95,
            ],
            "output_reserve_tokens":
                4096,
            "safety_margin_tokens":
                512,
            "target_tolerance_tokens":
                128,
        },

        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "all_passed":
            passed == total,

        "profiles": rows,

        "cases": all_cases,

        "interpretation": {
            "supported":
                (
                    "Controlled single-fact positional "
                    "retrieval succeeded across all "
                    "tested context tiers and positions."
                ),

            "not_established": [
                "distributed-evidence reasoning",
                "repository-level reasoning",
                "security diagnosis quality",
                "optimal context budget",
                "multi-turn RLM performance",
            ],
        },
    }

    report_dir = (
        PROJECT_ROOT
        / "benchmarks"
        / "reports"
    )

    report_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        report_dir
        / "checkpoint2a-summary.json"
    )

    json_path.write_text(
        json.dumps(
            aggregate,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    md = [
        "# Checkpoint 2A — Long-Context Positional Retrieval",
        "",
        "## Result",
        "",
        f"**{passed}/{total} cases passed.**",
        "",
        "| Profile | Prompt tokens | Passed | Mean latency | Min | Max | Cached |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        prompts = ",".join(
            str(x)
            for x
            in row["actual_prompt_tokens"]
        )

        md.append(
            "| "
            f"{row['profile']} | "
            f"{prompts} | "
            f"{row['passed']}/{row['cases']} | "
            f"{row['mean_latency_ms'] / 1000:.1f}s | "
            f"{row['min_latency_ms'] / 1000:.1f}s | "
            f"{row['max_latency_ms'] / 1000:.1f}s | "
            f"{row['cached_tokens_total']} |"
        )

    md.extend(
        [
            "",
            "## Protocol",
            "",
            "- SGLang radix cache flushed before every case.",
            "- Evidence positions: 5%, 25%, 50%, 75%, 95%.",
            "- Output reserve: 4,096 tokens.",
            "- Construction safety margin: 512 tokens.",
            "- Prompt construction tolerance: ±128 tokens.",
            "- Server-side `/v1/messages/count_tokens` calibrated against actual `usage.prompt_tokens` with zero delta.",
            "",
            "## Supported conclusion",
            "",
            "Gemma 4 12B QAT on Node A successfully recovered a single authoritative fact across every tested evidence position at approximately 28K, 61K, 94K, and 126K prompt-token scales under controlled cold-cache conditions.",
            "",
            "## Not established by this benchmark",
            "",
            "- Distributed-evidence reasoning.",
            "- Cross-file or repository-level reasoning.",
            "- Security diagnosis quality.",
            "- Optimal context budget selection.",
            "- Recursive retrieval/RLM performance.",
            "",
            "## Observed performance anomaly",
            "",
            "The 64K and 96K 75%-position runs exhibited unusually high latency. Retrieval remained correct. The 128K cold-cache runs were comparatively uniform across positions, so no position-dependent compute conclusion is drawn from the anomaly.",
            "",
        ]
    )

    docs_path = (
        PROJECT_ROOT
        / "docs"
        / "benchmarks"
        / "checkpoint2a-long-context.md"
    )

    docs_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    docs_path.write_text(
        "\n".join(md),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status":
                    "PASS"
                    if passed == total
                    else "FAIL",
                "total_cases":
                    total,
                "passed":
                    passed,
                "failed":
                    total - passed,
                "json_report":
                    str(json_path),
                "markdown_report":
                    str(docs_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
