"""2E-0.7C1: read-only synthetic-target application preflight; NO source writes.

This module refuses a missing/rejected decision, mismatched evidence, changed
local principal, changed target Git commit, dirty or symlinked target, and any
path beyond one run-scoped application_workspace. It does not grant a fresh
application authorization; that is a separate future implementation.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from benchmark_runner import agentic_workflow_v03 as fixture
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner import operator_decisions_v07b as decisions
from benchmark_runner import operator_review_v07a as review
from benchmark_runner.durable_runtime_v04 import TransitionError

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWLIST = ("app.py", "web.py", "verify.py", "README.md")


def _git(target: Path, *args: str, raw: bool = False) -> str | bytes:
    # Read-only Git, with optional index locking disabled; never execute hooks,
    # fsmonitor or user-global Git configuration in this inspection path.
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
             "-C", str(target), *args],
            capture_output=True, timeout=20, check=True, env=env,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise TransitionError("Target Git inspection failed") from exc
    return result.stdout if raw else result.stdout.decode("utf-8", "strict").strip()


def _target_path(run_id: str, target: Path, run_base: Path) -> Path:
    ps = bridge.paths(run_id, run_base)
    expected = ps["folder"] / "application_workspace"
    supplied = Path(target)
    if ".." in supplied.parts or supplied.is_symlink() or expected.is_symlink():
        raise TransitionError("Unsafe application target path")
    if supplied.absolute() != expected.absolute():
        raise TransitionError("Only the isolated run application_workspace is allowlisted")
    for parent in (run_base, ps["folder"], expected, expected / ".git"):
        if parent.is_symlink():
            raise TransitionError("Symlinked application path forbidden")
    if not expected.is_dir() or not (expected / ".git").is_dir():
        raise TransitionError("Pre-provisioned independent synthetic Git clone required")
    if expected.stat().st_uid != os.getuid():
        raise TransitionError("Target owner differs from invoking OS principal")
    return expected


def preflight(run_id: str, *, target: Path,
              expected_candidate_sha256: str,
              expected_verification_sha256: str,
              expected_decision_receipt_sha256: str,
              decision_db: Path = decisions.DECISION_DB,
              queue_db: Path = worker.BASE / "jobs.sqlite3",
              run_base: Path = bridge.BASE) -> dict[str, Any]:
    """Preview only. NO application authorization, filesystem writes or network calls."""
    bridge.validate_run_id(run_id)
    if not all(isinstance(v, str) and _SHA.fullmatch(v) for v in (
        expected_candidate_sha256, expected_verification_sha256,
        expected_decision_receipt_sha256,
    )):
        raise TransitionError("Explicit reviewed candidate, verification and decision SHA-256 required")

    who = decisions.principal()
    record = decisions.inspect(run_id, db_file=decision_db)["decision"]
    if record is None or record["decision"] != "APPROVE":
        raise TransitionError("Application preflight requires committed APPROVE decision")
    if record["receipt_sha256"] != expected_decision_receipt_sha256:
        raise TransitionError("Decision receipt changed since operator review")
    if (record["principal_uid"] != who["uid"]
            or record["principal_name"] != who["name"]
            or record["identity_assurance"] != "local_os_account_only"):
        raise TransitionError("Applying principal differs from approving OS account")

    proof = decisions._eligible(  # Re-check CURRENT durable state and all artifacts.
        run_id, expected_candidate_sha256=expected_candidate_sha256,
        expected_verification_sha256=expected_verification_sha256,
        queue_db=queue_db, run_base=run_base,
    )
    for key in ("scope", "candidate_sha256", "diff_sha256", "fixture_commit",
                "verification_artifact_sha256", "review_artifact_sha256",
                "approval_boundary"):
        if record[key] != proof[key]:
            raise TransitionError("Decision and current durable evidence disagree")
    if record["scope"] != review.SCOPE:
        raise TransitionError("Production and arbitrary targets unsupported")

    destination = _target_path(run_id, target, run_base)
    toplevel = _git(destination, "rev-parse", "--show-toplevel")
    if Path(toplevel).resolve(strict=True) != destination.resolve(strict=True):
        raise TransitionError("Target must be its own independent Git repository root")
    commit = _git(destination, "rev-parse", "HEAD")
    if not _GIT_SHA.fullmatch(commit) or commit != record["fixture_commit"]:
        raise TransitionError("Target commit differs from reviewed fixture commit")
    if _git(destination, "status", "--porcelain=v1", "--untracked-files=all"):
        raise TransitionError("Target has uncommitted or untracked changes")
    tracked = _git(destination, "ls-files", "--cached").splitlines()
    if sorted(tracked) != sorted(_ALLOWLIST):
        raise TransitionError("Target file inventory differs from synthetic fixture")
    for name in _ALLOWLIST:
        path = destination / name
        if path.is_symlink() or not path.is_file():
            raise TransitionError("Target contains missing/symlinked fixture file")
        committed = _git(destination, "show", f"HEAD:{name}", raw=True)
        if path.read_bytes() != committed:
            raise TransitionError("Target file differs from Git snapshot")
    if (destination / "app.py").read_bytes() != fixture.APP_VULNERABLE.encode("utf-8"):
        raise TransitionError("Target is not the known vulnerable synthetic app.py")
    # Never print candidate source, justification, free-text model review or credentials.
    return {
        "result": "APPLICATION_PREFLIGHT_ELIGIBLE",
        "run_id": run_id, "scope": review.SCOPE,
        "target": str(destination.absolute()), "target_git_commit": commit,
        "target_file": "app.py", "candidate_sha256": proof["candidate_sha256"],
        "verification_artifact_sha256": proof["verification_artifact_sha256"],
        "decision_receipt_sha256": record["receipt_sha256"],
        "operator": who,
        "application_authorized": False,
        "applies_code": False,
        "limitation": "Separate application authorization and source mutation NOT implemented in 0.7C1",
    }
