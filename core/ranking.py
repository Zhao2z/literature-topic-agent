"""Ranking logic for candidate papers."""

from __future__ import annotations

from datetime import datetime

from domain.models import PaperRecord, RankingWeights

CCF_RANK_SCORES = {
    "A": 1.0,
    "B": 0.7,
    "C": 0.45,
    "Unranked": 0.1,
}


def compute_rank_score(
    paper: PaperRecord,
    weights: RankingWeights,
    current_year: int | None = None,
) -> float:
    """Compute a weighted ranking score for a paper."""

    reference_year = current_year or datetime.utcnow().year
    recency = max(0.0, 1.0 - max(reference_year - paper.year, 0) / 10.0)
    citations = max(float(paper.citations or 0), 0.0)
    citation_signal = min(citations / 1000.0, 1.0)
    keyword_signal = min(float(len(paper.keyword_matches)) / 4.0, 1.0)
    ccf_signal = CCF_RANK_SCORES.get(paper.ccf_rank, CCF_RANK_SCORES["Unranked"])

    score = (
        weights.ccf_rank * ccf_signal
        + weights.recency * recency
        + weights.citations * citation_signal
        + weights.keyword_match * keyword_signal
    )
    return round(score, 6)


def assign_processing_priority(papers: list[PaperRecord]) -> list[PaperRecord]:
    """Assign processing priority based on descending rank score."""

    ordered = sorted(papers, key=lambda item: item.rank_score, reverse=True)
    for index, paper in enumerate(ordered, start=1):
        paper.processing_priority = index
    return ordered
