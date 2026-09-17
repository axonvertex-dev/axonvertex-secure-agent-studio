from __future__ import annotations

from typing import Any

import httpx

from .config import ModelEndpoint


class TokenCounter:
    def __init__(
        self,
        endpoint: ModelEndpoint,
    ) -> None:
        self.endpoint = endpoint

        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=10.0,
                read=300.0,
                write=60.0,
                pool=10.0,
            ),
            headers={
                "Authorization": f"Bearer {endpoint.api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def count(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "model": self.endpoint.model,
            "messages": messages,
        }

        if system is not None:
            payload["system"] = system

        response = self._client.post(
            f"{self.endpoint.base_url}/messages/count_tokens",
            json=payload,
        )

        response.raise_for_status()

        body = response.json()
        count = body.get("input_tokens")

        if not isinstance(count, int):
            raise RuntimeError(
                f"Invalid count_tokens response: {body!r}"
            )

        return count
