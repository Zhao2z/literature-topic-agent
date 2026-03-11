"""Xiaomi Mimo OpenAI-compatible client."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from summarize.llm_client import AbstractLlmClient, LlmClientError


class MimoClient(AbstractLlmClient):
    """HTTP client for Xiaomi Mimo chat completions."""

    DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.getenv("MIMO_API_KEY")
        self.base_url = base_url
        self._client = client or httpx.Client(timeout=timeout)

    def build_headers(self) -> dict[str, str]:
        """Build auth headers for Mimo."""

        if not self.api_key:
            raise LlmClientError("MIMO_API_KEY is not configured.")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "api-key": self.api_key,
        }

    def build_payload(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Build an OpenAI-compatible chat completion payload."""

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if response_schema is not None:
            payload["response_schema"] = response_schema
        return payload

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> str:
        """Call Mimo and return the assistant JSON string."""

        payload = self.build_payload(
            messages=messages,
            model=model,
            response_schema=response_schema,
            temperature=temperature,
        )
        response = self._client.post(self.base_url, headers=self.build_headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmClientError("Mimo response does not contain assistant content.") from exc
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        if not isinstance(content, str) or not content.strip():
            raise LlmClientError("Mimo returned empty content.")
        _ensure_valid_json(content)
        return content.strip()


def _ensure_valid_json(content: str) -> None:
    try:
        json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmClientError("Mimo did not return valid JSON.") from exc
