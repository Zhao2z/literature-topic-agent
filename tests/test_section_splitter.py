from parse.page_model import HeadingCandidate, PageLine, ParsedPage, SectionBoundary
from parse.section_splitter import infer_section_boundaries, split_sections


def test_split_sections_uses_heading_boundaries() -> None:
    pages = [
        ParsedPage(
            page_number=1,
            text="",
            lines=[
                PageLine(page_number=1, line_index=0, text="A Parser Paper"),
                PageLine(page_number=1, line_index=1, text="Abstract"),
                PageLine(page_number=1, line_index=2, text="This is the abstract."),
                PageLine(page_number=1, line_index=3, text="1 Introduction"),
                PageLine(page_number=1, line_index=4, text="This is the introduction."),
                PageLine(page_number=1, line_index=5, text="2 Method"),
                PageLine(page_number=1, line_index=6, text="This is the method."),
            ],
        )
    ]
    headings = [
        HeadingCandidate(
            page_number=1,
            line_index=1,
            text="Abstract",
            score=0.9,
            accepted=True,
            reasons=["known_section_keyword"],
            canonical_name="abstract",
        ),
        HeadingCandidate(
            page_number=1,
            line_index=3,
            text="1 Introduction",
            score=0.9,
            accepted=True,
            reasons=["numbered_heading_pattern"],
            canonical_name="introduction",
        ),
        HeadingCandidate(
            page_number=1,
            line_index=5,
            text="2 Method",
            score=0.9,
            accepted=True,
            reasons=["numbered_heading_pattern"],
            canonical_name="method",
        ),
    ]

    boundaries, warnings = infer_section_boundaries(pages=pages, title="A Parser Paper", heading_candidates=headings)
    sections = split_sections(pages, boundaries)

    assert not warnings
    assert [section.canonical_name for section in sections] == ["title", "abstract", "introduction", "method"]
    assert sections[1].content == "This is the abstract."
    assert sections[2].content == "This is the introduction."
    assert sections[3].content == "This is the method."


def test_infer_section_boundaries_falls_back_to_introduction() -> None:
    pages = [
        ParsedPage(
            page_number=1,
            text="",
            lines=[
                PageLine(page_number=1, line_index=0, text="A Parser Paper"),
                PageLine(page_number=1, line_index=1, text="Abstract"),
                PageLine(page_number=1, line_index=2, text="A short abstract."),
                PageLine(page_number=1, line_index=3, text="This body paragraph starts the paper."),
            ],
        )
    ]

    boundaries, warnings = infer_section_boundaries(
        pages=pages,
        title="A Parser Paper",
        heading_candidates=[
            HeadingCandidate(
                page_number=1,
                line_index=1,
                text="Abstract",
                score=0.8,
                accepted=True,
                reasons=[],
                canonical_name="abstract",
            )
        ],
    )

    assert any(boundary.canonical_name == "introduction" for boundary in boundaries)
    assert "introduction_inferred_from_first_body_text" in warnings


def test_split_sections_normalizes_inline_abstract_title_and_references_metadata() -> None:
    pages = [
        ParsedPage(
            page_number=1,
            text="",
            lines=[
                PageLine(page_number=1, line_index=0, text="A Parser Paper"),
                PageLine(page_number=1, line_index=1, text="Abstract—A concise summary."),
                PageLine(page_number=1, line_index=2, text="More abstract detail."),
                PageLine(page_number=1, line_index=3, text="References"),
                PageLine(page_number=1, line_index=4, text="[1] First paper."),
                PageLine(page_number=1, line_index=5, text="[2] Second paper."),
            ],
        )
    ]

    sections = split_sections(
        pages,
        [
            SectionBoundary(
                title="A Parser Paper",
                canonical_name="title",
                start_page=1,
                start_line_index=0,
            ),
            SectionBoundary(
                title="Abstract—A concise summary.",
                canonical_name="abstract",
                start_page=1,
                start_line_index=1,
            ),
            SectionBoundary(
                title="References",
                canonical_name="references",
                start_page=1,
                start_line_index=3,
            ),
        ],
    )

    abstract = next(section for section in sections if section.canonical_name == "abstract")
    references = next(section for section in sections if section.canonical_name == "references")
    assert abstract.title == "Abstract"
    assert abstract.content.startswith("A concise summary.")
    assert references.title == "References"
    assert references.metadata["entries"][0]["label"] == "[1]"
    assert references.metadata["entries"][0]["text"] == "First paper."
