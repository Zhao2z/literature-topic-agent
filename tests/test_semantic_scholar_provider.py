from providers.semantic_scholar import (
    SemanticScholarSearchClient,
    _normalize_semantic_scholar_result,
)


def test_normalize_semantic_scholar_result() -> None:
    result = {
        "title": "Test Case Generation with LLMs",
        "year": 2024,
        "url": "https://www.semanticscholar.org/paper/123",
        "authors": [{"name": "Alice Smith"}, {"name": "Bob Lee"}],
        "externalIds": {"DOI": "10.1000/example"},
        "publicationTypes": ["Conference"],
        "publicationVenue": {"name": "ICSE", "type": "conference"},
    }

    record = _normalize_semantic_scholar_result(result)

    assert record is not None
    assert record.title == "Test Case Generation with LLMs"
    assert record.authors == ["Alice Smith", "Bob Lee"]
    assert record.venue == "ICSE"
    assert record.year == 2024
    assert record.doi == "10.1000/example"
    assert record.venue_type == "conference"


def test_semantic_scholar_search_normalizes_records() -> None:
    client = SemanticScholarSearchClient()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {
                        "title": "Paper 1",
                        "year": 2024,
                        "url": "https://www.semanticscholar.org/paper/1",
                        "authors": [{"name": "Alice"}],
                        "externalIds": {"DOI": "10.1000/p1"},
                        "publicationTypes": ["JournalArticle"],
                        "publicationVenue": {"name": "TOSEM", "type": "journal"},
                    }
                ]
            }

    class FakeHttpClient:
        def get(self, url: str, params: dict[str, object]) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    client._client = FakeHttpClient()  # type: ignore[assignment]

    records = client.search("test generation", limit=5)

    assert len(records) == 1
    assert records[0].title == "Paper 1"
    assert records[0].venue_type == "journal"
