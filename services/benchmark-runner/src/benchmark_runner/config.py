from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[4]

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class ModelEndpoint:
    name: str
    base_url: str
    model: str
    api_key: str
    configured_context_limit: int | None


def gemma_endpoint() -> ModelEndpoint:
    base_url = os.environ.get(
        "GEMMA_BASE_URL",
        "http://127.0.0.1:11433/v1",
    ).rstrip("/")

    model = os.environ.get(
        "GEMMA_MODEL",
        "gemma-4-12b-it-qat",
    )

    api_key = os.environ.get(
        "GEMMA_API_KEY",
        "",
    ).strip()

    if not api_key:
        raise RuntimeError(
            "GEMMA_API_KEY is missing from project .env"
        )

    context_raw = os.environ.get(
        "GEMMA_CONTEXT_LIMIT"
    )

    context_limit = (
        int(context_raw)
        if context_raw
        else None
    )

    return ModelEndpoint(
        name="node-a-gemma",
        base_url=base_url,
        model=model,
        api_key=api_key,
        configured_context_limit=context_limit,
    )
