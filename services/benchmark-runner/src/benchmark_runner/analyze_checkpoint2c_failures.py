from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT


RUN_DIR = (
    PROJECT_ROOT
    / "benchmarks"
    / "results"
    / "checkpoint2c"
    / "checkpoint2c-baseline-v1"
)

REPORT_JSON = (
    PROJECT_ROOT
    / "benchmarks"
    / "reports"
    / "checkpoint2c-failure-analysis.json"
)

REPORT_MD = (
    PROJECT_ROOT
    / "docs"
    / "benchmarks"
    / "checkpoint2c-failure-analysis.md"
)


def first_set(
    data: dict[str, Any],
    *keys: str,
) -> set[str]:
    """
    Read the first evidence-list field present.

    Checkpoint 2C spans two closely related result-schema
    generations, so preserve compatibility with both
    `required_*` and earlier `expected_*` names.
    """
    for key in keys:
        if key in data:
            value = data.get(key)

            if value is None:
                return set()

            if not isinstance(value, list):
                raise TypeError(
                    f"{key} must be a list, "
                    f"got {type(value).__name__}"
                )

            return {
                str(item)
                for item in value
            }

    return set()


def analyze_case(
    data: dict[str, Any],
) -> dict[str, Any]:
    required_support = first_set(
        data,
        "required_evidence_ids",
        "expected_evidence_ids",
    )

    actual_support = first_set(
        data,
        "actual_evidence_ids",
    )

    required_counter = first_set(
        data,
        "required_counter_evidence_ids",
        "expected_counter_evidence_ids",
    )

    actual_counter = first_set(
        data,
        "actual_counter_evidence_ids",
    )

    required_uncertainty = first_set(
        data,
        "required_uncertainty_evidence_ids",
        "expected_uncertainty_evidence_ids",
    )

    actual_uncertainty = first_set(
        data,
        "actual_uncertainty_evidence_ids",
    )

    missing_support = (
        required_support
        - actual_support
    )

    missing_counter = (
        required_counter
        - actual_counter
    )

    missing_uncertainty = (
        required_uncertainty
        - actual_uncertainty
    )

    failure_classes: list[str] = []

    if not data.get(
        "infrastructure_contract_pass",
        False,
    ):
        failure_classes.append(
            "INFRASTRUCTURE_FAILURE"
        )

    if (
        missing_support
        or missing_counter
        or missing_uncertainty
    ):
        failure_classes.append(
            "MISSING_REQUIRED_PROVENANCE"
        )

    if not data.get(
        "provenance_contract_pass",
        False,
    ):
        failure_classes.append(
            "PROVENANCE_CONTRACT_FAILURE"
        )

    if not data.get(
        "semantic_reasoning_pass",
        False,
    ):
        failure_classes.append(
            "SEMANTIC_VERDICT_FAILURE"
        )

    trace_verdict_contradiction = (
        data.get("expected_verdict")
        == "INSUFFICIENT_EVIDENCE"
        and data.get("actual_verdict")
        != "INSUFFICIENT_EVIDENCE"
        and bool(actual_uncertainty)
    )

    if trace_verdict_contradiction:
        failure_classes.append(
            "TRACE_VERDICT_CONTRADICTION"
        )

    return {
        "profile":
            data.get("profile"),

        "scenario_id":
            data.get("scenario_id"),

        "status":
            data.get("status"),

        "expected_verdict":
            data.get("expected_verdict"),

        "actual_verdict":
            data.get("actual_verdict"),

        "semantic_reasoning_pass":
            data.get(
                "semantic_reasoning_pass"
            ),

        "provenance_contract_pass":
            data.get(
                "provenance_contract_pass"
            ),

        "infrastructure_contract_pass":
            data.get(
                "infrastructure_contract_pass"
            ),

        "required_supporting_evidence":
            sorted(required_support),

        "actual_supporting_evidence":
            sorted(actual_support),

        "missing_supporting_evidence":
            sorted(missing_support),

        "required_counter_evidence":
            sorted(required_counter),

        "actual_counter_evidence":
            sorted(actual_counter),

        "missing_counter_evidence":
            sorted(missing_counter),

        "required_uncertainty_evidence":
            sorted(required_uncertainty),

        "actual_uncertainty_evidence":
            sorted(actual_uncertainty),

        "missing_uncertainty_evidence":
            sorted(missing_uncertainty),

        "failure_classes":
            failure_classes,

        "trace_verdict_contradiction":
            trace_verdict_contradiction,

        "prompt_tokens":
            data.get(
                "actual_prompt_tokens"
            ),

        "latency_ms":
            data.get(
                "latency_ms"
            ),
    }


def main() -> None:
    paths = sorted(
        RUN_DIR.glob("*__*.json")
    )

    if len(paths) != 12:
        raise RuntimeError(
            f"Expected 12 Checkpoint 2C case files, "
            f"found {len(paths)}"
        )

    cases = []

    for path in paths:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        cases.append(
            analyze_case(data)
        )

    failures = [
        case
        for case in cases
        if case["status"] != "PASS"
    ]

    class_counts = Counter(
        failure_class
        for case in failures
        for failure_class
        in case["failure_classes"]
    )

    missing_ids = Counter()

    for case in failures:
        for key in (
            "missing_supporting_evidence",
            "missing_counter_evidence",
            "missing_uncertainty_evidence",
        ):
            for evidence_id in case[key]:
                missing_ids[evidence_id] += 1

    report = {
        "schema_version":
            "checkpoint2c-failure-analysis.v2",

        "checkpoint":
            "2C.1",

        "source_run":
            "checkpoint2c-baseline-v1",

        "total_cases":
            len(cases),

        "passed":
            sum(
                c["status"] == "PASS"
                for c in cases
            ),

        "failed":
            len(failures),

        "failure_class_counts":
            dict(class_counts),

        "missing_evidence_frequency":
            dict(missing_ids),

        "failed_cases":
            failures,
    }

    REPORT_JSON.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_MD.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_JSON.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Checkpoint 2C.1 — Failure Characterization",
        "",
        "## Baseline",
        "",
        f"- Total cases: {len(cases)}",
        f"- PASS: {report['passed']}",
        f"- FAIL: {report['failed']}",
        "",
        "## Failure classes",
        "",
    ]

    for key, value in sorted(
        class_counts.items()
    ):
        lines.append(
            f"- `{key}`: {value}"
        )

    lines += [
        "",
        "## Missing required evidence",
        "",
    ]

    if missing_ids:
        for key, value in sorted(
            missing_ids.items()
        ):
            lines.append(
                f"- `{key}` omitted in "
                f"{value} failed case(s)"
            )
    else:
        lines.append(
            "- No required evidence omissions."
        )

    lines += [
        "",
        "## Failed cases",
        "",
        "| Profile | Scenario | Expected | Actual | "
        "Failure classes | Missing required evidence |",
        "|---|---|---|---|---|---|",
    ]

    for case in failures:
        missing = (
            case["missing_supporting_evidence"]
            + case["missing_counter_evidence"]
            + case["missing_uncertainty_evidence"]
        )

        lines.append(
            "| {profile} | {scenario} | {expected} | "
            "{actual} | {classes} | {missing} |".format(
                profile=case["profile"],
                scenario=case["scenario_id"],
                expected=case[
                    "expected_verdict"
                ],
                actual=case[
                    "actual_verdict"
                ],
                classes=", ".join(
                    case["failure_classes"]
                ),
                missing=(
                    ", ".join(missing)
                    if missing
                    else "—"
                ),
            )
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "The baseline exposes two distinct long-context "
        "degradation modes:",
        "",
        "1. **Provenance coverage degradation.** "
        "The verdict remains semantically correct, "
        "but required corroborating evidence is omitted.",
        "",
        "2. **Trace/verdict inconsistency.** "
        "The model explicitly surfaces uncertainty evidence "
        "but reaches a verdict that assumes the unresolved "
        "causal link is known.",
        "",
        "These modes should be evaluated separately before "
        "changing reasoning effort, compaction, or routing.",
        "",
    ]

    REPORT_MD.write_text(
        "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status":
                    "PASS",

                "cases":
                    len(cases),

                "failures":
                    len(failures),

                "failure_class_counts":
                    dict(class_counts),

                "missing_evidence_frequency":
                    dict(missing_ids),

                "json_report":
                    str(REPORT_JSON),

                "markdown_report":
                    str(REPORT_MD),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
