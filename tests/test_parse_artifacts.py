import json
from pathlib import Path

from parse.artifacts import paper_artifact_dir, write_parse_artifacts
from parse.page_model import ParseDebugInfo, ParsedPage, ParsedSection, PdfParseResult


def test_write_parse_artifacts_creates_expected_files(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    result = PdfParseResult(
        paper_id="paper-1",
        file_path=str(pdf_path),
        backend="pymupdf",
        parser_version="0.1",
        title="A Parser Paper",
        page_count=1,
        pages=[ParsedPage(page_number=1, text="Example text", lines=[])],
        sections=[
            ParsedSection(
                title="Abstract",
                canonical_name="abstract",
                start_page=1,
                end_page=1,
                content="This is the abstract.",
            )
        ],
        warnings=["minor_warning"],
        debug=ParseDebugInfo(warning_flags=["minor_warning"]),
    )

    artifact_paths = write_parse_artifacts(result, preview_full_content=False, preview_char_limit=10)

    artifact_dir = paper_artifact_dir(pdf_path)
    assert artifact_dir.exists()
    assert set(artifact_paths) == {"artifact_dir", "pdf_parse", "sections", "sections_preview", "parser_debug"}
    assert json.loads((artifact_dir / "sections.json").read_text(encoding="utf-8"))["sections"]["abstract"]["content"] == (
        "This is the abstract."
    )
    assert "This is th..." in (artifact_dir / "sections_preview.md").read_text(encoding="utf-8")
