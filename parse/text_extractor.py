"""Text extraction orchestration for PDF backends."""

from __future__ import annotations

from pathlib import Path

from parse.page_model import ParsedPage
from parse.pdf_loader import AbstractPdfBackend


class PageTextExtractor:
    """Thin service layer around a selected PDF backend."""

    def __init__(self, backend: AbstractPdfBackend) -> None:
        self.backend = backend

    def extract(self, pdf_path: Path) -> list[ParsedPage]:
        """Extract page-wise text from the given PDF."""

        return self.backend.extract_pages(pdf_path)
