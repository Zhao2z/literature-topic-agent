"""arXiv candidate rules."""

from __future__ import annotations

from urllib.parse import urlparse

from domain.models import DownloadCandidate, PaperRecord


class ArxivResolver:
    """Build arXiv PDF candidates."""

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        candidates: list[DownloadCandidate] = []
        for url in [paper.landing_url, paper.pdf_url]:
            pdf_url = _derive_arxiv_pdf(url)
            if pdf_url:
                candidates.append(DownloadCandidate(source="arxiv_pdf_rule", url=pdf_url, priority=75))
        if paper.doi and paper.doi.upper().startswith("10.48550/ARXIV."):
            paper_id = paper.doi.split(".", 1)[1]
            candidates.append(DownloadCandidate(source="arxiv_pdf_rule", url=f"https://arxiv.org/pdf/{paper_id}", priority=75))
        return candidates


def _derive_arxiv_pdf(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.netloc != "arxiv.org":
        return None
    if parsed.path.startswith("/pdf/"):
        return url
    if parsed.path.startswith("/abs/"):
        return f"https://arxiv.org/pdf/{parsed.path.removeprefix('/abs/')}"
    return None
