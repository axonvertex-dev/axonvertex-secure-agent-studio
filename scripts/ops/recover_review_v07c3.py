#!/usr/bin/env python3
"""Operator-authorized, versioned Node C citation-review retry (controlled fixture only).

Default is a dry run. --apply queues ONE additional Node C review attempt; it
never directly invokes a model or authorizes a candidate patch/application.
Run locally from repo root as the intended OS account, not as root.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/benchmark-runner/src"))

from benchmark_runner import review_recovery_v07c3 as retry
from benchmark_runner.durable_runtime_v04 import TransitionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-rejected-review-sha256", required=True)
    parser.add_argument("--reason-code", required=True, choices=(retry.REASON,))
    parser.add_argument("--apply", action="store_true", help="Queue a single versioned review retry")
    args = parser.parse_args(argv)
    try:
        result = retry.recover(args.run_id, args.expected_rejected_review_sha256, apply=args.apply)
    except (TransitionError, RuntimeError, OSError, sqlite3.Error, KeyError, TypeError, ValueError):
        print("REVIEW_RECOVERY_REFUSED: INVALID_QUARANTINE_OR_CHANGED_EVIDENCE", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
