from pathlib import Path

import httpx

from domain.models import DownloadCandidate, PaperRecord, TopicConfig
from download.candidate_builder import DownloadCandidateBuilder
from download.downloader import CandidateDownloader, _extract_pdf_urls
from download.naming import build_pdf_filename
from topic.workspace import TopicWorkspace


def build_paper(**overrides: object) -> PaperRecord:
    payload = {
        "paper_id": "paper-1",
        "topic_slug": "topic",
        "title": "A Study on PDF Downloads",
        "authors": ["Alice"],
        "venue": "ICSE",
        "year": 2025,
        "dblp_url": "https://dblp.org/rec/conf/icse/1",
        "ccf_rank": "A",
        "doi": "10.1000/example",
        "processing_priority": 1,
    }
    payload.update(overrides)
    return PaperRecord(**payload)


def build_workspace(tmp_path: Path) -> TopicWorkspace:
    topic = TopicConfig(
        topic_name="Topic",
        slug="topic",
        keyword_groups=[["test"]],
        initial_parse_limit=5,
    )
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    return workspace


def test_extract_pdf_urls_prefers_meta_and_links() -> None:
    html = """
    <html>
      <head>
        <meta name="citation_pdf_url" content="/download/paper.pdf">
      </head>
      <body>
        <a href="files/appendix.pdf">PDF</a>
      </body>
    </html>
    """

    urls = _extract_pdf_urls(html, base_url="https://example.org/article")

    assert urls == [
        "https://example.org/download/paper.pdf",
        "https://example.org/files/appendix.pdf",
    ]


def test_build_pdf_filename_uses_priority_id_and_title() -> None:
    paper = build_paper()

    filename = build_pdf_filename(paper)

    assert filename == "2025-ICSE-A_Study_on_PDF_Downloads.pdf"
    assert filename.endswith(".pdf")


def test_build_pdf_filename_uses_emse_alias() -> None:
    paper = build_paper(venue="Empir. Softw. Eng.", title="A practical study")

    filename = build_pdf_filename(paper)

    assert filename == "2025-EMSE-A_practical_study.pdf"


def test_download_paper_resolves_doi_to_landing_page_and_pdf(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.openalex.org/works/https://doi.org/10.1000/example":
            return httpx.Response(
                200,
                json={"best_oa_location": {}, "primary_location": {}},
                request=request,
            )
        if str(request.url) == "https://doi.org/10.1000/example":
            return httpx.Response(
                302,
                headers={"location": "https://example.org/paper"},
                request=request,
            )
        if str(request.url) == "https://example.org/paper":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text='<meta name="citation_pdf_url" content="/paper.pdf">',
                request=request,
            )
        if str(request.url) == "https://example.org/paper.pdf":
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.4 test pdf",
                request=request,
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    downloader = CandidateDownloader(client=client)
    workspace = build_workspace(tmp_path)
    paper = build_paper()

    downloaded = downloader.download_paper(paper, workspace)

    assert downloaded is True
    assert paper.landing_url == "https://example.org/paper"
    assert paper.pdf_url == "https://example.org/paper.pdf"
    assert paper.download_source in {"openalex_oa_landing_html", "doi_resolved_html"}
    assert paper.local_pdf_path is not None
    assert Path(paper.local_pdf_path).exists()
    assert Path(paper.local_pdf_path).read_bytes().startswith(b"%PDF")


def test_candidate_builder_orders_candidates_by_priority() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.openalex.org/works/https://doi.org/10.1000/example":
            return httpx.Response(
                200,
                json={
                    "best_oa_location": {"pdf_url": "https://oa.example/paper.pdf"},
                    "primary_location": {"landing_page_url": "https://primary.example/paper"},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    builder = DownloadCandidateBuilder(client)
    paper = build_paper(landing_url="https://ieeexplore.ieee.org/document/1234567/")

    candidates = builder.build(paper)

    assert [candidate.source for candidate in candidates[:5]] == [
        "openalex_oa",
        "openalex_oa_landing",
        "dblp_ee",
        "doi_resolved",
        "ieee_stamp",
    ]


def test_candidate_builder_ignores_invalid_openalex_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.openalex.org/works/https://doi.org/10.1000/example":
            return httpx.Response(
                200,
                json={
                    "best_oa_location": {"pdf_url": None, "landing_page_url": None},
                    "primary_location": {"pdf_url": "None", "landing_page_url": "   "},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    builder = DownloadCandidateBuilder(client)
    paper = build_paper()

    candidates = builder.build(paper)

    assert all(not candidate.source.startswith("openalex_oa") for candidate in candidates)


def test_download_paper_does_not_crash_on_invalid_candidate_url(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No HTTP call expected, got {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = CandidateDownloader(client=client)
    workspace = build_workspace(tmp_path)
    paper = build_paper(doi=None, landing_url="/None")

    downloaded = downloader.download_paper(paper, workspace)

    assert downloaded is False
    assert paper.download_failure_code == "invalid_candidate_url"


def test_download_paper_reuses_existing_identical_canonical_file(tmp_path: Path) -> None:
    pdf_bytes = b"%PDF-1.4 duplicate content"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.org/paper.pdf":
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
                request=request,
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = CandidateDownloader(client=client)
    workspace = build_workspace(tmp_path)
    paper = build_paper(doi=None, pdf_url="https://example.org/paper.pdf")

    canonical = workspace.rank_directory(paper.ccf_rank) / build_pdf_filename(paper)
    canonical.write_bytes(pdf_bytes)

    downloaded = downloader.download_paper(paper, workspace)

    assert downloaded is True
    assert paper.local_pdf_path == str(canonical)
    siblings = list(canonical.parent.glob(f"{canonical.stem}*.pdf"))
    assert siblings == [canonical]


def test_download_paper_prioritizes_phase_one_candidates(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.org/direct.pdf":
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.4 direct",
                request=request,
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    class FakeBuilder:
        def build(self, paper: PaperRecord) -> list[DownloadCandidate]:
            return [
                DownloadCandidate(source="openalex_oa_landing", url="https://example.org/landing", priority=100),
                DownloadCandidate(source="openalex_oa", url="https://example.org/direct.pdf", priority=90),
            ]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = CandidateDownloader(client=client)
    downloader._builder = FakeBuilder()  # type: ignore[assignment]
    workspace = build_workspace(tmp_path)
    paper = build_paper(doi=None)

    downloaded = downloader.download_paper(paper, workspace)

    assert downloaded is True
    assert paper.pdf_url == "https://example.org/direct.pdf"


def test_download_paper_blocks_domain_after_challenge_failures(tmp_path: Path) -> None:
    calls = {"blocked.example": 0, "good.example": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        domain = request.url.host
        calls[domain] += 1
        if domain == "blocked.example":
            return httpx.Response(
                403,
                headers={"content-type": "text/html"},
                text="cloudflare challenge page",
                request=request,
            )
        if domain == "good.example":
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.4 fallback",
                request=request,
            )
        raise AssertionError(f"Unexpected domain: {domain}")

    class FakeBuilder:
        def build(self, paper: PaperRecord) -> list[DownloadCandidate]:
            return [
                DownloadCandidate(source="openalex_oa_landing", url="https://blocked.example/a", priority=100),
                DownloadCandidate(source="doi_resolved", url="https://blocked.example/b", priority=99),
                DownloadCandidate(source="openalex_oa_landing", url="https://good.example/c", priority=98),
            ]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = CandidateDownloader(client=client, challenge_block_threshold=1)
    downloader._builder = FakeBuilder()  # type: ignore[assignment]
    workspace = build_workspace(tmp_path)
    paper = build_paper(doi=None)

    downloaded = downloader.download_paper(paper, workspace)

    assert downloaded is True
    assert calls["blocked.example"] == 1
    assert calls["good.example"] == 1
