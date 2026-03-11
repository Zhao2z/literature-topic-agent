"""End-to-end PDF parsing service."""

from __future__ import annotations

from pathlib import Path

from core.logging import get_logger
from parse.page_model import ParseDebugInfo, PdfParseResult
from parse.section_detector import detect_heading_candidates
from parse.section_normalizer import normalize_section_name
from parse.section_splitter import infer_section_boundaries, split_sections
from parse.text_extractor import PageTextExtractor

LOGGER = get_logger(__name__)
PARSER_VERSION = "0.1"


class ParserService:
    """Parse a downloaded paper PDF into canonical sections."""

    def __init__(self, extractor: PageTextExtractor) -> None:
        self.extractor = extractor

    def parse_pdf(self, *, paper_id: str, pdf_path: Path) -> PdfParseResult:
        """Parse a local PDF file and produce section artifacts."""

        pages = self.extractor.extract(pdf_path)
        title = _infer_title(pages, pdf_path)
        accepted, rejected = detect_heading_candidates(pages)
        normalization_decisions = [normalize_section_name(candidate.text) for candidate in accepted + rejected]
        boundaries, warnings = infer_section_boundaries(pages=pages, title=title, heading_candidates=accepted)
        sections = split_sections(pages, boundaries)
        if not sections:
            warnings.append("no_sections_extracted")

        debug = ParseDebugInfo(
            raw_heading_candidates=accepted,
            rejected_heading_candidates=rejected,
            normalization_decisions=normalization_decisions,
            warning_flags=list(warnings),
        )
        result = PdfParseResult(
            paper_id=paper_id,
            file_path=str(pdf_path),
            backend=self.extractor.backend.backend_name,
            parser_version=PARSER_VERSION,
            title=title,
            page_count=len(pages),
            pages=pages,
            sections=sections,
            section_boundaries=boundaries,
            warnings=warnings,
            debug=debug,
        )
        LOGGER.bind(
            paper_id=paper_id,
            backend=result.backend,
            page_count=result.page_count,
            sections=len(result.sections),
            warnings=len(result.warnings),
        ).info("Parsed PDF into sections")
        return result


def _infer_title(pages, pdf_path: Path) -> str:
    if not pages:
        return pdf_path.stem

    first_page = pages[0]
    title_lines: list[str] = []
    for line in first_page.lines[:12]:
        decision = normalize_section_name(line.text)
        if decision.canonical_name in {"abstract", "introduction"}:
            break
        if "@" in line.text or len(line.text.split()) <= 1:
            continue
        if len(line.text) > 160:
            continue
        title_lines.append(line.text)
        if len(title_lines) >= 2:
            break
    return " ".join(title_lines).strip() or pdf_path.stem
