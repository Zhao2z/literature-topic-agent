"""Springer candidate rules."""

from __future__ import annotations

from domain.models import DownloadCandidate, PaperRecord


class SpringerResolver:
    """Build Springer direct candidates."""

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        if not paper.doi or not paper.doi.lower().startswith("10.1007/"):
            return []
        normalized = paper.doi.lower()
        return [
            DownloadCandidate(
                source="springer_pdf_rule",
                url=f"https://link.springer.com/content/pdf/{normalized}.pdf",
                priority=70,
            ),
            DownloadCandidate(
                source="springer_article_rule",
                url=f"https://link.springer.com/article/{normalized}",
                priority=65,
            ),
        ]
