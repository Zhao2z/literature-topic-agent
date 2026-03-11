"""OpenAI-compatible client abstractions for structured analysis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AbstractLlmClient(ABC):
    """Abstract interface for structured JSON generation."""

    @abstractmethod
    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> str:
        """Generate a JSON string from chat messages."""


class LlmClientError(RuntimeError):
    """Raised when an LLM request fails or returns invalid content."""
