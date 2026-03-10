"""Provider interfaces."""

from __future__ import annotations

from typing import Protocol

from domain.models import DblpRawRecord


class AbstractSearchProvider(Protocol):
    """Search provider interface."""

    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        """Search for papers by query."""


class AbstractCitationProvider(Protocol):
    """Citation provider interface."""

    def get_citations(self, doi: str | None, title: str) -> int | None:
        """Return a citation count if available."""


class AbstractVenueRankProvider(Protocol):
    """Venue ranking provider interface."""

    def get_rank(self, venue: str, dblp_url: str | None = None) -> str:
        """Return the CCF rank for a venue."""
