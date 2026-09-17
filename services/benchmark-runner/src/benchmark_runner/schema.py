from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ExpectedResult(BaseModel):
    exact_text: str | None = None
    required_substrings: list[str] = Field(default_factory=list)


class BenchmarkTask(BaseModel):
    id: str
    category: str
    description: str

    system_prompt: str
    user_prompt: str

    temperature: float = 0.0
    max_output_tokens: int = 64

    expected: ExpectedResult


class UsageRecord(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None


class BenchmarkResult(BaseModel):
    schema_version: Literal["benchmark-result.v1"] = "benchmark-result.v1"

    task_id: str

    endpoint_name: str
    endpoint_url: str
    model: str

    advertised_context_limit: int | None = None

    status: Literal[
        "PASS",
        "FAIL",
        "ERROR",
    ]

    response_text: str | None = None

    exact_match: bool | None = None
    required_substrings_match: bool | None = None

    latency_ms: int | None = None

    usage: UsageRecord = Field(
        default_factory=UsageRecord
    )

    finish_reason: str | None = None

    error: str | None = None

    raw_metadata: dict[str, Any] = Field(
        default_factory=dict
    )
