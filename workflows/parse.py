"""PDF parsing workflow for downloaded papers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.logging import get_logger
from domain.models import JobStageCounts, PaperRecord, PaperStatus, ProcessingJob, TopicConfig
from parse.artifacts import write_parse_artifacts
from parse.parser_service import ParserService
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)


class ParseWorkflow:
    """Parse downloaded PDFs and persist structured section artifacts."""

    def __init__(
        self,
        *,
        parser_service: ParserService,
        sqlite_store: SQLiteStore,
        json_store: JsonArtifactStore,
    ) -> None:
        self.parser_service = parser_service
        self.sqlite_store = sqlite_store
        self.json_store = json_store

    def run(
        self,
        *,
        topic_config: TopicConfig,
        workspace: TopicWorkspace,
        top_n: int = 20,
        paper_id: str | None = None,
        force: bool = False,
        preview_full_content: bool = False,
    ) -> tuple[list[PaperRecord], ProcessingJob]:
        """Parse eligible downloaded papers for a topic workspace."""

        try:
            papers = self.json_store.load_papers()
        except FileNotFoundError:
            papers = []
        candidates = self._select_candidates(papers, top_n=top_n, paper_id=paper_id, force=force)
        LOGGER.bind(
            topic=topic_config.slug,
            total=len(papers),
            candidates=len(candidates),
            force=force,
            paper_id=paper_id,
        ).info("Starting parse workflow")

        parsed_count = 0
        for paper in candidates:
            assert paper.local_pdf_path is not None
            pdf_path = Path(paper.local_pdf_path)
            if not pdf_path.exists():
                paper.last_error = f"PDF file not found: {pdf_path}"
                paper.parse_warnings = ["missing_local_pdf"]
                continue
            try:
                result = self.parser_service.parse_pdf(paper_id=paper.paper_id, pdf_path=pdf_path)
                paper.sections = result.to_llm_ready_sections()
                paper.section_metadata = result.to_section_metadata()
                paper.parse_warnings = list(result.warnings)
                paper.parse_artifact_paths = write_parse_artifacts(
                    result,
                    preview_full_content=preview_full_content,
                )
                paper.status = PaperStatus.PARSED
                paper.last_error = None
                paper.timestamps.parsed_at = datetime.now(timezone.utc)
                paper.timestamps.updated_at = paper.timestamps.parsed_at
                parsed_count += 1
            except Exception as exc:
                LOGGER.bind(paper_id=paper.paper_id, pdf_path=str(pdf_path)).exception("PDF parse failed")
                paper.last_error = str(exc)
                if not paper.parse_warnings:
                    paper.parse_warnings = ["parse_failed"]

        job = ProcessingJob(
            topic_slug=topic_config.slug,
            total_papers=len(papers),
            processed_counts=_build_stage_counts(papers),
            eta_seconds=0,
            updated_at=datetime.now(timezone.utc),
        )
        LOGGER.bind(
            topic=topic_config.slug,
            attempted=len(candidates),
            parsed_count=parsed_count,
            parsed_total=job.processed_counts.parsed,
        ).info("Completed parse workflow")
        self.sqlite_store.upsert_papers(papers)
        self.sqlite_store.save_job(job)
        self.json_store.save_papers(papers)
        self.json_store.save_job(job)
        return papers, job

    def _select_candidates(
        self,
        papers: list[PaperRecord],
        *,
        top_n: int,
        paper_id: str | None,
        force: bool,
    ) -> list[PaperRecord]:
        filtered = [paper for paper in papers if paper.local_pdf_path]
        if paper_id is not None:
            filtered = [paper for paper in filtered if paper.paper_id == paper_id]
        else:
            filtered.sort(key=lambda item: item.processing_priority)
        candidates = [paper for paper in filtered if force or paper.status == PaperStatus.DOWNLOADED]
        if paper_id is None and top_n > 0:
            candidates = candidates[:top_n]
        return candidates


def _build_stage_counts(papers: list[PaperRecord]) -> JobStageCounts:
    return JobStageCounts(
        discovered=len(papers),
        ranked=sum(1 for paper in papers if paper.status in {PaperStatus.RANKED, PaperStatus.DOWNLOADED, PaperStatus.PARSED, PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        downloaded=sum(1 for paper in papers if paper.local_pdf_path and Path(paper.local_pdf_path).exists()),
        parsed=sum(1 for paper in papers if paper.status in {PaperStatus.PARSED, PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        summarized=sum(1 for paper in papers if paper.status in {PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        exported=sum(1 for paper in papers if paper.status == PaperStatus.EXPORTED),
        failed=sum(1 for paper in papers if paper.status == PaperStatus.FAILED),
    )
