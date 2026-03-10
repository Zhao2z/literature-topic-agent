"""Build ordered download candidate chains for papers."""

from __future__ import annotations

import httpx

from domain.models import DownloadCandidate, PaperRecord
from download.resolvers import (
    AcmResolver,
    ArxivResolver,
    DblpEeResolver,
    DoiResolver,
    IeeeResolver,
    OpenAlexResolver,
    SpringerResolver,
)


class DownloadCandidateBuilder:
    """Build and deduplicate ordered download candidates."""

    def __init__(self, client: httpx.Client) -> None:
        self._resolvers = [
            OpenAlexResolver(client),
            DblpEeResolver(),
            DoiResolver(),
            ArxivResolver(),
            SpringerResolver(),
            AcmResolver(),
            IeeeResolver(),
        ]

    def build(self, paper: PaperRecord) -> list[DownloadCandidate]:
        candidates: list[DownloadCandidate] = []
        seen: set[str] = set()
        if paper.pdf_url:
            seen.add(paper.pdf_url)
            candidates.append(DownloadCandidate(source="stored_pdf_url", url=paper.pdf_url, priority=85))
        for resolver in self._resolvers:
            for candidate in resolver.resolve(paper):
                if candidate.url in seen:
                    continue
                seen.add(candidate.url)
                candidates.append(candidate)
        candidates.sort(key=lambda item: item.priority, reverse=True)
        return candidates
