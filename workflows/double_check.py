"""Double-check workflow for syncing local PDFs with the paper list."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.logging import get_logger
from domain.models import DblpRawRecord, JobStageCounts, PaperRecord, PaperStatus, ProcessingJob, TopicConfig
from domain.normalization import build_paper_id, normalize_paper, normalize_title
from parse.artifacts import write_parse_artifacts
from parse.parser_service import ParserService
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)


class DoubleCheckWorkflow:
    """Scan local PDFs, enrich metadata, and reconcile them into the paper list."""

    def __init__(
        self,
        *,
        parser_service: ParserService,
        search_provider,
        sqlite_store: SQLiteStore,
        json_store: JsonArtifactStore,
    ) -> None:
        self.parser_service = parser_service
        self.search_provider = search_provider
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
        pdf_paths = sorted((pdf_root or workspace.topic_dir).rglob("*.pdf"))
        added = 0
        for pdf_path in pdf_paths:
            resolved_pdf = pdf_path.resolve()
            paper = paper_by_pdf.get(resolved_pdf)
            if paper is None:
                paper = self._build_paper_from_pdf(topic_config=topic_config, pdf_path=resolved_pdf)
                papers.append(paper)
                paper_by_pdf[resolved_pdf] = paper
                added += 1
            if force_reparse or paper.status != PaperStatus.PARSED or not paper.parse_artifact_paths.get("sections"):
                result = self.parser_service.parse_pdf(paper_id=paper.paper_id, pdf_path=resolved_pdf)
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
        self.json_store.save_job(job)
        LOGGER.bind(topic=topic_config.slug, scanned=len(pdf_paths), added=added).info("Completed double-check workflow")
        return papers, job

    def _build_paper_from_pdf(self, *, topic_config: TopicConfig, pdf_path: Path) -> PaperRecord:
        parsed = self.parser_service.parse_pdf(paper_id=f"scan-{pdf_path.stem}", pdf_path=pdf_path)
        title = parsed.title
        raw_record = self._lookup_source_metadata(title=title)
        if raw_record is not None:
            paper = normalize_paper(raw_record, topic_config.slug, [])
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
        paper.local_pdf_path = str(pdf_path)
        paper.status = PaperStatus.DOWNLOADED
        paper.timestamps.downloaded_at = datetime.now(timezone.utc)
        paper.timestamps.updated_at = paper.timestamps.downloaded_at
        return paper

    def _lookup_source_metadata(self, *, title: str) -> DblpRawRecord | None:
        try:
            results = self.search_provider.search(title, limit=5)
        except Exception:
            LOGGER.bind(title=title).warning("DBLP lookup failed during double-check")
            return None
        normalized = normalize_title(title)
        for result in results:
            if normalize_title(result.title) == normalized:
                return result
        return results[0] if results else None


def _guess_year_from_path(pdf_path: Path) -> int:
    for part in (pdf_path.stem, pdf_path.name):
        for token in part.split("-"):
            if token.isdigit() and len(token) == 4:
                return int(token)
    return datetime.now(timezone.utc).year
