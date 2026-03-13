from __future__ import annotations

import httpx

from providers.dblp_bibtex import DblpBibtexClient


def test_dblp_bibtex_client_builds_bib_url_for_journal_record() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            request=request,
            text="@article{DBLP:journals/tse/0001A25,\n  title={Paper \\\\& Practice}\n}",
        )

    client = DblpBibtexClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    bibtex = client.fetch_bibtex("https://dblp.org/rec/journals/tse/0001A25")

    assert requested_urls == ["https://dblp.org/rec/journals/tse/0001A25.bib"]
    assert bibtex is not None
    assert "DBLP:journals/tse/0001A25" in bibtex


def test_dblp_bibtex_client_strips_html_suffix_before_fetch() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, request=request, text="@article{DBLP:journals/tse/Test25,\n  title={Paper}\n}")

    client = DblpBibtexClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    bibtex = client.fetch_bibtex("https://dblp.org/rec/journals/tse/Test25.html")

    assert requested_urls == ["https://dblp.org/rec/journals/tse/Test25.bib"]
    assert bibtex is not None


def test_dblp_bibtex_client_raises_on_http_failure_for_debugging() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(503, request=request, text="upstream unavailable")

    client = DblpBibtexClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        client.fetch_bibtex("https://dblp.org/rec/journals/tse/0001A25")
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 503
        assert str(exc.request.url) == "https://dblp.org/rec/journals/tse/0001A25.html?view=bibtex"
        assert requested_urls == [
            "https://dblp.org/rec/journals/tse/0001A25.bib",
            "https://dblp.org/rec/journals/tse/0001A25.html?view=bibtex",
        ]
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("Expected HTTPStatusError for failed DBLP BibTeX request")


def test_dblp_bibtex_client_sanitizes_html_entities() -> None:
    bibtex = DblpBibtexClient.sanitize_bibtex(
        "@article{DBLP:journals/tse/0001A25,\n  author={Marcelo d&apos;Amorim and A & B}\n}"
    )

    assert "d'Amorim" in bibtex
    assert "A \\& B" in bibtex


def test_dblp_bibtex_client_falls_back_to_html_view_when_bib_disconnects() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url).endswith(".bib"):
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(
            200,
            request=request,
            text=(
                '<html><body><pre class="verbatim select-on-click">\n'
                '@article{DBLP:journals/tse/0001A25,\n  title={Paper}\n}\n'
                "</pre></body></html>"
            ),
        )

    client = DblpBibtexClient(client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=1)

    bibtex = client.fetch_bibtex("https://dblp.org/rec/journals/tse/0001A25")

    assert requested_urls == [
        "https://dblp.org/rec/journals/tse/0001A25.bib",
        "https://dblp.org/rec/journals/tse/0001A25.html?view=bibtex",
    ]
    assert bibtex is not None
    assert "@article{DBLP:journals/tse/0001A25," in bibtex
