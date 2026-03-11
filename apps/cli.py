"""CLI entrypoint for literature-topic-agent."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.logging import configure_logging
from core.logging import get_logger
from domain.models import JobStageCounts, PaperStatus, ProcessingJob
from download.pdf import DoiPdfDownloader
from exporters.markdown import MarkdownReportExporter
from providers.ccf import LocalCcfRankProvider
from providers.citations import NullCitationProvider
from providers.dblp import DblpSearchClient
from providers.google_scholar import GoogleScholarSearchClient
from providers.search import FallbackSearchProvider
from providers.semantic_scholar import SemanticScholarSearchClient
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.loader import load_topic_config
from topic.workspace import TopicWorkspace
from workflows.discovery import DiscoveryWorkflow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGGER = get_logger(__name__)

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None


if typer is not None:
    app = typer.Typer(add_completion=False, help="Topic-driven literature discovery.")

    @app.command("discover")
    def discover(
        config_path: Path,
        workspace_root: Path = Path("workspace"),
        ccf_mapping_path: Path = PROJECT_ROOT / "config" / "ccf_venues.json",
        render_markdown: bool = True,
        reuse_paper_list: bool = False,
        retry_failed_only: bool = True,
        retry_limit: int | None = None,
        download_timeout: float = 120.0,
        download_attempts: int = 5,
        download_workers: int = 4,
        challenge_block_threshold: int = 3,
    ) -> None:
        """Run discovery for a topic config."""

        topic_config = load_topic_config(config_path)
        workspace = TopicWorkspace(workspace_root, topic_config)
        workspace.ensure()
        configure_logging(log_file=workspace.logs_dir / "run.log")
        json_store = JsonArtifactStore(workspace.artifacts_dir)
        sqlite_store = SQLiteStore(workspace.database_path)
        downloader = DoiPdfDownloader(
            timeout=download_timeout,
            max_request_attempts=download_attempts,
            max_workers=download_workers,
            challenge_block_threshold=challenge_block_threshold,
        )

        search_client = FallbackSearchProvider(
            [
                DblpSearchClient(),
                SemanticScholarSearchClient(),
                GoogleScholarSearchClient(),
            ]
        )
        workflow = DiscoveryWorkflow(
            search_provider=search_client,
            citation_provider=NullCitationProvider(),
            venue_rank_provider=LocalCcfRankProvider(ccf_mapping_path),
            sqlite_store=sqlite_store,
            json_store=json_store,
            paper_downloader=downloader,
        )
        if reuse_paper_list:
            papers, _job = _retry_downloads_from_saved_papers(
                topic_config=topic_config,
                workspace=workspace,
                json_store=json_store,
                sqlite_store=sqlite_store,
                downloader=downloader,
                retry_failed_only=retry_failed_only,
                retry_limit=retry_limit,
            )
        else:
            papers, _job = workflow.run(topic_config, workspace)
        if render_markdown:
            exporter = MarkdownReportExporter(PROJECT_ROOT / "templates")
            output = exporter.render(topic_config, papers)
            (workspace.topic_dir / "summary.md").write_text(output, encoding="utf-8")


def _retry_downloads_from_saved_papers(
    *,
    topic_config,
    workspace: TopicWorkspace,
    json_store: JsonArtifactStore,
    sqlite_store: SQLiteStore,
    downloader: DoiPdfDownloader,
    retry_failed_only: bool,
    retry_limit: int | None,
) -> tuple[list, ProcessingJob]:
    papers = json_store.load_papers()
    for paper in papers:
        if (
            paper.status == PaperStatus.DOWNLOADED
            and paper.local_pdf_path
            and Path(paper.local_pdf_path).exists()
        ):
            continue
        if paper.status == PaperStatus.DOWNLOADED:
            paper.status = PaperStatus.RANKED

    pending = [
        paper
        for paper in papers
        if (
            paper.status != PaperStatus.DOWNLOADED
            or not paper.local_pdf_path
            or not Path(paper.local_pdf_path).exists()
        )
        and (not retry_failed_only or bool(paper.download_failure_code))
    ]
    if retry_limit is not None and retry_limit > 0:
        pending = pending[:retry_limit]

    LOGGER.bind(
        topic=topic_config.slug,
        total=len(papers),
        pending=len(pending),
        retry_failed_only=retry_failed_only,
        retry_limit=retry_limit,
    ).info("Starting saved paper list download retry")

    now = datetime.now(timezone.utc)
    job = ProcessingJob(
        topic_slug=topic_config.slug,
        total_papers=len(papers),
        processed_counts=JobStageCounts(
            discovered=len(papers),
            ranked=len(papers),
            downloaded=sum(
                1
                for paper in papers
                if paper.status == PaperStatus.DOWNLOADED
                and paper.local_pdf_path
                and Path(paper.local_pdf_path).exists()
            ),
        ),
        eta_seconds=0,
        updated_at=now,
    )

    if pending:
        downloader.download_papers(pending, workspace, limit=None)
    else:
        LOGGER.bind(
            topic=topic_config.slug,
            total=len(papers),
            retry_failed_only=retry_failed_only,
        ).info("No papers matched retry filter")

    job.processed_counts.downloaded = sum(
        1
        for paper in papers
        if paper.status == PaperStatus.DOWNLOADED
        and paper.local_pdf_path
        and Path(paper.local_pdf_path).exists()
    )
    job.updated_at = datetime.now(timezone.utc)
    sqlite_store.upsert_papers(papers)
    sqlite_store.save_job(job)
    json_store.save_papers(papers)
    json_store.save_job(job)
    LOGGER.bind(
        topic=topic_config.slug,
        attempted=len(pending),
        downloaded_total=job.processed_counts.downloaded,
    ).info("Completed saved paper list download retry")
    return papers, job


def main() -> None:
    """Run the CLI."""

    if typer is None:  # pragma: no cover
        raise RuntimeError("typer is not installed; install project dependencies to use the CLI")
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
