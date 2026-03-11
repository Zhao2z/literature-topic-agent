"""Typed models for PDF parsing and section extraction."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PageLine(BaseModel):
    """A normalized text line extracted from a PDF page."""

    page_number: int
    line_index: int
    text: str
    font_size: float = 0.0
    is_bold: bool = False
    is_italic: bool = False
    bbox: tuple[float, float, float, float] | None = None


class ParsedPage(BaseModel):
    """Page-level extracted text with line granularity."""

    page_number: int
    text: str
    lines: list[PageLine] = Field(default_factory=list)


class HeadingCandidate(BaseModel):
    """A line that may represent a section heading."""

    page_number: int
    line_index: int
    text: str
    score: float
    accepted: bool
    reasons: list[str] = Field(default_factory=list)
    canonical_name: str | None = None


class SectionBoundary(BaseModel):
    """A canonicalized section start position."""

    title: str
    canonical_name: str
    start_page: int
    start_line_index: int
    confidence: float = 0.0
    source_text: str | None = None


class ParsedSection(BaseModel):
    """A materialized section extracted from the paper."""

    title: str
    canonical_name: str
    start_page: int
    end_page: int
    content: str
    source_heading: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizationDecision(BaseModel):
    """Trace output for section title normalization."""

    source_text: str
    normalized_text: str
    canonical_name: str | None = None
    reasons: list[str] = Field(default_factory=list)


class ParseDebugInfo(BaseModel):
    """Intermediate signals captured during parsing."""

    raw_heading_candidates: list[HeadingCandidate] = Field(default_factory=list)
    rejected_heading_candidates: list[HeadingCandidate] = Field(default_factory=list)
    normalization_decisions: list[NormalizationDecision] = Field(default_factory=list)
    warning_flags: list[str] = Field(default_factory=list)


class PdfParseResult(BaseModel):
    """Backend-independent parse output for a PDF paper."""

    paper_id: str
    file_path: str
    backend: str
    parser_version: str
    title: str
    page_count: int
    pages: list[ParsedPage] = Field(default_factory=list)
    sections: list[ParsedSection] = Field(default_factory=list)
    section_boundaries: list[SectionBoundary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    debug: ParseDebugInfo = Field(default_factory=ParseDebugInfo)

    def to_sections_payload(self) -> dict[str, Any]:
        """Return the persisted `sections.json` payload."""

        sections: dict[str, Any] = {}
        for section in self.sections:
            sections[section.canonical_name] = {
                "title": section.title,
                "canonical_name": section.canonical_name,
                "start_page": section.start_page,
                "end_page": section.end_page,
                "content": section.content,
                **({"metadata": section.metadata} if section.metadata else {}),
            }
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "page_count": self.page_count,
            "sections": sections,
        }

    def to_pdf_parse_payload(self) -> dict[str, Any]:
        """Return the persisted `pdf_parse.json` payload."""

        return {
            "paper_id": self.paper_id,
            "file_path": self.file_path,
            "page_count": self.page_count,
            "pages": [
                {
                    "page_number": page.page_number,
                    "text": page.text,
                }
                for page in self.pages
            ],
            "detected_heading_candidates": [candidate.model_dump(mode="json") for candidate in self.debug.raw_heading_candidates],
            "section_boundaries": [boundary.model_dump(mode="json") for boundary in self.section_boundaries],
            "parse_warnings": list(self.warnings),
            "backend": self.backend,
            "parser_version": self.parser_version,
        }

    def to_debug_payload(self) -> dict[str, Any]:
        """Return the persisted `parser_debug.json` payload."""

        return {
            "paper_id": self.paper_id,
            "backend": self.backend,
            "parser_version": self.parser_version,
            "raw_heading_candidates": [candidate.model_dump(mode="json") for candidate in self.debug.raw_heading_candidates],
            "rejected_heading_candidates": [
                candidate.model_dump(mode="json") for candidate in self.debug.rejected_heading_candidates
            ],
            "normalization_decisions": [
                decision.model_dump(mode="json") for decision in self.debug.normalization_decisions
            ],
            "confidence_flags": list(self.debug.warning_flags),
            "warnings": list(self.warnings),
        }

    def to_llm_ready_sections(self) -> dict[str, str]:
        """Return a compact canonical section mapping for future LLM use."""

        preferred_sections = (
            "title",
            "abstract",
            "introduction",
            "related_work",
            "background",
            "method",
            "approach",
            "model",
            "implementation",
            "experiments",
            "evaluation",
            "results",
            "discussion",
            "threats_to_validity",
            "conclusion",
            "limitations",
            "references",
        )
        by_name = {section.canonical_name: section.content for section in self.sections}
        return {name: by_name[name] for name in preferred_sections if by_name.get(name)}

    def to_section_metadata(self) -> dict[str, dict[str, Any]]:
        """Return metadata without large content blocks for persistence."""

        return {
            section.canonical_name: {
                "title": section.title,
                "canonical_name": section.canonical_name,
                "start_page": section.start_page,
                "end_page": section.end_page,
                "content_length": len(section.content),
                **({"metadata": section.metadata} if section.metadata else {}),
            }
            for section in self.sections
        }
