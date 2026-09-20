#!/usr/bin/env python3
"""Local synthetic-only operator application authorization and execution CLI."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/benchmark-runner/src"))
from benchmark_runner import application_execution_v07c2 as execution
from benchmark_runner.durable_runtime_v04 import TransitionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("authorize", "execute", "reconcile", "inspect"):
        p = sub.add_parser(name)
        p.add_argument("--run-id", required=True)
        if name != "inspect":
            p.add_argument("--target", type=Path, required=True)
            p.add_argument("--request-id", required=True)
        if name == "authorize":
            p.add_argument("--expected-candidate-sha256", required=True)
            p.add_argument("--expected-verification-sha256", required=True)
            p.add_argument("--expected-decision-receipt-sha256", required=True)
            p.add_argument("--expected-target-commit", required=True)
            p.add_argument("--record-authorization", action="store_true")
        if name in ("execute", "reconcile"):
            p.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            output = execution.inspect(args.run_id)
        elif args.command == "authorize":
            output = execution.authorize(args.run_id, target=args.target,
                expected_candidate_sha256=args.expected_candidate_sha256,
                expected_verification_sha256=args.expected_verification_sha256,
                expected_decision_receipt_sha256=args.expected_decision_receipt_sha256,
                expected_target_commit=args.expected_target_commit,
                request_id=args.request_id, record=args.record_authorization)
        elif args.command == "execute":
            output = execution.execute(args.run_id, target=args.target,
                request_id=args.request_id, apply=args.apply)
        else:
            output = execution.reconcile(args.run_id, target=args.target,
                request_id=args.request_id, apply=args.apply)
    except (TransitionError, ValueError, OSError, sqlite3.Error, RuntimeError):
        print("APPLICATION_OPERATION_REFUSED_OR_HELD: INSPECT_STATE_AND_EVIDENCE", file=sys.stderr)
        return 2
    if args.command == "inspect" and output["application"] is not None:
        # Operator private record may include local path but no model outputs.
        pass
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
