"""Google Scholar search provider."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from core.logging import get_logger
from domain.models import DblpRawRecord

LOGGER = get_logger(__name__)


class GoogleScholarSearchClient:
    """Search Google Scholar via the unofficial `scholarly` package."""

    def __init__(self) -> None:
        self._scholarly = _load_scholarly_module()

    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        """Search Google Scholar for papers matching a query."""

        if self._scholarly is None:
            LOGGER.bind(query=query).warning("scholarly is unavailable, skipping Google Scholar search")
            return []

        try:
            iterator = self._scholarly.search_pubs(query)
        except Exception as exc:
            LOGGER.bind(query=query, error_type=type(exc).__name__, error=str(exc)).warning(
                "Google Scholar search initialization failed"
            )
            return []

        records: list[DblpRawRecord] = []
        for index, result in enumerate(_iter_publications(iterator), start=1):
            if index > limit:
                break
            raw_record = _normalize_scholar_result(result)
            if raw_record is not None:
                records.append(raw_record)
        return records


def _load_scholarly_module() -> Any | None:
    """Load the scholarly client lazily."""

    try:
        from scholarly import scholarly
    except Exception:
        return None
    return scholarly


def _iter_publications(iterator: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Iterate over Google Scholar search results defensively."""

    while True:
        try:
            yield next(iterator)
        except StopIteration:
            return
        except Exception as exc:
            LOGGER.bind(error_type=type(exc).__name__, error=str(exc)).warning(
                "Google Scholar iteration stopped due to provider error"
            )
            return


def _normalize_scholar_result(result: dict[str, Any]) -> DblpRawRecord | None:
    """Normalize a `scholarly` search result to the local raw-paper model."""

    bib = result.get("bib", {})
    title = str(bib.get("title", "")).strip()
    if not title:
        return None

    year_value = bib.get("pub_year") or bib.get("year")
    try:
        year = int(year_value)
    except (TypeError, ValueError):
        LOGGER.bind(raw_title=title).debug("Skipping Google Scholar hit without valid year")
        return None

    authors_value = bib.get("author", [])
    if isinstance(authors_value, str):
        authors = [item.strip() for item in authors_value.split(" and ") if item.strip()]
    else:
        authors = [str(item).strip() for item in authors_value if str(item).strip()]

    venue = (
        str(bib.get("venue", "")).strip()
        or str(bib.get("journal", "")).strip()
        or str(bib.get("conference", "")).strip()
    )
    pub_url = str(result.get("pub_url", "")).strip()
    author_pub_id = str(result.get("author_pub_id", "")).strip()
    scholar_url = f"https://scholar.google.com/scholar?cluster={author_pub_id}" if author_pub_id else pub_url
    doi = _extract_doi(pub_url) or _extract_doi(str(result.get("eprint_url", "")).strip())
    venue_type = _infer_venue_type(bib)

    return DblpRawRecord(
        title=title,
        authors=authors,
        venue=venue,
        year=year,
        dblp_url=scholar_url,
        doi=doi,
        bibtex=None,
        venue_type=venue_type,
    )


def _infer_venue_type(bib: dict[str, Any]) -> str:
    """Infer a venue type from scholar metadata."""

    if bib.get("journal"):
        return "journal"
    if bib.get("conference") or bib.get("venue"):
        return "conference"
    return "unknown"


def _extract_doi(url: str) -> str | None:
    """Extract a DOI from a URL when present."""

    marker = "doi.org/"
    if marker not in url:
        return None
    doi = url.split(marker, 1)[1].strip().strip("/")
    return doi or None
