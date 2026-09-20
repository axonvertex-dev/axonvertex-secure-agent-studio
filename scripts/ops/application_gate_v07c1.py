#!/usr/bin/env python3
"""Read-only, synthetic-fixture-only application preflight; does NOT apply code."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/benchmark-runner/src"))
from benchmark_runner import application_gate_v07c1 as gate
from benchmark_runner.durable_runtime_v04 import TransitionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-verification-sha256", required=True)
    parser.add_argument("--expected-decision-receipt-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        output = gate.preflight(args.run_id, target=args.target,
            expected_candidate_sha256=args.expected_candidate_sha256,
            expected_verification_sha256=args.expected_verification_sha256,
            expected_decision_receipt_sha256=args.expected_decision_receipt_sha256)
    except (TransitionError, ValueError, OSError, sqlite3.Error):
        print("APPLICATION_PREFLIGHT_REFUSED: IDENTITY_DECISION_EVIDENCE_OR_TARGET", file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
