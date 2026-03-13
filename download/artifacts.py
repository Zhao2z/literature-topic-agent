"""Helpers for download candidate and failure artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from domain.models import PaperRecord


def build_download_candidates_payload(papers: list[PaperRecord]) -> list[dict[str, Any]]:
    """Build a machine-readable snapshot of download candidates and outcomes."""

    rows: list[dict[str, Any]] = []
    for paper in papers:
        rows.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "venue": paper.venue,
                "year": paper.year,
                "ccf_rank": paper.ccf_rank,
                "doi": paper.doi,
                "dblp_url": paper.dblp_url,
                "landing_url": paper.landing_url,
                "selected_pdf_url": paper.pdf_url,
                "download_source": paper.download_source,
                "local_pdf_path": paper.local_pdf_path,
                "status": paper.status.value,
                "download_failure_code": paper.download_failure_code,
                "last_error": paper.last_error,
                "candidate_count": len(paper.download_candidates),
                "candidates": [candidate.model_dump(mode="json") for candidate in paper.download_candidates],
            }
        )
    return rows


def collect_manual_pdf_paths(*, topic_dir: Path) -> list[Path]:
    """Return PDF files stored in standard manual PDF directories."""

    candidates = [topic_dir / "manual_pdfs", topic_dir / "manual-pdfs"]
    paths: list[Path] = []
    for root in candidates:
        if not root.exists():
            continue
        paths.extend(sorted(root.rglob("*.pdf")))
    return sorted(dict.fromkeys(path.resolve() for path in paths))
