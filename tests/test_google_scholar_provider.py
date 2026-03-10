from providers.google_scholar import GoogleScholarSearchClient, _normalize_scholar_result


def test_normalize_google_scholar_result() -> None:
    result = {
        "bib": {
            "title": "Test Case Generation with LLMs",
            "author": "Alice Smith and Bob Lee",
            "pub_year": "2024",
            "venue": "ICSE",
        },
        "pub_url": "https://doi.org/10.1000/example",
        "author_pub_id": "1234567890",
    }

    record = _normalize_scholar_result(result)

    assert record is not None
    assert record.title == "Test Case Generation with LLMs"
    assert record.authors == ["Alice Smith", "Bob Lee"]
    assert record.year == 2024
    assert record.doi == "10.1000/example"


def test_google_scholar_search_limits_results() -> None:
    client = GoogleScholarSearchClient()
    client._scholarly = type(
        "FakeScholarly",
        (),
        {
            "search_pubs": staticmethod(
                lambda query: iter(
                    [
                        {"bib": {"title": "Paper 1", "author": "Alice", "pub_year": "2024", "venue": "ICSE"}},
                        {"bib": {"title": "Paper 2", "author": "Bob", "pub_year": "2023", "venue": "ASE"}},
                    ]
                )
            )
        },
    )()

    records = client.search("test generation", limit=1)

    assert len(records) == 1
    assert records[0].title == "Paper 1"
