"""CLI entrypoint for literature-topic-agent."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from core.logging import configure_logging
from core.logging import get_logger
from domain.models import JobStageCounts, PaperStatus, ProcessingJob
from download.pdf import DoiPdfDownloader
from exporters.markdown import MarkdownReportExporter
from parse.parser_service import ParserService
from parse.pdf_loader import build_pdf_backend
from parse.text_extractor import PageTextExtractor
from providers.ccf import LocalCcfRankProvider
from providers.citations import NullCitationProvider
from providers.dblp import DblpSearchClient
from providers.google_scholar import GoogleScholarSearchClient
from providers.search import FallbackSearchProvider
from providers.semantic_scholar import SemanticScholarSearchClient
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from domain.models import TopicConfig
from summarize.analyzer import PaperAnalyzer
from summarize.mimo_client import MimoClient
from summarize.renderer import AnalysisRenderer
from topic.loader import load_topic_config
from topic.workspace import TopicWorkspace
from workflows.discovery import DiscoveryWorkflow
from workflows.parse import ParseWorkflow
from summarize.workflow import AnalysisWorkflow, SurveyBuilder
from workflows.double_check import DoubleCheckWorkflow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGGER = get_logger(__name__)
WORKSPACE_ENV_VAR = "LTA_WORKSPACE_ROOT"

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None


if typer is not None:
    app = typer.Typer(add_completion=False, help="Topic-driven literature discovery.")
    topic_app = typer.Typer(add_completion=False, help="Operate on an existing topic workspace.")

    @app.command("discover")
    def discover(
        config_path: Path,
        workspace_root: Path = typer.Option(
            Path("workspace"),
            "--workspace-root",
            envvar=WORKSPACE_ENV_VAR,
            help="Workspace root containing topic directories. Supports LTA_WORKSPACE_ROOT.",
        ),
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

    @topic_app.command("parse")
    def parse_topic(
        topic: str = typer.Option(..., "--topic", help="Topic slug under the workspace root."),
        workspace_root: Path = typer.Option(
            Path("workspace"),
            "--workspace-root",
            envvar=WORKSPACE_ENV_VAR,
            help="Workspace root containing topic directories. Supports LTA_WORKSPACE_ROOT.",
        ),
        top_n: int = typer.Option(20, min=1, help="Parse at most this many papers by priority."),
        paper_id: str | None = typer.Option(None, help="Parse only the specified paper."),
        force: bool = typer.Option(False, help="Re-parse papers even if they are already marked parsed."),
        backend: str = typer.Option("pymupdf", help="Parser backend to use, e.g. pymupdf or marker."),
        preview_full: bool = typer.Option(False, help="Write full section content to the Markdown preview."),
    ) -> None:
        """Parse downloaded PDFs for an existing topic workspace."""

        topic_config = _load_workspace_topic_config(workspace_root=workspace_root, topic_slug=topic)
        workspace = TopicWorkspace(workspace_root, topic_config)
        workspace.ensure()
        configure_logging(log_file=workspace.logs_dir / "parse.log")
        json_store = JsonArtifactStore(workspace.artifacts_dir)
        sqlite_store = SQLiteStore(workspace.database_path)
        parser_service = ParserService(PageTextExtractor(build_pdf_backend(backend)))
        workflow = ParseWorkflow(
            parser_service=parser_service,
            sqlite_store=sqlite_store,
            json_store=json_store,
        )
        workflow.run(
            topic_config=topic_config,
            workspace=workspace,
            top_n=top_n,
            paper_id=paper_id,
            force=force,
            preview_full_content=preview_full,
        )

    @topic_app.command("analyze")
    def analyze_topic(
        topic: str = typer.Option(..., "--topic", help="Topic slug under the workspace root."),
        workspace_root: Path = typer.Option(
            Path("workspace"),
            "--workspace-root",
            envvar=WORKSPACE_ENV_VAR,
            help="Workspace root containing topic directories. Supports LTA_WORKSPACE_ROOT.",
        ),
        top_n: int = typer.Option(20, min=1, help="Analyze at most this many papers."),
        ccf: str = typer.Option("A,B", "--ccf", help="Comma-separated CCF ranks to prioritize, e.g. A,B."),
        model: str = typer.Option("mimo-v2-flash", help="LLM model name."),
        force: bool = typer.Option(False, help="Re-analyze papers that already have analysis artifacts."),
    ) -> None:
        """Run structured LLM analysis for parsed papers."""

        topic_config = _load_workspace_topic_config(workspace_root=workspace_root, topic_slug=topic)
        workspace = TopicWorkspace(workspace_root, topic_config)
        workspace.ensure()
        configure_logging(log_file=workspace.logs_dir / "analyze.log")
        json_store = JsonArtifactStore(workspace.artifacts_dir)
        sqlite_store = SQLiteStore(workspace.database_path)
        renderer = AnalysisRenderer(PROJECT_ROOT / "templates")
        workflow = AnalysisWorkflow(
            analyzer=PaperAnalyzer(llm_client=MimoClient(), model_name=model),
            renderer=renderer,
            sqlite_store=sqlite_store,
            json_store=json_store,
        )
        workflow.run(
            topic_config=topic_config,
            workspace=workspace,
            top_n=top_n,
            allowed_ccf=_parse_ccf_filter(ccf),
            force=force,
        )

    @topic_app.command("survey-build")
    def survey_build(
        topic: str = typer.Option(..., "--topic", help="Topic slug under the workspace root."),
        workspace_root: Path = typer.Option(
            Path("workspace"),
            "--workspace-root",
            envvar=WORKSPACE_ENV_VAR,
            help="Workspace root containing topic directories. Supports LTA_WORKSPACE_ROOT.",
        ),
    ) -> None:
        """Build the grouped survey LaTeX report from analyzed papers."""

        topic_config = _load_workspace_topic_config(workspace_root=workspace_root, topic_slug=topic)
        workspace = TopicWorkspace(workspace_root, topic_config)
        workspace.ensure()
        configure_logging(log_file=workspace.logs_dir / "survey.log")
        json_store = JsonArtifactStore(workspace.artifacts_dir)
        papers = json_store.load_papers()
        builder = SurveyBuilder(renderer=AnalysisRenderer(PROJECT_ROOT / "templates"), template_root=PROJECT_ROOT / "templates")
        builder.build(topic_config=topic_config, workspace=workspace, papers=papers)

    @topic_app.command("double-check")
    def double_check_topic(
        topic: str = typer.Option(..., "--topic", help="Topic slug under the workspace root."),
        workspace_root: Path = typer.Option(
            Path("workspace"),
            "--workspace-root",
            envvar=WORKSPACE_ENV_VAR,
            help="Workspace root containing topic directories. Supports LTA_WORKSPACE_ROOT.",
        ),
        pdf_dir: Path | None = typer.Option(None, "--pdf-dir", help="Optional PDF root to scan. Defaults to the whole topic directory."),
        backend: str = typer.Option("pymupdf", help="Parser backend to use."),
        force_reparse: bool = typer.Option(False, help="Re-parse PDFs even if they already have parse artifacts."),
    ) -> None:
        """Scan local PDFs, enrich metadata, and sync them into the paper list."""

        topic_config = _load_workspace_topic_config(workspace_root=workspace_root, topic_slug=topic)
        workspace = TopicWorkspace(workspace_root, topic_config)
        workspace.ensure()
        configure_logging(log_file=workspace.logs_dir / "double-check.log")
        json_store = JsonArtifactStore(workspace.artifacts_dir)
        sqlite_store = SQLiteStore(workspace.database_path)
        parser_service = ParserService(PageTextExtractor(build_pdf_backend(backend)))
        workflow = DoubleCheckWorkflow(
            parser_service=parser_service,
            search_provider=DblpSearchClient(),
            sqlite_store=sqlite_store,
            json_store=json_store,
        )
        workflow.run(
            topic_config=topic_config,
            workspace=workspace,
            pdf_root=pdf_dir,
            force_reparse=force_reparse,
        )

    @topic_app.command("survey-compile")
    def survey_compile(
        topic: str = typer.Option(..., "--topic", help="Topic slug under the workspace root."),
        workspace_root: Path = typer.Option(
            Path("workspace"),
            "--workspace-root",
            envvar=WORKSPACE_ENV_VAR,
            help="Workspace root containing topic directories. Supports LTA_WORKSPACE_ROOT.",
        ),
        engine: str = typer.Option("latexmk", help="Compiler executable. `latexmk` defaults to `latexmk -xelatex`."),
    ) -> None:
        """Compile the generated survey LaTeX locally."""

        topic_config = _load_workspace_topic_config(workspace_root=workspace_root, topic_slug=topic)
        workspace = TopicWorkspace(workspace_root, topic_config)
        survey_dir = workspace.reports_dir / "survey"
        if engine == "latexmk":
            command = [engine, "-xelatex", "main.tex"]
        else:
            command = [engine, "main.tex"]
        subprocess.run(command, cwd=survey_dir, check=True)

    app.add_typer(topic_app, name="topic")


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


def _load_workspace_topic_config(*, workspace_root: Path, topic_slug: str) -> TopicConfig:
    topic_path = workspace_root / topic_slug / "topic.json"
    return load_topic_config(topic_path)


def _parse_ccf_filter(raw_value: str) -> set[str]:
    values = {item.strip().upper() for item in raw_value.split(",") if item.strip()}
    normalized: set[str] = set()
    for value in values:
        if value == "UNRANKED":
            normalized.add("Unranked")
        else:
            normalized.add(value)
    return normalized


if __name__ == "__main__":  # pragma: no cover
    main()
