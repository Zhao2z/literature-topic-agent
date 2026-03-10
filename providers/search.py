"""Search-provider composition utilities."""

from __future__ import annotations

from core.logging import get_logger
from domain.models import DblpRawRecord
from providers.interfaces import AbstractSearchProvider

LOGGER = get_logger(__name__)


class FallbackSearchProvider:
    """Try search providers in order until one returns records."""

    def __init__(self, providers: list[AbstractSearchProvider]) -> None:
        self.providers = providers

    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        """Search with the first provider that returns usable results."""

        for provider in self.providers:
            provider_name = provider.__class__.__name__
            try:
                records = provider.search(query, limit=limit)
            except Exception as exc:
                LOGGER.bind(
                    query=query,
                    provider=provider_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                ).warning("Search provider failed")
                continue
            if records:
                LOGGER.bind(query=query, provider=provider_name, count=len(records)).info(
                    "Search provider returned results"
                )
                return records
            LOGGER.bind(query=query, provider=provider_name).warning("Search provider returned no results")
        return []
