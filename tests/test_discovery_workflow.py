import json
from pathlib import Path

from apps.cli import _retry_downloads_from_saved_papers
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


class EmptySearchProvider:
    def search(self, query: str, limit: int = 100) -> list[DblpRawRecord]:
        return []


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


class SelectiveDownloader:
    def __init__(self) -> None:
        self.calls = 0
        self.titles: list[str] = []

    def download_papers(self, papers, workspace: TopicWorkspace, limit: int | None = None) -> int:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.titles = [paper.title for paper in papers]
        for paper in papers:
            target = workspace.rank_directory(paper.ccf_rank) / build_pdf_filename(paper)
            target.write_bytes(b"%PDF-1.4 retry")
            paper.local_pdf_path = str(target)
            paper.status = PaperStatus.DOWNLOADED
            paper.download_failure_code = None
            paper.last_error = None
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


def test_retry_downloads_from_saved_paper_list_only_retries_failed_items(tmp_path: Path) -> None:
    topic = TopicConfig(
        topic_name="Retry Topic",
        slug="retry-topic",
        keyword_groups=[["retry"]],
        max_candidate_count=10,
        initial_parse_limit=5,
    )
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()

    sqlite_store = SQLiteStore(workspace.database_path)
    json_store = JsonArtifactStore(workspace.artifacts_dir)

    workflow = DiscoveryWorkflow(
        search_provider=FakeSearchProvider(),
        citation_provider=NullCitationProvider(),
        venue_rank_provider=FakeVenueRankProvider(),
        sqlite_store=sqlite_store,
        json_store=json_store,
        paper_downloader=CountingDownloader(),
    )
    papers, _ = workflow.run(topic, workspace)

    downloaded_paper = papers[0]
    failed_paper = downloaded_paper.model_copy(deep=True)
    failed_paper.paper_id = "paper-2"
    failed_paper.title = "Needs Retry"
    failed_paper.local_pdf_path = None
    failed_paper.status = PaperStatus.RANKED
    failed_paper.download_failure_code = "landing_page_missing"
    failed_paper.last_error = "No PDF link found"

    json_store.save_papers([downloaded_paper, failed_paper])
    sqlite_store.upsert_papers([downloaded_paper, failed_paper])

    downloader = SelectiveDownloader()
    retried_papers, job = _retry_downloads_from_saved_papers(
        topic_config=topic,
        workspace=workspace,
        json_store=json_store,
        sqlite_store=sqlite_store,
        downloader=downloader,  # type: ignore[arg-type]
        retry_failed_only=True,
        retry_limit=None,
    )

    assert downloader.calls == 1
    assert downloader.titles == ["Needs Retry"]
    assert job.processed_counts.downloaded == 2
    retried = {paper.paper_id: paper for paper in retried_papers}
    assert retried["paper-2"].status == PaperStatus.DOWNLOADED
    assert retried["paper-2"].download_failure_code is None
    assert retried["paper-2"].local_pdf_path is not None
    assert Path(retried["paper-2"].local_pdf_path).exists()
    candidates_payload = json.loads((workspace.artifacts_dir / "download_candidates.json").read_text(encoding="utf-8"))
    assert len(candidates_payload) == 2
    assert any(item["paper_id"] == "paper-2" for item in candidates_payload)


def test_workflow_preserves_existing_paper_list_when_search_returns_empty(tmp_path: Path) -> None:
    topic = TopicConfig(
        topic_name="Preserve Topic",
        slug="preserve-topic",
        keyword_groups=[["preserve"]],
        max_candidate_count=10,
        initial_parse_limit=5,
    )
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()

    sqlite_store = SQLiteStore(workspace.database_path)
    json_store = JsonArtifactStore(workspace.artifacts_dir)

    first_workflow = DiscoveryWorkflow(
        search_provider=FakeSearchProvider(),
        citation_provider=NullCitationProvider(),
        venue_rank_provider=FakeVenueRankProvider(),
        sqlite_store=sqlite_store,
        json_store=json_store,
        paper_downloader=CountingDownloader(),
    )
    first_papers, _ = first_workflow.run(topic, workspace)
    assert len(first_papers) == 1

    second_workflow = DiscoveryWorkflow(
        search_provider=EmptySearchProvider(),
        citation_provider=NullCitationProvider(),
        venue_rank_provider=FakeVenueRankProvider(),
        sqlite_store=sqlite_store,
        json_store=json_store,
        paper_downloader=CountingDownloader(),
    )
    second_papers, _ = second_workflow.run(topic, workspace)

    assert len(second_papers) == 1
    assert second_papers[0].paper_id == first_papers[0].paper_id

    persisted = json_store.load_papers()
    assert len(persisted) == 1
    assert persisted[0].paper_id == first_papers[0].paper_id
