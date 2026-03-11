"""CLI entrypoint for literature-topic-agent."""

from __future__ import annotations

from pathlib import Path

from core.logging import configure_logging
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
            sqlite_store=SQLiteStore(workspace.database_path),
            json_store=JsonArtifactStore(workspace.artifacts_dir),
            paper_downloader=DoiPdfDownloader(
                timeout=download_timeout,
                max_request_attempts=download_attempts,
                max_workers=download_workers,
                challenge_block_threshold=challenge_block_threshold,
            ),
        )
        papers, _job = workflow.run(topic_config, workspace)
        if render_markdown:
            exporter = MarkdownReportExporter(PROJECT_ROOT / "templates")
            output = exporter.render(topic_config, papers)
            (workspace.topic_dir / "summary.md").write_text(output, encoding="utf-8")


def main() -> None:
    """Run the CLI."""

    if typer is None:  # pragma: no cover
        raise RuntimeError("typer is not installed; install project dependencies to use the CLI")
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
