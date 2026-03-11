"""Public parser subsystem exports."""

from parse.artifacts import paper_artifact_dir, write_parse_artifacts
from parse.parser_service import ParserService
from parse.pdf_loader import AbstractPdfBackend, MarkerPdfBackend, PdfBackendError, PyMuPDFBackend, build_pdf_backend
from parse.reference_parser import parse_reference_entries
from parse.text_extractor import PageTextExtractor
from parse.text_cleaner import is_noise_line, normalize_section_content

__all__ = [
    "AbstractPdfBackend",
    "MarkerPdfBackend",
    "PageTextExtractor",
    "ParserService",
    "PdfBackendError",
    "PyMuPDFBackend",
    "build_pdf_backend",
    "parse_reference_entries",
    "is_noise_line",
    "normalize_section_content",
    "paper_artifact_dir",
    "write_parse_artifacts",
]
