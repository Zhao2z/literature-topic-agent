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
        ccf_mapping_path: Path = PROJECT_ROOT / "temp" / "CCFrank4dblp" / "data",
        render_markdown: bool = True,
    ) -> None:
        """Run discovery for a topic config."""

        configure_logging()
        topic_config = load_topic_config(config_path)
        workspace = TopicWorkspace(workspace_root, topic_config)
        workspace.ensure()

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
            paper_downloader=DoiPdfDownloader(),
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
