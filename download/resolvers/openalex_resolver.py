"""OpenAlex-based OA download candidates."""

from __future__ import annotations

import httpx

from domain.models import DownloadCandidate, PaperRecord


class OpenAlexResolver:
    """Fetch OA candidates from OpenAlex."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def resolve(self, paper: PaperRecord) -> list[DownloadCandidate]:
        if not paper.doi:
            return []
        request_url = f"https://api.openalex.org/works/https://doi.org/{paper.doi}"
        try:
            response = self._client.get(request_url)
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        payload = response.json()
        candidates: list[DownloadCandidate] = []
        for location in [payload.get("best_oa_location") or {}, payload.get("primary_location") or {}]:
            pdf_url = str(location.get("pdf_url", "")).strip()
            landing_url = str(location.get("landing_page_url", "")).strip()
            if pdf_url:
                candidates.append(DownloadCandidate(source="openalex_oa", url=pdf_url, priority=100))
            if landing_url:
                candidates.append(DownloadCandidate(source="openalex_oa_landing", url=landing_url, priority=95))
        return candidates
