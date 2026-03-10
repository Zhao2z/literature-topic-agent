"""Semantic Scholar search provider."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.logging import get_logger
from domain.models import DblpRawRecord

LOGGER = get_logger(__name__)


class SemanticScholarSearchClient:
    """Search Semantic Scholar via its official public API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    DEFAULT_FIELDS = (
        "title,year,venue,url,authors,externalIds,publicationTypes,publicationVenue,openAccessPdf"
    )

    def __init__(self, timeout: float = 20.0, api_key: str | None = None) -> None:
        headers = {"User-Agent": "literature-topic-agent/0.1"}
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.Client(timeout=timeout, headers=headers, follow_redirects=True)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        """Search Semantic Scholar for papers matching a query."""

        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": self.DEFAULT_FIELDS,
        }
        try:
            response = self._client.get(self.BASE_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.bind(query=query, limit=limit, error_type=type(exc).__name__, error=str(exc)).warning(
                "Semantic Scholar request failed"
            )
            return []

        payload = response.json()
        items = payload.get("data", [])
        records: list[DblpRawRecord] = []
        for item in items:
            record = _normalize_semantic_scholar_result(item)
            if record is not None:
                records.append(record)
        return records

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()


def _normalize_semantic_scholar_result(result: dict[str, Any]) -> DblpRawRecord | None:
    """Normalize a Semantic Scholar result to the local raw-paper model."""

    title = str(result.get("title", "")).strip()
    if not title:
        return None

    try:
        year = int(result.get("year"))
    except (TypeError, ValueError):
        LOGGER.bind(raw_title=title).debug("Skipping Semantic Scholar hit without valid year")
        return None

    authors = [
        str(author.get("name", "")).strip()
        for author in result.get("authors", [])
        if str(author.get("name", "")).strip()
    ]
    venue = _resolve_venue(result)
    url = str(result.get("url", "")).strip()
    doi = _extract_doi(result.get("externalIds", {}))
    venue_type = _infer_venue_type(result)

    return DblpRawRecord(
        title=title,
        authors=authors,
        venue=venue,
        year=year,
        dblp_url=url,
        doi=doi,
        bibtex=None,
        venue_type=venue_type,
    )


def _resolve_venue(result: dict[str, Any]) -> str:
    """Resolve the best venue string from a Semantic Scholar result."""

    publication_venue = result.get("publicationVenue") or {}
    name = str(publication_venue.get("name", "")).strip()
    if name:
        return name
    return str(result.get("venue", "")).strip()


def _extract_doi(external_ids: dict[str, Any]) -> str | None:
    """Extract DOI from Semantic Scholar external IDs."""

    doi = external_ids.get("DOI")
    if doi is None:
        return None
    value = str(doi).strip()
    return value or None


def _infer_venue_type(result: dict[str, Any]) -> str:
    """Infer a venue type from Semantic Scholar metadata."""

    publication_types = [str(item).lower() for item in result.get("publicationTypes", [])]
    if any("journal" in item for item in publication_types):
        return "journal"
    if any("conference" in item or "review" in item for item in publication_types):
        return "conference"

    publication_venue = result.get("publicationVenue") or {}
    raw_type = str(publication_venue.get("type", "")).lower()
    if "journal" in raw_type:
        return "journal"
    if "conference" in raw_type:
        return "conference"
    return "unknown"
