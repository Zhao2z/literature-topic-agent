"""Topic discovery workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.logging import get_logger
from download.interfaces import AbstractPaperDownloader
from core.ranking import assign_processing_priority, compute_rank_score
from domain.deduplication import deduplicate_papers
from domain.models import DblpRawRecord, JobStageCounts, PaperRecord, PaperStatus, ProcessingJob, TopicConfig
from domain.normalization import normalize_paper
from providers.interfaces import AbstractCitationProvider, AbstractSearchProvider, AbstractVenueRankProvider
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)


class DiscoveryWorkflow:
    """Discover, rank, and persist papers for a topic."""

    def __init__(
        self,
        search_provider: AbstractSearchProvider,
        citation_provider: AbstractCitationProvider,
        venue_rank_provider: AbstractVenueRankProvider,
        sqlite_store: SQLiteStore,
        json_store: JsonArtifactStore,
        paper_downloader: AbstractPaperDownloader | None = None,
    ) -> None:
        self.search_provider = search_provider
        self.citation_provider = citation_provider
        self.venue_rank_provider = venue_rank_provider
        self.sqlite_store = sqlite_store
        self.json_store = json_store
        self.paper_downloader = paper_downloader

    def run(self, topic_config: TopicConfig, workspace: TopicWorkspace) -> tuple[list[PaperRecord], ProcessingJob]:
        """Execute the Phase 1 discovery workflow."""

        workspace.ensure()
        raw_records = self._collect_raw_records(topic_config)
        normalized_records = self._normalize_records(raw_records, topic_config)
        deduplicated = deduplicate_papers(normalized_records)
        ranked = self._enrich_and_rank(deduplicated, topic_config)
        self._hydrate_download_state(ranked)

        job = ProcessingJob(
            topic_slug=topic_config.slug,
            total_papers=len(ranked),
            processed_counts=JobStageCounts(
                discovered=len(ranked),
                ranked=len(ranked),
            ),
            eta_seconds=0,
            updated_at=datetime.now(timezone.utc),
        )

        if self.paper_downloader is not None and topic_config.initial_parse_limit > 0:
            to_download = [paper for paper in ranked if not _is_downloaded_locally(paper)][: topic_config.initial_parse_limit]
            LOGGER.bind(
                topic=topic_config.slug,
                limit=topic_config.initial_parse_limit,
                total=len(ranked),
                pending=len(to_download),
            ).info("Starting PDF download stage")
            downloaded_count = 0
            if to_download:
                downloaded_count = self.paper_downloader.download_papers(to_download, workspace, limit=None)
            job.processed_counts.downloaded = sum(1 for paper in ranked if paper.status == PaperStatus.DOWNLOADED)
            job.updated_at = datetime.now(timezone.utc)
            LOGGER.bind(
                topic=topic_config.slug,
                attempted=len(to_download),
                successful_this_run=downloaded_count,
                downloaded_total=job.processed_counts.downloaded,
            ).info("Completed PDF download stage")

        self.sqlite_store.upsert_papers(ranked)
        self.sqlite_store.save_job(job)
        self.json_store.save_papers(ranked)
        self.json_store.save_job(job)
        return ranked, job

    def _collect_raw_records(self, topic_config: TopicConfig) -> list[tuple[DblpRawRecord, list[str]]]:
        collected: list[tuple[DblpRawRecord, list[str]]] = []
        per_group_limit = max(1, topic_config.max_candidate_count // max(1, len(topic_config.keyword_groups)))
        for group in topic_config.keyword_groups:
            query = " ".join(group)
            LOGGER.bind(query=query).info("Searching DBLP")
            try:
                records = self.search_provider.search(query, limit=per_group_limit)
            except Exception:
                LOGGER.bind(query=query).exception("Keyword group search failed")
                continue
            for record in records:
                if not _matches_year_range(record.year, topic_config):
                    continue
                collected.append((record, group))
        return collected

    def _normalize_records(
        self,
        raw_records: list[tuple[DblpRawRecord, list[str]]],
        topic_config: TopicConfig,
    ) -> list[PaperRecord]:
        normalized: list[PaperRecord] = []
        for raw_record, keyword_group in raw_records:
            normalized.append(normalize_paper(raw_record, topic_config.slug, keyword_group))
        return normalized

    def _enrich_and_rank(self, papers: list[PaperRecord], topic_config: TopicConfig) -> list[PaperRecord]:
        for paper in papers:
            paper.ccf_rank = self.venue_rank_provider.get_rank(paper.venue, paper.dblp_url)
            paper.citations = self.citation_provider.get_citations(paper.doi, paper.title)
            paper.rank_score = compute_rank_score(paper, topic_config.ranking_weights)
            paper.status = PaperStatus.RANKED
            paper.timestamps.updated_at = datetime.now(timezone.utc)
        return assign_processing_priority(papers)

    def _hydrate_download_state(self, papers: list[PaperRecord]) -> None:
        state_by_id = self.sqlite_store.load_download_state([paper.paper_id for paper in papers])
        for paper in papers:
            state = state_by_id.get(paper.paper_id)
            if state is None:
                continue
            local_pdf_path = state.get("local_pdf_path")
            if state.get("status") == PaperStatus.DOWNLOADED.value and local_pdf_path and Path(local_pdf_path).exists():
                paper.local_pdf_path = local_pdf_path
                paper.pdf_url = state.get("pdf_url")
                paper.landing_url = state.get("landing_url")
                paper.download_source = state.get("download_source")
                paper.status = PaperStatus.DOWNLOADED


def _matches_year_range(year: int, topic_config: TopicConfig) -> bool:
    if topic_config.year_range.start and year < topic_config.year_range.start:
        return False
    if topic_config.year_range.end and year > topic_config.year_range.end:
        return False
    return True


def _is_downloaded_locally(paper: PaperRecord) -> bool:
    return (
        paper.status == PaperStatus.DOWNLOADED
        and bool(paper.local_pdf_path)
        and Path(paper.local_pdf_path).exists()
    )
