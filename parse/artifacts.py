"""Artifact generation for parsed PDF content."""

from __future__ import annotations

import json
from pathlib import Path

from parse.page_model import PdfParseResult


def paper_artifact_dir(pdf_path: Path) -> Path:
    """Return the deterministic artifact directory for a paper PDF."""

    return pdf_path.with_suffix("")


def write_parse_artifacts(
    result: PdfParseResult,
    *,
    preview_full_content: bool = False,
    preview_char_limit: int = 1200,
) -> dict[str, str]:
    """Write parser artifacts next to the paper PDF."""

    artifact_dir = paper_artifact_dir(Path(result.file_path))
    artifact_dir.mkdir(parents=True, exist_ok=True)

    pdf_parse_path = artifact_dir / "pdf_parse.json"
    sections_path = artifact_dir / "sections.json"
    preview_path = artifact_dir / "sections_preview.md"
    debug_path = artifact_dir / "parser_debug.json"

    pdf_parse_path.write_text(
        json.dumps(result.to_pdf_parse_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sections_path.write_text(
        json.dumps(result.to_sections_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    preview_path.write_text(
        _build_sections_preview(result, preview_full_content=preview_full_content, preview_char_limit=preview_char_limit),
        encoding="utf-8",
    )
    debug_path.write_text(
        json.dumps(result.to_debug_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "artifact_dir": str(artifact_dir),
        "pdf_parse": str(pdf_parse_path),
        "sections": str(sections_path),
        "sections_preview": str(preview_path),
        "parser_debug": str(debug_path),
    }


def _build_sections_preview(
    result: PdfParseResult,
    *,
    preview_full_content: bool,
    preview_char_limit: int,
) -> str:
    lines = [
        f"# {result.title}",
        "",
        f"- Page count: {result.page_count}",
        f"- Backend: `{result.backend}`",
        f"- Sections: {', '.join(section.canonical_name for section in result.sections)}",
        "",
    ]
    for section in result.sections:
        lines.append(f"## {section.title} (`{section.canonical_name}`)")
        lines.append("")
        content = section.content
        if not preview_full_content and len(content) > preview_char_limit:
            content = f"{content[:preview_char_limit].rstrip()}..."
        lines.append(content or "_No content extracted._")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
