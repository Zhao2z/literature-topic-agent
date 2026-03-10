from domain.models import DblpRawRecord
from domain.normalization import normalize_paper, normalize_title


def test_normalize_title() -> None:
    assert normalize_title("  Test-Case Generation: An Overview ") == "test case generation an overview"


def test_normalize_paper() -> None:
    raw = DblpRawRecord(
        title="  Test Case Generation with LLMs ",
        authors=[" Alice  ", "Bob"],
        venue=" ICSE ",
        year=2024,
        dblp_url="https://dblp.org/rec/conf/icse/demo",
        doi="10.1000/example",
        venue_type="conference",
    )

    paper = normalize_paper(raw, "test-case-generation", ["LLM", "Test Generation"])

    assert paper.paper_id
    assert paper.title == "Test Case Generation with LLMs"
    assert paper.authors == ["Alice", "Bob"]
    assert paper.keyword_matches == ["LLM", "Test Generation"]
