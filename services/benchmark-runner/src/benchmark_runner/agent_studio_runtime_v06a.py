"""Checkpoint 2E-0.6A: stable fixture-scoped Agent Runtime front door and loopback API.

Routes to the proven v05C worker; does not replace/migrate its state machine.
This is NOT a general repository scanner, approval executor, or multi-host service.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, parse_qs

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_runner import continuous_remediation_worker_v05c as engine
from benchmark_runner import continuous_worker_v05a as worker
from benchmark_runner import durable_live_bridge_v04b as bridge
from benchmark_runner.durable_runtime_v04 import TransitionError, artifact_digest

HOST = "127.0.0.1"
PORT = 17713
MAX_BODY = 4096
MAX_PAGE = 100


@dataclass(frozen=True)
class RuntimeConfig:
    queue_db: Path = engine.BASE / "jobs.sqlite3"
    run_base: Path = engine.RUN_BASE
    locks: Path = engine.BASE / "locks"
    api_key: str = ""


def api_key_from_environment(env: Mapping[str, str] | None = None) -> str:
    """Prefer process env; fall back to ignored .env. Never print the secret."""
    from dotenv import dotenv_values
    config = dict(dotenv_values(Path.cwd() / ".env"))
    config.update(dict(os.environ if env is None else env))
    key = config.get("AGENT_STUDIO_API_KEY") or ""
    reserved = [config.get(k) for k in (
        "GEMMA_API_KEY", "GEMMA_GATEWAY_CHAT_KEY", "GEMMA_GATEWAY_WORKFLOW_KEY",
        "GEMMA_GATEWAY_BACKGROUND_KEY")]
    if len(key) < 32 or any(key == other for other in reserved if other):
        raise RuntimeError("Invalid or reused Agent Studio API credential")
    return key


def metadata(run_id: str, cfg: RuntimeConfig) -> dict[str, Any]:
    bridge.validate_run_id(run_id)
    with worker.Queue(cfg.queue_db) as queue:
        result = queue.inspect(run_id)
    # Do not expose worker event 'details' in the inspection contract.
    output: dict[str, Any] = {"job": result["job"], "bridge_status": "NOT_PREPARED",
                              "tasks": [], "outbox": [], "artifacts": []}
    if result["job"]["phase"] == "PREPARE":
        return output
    ps = bridge.paths(run_id, cfg.run_base)
    if not ps["db"].is_file():
        output["bridge_status"] = "PARTIAL_OR_UNAVAILABLE"
        return output
    with engine.RemediationRuntime(ps["db"]) as runtime:
        snap = runtime.snapshot(run_id)
    # Verify committed artifact digests; expose ONLY metadata, never source,
    # prompts, raw model responses, review bodies, or sandbox stdout.
    for record in snap["artifacts"]:
        if artifact_digest(record["payload"]) != record["content_sha256"]:
            raise TransitionError("Artifact integrity mismatch")
    output["bridge_status"] = snap["status"]
    output["tasks"] = snap["tasks"]
    output["outbox"] = snap["outbox"]
    output["artifacts"] = [
        {"artifact_id": a["artifact_id"], "artifact_type": a["artifact_type"],
         "producer_task_id": a["producer_task_id"], "content_sha256": a["content_sha256"]}
        for a in snap["artifacts"]]
    return output


def list_runs(cfg: RuntimeConfig, *, limit: int = MAX_PAGE) -> dict[str, Any]:
    if not 1 <= limit <= MAX_PAGE:
        raise ValueError("Invalid page size")
    with worker.Queue(cfg.queue_db) as q:
        records = q.db.execute(
            "SELECT run_id,status,phase,created_at,updated_at FROM jobs "
            "ORDER BY created_at DESC,run_id DESC LIMIT ?", (limit,)).fetchall()
    return {"runs": [dict(r) for r in records], "limit": limit}


def events(run_id: str, cfg: RuntimeConfig, *, worker_after: int = 0,
           runtime_after: int = 0, limit: int = MAX_PAGE) -> dict[str, Any]:
    bridge.validate_run_id(run_id)
    if min(worker_after, runtime_after) < 0 or max(worker_after, runtime_after) > 2**63 - 1:
        raise ValueError("Invalid event cursor")
    if not 1 <= limit <= MAX_PAGE:
        raise ValueError("Invalid event limit")
    with worker.Queue(cfg.queue_db) as q:
        q.inspect(run_id)  # unknown runs fail closed
        rows = q.db.execute(
            "SELECT seq,kind,reason_code,phase,created_at FROM worker_events "
            "WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
            (run_id, worker_after, limit)).fetchall()
    worker_rows = [dict(row) for row in rows]
    runtime_rows: list[dict[str, Any]] = []
    ps = bridge.paths(run_id, cfg.run_base)
    if ps["db"].is_file():
        with engine.RemediationRuntime(ps["db"]) as rt:
            rr = rt.db.execute(
                "SELECT seq,event_type,actor,reason_code,task_id,created_at FROM events "
                "WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, runtime_after, limit)).fetchall()
            runtime_rows = [dict(row) for row in rr]
    return {"run_id": run_id, "worker_events": worker_rows,
            "runtime_events": runtime_rows,
            "next_worker_after": worker_rows[-1]["seq"] if worker_rows else worker_after,
            "next_runtime_after": runtime_rows[-1]["seq"] if runtime_rows else runtime_after}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def make_api(cfg: RuntimeConfig, *, port: int = PORT) -> ThreadingHTTPServer:
    if len(cfg.api_key) < 32:
        raise RuntimeError("API credential required")
    if not 0 <= port <= 65535:
        raise ValueError("Invalid API port")

    class Handler(BaseHTTPRequestHandler):
        server_version = "AXONVERTEX-Agent-Runtime"
        sys_version = ""

        def log_message(self, *_: Any) -> None:
            # No URLs, auth headers, user content, or stack traces in access logs.
            return

        def respond(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def auth(self) -> bool:
            token = self.headers.get("Authorization", "")
            if not token.startswith("Bearer ") or not hmac.compare_digest(token[7:], cfg.api_key):
                self.respond(401, {"error": {"code": "UNAUTHORIZED"}})
                return False
            return True

        def _route(self, *, post: bool) -> None:
            self.connection.settimeout(10)  # bound slow/incomplete loopback requests
            path = urlsplit(self.path)
            if path.fragment or "%" in path.path or "//" in path.path:
                self.respond(404, {"error": {"code": "NOT_FOUND"}})
                return
            if not post and path.path == "/health" and not path.query:
                self.respond(200, {"status": "ok", "service": "axonvertex-agent-runtime-api",
                                   "worker_process": "separate"})
                return
            if not self.auth():
                return
            try:
                if post:
                    if path.path != "/v1/runs" or path.query:
                        self.respond(404, {"error": {"code": "NOT_FOUND"}})
                        return
                    if (self.headers.get("Transfer-Encoding") or
                        self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json"):
                        raise ValueError("Invalid request encoding")
                    lengths = self.headers.get_all("Content-Length", [])
                    if len(lengths) != 1 or not lengths[0].isdigit():
                        raise ValueError("Content-Length required")
                    size = int(lengths[0])
                    if size < 1 or size > MAX_BODY:
                        self.respond(413, {"error": {"code": "REQUEST_TOO_LARGE"}})
                        return
                    body = json.loads(self.rfile.read(size), object_pairs_hook=_unique_pairs)
                    if not isinstance(body, dict) or set(body) != {"run_id"} or not isinstance(body["run_id"], str):
                        raise ValueError("Only run_id is supported")
                    bridge.validate_run_id(body["run_id"])
                    with worker.Queue(cfg.queue_db) as q:
                        try:
                            q.submit(body["run_id"])
                        except TransitionError:
                            self.respond(409, {"error": {"code": "RUN_ALREADY_EXISTS"}})
                            return
                    self.respond(201, metadata(body["run_id"], cfg))
                    return
                if path.path == "/v1/runs":
                    if path.query:
                        raise ValueError("Unexpected query")
                    self.respond(200, list_runs(cfg))
                    return
                parts = path.path.split("/")
                if len(parts) not in (4, 5) or parts[:3] != ["", "v1", "runs"]:
                    self.respond(404, {"error": {"code": "NOT_FOUND"}})
                    return
                run_id = parts[3]
                bridge.validate_run_id(run_id)
                if len(parts) == 4:
                    if path.query:
                        raise ValueError("Unexpected query")
                    self.respond(200, metadata(run_id, cfg))
                    return
                if parts[4] != "events":
                    self.respond(404, {"error": {"code": "NOT_FOUND"}})
                    return
                q = parse_qs(path.query, strict_parsing=True, keep_blank_values=True) if path.query else {}
                if any(k not in {"worker_after", "runtime_after", "limit"} or len(v) != 1 or not v[0].isdigit()
                       for k, v in q.items()):
                    raise ValueError("Invalid query")
                self.respond(200, events(run_id, cfg,
                    worker_after=int(q.get("worker_after", ["0"])[0]),
                    runtime_after=int(q.get("runtime_after", ["0"])[0]),
                    limit=int(q.get("limit", [str(MAX_PAGE)])[0])))
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self.respond(400, {"error": {"code": "INVALID_REQUEST"}})
            except TransitionError as exc:
                code = "INTEGRITY_FAILURE" if str(exc) == "Artifact integrity mismatch" else "UNKNOWN_RUN_OR_STATE"
                self.respond(409 if code == "INTEGRITY_FAILURE" else 404, {"error": {"code": code}})
            except (OSError, sqlite3.Error, RuntimeError, KeyError):
                self.respond(503, {"error": {"code": "RUNTIME_UNAVAILABLE"}})

        def do_GET(self) -> None:
            self._route(post=False)

        def do_POST(self) -> None:
            self._route(post=True)

    return ThreadingHTTPServer((HOST, port), Handler)


def main(argv: Sequence[str] | None = None, *, cfg: RuntimeConfig | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("submit", "inspect", "events", "serve", "api"))
    parser.add_argument("--run-id")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--stop-when-idle", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--worker-after", type=int, default=0)
    parser.add_argument("--runtime-after", type=int, default=0)
    parser.add_argument("--limit", type=int, default=MAX_PAGE)
    args = parser.parse_args(argv)
    cfg = cfg or RuntimeConfig()
    try:
        if args.command == "api":
            if args.run_id or args.stop_when_idle or args.poll_seconds != 2:
                raise ValueError("API does not accept worker flags")
            key = cfg.api_key or api_key_from_environment()
            server = make_api(RuntimeConfig(cfg.queue_db, cfg.run_base, cfg.locks, key), port=args.port)
            print(f"AGENT_STUDIO_API_READY http://{HOST}:{server.server_port}", flush=True)
            try:
                server.serve_forever(poll_interval=.2)
            finally:
                server.server_close()
            return 0
        if args.command != "serve" and not args.run_id:
            raise ValueError("--run-id required")
        if args.run_id:
            bridge.validate_run_id(args.run_id)
        if args.command == "serve":
            with worker.Queue(cfg.queue_db) as queue:
                engine.serve(queue, base=cfg.run_base, locks=cfg.locks,
                             stop_when_idle=args.stop_when_idle,
                             poll_seconds=args.poll_seconds)
            return 0
        if args.command == "submit":
            with worker.Queue(cfg.queue_db) as q:
                q.submit(args.run_id)
            value = metadata(args.run_id, cfg)
        elif args.command == "inspect":
            value = metadata(args.run_id, cfg)
        else:
            value = events(args.run_id, cfg, worker_after=args.worker_after,
                           runtime_after=args.runtime_after, limit=args.limit)
        print(json.dumps(value, sort_keys=True, indent=2))
        return 0
    except (TransitionError, RuntimeError, OSError, sqlite3.Error, ValueError) as exc:
        print("AGENT_RUNTIME_ERROR: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
