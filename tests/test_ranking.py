from core.ranking import assign_processing_priority, compute_rank_score
from domain.models import PaperRecord, RankingWeights


def build_paper(**overrides: object) -> PaperRecord:
    payload = {
        "paper_id": "paper-1",
        "topic_slug": "topic",
        "title": "A Study",
        "authors": ["Alice"],
        "venue": "ICSE",
        "year": 2024,
        "dblp_url": "https://dblp.org/rec/conf/icse/1",
        "ccf_rank": "A",
        "citations": 200,
        "keyword_matches": ["A", "B"],
    }
    payload.update(overrides)
    return PaperRecord(**payload)


def test_compute_rank_score_prefers_stronger_paper() -> None:
    weights = RankingWeights(ccf_rank=0.4, recency=0.3, citations=0.2, keyword_match=0.1)
    strong = build_paper()
    weak = build_paper(ccf_rank="C", year=2018, citations=5, keyword_matches=["A"])

    strong_score = compute_rank_score(strong, weights, current_year=2025)
    weak_score = compute_rank_score(weak, weights, current_year=2025)

    assert strong_score > weak_score


def test_assign_processing_priority() -> None:
    first = build_paper(paper_id="1", rank_score=0.9)
    second = build_paper(paper_id="2", rank_score=0.4)

    ranked = assign_processing_priority([second, first])

    assert ranked[0].paper_id == "1"
    assert ranked[0].processing_priority == 1
    assert ranked[1].processing_priority == 2
