"""Topic discovery workflow."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from core.logging import get_logger
from download.artifacts import build_download_candidates_payload
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
        ranked = self._merge_with_existing_papers(ranked)
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
            self._log_download_failures(topic_config.slug, to_download)
            LOGGER.bind(
                topic=topic_config.slug,
                attempted=len(to_download),
                successful_this_run=downloaded_count,
                downloaded_total=job.processed_counts.downloaded,
            ).info("Completed PDF download stage")

        self.sqlite_store.upsert_papers(ranked)
        self.sqlite_store.save_job(job)
        self.json_store.save_papers(ranked)
        self.json_store.save_json(build_download_candidates_payload(ranked), "download_candidates.json")
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

    def _merge_with_existing_papers(self, discovered_papers: list[PaperRecord]) -> list[PaperRecord]:
        try:
            existing_papers = self.json_store.load_papers()
        except FileNotFoundError:
            existing_papers = []

        if not existing_papers:
            return discovered_papers
        if not discovered_papers:
            LOGGER.bind(existing=len(existing_papers)).warning(
                "Discovery returned no papers; preserving existing paper list"
            )
            return assign_processing_priority(existing_papers)

        merged_by_id: dict[str, PaperRecord] = {
            paper.paper_id: paper.model_copy(deep=True) for paper in existing_papers
        }
        for paper in discovered_papers:
            existing = merged_by_id.get(paper.paper_id)
            if existing is None:
                merged_by_id[paper.paper_id] = paper
                continue
            merged_by_id[paper.paper_id] = _merge_existing_and_discovered(existing, paper)

        merged = list(merged_by_id.values())
        LOGGER.bind(
            existing=len(existing_papers),
            discovered=len(discovered_papers),
            merged=len(merged),
        ).info("Merged discovered papers with existing paper list")
        return assign_processing_priority(merged)

    def _log_download_failures(self, topic_slug: str, papers: list[PaperRecord]) -> None:
        failed = [paper for paper in papers if paper.status != PaperStatus.DOWNLOADED and paper.download_failure_code]
        if not failed:
            return

        counter = Counter(paper.download_failure_code for paper in failed if paper.download_failure_code)
        examples_by_code: dict[str, list[PaperRecord]] = defaultdict(list)
        for paper in failed:
            assert paper.download_failure_code is not None
            if len(examples_by_code[paper.download_failure_code]) < 3:
                examples_by_code[paper.download_failure_code].append(paper)

        LOGGER.bind(
            topic=topic_slug,
            failed=len(failed),
            failed_by_code=", ".join(f"{code}:{count}" for code, count in counter.most_common()),
        ).warning("PDF download failures summary")

        for code, count in counter.most_common():
            for paper in examples_by_code[code]:
                LOGGER.bind(
                    topic=topic_slug,
                    failure_code=code,
                    count=count,
                    paper_id=paper.paper_id,
                    title=paper.title,
                    doi=paper.doi,
                    landing_url=paper.landing_url,
                    error=paper.last_error,
                ).warning("PDF download failure example")


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


def _merge_existing_and_discovered(existing: PaperRecord, discovered: PaperRecord) -> PaperRecord:
    merged = existing.model_copy(deep=True)
    merged.topic_slug = discovered.topic_slug
    merged.title = discovered.title or merged.title
    merged.authors = discovered.authors or merged.authors
    merged.venue = discovered.venue or merged.venue
    merged.year = discovered.year or merged.year
    merged.venue_type = discovered.venue_type or merged.venue_type
    merged.ccf_rank = discovered.ccf_rank or merged.ccf_rank
    merged.dblp_url = discovered.dblp_url or merged.dblp_url
    merged.doi = discovered.doi or merged.doi
    merged.bibtex = discovered.bibtex or merged.bibtex
    merged.citations = discovered.citations if discovered.citations is not None else merged.citations
    merged.keyword_matches = sorted(set(merged.keyword_matches + discovered.keyword_matches))
    merged.download_candidates = discovered.download_candidates or merged.download_candidates
    merged.landing_url = discovered.landing_url or merged.landing_url
    merged.pdf_url = discovered.pdf_url or merged.pdf_url
    merged.rank_score = discovered.rank_score
    merged.processing_priority = discovered.processing_priority
    merged.timestamps.updated_at = datetime.now(timezone.utc)
    return merged
