"""DBLP search client."""

from __future__ import annotations

import importlib.util
from typing import Any
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.logging import get_logger
from domain.models import DblpRawRecord

LOGGER = get_logger(__name__)


class DblpSearchClient:
    """Client for querying the DBLP API."""

    BASE_URL = "https://dblp.org/search/publ/api"

    def __init__(self, timeout: float = 20.0, local_library_root: str | Path = "temp/dblp-api") -> None:
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)
        self._local_library_root = Path(local_library_root)
        self._local_dblp_search: Any | None = None
        self._local_dblp_loaded = False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        """Search DBLP publications for a query."""

        try:
            return self._search_httpx(query=query, limit=limit)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code >= 500:
                LOGGER.bind(query=query, limit=limit, status_code=status_code).warning(
                    "DBLP returned server error, falling back to local dblp-api style search"
                )
                fallback_records = self._search_local_library(query=query, limit=limit)
                if fallback_records:
                    return fallback_records
                LOGGER.bind(query=query, limit=limit, status_code=status_code).warning(
                    "DBLP fallback produced no usable results"
                )
                return []
            raise
        except httpx.HTTPError:
            LOGGER.bind(query=query, limit=limit).warning("DBLP request failed")
            return []

    def _search_httpx(self, query: str, limit: int) -> list[DblpRawRecord]:
        """Search DBLP using the native HTTP API."""

        params = {
            "q": query,
            "h": limit,
            "format": "json",
            "app": "literature-topic-agent",
        }
        response = self._client.get(self.BASE_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        records: list[DblpRawRecord] = []
        for hit in hits:
            info = hit.get("info", {})
            authors_payload = info.get("authors", {}).get("author", [])
            authors: list[str]
            if isinstance(authors_payload, list):
                authors = [author.get("text", "") if isinstance(author, dict) else str(author) for author in authors_payload]
            elif isinstance(authors_payload, dict):
                authors = [authors_payload.get("text", "")]
            else:
                authors = [str(authors_payload)] if authors_payload else []

            venue = info.get("venue") or info.get("journal") or info.get("booktitle") or ""
            venue_type = "journal" if info.get("journal") else "conference" if info.get("booktitle") else "unknown"
            doi = info.get("doi")
            ee_url = _extract_ee_url(info.get("ee"))
            dblp_url = info.get("url", "")
            if dblp_url and not dblp_url.startswith("http"):
                dblp_url = f"https://dblp.org/rec/{quote_plus(dblp_url)}"
            try:
                year = int(info.get("year"))
            except (TypeError, ValueError):
                LOGGER.bind(raw_title=info.get("title")).debug("Skipping DBLP hit without valid year")
                continue

            title = _extract_title(info.get("title", ""))
            if not title:
                continue
            records.append(_build_raw_record(title, authors, venue, year, dblp_url, doi, venue_type, ee_url))
        return records

    def _search_local_library(self, query: str, limit: int) -> list[DblpRawRecord]:
        """Fallback to the locally cloned dblp-api package."""

        if not self._local_dblp_loaded and self._local_dblp_search is None:
            self._local_dblp_search = _load_local_dblp_search(self._local_library_root)
            self._local_dblp_loaded = True
        elif not self._local_dblp_loaded:
            self._local_dblp_loaded = True

        if self._local_dblp_search is None:
            LOGGER.bind(query=query).warning("Local dblp-api package is unavailable")
            return []

        try:
            results = self._local_dblp_search([query])
        except Exception as exc:
            LOGGER.bind(query=query, error_type=type(exc).__name__, error=str(exc)).warning(
                "Local dblp-api fallback search failed"
            )
            return []

        if not results:
            return []

        first = results[0]
        if first is None:
            return []

        if limit > 1:
            LOGGER.bind(query=query, limit=limit).warning(
                "Fallback dblp-api search returns only the top hit for this query"
            )
        raw_record = _normalize_library_result(first)
        return [raw_record] if raw_record is not None else []

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()


def _extract_title(raw_title: Any) -> str:
    """Extract a string title from DBLP API payloads."""

    if isinstance(raw_title, str):
        return raw_title
    if isinstance(raw_title, dict):
        return str(raw_title.get("text", ""))
    return str(raw_title or "")


def _normalize_library_result(result: dict[str, Any]) -> DblpRawRecord | None:
    """Normalize a result returned by the local dblp-api package."""

    title = _extract_title(result.get("title", ""))
    if not title:
        return None
    try:
        year = int(result.get("year"))
    except (TypeError, ValueError):
        LOGGER.bind(raw_title=title).debug("Skipping fallback DBLP hit without valid year")
        return None

    authors = [str(author).strip() for author in result.get("authors", []) if str(author).strip()]
    venue = str(result.get("venue", "")).strip()
    doi = str(result["doi"]).strip() if result.get("doi") else None
    dblp_url = str(result.get("url", "")).strip()
    venue_type = _map_library_type_to_venue_type(result.get("type"))
    return _build_raw_record(title, authors, venue, year, dblp_url, doi, venue_type)


def _extract_ee_url(raw_ee: Any) -> str | None:
    """Extract a usable external URL from DBLP's ee field."""

    if isinstance(raw_ee, str):
        return raw_ee.strip() or None
    if isinstance(raw_ee, list):
        for item in raw_ee:
            value = str(item).strip()
            if value:
                return value
    return None


def _map_library_type_to_venue_type(raw_type: Any) -> str:
    """Map dblp-api result types to the local venue_type field."""

    value = str(raw_type or "").lower()
    if "journal" in value:
        return "journal"
    if "conference" in value or "workshop" in value:
        return "conference"
    return "unknown"


def _build_raw_record(
    title: str,
    authors: list[str],
    venue: str,
    year: int,
    dblp_url: str,
    doi: str | None,
    venue_type: str,
    ee_url: str | None = None,
) -> DblpRawRecord:
    """Build a normalized raw DBLP record."""

    if dblp_url and not dblp_url.startswith("http"):
        dblp_url = f"https://dblp.org/rec/{quote_plus(dblp_url)}"
    return DblpRawRecord(
        title=title,
        authors=authors,
        venue=venue,
        year=year,
        dblp_url=dblp_url,
        doi=doi,
        ee_url=ee_url,
        bibtex=None,
        venue_type=venue_type,
    )


def _load_local_dblp_search(local_library_root: Path) -> Any | None:
    """Load the local dblp-api search function if the clone is present."""

    module_path = local_library_root / "dblp" / "api.py"
    if not module_path.exists():
        return None

    spec = importlib.util.spec_from_file_location("dblp_local_api", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "search", None)
