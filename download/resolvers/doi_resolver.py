"""DOI landing-page candidates."""

from __future__ import annotations

from domain.models import DownloadCandidate, PaperRecord


class DoiResolver:
    """Use the DOI redirect as a candidate."""

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        if not paper.doi:
            return []
        return [DownloadCandidate(source="doi_resolved", url=f"https://doi.org/{paper.doi.lstrip('/')}", priority=80)]
