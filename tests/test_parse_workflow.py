from pathlib import Path

from domain.models import PaperRecord, PaperStatus, TopicConfig
from parse.page_model import ParseDebugInfo, ParsedPage, ParsedSection, PdfParseResult
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace
from workflows.parse import ParseWorkflow


class FakeParserService:
    def parse_pdf(self, *, paper_id: str, pdf_path: Path) -> PdfParseResult:
        return PdfParseResult(
            paper_id=paper_id,
            file_path=str(pdf_path),
            backend="fake",
            parser_version="0.1",
            title="A Parser Paper",
            page_count=1,
            pages=[ParsedPage(page_number=1, text="Example text", lines=[])],
            sections=[
                ParsedSection(
                    title="Abstract",
                    canonical_name="abstract",
                    start_page=1,
                    end_page=1,
                    content="This is the abstract.",
                )
            ],
            warnings=["minor_warning"],
            debug=ParseDebugInfo(warning_flags=["minor_warning"]),
        )


def test_parse_workflow_updates_status_and_artifacts(tmp_path: Path) -> None:
    topic = TopicConfig(
        topic_name="Parse Topic",
        slug="parse-topic",
        keyword_groups=[["parse"]],
    )
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    sqlite_store = SQLiteStore(workspace.database_path)
    json_store = JsonArtifactStore(workspace.artifacts_dir)

    pdf_path = workspace.rank_directory("A") / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    paper = PaperRecord(
        paper_id="paper-1",
        topic_slug=topic.slug,
        title="A Parser Paper",
        authors=["Alice"],
        venue="ICSE",
        year=2025,
        dblp_url="https://dblp.org/rec/conf/icse/1",
        ccf_rank="A",
        local_pdf_path=str(pdf_path),
        status=PaperStatus.DOWNLOADED,
    )
    json_store.save_papers([paper])
    sqlite_store.upsert_papers([paper])

    workflow = ParseWorkflow(
        parser_service=FakeParserService(),  # type: ignore[arg-type]
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers, job = workflow.run(topic_config=topic, workspace=workspace, top_n=20)

    assert papers[0].status == PaperStatus.PARSED
    assert papers[0].sections == {"abstract": "This is the abstract."}
    assert "sections" in papers[0].parse_artifact_paths
    assert Path(papers[0].parse_artifact_paths["sections"]).exists()
    assert job.processed_counts.parsed == 1
