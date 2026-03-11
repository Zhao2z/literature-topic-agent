from pathlib import Path

import pytest

from parse.page_model import PageLine, ParsedPage
from parse.parser_service import ParserService
from parse.pdf_loader import AbstractPdfBackend, PdfBackendError
from parse.text_extractor import PageTextExtractor


class FakePdfBackend(AbstractPdfBackend):
    backend_name = "fake"

    def __init__(self, *, pages: list[ParsedPage] | None = None, error: Exception | None = None) -> None:
        self._pages = pages or []
        self._error = error

    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        if self._error is not None:
            raise self._error
        return self._pages


def test_parser_service_parses_sections_from_backend_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    backend = FakePdfBackend(
        pages=[
            ParsedPage(
                page_number=1,
                text="",
                lines=[
                    PageLine(page_number=1, line_index=0, text="A Parser Paper"),
                    PageLine(page_number=1, line_index=1, text="Abstract"),
                    PageLine(page_number=1, line_index=2, text="This is the abstract."),
                    PageLine(page_number=1, line_index=3, text="1 Introduction"),
                    PageLine(page_number=1, line_index=4, text="This is the introduction."),
                    PageLine(page_number=1, line_index=5, text="References"),
                    PageLine(page_number=1, line_index=6, text="[1] Ref"),
                ],
            )
        ]
    )
    service = ParserService(PageTextExtractor(backend))

    result = service.parse_pdf(paper_id="paper-1", pdf_path=pdf_path)

    assert result.title == "A Parser Paper"
    assert result.to_llm_ready_sections()["abstract"] == "This is the abstract."
    assert result.to_llm_ready_sections()["introduction"] == "This is the introduction."
    assert result.to_llm_ready_sections()["references"] == "[1] Ref"


def test_parser_service_raises_for_malformed_pdf() -> None:
    service = ParserService(PageTextExtractor(FakePdfBackend(error=PdfBackendError("bad pdf"))))

    with pytest.raises(PdfBackendError):
        service.parse_pdf(paper_id="paper-1", pdf_path=Path("/tmp/bad.pdf"))
