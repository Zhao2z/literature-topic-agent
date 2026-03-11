from parse.page_model import PageLine, ParsedPage
from parse.section_detector import detect_heading_candidates


def test_detect_heading_candidates_accepts_numbered_sections() -> None:
    pages = [
        ParsedPage(
            page_number=1,
            text="",
            lines=[
                PageLine(page_number=1, line_index=0, text="1 Introduction"),
                PageLine(
                    page_number=1,
                    line_index=1,
                    text="This paper studies a practical parsing pipeline for academic PDFs.",
                ),
                PageLine(page_number=1, line_index=2, text="Related Work"),
            ],
        )
    ]

    accepted, rejected = detect_heading_candidates(pages)

    assert [candidate.text for candidate in accepted] == ["1 Introduction", "Related Work"]
    assert any(candidate.text.startswith("This paper") for candidate in rejected)
