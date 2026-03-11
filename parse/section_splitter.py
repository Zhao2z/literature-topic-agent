"""Boundary inference and section splitting."""

from __future__ import annotations

from dataclasses import dataclass

from parse.page_model import HeadingCandidate, ParsedPage, ParsedSection, SectionBoundary
from parse.reference_parser import parse_reference_entries
from parse.section_normalizer import CANONICAL_SECTION_ORDER, normalize_section_name
from parse.text_cleaner import normalize_section_content


@dataclass(slots=True)
class _LineRef:
    page_number: int
    line_index: int
    text: str


def infer_section_boundaries(
    *,
    pages: list[ParsedPage],
    title: str,
    heading_candidates: list[HeadingCandidate],
) -> tuple[list[SectionBoundary], list[str]]:
    """Infer section boundaries from accepted heading candidates."""

    warnings: list[str] = []
    boundaries: list[SectionBoundary] = [
        SectionBoundary(
            title=title,
            canonical_name="title",
            start_page=1,
            start_line_index=0,
            confidence=1.0,
            source_text=title,
        )
    ]

    for candidate in heading_candidates:
        if candidate.canonical_name is None:
            continue
        if any(existing.canonical_name == candidate.canonical_name for existing in boundaries):
            continue
        boundaries.append(
            SectionBoundary(
                title=candidate.text,
                canonical_name=candidate.canonical_name,
                start_page=candidate.page_number,
                start_line_index=candidate.line_index,
                confidence=candidate.score,
                source_text=candidate.text,
            )
        )

    boundaries = _sort_boundaries(boundaries)
    if not any(boundary.canonical_name == "abstract" for boundary in boundaries):
        inline_abstract = _infer_inline_abstract_boundary(pages)
        if inline_abstract is not None:
            boundaries.append(inline_abstract)
            warnings.append("abstract_inferred_from_inline_text")
    if not any(boundary.canonical_name == "introduction" for boundary in boundaries) and pages:
        fallback_line = _first_body_line_after_abstract_or_title(pages, boundaries)
        if fallback_line is not None:
            boundaries.append(
                SectionBoundary(
                    title="Introduction",
                    canonical_name="introduction",
                    start_page=fallback_line.page_number,
                    start_line_index=fallback_line.line_index,
                    confidence=0.35,
                    source_text=None,
                )
            )
            warnings.append("introduction_inferred_from_first_body_text")

    boundaries = _sort_boundaries(boundaries)
    return _prune_out_of_order_boundaries(boundaries), warnings


def split_sections(pages: list[ParsedPage], boundaries: list[SectionBoundary]) -> list[ParsedSection]:
    """Split page text into section content ranges."""

    line_refs = [
        _LineRef(page_number=line.page_number, line_index=line.line_index, text=line.text)
        for page in pages
        for line in page.lines
    ]
    if not line_refs:
        return []

    boundary_positions = {
        (boundary.start_page, boundary.start_line_index): boundary
        for boundary in boundaries
    }
    ordered_boundaries = sorted(boundaries, key=lambda item: (item.start_page, item.start_line_index))
    sections: list[ParsedSection] = []

    for index, boundary in enumerate(ordered_boundaries):
        start_position = _find_line_position(line_refs, boundary.start_page, boundary.start_line_index)
        end_position = len(line_refs)
        if index + 1 < len(ordered_boundaries):
            next_boundary = ordered_boundaries[index + 1]
            end_position = _find_line_position(line_refs, next_boundary.start_page, next_boundary.start_line_index)

        content_lines: list[str] = []
        if boundary.canonical_name == "title":
            content_lines = [boundary.title]
        else:
            for line_ref in line_refs[start_position:end_position]:
                if (line_ref.page_number, line_ref.line_index) in boundary_positions and line_ref.text == boundary.title:
                    continue
                content_lines.append(line_ref.text)
        title, content = _normalize_section_title_and_content(boundary=boundary, content_lines=content_lines)
        metadata = _build_section_metadata(boundary.canonical_name, content)
        end_page = line_refs[end_position - 1].page_number if end_position > start_position else boundary.start_page
        sections.append(
            ParsedSection(
                title=title,
                canonical_name=boundary.canonical_name,
                start_page=boundary.start_page,
                end_page=end_page,
                content=content,
                source_heading=boundary.source_text,
                metadata=metadata,
            )
        )

    return [section for section in sections if section.content or section.canonical_name == "title"]


def _sort_boundaries(boundaries: list[SectionBoundary]) -> list[SectionBoundary]:
    ordered_names = {name: index for index, name in enumerate(CANONICAL_SECTION_ORDER)}
    return sorted(
        boundaries,
        key=lambda item: (
            item.start_page,
            item.start_line_index,
            ordered_names.get(item.canonical_name, len(ordered_names)),
        ),
    )


def _prune_out_of_order_boundaries(boundaries: list[SectionBoundary]) -> list[SectionBoundary]:
    pruned: list[SectionBoundary] = []
    seen_names: set[str] = set()
    for boundary in boundaries:
        if boundary.canonical_name == "title":
            pruned.append(boundary)
            continue
        if boundary.canonical_name in seen_names:
            continue
        seen_names.add(boundary.canonical_name)
        pruned.append(boundary)
    return pruned


def _infer_inline_abstract_boundary(pages: list[ParsedPage]) -> SectionBoundary | None:
    if not pages:
        return None
    first_page = pages[0]
    for line in first_page.lines[:20]:
        decision = normalize_section_name(line.text)
        if decision.canonical_name == "abstract":
            return SectionBoundary(
                title="Abstract",
                canonical_name="abstract",
                start_page=line.page_number,
                start_line_index=line.line_index,
                confidence=0.55,
                source_text=line.text,
            )
        if line.text.lower().startswith("abstract"):
            return SectionBoundary(
                title="Abstract",
                canonical_name="abstract",
                start_page=line.page_number,
                start_line_index=line.line_index,
                confidence=0.5,
                source_text=line.text,
            )
    return None


def _first_body_line_after_abstract_or_title(
    pages: list[ParsedPage],
    boundaries: list[SectionBoundary],
) -> _LineRef | None:
    abstract_boundary = next((boundary for boundary in boundaries if boundary.canonical_name == "abstract"), None)
    start_page = abstract_boundary.start_page if abstract_boundary is not None else 1
    start_line_index = abstract_boundary.start_line_index + 1 if abstract_boundary is not None else 1
    for page in pages:
        if page.page_number < start_page:
            continue
        for line in page.lines:
            if page.page_number == start_page and line.line_index < start_line_index:
                continue
            if len(line.text.split()) >= 5:
                return _LineRef(page_number=line.page_number, line_index=line.line_index, text=line.text)
    return None


def _find_line_position(line_refs: list[_LineRef], page_number: int, line_index: int) -> int:
    for position, line_ref in enumerate(line_refs):
        if (line_ref.page_number, line_ref.line_index) == (page_number, line_index):
            return position
    return 0


def _normalize_section_title_and_content(*, boundary: SectionBoundary, content_lines: list[str]) -> tuple[str, str]:
    title = boundary.title
    normalized_lines = list(content_lines)
    if boundary.canonical_name == "abstract" and title.lower().startswith("abstract"):
        split_text = _split_inline_abstract_title(title)
        title = "Abstract"
        if split_text:
            normalized_lines.insert(0, split_text)
    elif boundary.canonical_name == "references":
        title = "References"
    content = normalize_section_content(normalized_lines)
    return title, content


def _split_inline_abstract_title(title: str) -> str:
    for marker in ("—", "-", ":"):
        if marker in title:
            _, remainder = title.split(marker, 1)
            return remainder.strip()
    return ""


def _build_section_metadata(canonical_name: str, content: str) -> dict[str, object]:
    if canonical_name == "references":
        entries = parse_reference_entries(content)
        if entries:
            return {"entries": entries}
    return {}
