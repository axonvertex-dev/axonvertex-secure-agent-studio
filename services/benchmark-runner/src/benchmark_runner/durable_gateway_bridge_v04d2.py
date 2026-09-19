"""Checkpoint 2E-0.4D2: existing durable A->B->A proof with all Node A calls routed
exclusively through the resident loopback Gemma gateway (:17712).

Additive CLI: never alters the frozen v04b bridge or the inference services.
Only the generated, controlled read-only Git fixture is supported by v04b.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_runner import agentic_workflow_v03 as old
from benchmark_runner import durable_live_bridge_v04b as bridge

GATEWAY_ROOT = "http://127.0.0.1:17712"


def read_gateway_config() -> dict[str, str]:
    env = dotenv_values(Path.cwd() / ".env")
    return {key: value for key, value in env.items() if value is not None}


class GatewayProvider:
    """Node A -> authenticated shared workflow gateway; Node B -> existing scout adapter.

    No alternative A provider path. No credential, prompt or raw upstream error in the
    gateway call ledger. Existing bridge retains its own normalized final-content artifacts.
    """

    def __init__(
        self,
        run_id: str,
        *,
        config: Mapping[str, str] | None = None,
        node_provider: Any | None = None,
        gateway_http: httpx.Client | None = None,
        base: Path = bridge.BASE,
    ):
        bridge.validate_run_id(run_id)
        env = dict(config) if config is not None else read_gateway_config()
        model = env.get("GEMMA_MODEL", "")
        credential = env.get("GEMMA_GATEWAY_WORKFLOW_KEY", "")
        if not model or len(credential) < 24:
            raise RuntimeError("Missing Gemma gateway model/workflow credential")
        if env.get("GEMMA_GATEWAY_URL", GATEWAY_ROOT).rstrip("/") != GATEWAY_ROOT:
            raise RuntimeError("Checkpoint gateway must be local http://127.0.0.1:17712")
        tokens = int(env.get("GEMMA_MAX_OUTPUT_TOKENS") or 1536)
        if not 1 <= tokens <= 2048:
            raise RuntimeError("Workflow output tokens outside gateway accepted range")
        timeout = float(env.get("GEMMA_GATEWAY_TIMEOUT_SECONDS") or 270)
        if not 5 <= timeout <= 600:
            raise RuntimeError("Invalid gateway HTTP timeout")
        self.run_id = run_id
        self.model = model
        self.key = credential
        self.max_tokens = tokens
        self.timeout = timeout
        self.base = base
        self.node_provider = node_provider if node_provider is not None else old.Provider(old.nodes_from_env())
        self.own_provider = node_provider is None
        self.http = gateway_http if gateway_http is not None else httpx.Client(trust_env=False)
        self.own_http = gateway_http is None
        self.nodes = {"A": {"model": model}, "B": self.node_provider.nodes["B"]}
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.own_http:
            self.http.close()
        if self.own_provider:
            self.node_provider.close()

    def _audit(self, item: dict[str, Any]) -> None:
        file = bridge.paths(self.run_id, self.base)["folder"] / "gateway-calls.jsonl"
        file.parent.mkdir(parents=True, exist_ok=True)
        line = old.jdump(item) + "\n"
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def call(self, node: str, messages: list[dict[str, Any]], *,
             tools: list[dict[str, Any]] | None = None,
             schema: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.closed:
            raise RuntimeError("Provider closed")
        if node == "B":
            return self.node_provider.call("B", messages, tools=tools, schema=schema)
        if node != "A":
            raise RuntimeError("Only Gemma/A and Antares/B supported by this proof")
        if tools or schema:
            raise RuntimeError("Gateway proof prohibits Gemma tool/schema requests")
        if not messages or len(messages) > 32 or any(
            item.get("role") not in ("system", "user", "assistant") or
            not isinstance(item.get("content"), str) or len(item["content"]) > 64000
            for item in messages
        ):
            raise RuntimeError("Invalid or excessive gateway messages")

        task_id = f"{self.run_id}:gateway:{uuid4().hex}"
        context_id = f"workflow:{self.run_id}"
        payload = {
            "model": self.model, "messages": messages,
            "temperature": 0, "max_tokens": self.max_tokens, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        receipt = {
            "task_id": task_id, "context_id": context_id, "lane": "workflow",
            "transport": "gemma_gateway_loopback", "model": self.model,
            "request_sha256": old.sha(old.jdump(payload)),
        }
        started = time.perf_counter()
        try:
            response = self.http.post(
                GATEWAY_ROOT + "/v1/chat/completions",
                headers={
                    "Authorization": "Bearer " + self.key,
                    "Content-Type": "application/json",
                    "X-Axonvertex-Lane": "workflow",
                    "X-Axonvertex-Task-Id": task_id,
                    "X-Axonvertex-Context-Id": context_id,
                },
                json=payload,
                timeout=httpx.Timeout(self.timeout, connect=5, write=20, pool=5),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self._audit({**receipt, "status": "TRANSPORT_FAILED", "exception_type": type(exc).__name__})
            raise RuntimeError("Gemma gateway unavailable; direct SGLang fallback prohibited") from None

        if response.status_code != 200:
            self._audit({**receipt, "status": response.status_code})
            raise RuntimeError(f"Gemma gateway HTTP {response.status_code}; no direct fallback")
        try:
            data = response.json()
            if data["model"] != self.model:
                raise ValueError("Model mismatch")
            choice = data["choices"][0]
            raw = choice["message"]["content"]
            if choice["finish_reason"] != "stop" or not isinstance(raw, str) or not raw.strip():
                raise ValueError("Incomplete response")
            if choice["message"].get("tool_calls"):
                raise ValueError("Unexpected model tools")
            usage = data.get("usage") or {}
            queue_ms = int(response.headers.get("x-axonvertex-queue-ms", "-1"))
            inference_ms = int(response.headers.get("x-axonvertex-inference-ms", "-1"))
            if queue_ms < 0 or inference_ms < 0:
                raise ValueError("Gateway timing receipt missing")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            self._audit({**receipt, "status": "INVALID_RESPONSE"})
            raise RuntimeError("Gemma gateway invalid or partial response") from None

        content, leak = old.normalize(raw)
        if leak or not content:
            self._audit({**receipt, "status": "UNEXPECTED_FORMAT"})
            raise RuntimeError("Gemma gateway output had unexpected formatting")
        result = {
            "node": "A", "model": self.model, "finish_reason": "stop",
            "content": content, "format_leak_detected": False, "tool_calls": [],
            "raw_content_sha256": old.sha(raw),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "request_sha256": receipt["request_sha256"],
        }
        self._audit({**receipt, "status": 200, "queued_ms": queue_ms,
                     "inference_ms": inference_ms, "response_sha256": old.sha(raw)})
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "scout", "resume", "inspect"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--crash-after-delegation", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            print(json.dumps(bridge.inspect(args.run_id), indent=2))
            return 0
        # Construct before prepare so missing gateway credentials cannot start a run.
        provider = GatewayProvider(args.run_id)
        try:
            if args.command == "prepare":
                bridge.prepare(args.run_id, provider=provider,
                               crash_after_commit=args.crash_after_delegation)
            elif args.command == "scout":
                bridge.scout_live(args.run_id, provider=provider)
            else:
                bridge.resume_live(args.run_id, provider=provider)
        finally:
            provider.close()
        return 0
    except (RuntimeError, ValueError, OSError, KeyError, StopIteration) as exc:
        print(f"DURABLE_GATEWAY_BRIDGE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
