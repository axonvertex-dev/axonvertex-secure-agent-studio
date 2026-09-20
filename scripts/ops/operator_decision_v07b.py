#!/usr/bin/env python3
"""Local, fixture-only review decisions; no API approval or code application.

Commands:
  inspect --run-id RUN
  decide --run-id RUN --decision APPROVE|REJECT --reason-code REASON
      --expected-candidate-sha256 HEX --expected-verification-sha256 HEX
      --request-id UUID [--apply]

Justification is prompted interactively and never placed in shell history.
Do not treat an OS account shared by multiple humans as individual identity.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/benchmark-runner/src"))
from benchmark_runner import operator_decisions_v07b as decisions
from benchmark_runner.durable_runtime_v04 import TransitionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("inspect", help="Read a local decision, if present")
    show.add_argument("--run-id", required=True)
    write = sub.add_parser("decide", help="Preview or record exactly one operator decision")
    write.add_argument("--run-id", required=True)
    write.add_argument("--decision", choices=("APPROVE", "REJECT"), required=True)
    write.add_argument("--reason-code", required=True)
    write.add_argument("--expected-candidate-sha256", required=True)
    write.add_argument("--expected-verification-sha256", required=True)
    write.add_argument("--request-id", required=True)
    write.add_argument("--apply", action="store_true",
                       help="Record decision in separate local ledger; NEVER apply source")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            value = decisions.inspect(args.run_id)
        else:
            if not sys.stdin.isatty():
                raise TransitionError("Operator must enter justification in a local terminal")
            print("Scope: synthetic fixture. Approval will NOT apply the patch.", file=sys.stderr)
            justification = input("Justification (12–1024 chars): ")
            value = decisions.decide(args.run_id, decision=args.decision,
                reason_code=args.reason_code, justification=justification,
                request_id=args.request_id,
                expected_candidate_sha256=args.expected_candidate_sha256,
                expected_verification_sha256=args.expected_verification_sha256,
                apply=args.apply)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (TransitionError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        print("OPERATOR_DECISION_REFUSED: INVALID_STATE_IDENTITY_OR_EVIDENCE", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
