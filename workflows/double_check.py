"""Double-check workflow for syncing local PDFs with the paper list."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil

from core.logging import get_logger
from download.artifacts import build_download_candidates_payload, collect_manual_pdf_paths
from download.naming import build_pdf_filename
from domain.models import DblpRawRecord, JobStageCounts, PaperRecord, PaperStatus, ProcessingJob, TopicConfig
from domain.normalization import build_paper_id, normalize_paper, normalize_title
from parse.artifacts import write_parse_artifacts
from parse.parser_service import ParserService
from providers.interfaces import AbstractVenueRankProvider
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)
YEAR_PREFIX_RE = re.compile(r"^\d{4}$")
AUTHOR_TAIL_RE = re.compile(r"\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}[∗*†‡]?$")


class DoubleCheckWorkflow:
    """Scan local PDFs, enrich metadata, and reconcile them into the paper list."""

    def __init__(
        self,
        *,
        parser_service: ParserService,
        search_provider,
        venue_rank_provider: AbstractVenueRankProvider | None,
        sqlite_store: SQLiteStore,
        json_store: JsonArtifactStore,
    ) -> None:
        self.parser_service = parser_service
        self.search_provider = search_provider
        self.venue_rank_provider = venue_rank_provider
        self.sqlite_store = sqlite_store
        self.json_store = json_store

    def run(
        self,
        *,
        topic_config: TopicConfig,
        workspace: TopicWorkspace,
        pdf_root: Path | None = None,
        force_reparse: bool = False,
    ) -> tuple[list[PaperRecord], ProcessingJob]:
        """Sync PDFs from disk into the topic paper list."""

        try:
            papers = self.json_store.load_papers()
        except FileNotFoundError:
            papers = []
        paper_by_pdf = {Path(paper.local_pdf_path).resolve(): paper for paper in papers if paper.local_pdf_path}
        paper_by_title = {normalize_title(paper.title): paper for paper in papers if paper.title}
        paper_by_doi = {paper.doi.strip().lower(): paper for paper in papers if paper.doi}
        if pdf_root is not None:
            pdf_paths = sorted(pdf_root.rglob("*.pdf"))
        else:
            pdf_paths = collect_manual_pdf_paths(topic_dir=workspace.topic_dir)
            if not pdf_paths:
                pdf_paths = sorted(workspace.topic_dir.rglob("*.pdf"))
        added = 0
        for pdf_path in pdf_paths:
            resolved_pdf = pdf_path.resolve()
            relocated_pdf = False
            paper = paper_by_pdf.get(resolved_pdf)
            if paper is None:
                built_paper = self._build_paper_from_pdf(topic_config=topic_config, pdf_path=resolved_pdf, workspace=workspace)
                paper = self._match_existing_paper(built_paper, paper_by_title=paper_by_title, paper_by_doi=paper_by_doi)
                if paper is None:
                    paper = built_paper
                    papers.append(paper)
                    added += 1
                else:
                    paper = self._merge_manual_pdf_into_existing(existing=paper, discovered=built_paper)
                paper_by_title[normalize_title(paper.title)] = paper
                if paper.doi:
                    paper_by_doi[paper.doi.strip().lower()] = paper
                paper_by_pdf[Path(paper.local_pdf_path).resolve()] = paper
                relocated_pdf = True
            else:
                relocated = self._ensure_canonical_pdf_location(workspace=workspace, paper=paper, pdf_path=resolved_pdf)
                if relocated != resolved_pdf:
                    paper.local_pdf_path = str(relocated)
                    paper_by_pdf.pop(resolved_pdf, None)
                    paper_by_pdf[relocated.resolve()] = paper
                    relocated_pdf = True
            if force_reparse or relocated_pdf or paper.status != PaperStatus.PARSED or not paper.parse_artifact_paths.get("sections"):
                assert paper.local_pdf_path is not None
                result = self.parser_service.parse_pdf(paper_id=paper.paper_id, pdf_path=Path(paper.local_pdf_path))
                paper.sections = result.to_llm_ready_sections()
                paper.section_metadata = result.to_section_metadata()
                paper.parse_warnings = list(result.warnings)
                paper.parse_artifact_paths = write_parse_artifacts(result)
                paper.status = PaperStatus.PARSED
                paper.timestamps.parsed_at = datetime.now(timezone.utc)
                paper.timestamps.updated_at = paper.timestamps.parsed_at

        job = ProcessingJob(
            topic_slug=topic_config.slug,
            total_papers=len(papers),
            processed_counts=JobStageCounts(
                discovered=len(papers),
                downloaded=sum(1 for paper in papers if paper.local_pdf_path),
                parsed=sum(1 for paper in papers if paper.status == PaperStatus.PARSED),
            ),
            eta_seconds=0,
            updated_at=datetime.now(timezone.utc),
        )
        self.sqlite_store.upsert_papers(papers)
        self.sqlite_store.save_job(job)
        self.json_store.save_papers(papers)
        self.json_store.save_json(build_download_candidates_payload(papers), "download_candidates.json")
        self.json_store.save_job(job)
        LOGGER.bind(topic=topic_config.slug, scanned=len(pdf_paths), added=added).info("Completed double-check workflow")
        return papers, job

    def _build_paper_from_pdf(self, *, topic_config: TopicConfig, pdf_path: Path, workspace: TopicWorkspace) -> PaperRecord:
        parsed = self.parser_service.parse_pdf(paper_id=f"scan-{pdf_path.stem}", pdf_path=pdf_path)
        title = parsed.title
        raw_record = self._lookup_source_metadata(title=title, pdf_path=pdf_path)
        if raw_record is not None:
            paper = normalize_paper(raw_record, topic_config.slug, [])
            if self.venue_rank_provider is not None:
                paper.ccf_rank = self.venue_rank_provider.get_rank(paper.venue, paper.dblp_url)
        else:
            year = _guess_year_from_path(pdf_path)
            paper = PaperRecord(
                paper_id=build_paper_id(title=title, year=year),
                topic_slug=topic_config.slug,
                title=title,
                authors=[],
                venue="Unknown Venue",
                year=year,
                venue_type="unknown",
                dblp_url="",
            )
        canonical_pdf_path = self._ensure_canonical_pdf_location(workspace=workspace, paper=paper, pdf_path=pdf_path)
        paper.local_pdf_path = str(canonical_pdf_path)
        paper.download_source = "manual_pdf"
        paper.status = PaperStatus.DOWNLOADED
        paper.timestamps.downloaded_at = datetime.now(timezone.utc)
        paper.timestamps.updated_at = paper.timestamps.downloaded_at
        return paper

    def _lookup_source_metadata(self, *, title: str, pdf_path: Path) -> DblpRawRecord | None:
        queries = _build_lookup_queries(title=title, pdf_path=pdf_path)
        for query in queries:
            try:
                results = self.search_provider.search(query, limit=5)
            except Exception:
                LOGGER.bind(title=title, query=query).warning("DBLP lookup failed during double-check")
                continue
            normalized_queries = {normalize_title(candidate) for candidate in queries}
            for result in results:
                if normalize_title(result.title) in normalized_queries:
                    return result
            if results:
                return results[0]
        return None

    def _match_existing_paper(
        self,
        discovered: PaperRecord,
        *,
        paper_by_title: dict[str, PaperRecord],
        paper_by_doi: dict[str, PaperRecord],
    ) -> PaperRecord | None:
        if discovered.doi:
            match = paper_by_doi.get(discovered.doi.strip().lower())
            if match is not None:
                return match
        return paper_by_title.get(normalize_title(discovered.title))

    @staticmethod
    def _merge_manual_pdf_into_existing(*, existing: PaperRecord, discovered: PaperRecord) -> PaperRecord:
        existing.title = discovered.title or existing.title
        existing.authors = discovered.authors or existing.authors
        existing.venue = discovered.venue or existing.venue
        existing.year = discovered.year or existing.year
        existing.venue_type = discovered.venue_type or existing.venue_type
        existing.ccf_rank = discovered.ccf_rank or existing.ccf_rank
        existing.dblp_url = discovered.dblp_url or existing.dblp_url
        existing.doi = discovered.doi or existing.doi
        existing.bibtex = discovered.bibtex or existing.bibtex
        existing.landing_url = discovered.landing_url or existing.landing_url
        existing.pdf_url = discovered.pdf_url or existing.pdf_url
        existing.local_pdf_path = discovered.local_pdf_path or existing.local_pdf_path
        existing.download_source = discovered.download_source or existing.download_source
        existing.download_failure_code = None
        existing.last_error = None
        existing.status = PaperStatus.DOWNLOADED
        existing.timestamps.downloaded_at = datetime.now(timezone.utc)
        existing.timestamps.updated_at = existing.timestamps.downloaded_at
        return existing

    @staticmethod
    def _ensure_canonical_pdf_location(*, workspace: TopicWorkspace, paper: PaperRecord, pdf_path: Path) -> Path:
        rank_dir = workspace.rank_directory(paper.ccf_rank)
        target = rank_dir / build_pdf_filename(paper)
        if pdf_path.resolve() == target.resolve():
            return target
        source_artifact_dir = pdf_path.with_suffix("")
        if target.exists():
            if target.read_bytes() == pdf_path.read_bytes():
                pdf_path.unlink(missing_ok=True)
                if source_artifact_dir.exists():
                    shutil.rmtree(source_artifact_dir, ignore_errors=True)
                return target
            target = rank_dir / f"{target.stem}-{paper.paper_id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.replace(target)
        if source_artifact_dir.exists():
            shutil.rmtree(source_artifact_dir, ignore_errors=True)
        return target


def _guess_year_from_path(pdf_path: Path) -> int:
    for part in (pdf_path.stem, pdf_path.name):
        for token in part.split("-"):
            if token.isdigit() and len(token) == 4:
                return int(token)
    return datetime.now(timezone.utc).year


def _build_lookup_queries(*, title: str, pdf_path: Path) -> list[str]:
    queries: list[str] = []
    for candidate in (
        title.strip(),
        _strip_author_tail(title),
        _title_from_filename(pdf_path),
    ):
        cleaned = " ".join(candidate.split())
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    return queries


def _strip_author_tail(title: str) -> str:
    stripped = title.strip()
    while True:
        updated = AUTHOR_TAIL_RE.sub("", stripped).strip(" -:")
        if updated == stripped:
            return stripped
        stripped = updated


def _title_from_filename(pdf_path: Path) -> str:
    stem = pdf_path.stem
    parts = [part.strip() for part in stem.split(" - ") if part.strip()]
    if len(parts) >= 3 and YEAR_PREFIX_RE.match(parts[1]):
        return " - ".join(parts[2:])
    if len(parts) >= 2 and YEAR_PREFIX_RE.match(parts[0]):
        return " - ".join(parts[2:] or parts[1:])
    return stem
