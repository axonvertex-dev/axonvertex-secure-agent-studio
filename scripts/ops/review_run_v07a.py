#!/usr/bin/env python3
"""Local operator review (READ ONLY). Run from the Secure Agent Studio repo root.

Use --include-content only when intentionally displaying candidate source,
patch and untrusted model review summary in your terminal. Never paste .env.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/benchmark-runner/src"))
from benchmark_runner.operator_review_v07a import project
from benchmark_runner.durable_runtime_v04 import TransitionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--include-content", action="store_true",
                        help="Show candidate source, unified diff and model review summary locally")
    args = parser.parse_args(argv)
    try:
        result = project(args.run_id, include_content=args.include_content)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (TransitionError, OSError, ValueError, KeyError, TypeError, sqlite3.Error,
            json.JSONDecodeError):
        # No private payloads, environment variables, DB paths, or raw errors.
        print("OPERATOR_REVIEW_REFUSED: INVALID_OR_UNAVAILABLE_EVIDENCE", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
