"""ACM candidate rules."""

from __future__ import annotations

from domain.models import DownloadCandidate, PaperRecord


class AcmResolver:
    """Build ACM direct PDF candidates."""

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        if not paper.doi or not paper.doi.startswith("10.1145/"):
            return []
        return [DownloadCandidate(source="acm_pdf_rule", url=f"https://dl.acm.org/doi/pdf/{paper.doi}", priority=70)]
