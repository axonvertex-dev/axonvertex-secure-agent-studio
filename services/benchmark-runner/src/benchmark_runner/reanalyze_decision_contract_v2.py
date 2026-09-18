from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT


CONTRACT_PATH = (
    PROJECT_ROOT
    / "benchmarks"
    / "contracts"
    / "distributed-evidence-contract-v2.json"
)

BASELINE_DIR = (
    PROJECT_ROOT
    / "benchmarks"
    / "results"
    / "checkpoint2c"
    / "checkpoint2c-baseline-v1"
)

COMPACTION_DIR = (
    PROJECT_ROOT
    / "benchmarks"
    / "results"
    / "checkpoint2c3"
    / "checkpoint2c3-compaction-v1"
)

REPORT_PATH = (
    PROJECT_ROOT
    / "benchmarks"
    / "reports"
    / "checkpoint2c-decision-contract-v2-analysis.json"
)


def ids(data: dict[str, Any], key: str) -> set[str]:
    return set(data.get(key) or [])


def analyze(
    data: dict[str, Any],
    contract: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    scenario_id = data["scenario_id"]
    c = contract["scenarios"][scenario_id]

    support = ids(data, "actual_evidence_ids")
    counter = ids(data, "actual_counter_evidence_ids")
    uncertainty = ids(
        data,
        "actual_uncertainty_evidence_ids",
    )

    actual_all = support | counter | uncertainty

    required_support = set(
        c["decision_required_support"]
    )
    required_counter = set(
        c["decision_required_counter"]
    )
    required_uncertainty = set(
        c["decision_required_uncertainty"]
    )

    allowed_support = set(
        c["decision_allowed_support"]
    )
    allowed_counter = set(
        c["decision_allowed_counter"]
    )
    allowed_uncertainty = set(
        c["decision_allowed_uncertainty"]
    )

    audit_relevant = set(
        c["audit_relevant_evidence"]
    )

    verdict_ok = (
        data.get("actual_verdict")
        == c["expected_verdict"]
    )

    support_ok = required_support <= support
    counter_ok = required_counter <= counter
    uncertainty_ok = (
        required_uncertainty <= uncertainty
    )

    allowed_only = (
        support <= allowed_support
        and counter <= allowed_counter
        and uncertainty <= allowed_uncertainty
    )

    disjoint = (
        support.isdisjoint(counter)
        and support.isdisjoint(uncertainty)
        and counter.isdisjoint(uncertainty)
    )

    decision_sufficiency_pass = all([
        verdict_ok,
        support_ok,
        counter_ok,
        uncertainty_ok,
        allowed_only,
        disjoint,
    ])

    model_audit_citation_complete = (
        audit_relevant <= actual_all
    )

    missing_audit_citations = sorted(
        audit_relevant - actual_all
    )

    return {
        "source": source,
        "profile": (
            data.get("profile")
            or data.get("source_profile")
        ),
        "scenario_id": scenario_id,
        "expected_verdict": c["expected_verdict"],
        "actual_verdict": data.get("actual_verdict"),
        "verdict_correct": verdict_ok,
        "decision_support_complete": support_ok,
        "decision_counter_complete": counter_ok,
        "decision_uncertainty_complete": uncertainty_ok,
        "decision_sufficiency_pass":
            decision_sufficiency_pass,
        "model_audit_citation_complete":
            model_audit_citation_complete,
        "missing_audit_citations":
            missing_audit_citations,
        "actual_support": sorted(support),
        "actual_counter": sorted(counter),
        "actual_uncertainty": sorted(uncertainty),
    }


def load_cases(
    directory: Path,
    contract: dict[str, Any],
    source: str,
) -> list[dict[str, Any]]:
    results = []

    for path in sorted(directory.glob("*__*.json")):
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
        results.append(
            analyze(data, contract, source)
        )

    return results


def summarize(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "total": len(cases),
        "decision_sufficiency_passed": sum(
            c["decision_sufficiency_pass"]
            for c in cases
        ),
        "decision_sufficiency_failed": sum(
            not c["decision_sufficiency_pass"]
            for c in cases
        ),
        "model_audit_citation_complete": sum(
            c["model_audit_citation_complete"]
            for c in cases
        ),
        "model_audit_citation_incomplete": sum(
            not c["model_audit_citation_complete"]
            for c in cases
        ),
    }


def main() -> None:
    contract = json.loads(
        CONTRACT_PATH.read_text(
            encoding="utf-8"
        )
    )

    baseline = load_cases(
        BASELINE_DIR,
        contract,
        "checkpoint2c-baseline-v1",
    )

    compaction = load_cases(
        COMPACTION_DIR,
        contract,
        "checkpoint2c3-compaction-v1",
    )

    report = {
        "schema_version":
            "decision-contract-v2-analysis.v1",
        "note":
            "Historical benchmark results are unchanged. "
            "This report applies a second, explicitly "
            "separated causal-decision rubric.",
        "baseline": {
            "summary": summarize(baseline),
            "cases": baseline,
        },
        "compaction": {
            "summary": summarize(compaction),
            "cases": compaction,
        },
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print("BASELINE")
    print(
        json.dumps(
            report["baseline"]["summary"],
            indent=2,
        )
    )

    print()
    print("COMPACTION")
    print(
        json.dumps(
            report["compaction"]["summary"],
            indent=2,
        )
    )

    print()
    print("CASES")

    for case in baseline:
        print(
            "RAW",
            case["profile"],
            case["scenario_id"],
            "DECISION="
            + (
                "PASS"
                if case["decision_sufficiency_pass"]
                else "FAIL"
            ),
            "AUDIT_CITATION="
            + (
                "COMPLETE"
                if case["model_audit_citation_complete"]
                else "INCOMPLETE"
            ),
            "MISSING=",
            case["missing_audit_citations"],
        )

    for case in compaction:
        print(
            "COMPACT",
            case["profile"],
            case["scenario_id"],
            "DECISION="
            + (
                "PASS"
                if case["decision_sufficiency_pass"]
                else "FAIL"
            ),
            "AUDIT_CITATION="
            + (
                "COMPLETE"
                if case["model_audit_citation_complete"]
                else "INCOMPLETE"
            ),
            "MISSING=",
            case["missing_audit_citations"],
        )


if __name__ == "__main__":
    main()
