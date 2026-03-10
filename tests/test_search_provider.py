from domain.models import DblpRawRecord
from providers.search import FallbackSearchProvider


class EmptyProvider:
    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        return []


class SuccessProvider:
    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        return [
            DblpRawRecord(
                title="Paper",
                authors=["Alice"],
                venue="ICSE",
                year=2024,
                dblp_url="https://example.com/paper",
            )
        ]


def test_fallback_search_provider_uses_next_provider() -> None:
    provider = FallbackSearchProvider([EmptyProvider(), SuccessProvider()])

    results = provider.search("query", limit=10)

    assert len(results) == 1
    assert results[0].title == "Paper"
