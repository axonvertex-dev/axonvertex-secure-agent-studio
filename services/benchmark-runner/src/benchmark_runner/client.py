from __future__ import annotations

from typing import Any

import httpx

from .config import ModelEndpoint


class OpenAICompatibleClient:
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
                "Authorization":
                    f"Bearer {endpoint.api_key}",
                "Content-Type":
                    "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def models(self) -> dict[str, Any]:
        response = self._client.get(
            f"{self.endpoint.base_url}/models"
        )

        response.raise_for_status()

        return response.json()

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"{self.endpoint.base_url}/chat/completions",
            json={
                "model": self.endpoint.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )

        response.raise_for_status()

        return response.json()
