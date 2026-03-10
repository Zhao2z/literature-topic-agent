"""DBLP ee download candidates."""

from __future__ import annotations

from domain.models import DownloadCandidate, PaperRecord


class DblpEeResolver:
    """Use DBLP's external URL as a candidate."""

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        if not paper.landing_url:
            return []
        return [DownloadCandidate(source="dblp_ee", url=paper.landing_url, priority=90)]
