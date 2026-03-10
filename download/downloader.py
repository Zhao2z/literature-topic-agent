"""Resolver-based paper downloader."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from core.logging import get_logger
from domain.models import DownloadCandidate, PaperRecord, PaperStatus
from download.candidate_builder import DownloadCandidateBuilder
from download.naming import build_pdf_filename
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)

DEFAULT_USER_AGENT = "literature-topic-agent/0.1 (+https://doi.org)"
PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}
HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}


class CandidateDownloader:
    """Try ordered candidate URLs until one yields a PDF."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/pdf, text/html;q=0.9, */*;q=0.8",
            },
        )
        self._owns_client = client is None
        self._builder = DownloadCandidateBuilder(self._client)

    def __del__(self) -> None:
        if self._owns_client:
            self._client.close()

    def download_papers(self, papers: list[PaperRecord], workspace: TopicWorkspace, limit: int | None = None) -> int:
        selected = papers if limit is None or limit <= 0 else papers[:limit]
        successful_downloads = 0
        for paper in selected:
            if self.download_paper(paper, workspace):
                successful_downloads += 1
        return successful_downloads

    def download_paper(self, paper: PaperRecord, workspace: TopicWorkspace) -> bool:
        paper.download_candidates = self._builder.build(paper)
        existing_path = Path(paper.local_pdf_path) if paper.local_pdf_path else None
        if existing_path and existing_path.exists():
            target_path = self._ensure_named_download(existing_path, workspace, paper)
            self._mark_downloaded(paper, target_path, paper.pdf_url, paper.landing_url, paper.download_source)
            return True

        if not paper.download_candidates:
            self._mark_failure(paper, _classify_missing_candidates(paper), "No download candidates built")
            return False

        for candidate in paper.download_candidates:
            success, detail = self._try_candidate(paper, workspace, candidate)
            if success:
                return True
            if detail is not None:
                self._mark_failure(paper, detail["code"], detail["message"])

        if not paper.download_failure_code:
            self._mark_failure(paper, "pdf_not_found", "No candidate produced a PDF")
        return False

    def _try_candidate(
        self,
        paper: PaperRecord,
        workspace: TopicWorkspace,
        candidate: DownloadCandidate,
    ) -> tuple[bool, dict[str, str] | None]:
        try:
            response = self._client.get(candidate.url)
        except httpx.HTTPError as exc:
            LOGGER.bind(paper_id=paper.paper_id, source=candidate.source, url=candidate.url).warning(
                "Paper download failed: {}", exc
            )
            return False, {"code": "network_error", "message": str(exc)}

        final_url = str(response.url)
        if _is_pdf_response(response, final_url):
            file_path = self._store_pdf_bytes(workspace, paper, response.content)
            self._mark_downloaded(paper, file_path, final_url, paper.landing_url or candidate.url, candidate.source)
            LOGGER.bind(paper_id=paper.paper_id, path=str(file_path), source_url=final_url).info("Downloaded PDF")
            return True, None

        media_type = _response_media_type(response)
        if media_type in HTML_MEDIA_TYPES:
            landing_url = paper.landing_url or final_url
            for pdf_url in _extract_pdf_urls(response.text, base_url=final_url):
                nested = DownloadCandidate(source=f"{candidate.source}_html", url=pdf_url, priority=candidate.priority - 1)
                nested_success, detail = self._try_candidate(paper, workspace, nested)
                if nested_success:
                    paper.landing_url = landing_url
                    return True, None
                if detail is not None:
                    self._mark_failure(paper, detail["code"], detail["message"])
            failure = _classify_http_failure(response, response.text)
            if failure:
                return False, failure
            return False, {"code": "landing_page_missing", "message": f"No PDF link found at {final_url}"}

        failure = _classify_http_failure(response, response.text if media_type.startswith("text/") else "")
        if failure:
            return False, failure
        return False, {"code": "pdf_not_found", "message": f"Unexpected non-PDF response from {candidate.url}"}

    def _store_pdf_bytes(self, workspace: TopicWorkspace, paper: PaperRecord, pdf_bytes: bytes) -> Path:
        rank_dir = workspace.rank_directory(paper.ccf_rank)
        target_path = self._resolve_target_path(rank_dir, paper)
        target_path.write_bytes(pdf_bytes)
        return target_path

    def _ensure_named_download(self, existing_path: Path, workspace: TopicWorkspace, paper: PaperRecord) -> Path:
        rank_dir = workspace.rank_directory(paper.ccf_rank)
        target_path = self._resolve_target_path(rank_dir, paper)
        if existing_path == target_path:
            return existing_path
        existing_path.replace(target_path)
        return target_path

    @staticmethod
    def _resolve_target_path(rank_dir: Path, paper: PaperRecord) -> Path:
        target_path = rank_dir / build_pdf_filename(paper)
        if not target_path.exists():
            return target_path
        return rank_dir / f"{target_path.stem}-{paper.paper_id}.pdf"

    @staticmethod
    def _mark_downloaded(
        paper: PaperRecord,
        file_path: Path,
        pdf_url: str | None,
        landing_url: str | None,
        download_source: str | None,
    ) -> None:
        now = datetime.now(timezone.utc)
        paper.pdf_url = pdf_url
        paper.landing_url = landing_url
        paper.local_pdf_path = str(file_path)
        paper.download_source = download_source
        paper.download_failure_code = None
        paper.last_error = None
        paper.status = PaperStatus.DOWNLOADED
        paper.timestamps.downloaded_at = now
        paper.timestamps.updated_at = now

    @staticmethod
    def _mark_failure(paper: PaperRecord, code: str, message: str) -> None:
        paper.download_failure_code = code
        paper.last_error = message
        paper.timestamps.updated_at = datetime.now(timezone.utc)


def _response_media_type(response: httpx.Response) -> str:
    header = response.headers.get("content-type", "")
    return header.split(";", 1)[0].strip().lower()


def _is_pdf_response(response: httpx.Response, url: str) -> bool:
    media_type = _response_media_type(response)
    if media_type in PDF_MEDIA_TYPES:
        return True
    return urlparse(url).path.lower().endswith(".pdf") and response.status_code < 400


def _extract_pdf_urls(html: str, *, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    for meta in soup.find_all("meta"):
        content = str(meta.get("content", "")).strip()
        name = str(meta.get("name", "")).strip().lower()
        prop = str(meta.get("property", "")).strip().lower()
        if content and (name == "citation_pdf_url" or prop == "citation_pdf_url"):
            candidates.append(urljoin(base_url, content))
    for tag in soup.find_all(["a", "link"]):
        href = str(tag.get("href", "")).strip()
        if not href:
            continue
        text = tag.get_text(" ", strip=True).lower()
        if "pdf" in href.lower() or "pdf" in text:
            candidates.append(urljoin(base_url, href))
    deduplicated: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            deduplicated.append(url)
    return deduplicated


def _classify_missing_candidates(paper: PaperRecord) -> str:
    if not paper.doi and not paper.landing_url:
        return "doi_missing"
    if not paper.landing_url:
        return "landing_page_missing"
    return "pdf_not_found"


def _classify_http_failure(response: httpx.Response, body: str) -> dict[str, str] | None:
    lowered = body.lower()
    if response.status_code == 403 and any(marker in lowered for marker in ["just a moment", "cloudflare", "challenge"]):
        return {"code": "403_challenge_page", "message": f"Challenge page at {response.url}"}
    if response.status_code == 418:
        return {"code": "418_rejected", "message": f"Request rejected by {response.url}"}
    if response.status_code == 404:
        return {"code": "pdf_not_found", "message": f"PDF not found at {response.url}"}
    if response.status_code >= 400:
        return {"code": "network_error", "message": f"HTTP {response.status_code} from {response.url}"}
    return None
