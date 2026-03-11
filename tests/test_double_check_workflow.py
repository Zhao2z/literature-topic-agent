from pathlib import Path

from domain.models import DblpRawRecord, PaperStatus, TopicConfig
from parse.page_model import ParseDebugInfo, ParsedPage, ParsedSection, PdfParseResult
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace
from workflows.double_check import DoubleCheckWorkflow


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
        sqlite_store=SQLiteStore(workspace.database_path),
        json_store=JsonArtifactStore(workspace.artifacts_dir),
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, pdf_root=manual_dir)

    assert len(papers) == 1
    assert papers[0].title == "Manual Added Paper"
    assert papers[0].status == PaperStatus.PARSED
    assert Path(papers[0].parse_artifact_paths["sections"]).exists()
