from domain.deduplication import deduplicate_papers
from domain.models import PaperRecord


def build_paper(**overrides: object) -> PaperRecord:
    payload = {
        "paper_id": "paper-1",
        "topic_slug": "topic",
        "title": "Test Case Generation with LLMs",
        "authors": ["Alice"],
        "venue": "ICSE",
        "year": 2024,
        "dblp_url": "https://dblp.org/rec/conf/icse/1",
    }
    payload.update(overrides)
    return PaperRecord(**payload)


def test_deduplicate_by_doi_and_merge_keywords() -> None:
    first = build_paper(doi="10.1000/example", keyword_matches=["LLM"])
    second = build_paper(
        paper_id="paper-2",
        doi="10.1000/example",
        keyword_matches=["Test Generation"],
        authors=["Alice", "Bob"],
    )

    papers = deduplicate_papers([first, second])

    assert len(papers) == 1
    assert papers[0].keyword_matches == ["LLM", "Test Generation"]
    assert papers[0].authors == ["Alice"]


def test_deduplicate_by_title_and_year() -> None:
    first = build_paper(keyword_matches=["LLM"], doi=None)
    second = build_paper(
        paper_id="paper-2",
        title="Test-Case Generation with LLMs",
        keyword_matches=["Automation"],
        doi=None,
    )

    papers = deduplicate_papers([first, second])

    assert len(papers) == 1
    assert papers[0].keyword_matches == ["Automation", "LLM"]
