"""Citation provider implementations."""

from __future__ import annotations


class NullCitationProvider:
    """Return no citation data."""

    def get_citations(self, doi: str | None, title: str) -> int | None:
        """Return an unavailable citation count."""

        return None
