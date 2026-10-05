#!/usr/bin/env python3

import json
import os
import re
import time
import urllib.request

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env(path=None):
    path = Path(path or ROOT / ".env.agent-system")

    if not path.exists():
        raise SystemExit(
            f"Missing {path}. "
            "Run scripts/bootstrap-secrets-node-b.sh first."
        )

    for raw in path.read_text().splitlines():
        raw = raw.strip()

        if not raw:
            continue

        if raw.startswith("#"):
            continue

        if "=" not in raw:
            continue

        key, value = raw.split("=", 1)

        if key not in os.environ:
            os.environ[key] = value


def call(
    base_url,
    api_key,
    model,
    messages,
    max_tokens=2000,
    temperature=0,
    timeout=900,
):
    url = base_url.rstrip("/") + "/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started = time.time()

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        result = json.load(response)
        http_status = response.status

    elapsed = round(time.time() - started, 2)

    choice = result["choices"][0]
    message = choice.get("message", {})

    return {
        "http_status": http_status,
        "elapsed_seconds": elapsed,
        "model": result.get("model", model),
        "finish_reason": choice.get("finish_reason"),
        "content": message.get("content") or "",
        "reasoning_content": message.get("reasoning_content") or "",
        "usage": result.get("usage", {}),
        "raw_id": result.get("id"),
    }


# Compatibility alias.
call_openai = call


def list_models(
    base_url,
    api_key,
    timeout=30,
):
    url = base_url.rstrip("/") + "/models"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return json.load(response)


def extract_json_candidates(text):
    decoder = json.JSONDecoder()
    candidates = []

    for match in re.finditer(r"\{", text or ""):
        try:
            obj, _ = decoder.raw_decode(
                text[match.start():]
            )

            if isinstance(obj, dict):
                candidates.append(obj)

        except Exception:
            pass

    return candidates


def save(prefix, obj):
    outdir = ROOT / "results"

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    path = outdir / (
        f"{prefix}-{timestamp}.json"
    )

    path.write_text(
        json.dumps(
            obj,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


# Compatibility alias.
write_result = save


# Compatibility with existing fast-track scripts.
def models(base, key, timeout=30):
    return list_models(base, key, timeout)
