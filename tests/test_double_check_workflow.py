from pathlib import Path

from domain.models import DblpRawRecord, PaperStatus, TopicConfig
from parse.page_model import ParseDebugInfo, ParsedPage, ParsedSection, PdfParseResult
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace
from workflows.double_check import DoubleCheckWorkflow, _build_lookup_queries


class FakeParserService:
    def parse_pdf(self, *, paper_id: str, pdf_path: Path) -> PdfParseResult:
        return PdfParseResult(
            paper_id=paper_id,
            file_path=str(pdf_path),
            backend="fake",
            parser_version="0.1",
            title="Manual Added Paper",
            page_count=1,
            pages=[ParsedPage(page_number=1, text="Example", lines=[])],
            sections=[
                ParsedSection(
                    title="Abstract",
                    canonical_name="abstract",
                    start_page=1,
                    end_page=1,
                    content="Abstract content",
                )
            ],
            debug=ParseDebugInfo(),
        )


class FakeSearchProvider:
    def search(self, query: str, limit: int = 5):  # type: ignore[no-untyped-def]
        return [
            DblpRawRecord(
                title="Manual Added Paper",
                authors=["Alice"],
                venue="ICSE",
                year=2025,
                dblp_url="https://dblp.org/rec/conf/icse/manual25",
            )
        ]


class FakeVenueRankProvider:
    def get_rank(self, venue: str, dblp_url: str | None = None) -> str:
        return "A"


def test_double_check_adds_manual_pdf_to_paper_list(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    manual_dir = workspace.topic_dir / "manual-pdfs"
    manual_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = manual_dir / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    workflow = DoubleCheckWorkflow(
        parser_service=FakeParserService(),  # type: ignore[arg-type]
        search_provider=FakeSearchProvider(),
        venue_rank_provider=FakeVenueRankProvider(),  # type: ignore[arg-type]
        sqlite_store=SQLiteStore(workspace.database_path),
        json_store=JsonArtifactStore(workspace.artifacts_dir),
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, pdf_root=manual_dir)

    assert len(papers) == 1
    assert papers[0].title == "Manual Added Paper"
    assert papers[0].status == PaperStatus.PARSED
    assert papers[0].download_source == "manual_pdf"
    assert "/papers/CCF-A/" in papers[0].local_pdf_path
    assert Path(papers[0].parse_artifact_paths["sections"]).exists()
    assert (workspace.artifacts_dir / "download_candidates.json").exists()


def test_double_check_defaults_to_manual_pdfs_directory(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    pdf_path = workspace.manual_pdfs_dir / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    workflow = DoubleCheckWorkflow(
        parser_service=FakeParserService(),  # type: ignore[arg-type]
        search_provider=FakeSearchProvider(),
        venue_rank_provider=FakeVenueRankProvider(),  # type: ignore[arg-type]
        sqlite_store=SQLiteStore(workspace.database_path),
        json_store=JsonArtifactStore(workspace.artifacts_dir),
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace)

    assert len(papers) == 1
    assert "/papers/CCF-A/" in papers[0].local_pdf_path
    assert not pdf_path.exists()


def test_build_lookup_queries_uses_filename_title_variant() -> None:
    pdf_path = Path("/tmp/Wang 等 - 2024 - HITS High-coverage LLM-based Unit Test Generation via Method Slicing.pdf")

    queries = _build_lookup_queries(
        title="HITS: High-coverage LLM-based Unit Test Generation via Method Zejun Wang∗",
        pdf_path=pdf_path,
    )

    assert "HITS High-coverage LLM-based Unit Test Generation via Method Slicing" in queries
