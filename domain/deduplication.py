"""Deduplicate and merge paper records."""

from __future__ import annotations

from domain.models import PaperRecord
from domain.normalization import normalize_title


def deduplicate_papers(papers: list[PaperRecord]) -> list[PaperRecord]:
    """Deduplicate papers by DOI first, then by normalized title across versions."""

    by_doi: dict[str, list[PaperRecord]] = {}
    without_doi: list[PaperRecord] = []
    for paper in papers:
        doi_key = paper.doi.lower() if paper.doi else None
        if doi_key:
            by_doi.setdefault(doi_key, []).append(paper)
        else:
            without_doi.append(paper)

    stage_one: list[PaperRecord] = []
    for same_doi_group in by_doi.values():
        stage_one.append(_merge_group(same_doi_group))
    stage_one.extend(without_doi)

    by_title: dict[str, list[PaperRecord]] = {}
    for paper in stage_one:
        title_key = normalize_title(paper.title)
        by_title.setdefault(title_key, []).append(paper)

    result: list[PaperRecord] = []
    for same_title_group in by_title.values():
        result.append(_merge_group(same_title_group))
    return result


def _merge_group(group: list[PaperRecord]) -> PaperRecord:
    merged = group[0]
    for candidate in group[1:]:
        primary, secondary = _select_primary_secondary(merged, candidate)
        _merge_metadata(primary, secondary)
        merged = primary
    return merged


def _select_primary_secondary(first: PaperRecord, second: PaperRecord) -> tuple[PaperRecord, PaperRecord]:
    first_preprint = _is_preprint_like(first)
    second_preprint = _is_preprint_like(second)
    if first_preprint != second_preprint:
        return (second, first) if first_preprint else (first, second)

    first_score = _record_quality_score(first)
    second_score = _record_quality_score(second)
    if second_score > first_score:
        return second, first
    return first, second


def _record_quality_score(paper: PaperRecord) -> tuple[int, int, int, int, int]:
    return (
        1 if paper.venue_type == "journal" else 0,
        1 if paper.venue_type == "conference" else 0,
        1 if bool(paper.doi) else 0,
        _ccf_rank_score(paper.ccf_rank),
        paper.year,
    )


def _ccf_rank_score(rank: str) -> int:
    return {
        "CCF-A": 3,
        "A": 3,
        "CCF-B": 2,
        "B": 2,
        "CCF-C": 1,
        "C": 1,
    }.get(rank, 0)


def _is_preprint_like(paper: PaperRecord) -> bool:
    venue = paper.venue.lower()
    dblp_url = paper.dblp_url.lower()
    doi = (paper.doi or "").lower()

    if "arxiv" in venue or "corr" in venue or "preprint" in venue:
        return True
    if "arxiv.org" in dblp_url or "/journals/corr/" in dblp_url:
        return True
    if doi.startswith("10.48550/arxiv."):
        return True
    return False


def _merge_metadata(primary: PaperRecord, secondary: PaperRecord) -> None:
    primary.keyword_matches = sorted(set(primary.keyword_matches + secondary.keyword_matches))
    primary.authors = primary.authors or secondary.authors
    primary.bibtex = primary.bibtex or secondary.bibtex
    primary.dblp_url = primary.dblp_url or secondary.dblp_url
    primary.doi = primary.doi or secondary.doi
    primary.venue = primary.venue or secondary.venue
    primary.venue_type = primary.venue_type or secondary.venue_type
    primary.landing_url = primary.landing_url or secondary.landing_url
    primary.pdf_url = primary.pdf_url or secondary.pdf_url
