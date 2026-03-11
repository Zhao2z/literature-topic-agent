from pathlib import Path

from domain.models import DblpRawRecord, PaperStatus, TopicConfig
from download.naming import build_pdf_filename
from providers.citations import NullCitationProvider
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from topic.workspace import TopicWorkspace
from workflows.discovery import DiscoveryWorkflow


class FakeSearchProvider:
    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        return [
            DblpRawRecord(
                title="A Study on Download Cache",
                authors=["Alice"],
                venue="ICSE",
                year=2025,
                dblp_url="https://dblp.org/rec/conf/icse/cache",
                doi="10.1000/cache-paper",
                venue_type="conference",
            )
        ]


class FakeVenueRankProvider:
    def get_rank(self, venue: str, dblp_url: str | None = None) -> str:
        return "A"


class CountingDownloader:
    def __init__(self) -> None:
        self.calls = 0
        self.last_batch_size = 0

    def download_papers(self, papers, workspace: TopicWorkspace, limit: int | None = None) -> int:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.last_batch_size = len(papers)
        for paper in papers:
            target = workspace.rank_directory(paper.ccf_rank) / build_pdf_filename(paper)
            target.write_bytes(b"%PDF-1.4 cache")
            paper.local_pdf_path = str(target)
            paper.status = PaperStatus.DOWNLOADED
        return len(papers)


def test_workflow_skips_download_when_record_and_file_exist(tmp_path: Path) -> None:
    topic = TopicConfig(
        topic_name="Download Cache",
        slug="download-cache",
        keyword_groups=[["download", "cache"]],
        max_candidate_count=10,
        initial_parse_limit=5,
    )
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()

    sqlite_store = SQLiteStore(workspace.database_path)
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    downloader = CountingDownloader()

    workflow = DiscoveryWorkflow(
        search_provider=FakeSearchProvider(),
        citation_provider=NullCitationProvider(),
        venue_rank_provider=FakeVenueRankProvider(),
        sqlite_store=sqlite_store,
        json_store=json_store,
        paper_downloader=downloader,
    )

    papers_first, _ = workflow.run(topic, workspace)
    assert downloader.calls == 1
    assert downloader.last_batch_size == 1
    assert papers_first[0].status == PaperStatus.DOWNLOADED
    assert papers_first[0].local_pdf_path is not None
    assert Path(papers_first[0].local_pdf_path).exists()

    papers_second, _ = workflow.run(topic, workspace)
    assert downloader.calls == 1
    assert papers_second[0].status == PaperStatus.DOWNLOADED
    assert papers_second[0].local_pdf_path is not None
    assert Path(papers_second[0].local_pdf_path).exists()
