"""PDF backend abstractions and loaders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.logging import get_logger
from parse.page_model import PageLine, ParsedPage
from parse.text_cleaner import is_noise_line

LOGGER = get_logger(__name__)


class PdfBackendError(RuntimeError):
    """Raised when a PDF backend cannot parse a file."""


class AbstractPdfBackend(ABC):
    """Interface for pluggable PDF parsing backends."""

    backend_name: str

    @abstractmethod
    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        """Return extracted pages for a local PDF."""


class PyMuPDFBackend(AbstractPdfBackend):
    """Lightweight default parser backend backed by PyMuPDF."""

    backend_name = "pymupdf"

    def __init__(self) -> None:
        try:
            import fitz  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency validation
            raise PdfBackendError("PyMuPDF is not installed; install `pymupdf` to use the default parser backend.") from exc
        self._fitz = fitz

    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        """Extract page text and normalized lines from a PDF."""

        if not pdf_path.exists():
            raise PdfBackendError(f"PDF file does not exist: {pdf_path}")

        try:
            with self._fitz.open(pdf_path) as document:
                pages: list[ParsedPage] = []
                for page_index, page in enumerate(document, start=1):
                    page_dict = page.get_text("dict")
                    lines: list[PageLine] = []
                    for block in page_dict.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line_index, line in enumerate(block.get("lines", []), start=len(lines)):
                            spans = line.get("spans", [])
                            text = "".join(span.get("text", "") for span in spans).strip()
                            if not text:
                                continue
                            if is_noise_line(text):
                                continue
                            font_size = max((float(span.get("size", 0.0)) for span in spans), default=0.0)
                            fonts = [str(span.get("font", "")) for span in spans]
                            flags = [int(span.get("flags", 0)) for span in spans]
                            bbox = tuple(float(value) for value in line.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                            lines.append(
                                PageLine(
                                    page_number=page_index,
                                    line_index=line_index,
                                    text=text,
                                    font_size=font_size,
                                    is_bold=any("Bold" in font or "Medi" in font for font in fonts),
                                    is_italic=any("Ital" in font or (flag & 2) != 0 for font, flag in zip(fonts, flags)),
                                    bbox=bbox,
                                )
                            )
                    text = "\n".join(item.text for item in lines)
                    pages.append(ParsedPage(page_number=page_index, text=text.strip(), lines=lines))
        except Exception as exc:  # pragma: no cover - fitz specific failures
            LOGGER.bind(pdf_path=str(pdf_path)).exception("PyMuPDF backend failed to extract PDF")
            raise PdfBackendError(f"Failed to parse PDF: {pdf_path}") from exc

        if not pages:
            raise PdfBackendError(f"PDF contained no readable pages: {pdf_path}")
        return pages


class MarkerPdfBackend(AbstractPdfBackend):
    """Placeholder adapter for future Marker integration."""

    backend_name = "marker"

    def extract_pages(self, pdf_path: Path) -> list[ParsedPage]:
        """Marker is not yet implemented in this phase."""

        raise PdfBackendError(
            "The `marker` backend is defined as an extension point but is not implemented in this phase."
        )


def build_pdf_backend(name: str) -> AbstractPdfBackend:
    """Construct a parser backend from its configured name."""

    normalized = name.strip().lower()
    if normalized == "pymupdf":
        return PyMuPDFBackend()
    if normalized == "marker":
        return MarkerPdfBackend()
    raise PdfBackendError(f"Unsupported parser backend: {name}")
