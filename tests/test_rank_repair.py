from pathlib import Path

from domain.models import PaperRecord, PaperStatus, TopicConfig
from providers.ccf import LocalCcfRankProvider
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace
from workflows.rank_repair import RankRepairWorkflow


def test_rank_repair_moves_paper_out_of_unranked(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)

    pdf_path = workspace.rank_directory("Unranked") / "2025-TSE-Paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    artifact_dir = pdf_path.with_suffix("")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "sections.json").write_text("{}", encoding="utf-8")
    paper = PaperRecord(
        paper_id="paper-1",
        topic_slug="topic",
        title="Paper",
        authors=["Alice"],
        venue="IEEE Trans. Software Eng.",
        year=2025,
        dblp_url="https://dblp.org/rec/journals/tse/HayetSd25",
        ccf_rank="Unranked",
        local_pdf_path=str(pdf_path),
        status=PaperStatus.PARSED,
        parse_artifact_paths={"sections": str((artifact_dir / "sections.json").resolve())},
    )
    json_store.save_papers([paper])
    sqlite_store.upsert_papers([paper])

    mapping_path = tmp_path / "ccf.json"
    mapping_path.write_text('{"TSE":"A"}', encoding="utf-8")
    workflow = RankRepairWorkflow(
        venue_rank_provider=LocalCcfRankProvider(mapping_path),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers = workflow.run(workspace=workspace)

    updated = papers[0]
    assert updated.ccf_rank == "A"
    assert "/papers/CCF-A/" in updated.local_pdf_path
    assert Path(updated.local_pdf_path).exists()
    assert "/papers/CCF-A/" in updated.parse_artifact_paths["sections"]
