"""Metadata normalization utilities."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from domain.models import DblpRawRecord, PaperRecord

WHITESPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_text(value: str) -> str:
    """Normalize text for matching and deduplication."""

    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    compact = WHITESPACE_RE.sub(" ", ascii_text).strip().lower()
    return compact


def normalize_title(value: str) -> str:
    """Normalize a title to a canonical matching form."""

    normalized = normalize_text(value)
    without_punctuation = PUNCT_RE.sub(" ", normalized)
    return WHITESPACE_RE.sub(" ", without_punctuation).strip()


def build_paper_id(title: str, year: int, doi: str | None = None) -> str:
    """Build a stable paper identifier."""

    basis = doi or f"{normalize_title(title)}::{year}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()
    return digest[:16]


def normalize_paper(
    raw: DblpRawRecord,
    topic_slug: str,
    keyword_matches: list[str],
) -> PaperRecord:
    """Convert a raw DBLP record into a normalized paper record."""

    title = WHITESPACE_RE.sub(" ", raw.title).strip()
    authors = [WHITESPACE_RE.sub(" ", author).strip() for author in raw.authors if author.strip()]
    venue = WHITESPACE_RE.sub(" ", raw.venue).strip()
    paper_id = build_paper_id(title=title, year=raw.year, doi=raw.doi)
    return PaperRecord(
        paper_id=paper_id,
        topic_slug=topic_slug,
        title=title,
        authors=authors,
        venue=venue,
        year=raw.year,
        venue_type=raw.venue_type,
        dblp_url=raw.dblp_url.strip(),
        doi=raw.doi.strip() if raw.doi else None,
        landing_url=raw.ee_url.strip() if raw.ee_url else None,
        bibtex=raw.bibtex,
        keyword_matches=sorted(set(keyword_matches)),
    )
