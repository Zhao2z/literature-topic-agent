from __future__ import annotations

import httpx

from providers.dblp import DblpSearchClient


def test_dblp_provider_falls_back_to_local_library_result() -> None:
    client = DblpSearchClient()
    client._local_dblp_search = lambda queries: [  # type: ignore[assignment]
        {
            "authors": ["Alice", "Bob"],
            "title": "Test Case Generation with LLMs.",
            "venue": "ICSE",
            "year": "2024",
            "type": "Conference and Workshop Papers",
            "doi": "10.1000/example",
            "url": "https://dblp.org/rec/conf/icse/Test2024",
        }
    ]

    request = httpx.Request("GET", "https://dblp.org/search/publ/api")
    response = httpx.Response(500, request=request)

    def raise_server_error(query: str, limit: int) -> list[object]:
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    client._search_httpx = raise_server_error  # type: ignore[method-assign]

    records = client.search("Test Case Generation", limit=10)

    assert len(records) == 1
    assert records[0].title == "Test Case Generation with LLMs."
    assert records[0].venue == "ICSE"
    assert records[0].venue_type == "conference"


def test_dblp_provider_returns_empty_when_fallback_also_fails() -> None:
    client = DblpSearchClient()

    request = httpx.Request("GET", "https://dblp.org/search/publ/api")
    response = httpx.Response(500, request=request)

    def raise_server_error(query: str, limit: int) -> list[object]:
        raise httpx.HTTPStatusError("server error", request=request, response=response)

    def broken_fallback(queries: list[str]) -> list[object]:
        raise ValueError("invalid json from upstream")

    client._search_httpx = raise_server_error  # type: ignore[method-assign]
    client._local_dblp_search = broken_fallback  # type: ignore[assignment]

    records = client.search("Test Case Generation", limit=10)

    assert records == []
