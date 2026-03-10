"""Deduplicate and merge paper records."""

from __future__ import annotations

from domain.models import PaperRecord
from domain.normalization import normalize_title


def deduplicate_papers(papers: list[PaperRecord]) -> list[PaperRecord]:
    """Deduplicate papers using DOI first and normalized title/year second."""

    merged: dict[str, PaperRecord] = {}
    title_index: dict[tuple[str, int], str] = {}

    for paper in papers:
        doi_key = paper.doi.lower() if paper.doi else None
        title_key = (normalize_title(paper.title), paper.year)

        existing_key = None
        if doi_key and doi_key in merged:
            existing_key = doi_key
        elif title_key in title_index:
            existing_key = title_index[title_key]

        if existing_key is None:
            storage_key = doi_key or paper.paper_id
            merged[storage_key] = paper
            title_index[title_key] = storage_key
            continue

        current = merged[existing_key]
        current.keyword_matches = sorted(set(current.keyword_matches + paper.keyword_matches))
        current.authors = current.authors or paper.authors
        current.bibtex = current.bibtex or paper.bibtex
        current.dblp_url = current.dblp_url or paper.dblp_url
        current.doi = current.doi or paper.doi
        current.venue = current.venue or paper.venue

    return list(merged.values())
