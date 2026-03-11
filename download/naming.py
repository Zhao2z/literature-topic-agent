"""Filename and venue normalization for downloaded papers."""

from __future__ import annotations

import re
import unicodedata

from domain.models import PaperRecord

INVALID_COMPONENT_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
WHITESPACE_RE = re.compile(r"\s+")

RAW_VENUE_ALIASES = {
    "international conference on software engineering": "ICSE",
    "icse": "ICSE",
    "icse companion": "ICSE-Companion",
    "automated software engineering": "ASE",
    "ase": "ASE",
    "international symposium on software testing and analysis": "ISSTA",
    "issta": "ISSTA",
    "ieee transactions on software engineering": "TSE",
    "ieee trans. software eng.": "TSE",
    "acm transactions on software engineering and methodology": "TOSEM",
    "acm trans. softw. eng. methodol.": "TOSEM",
    "empir. softw. eng.": "EMSE",
    "empir softw eng": "EMSE",
    "autom. softw. eng.": "ASEJ",
    "issre workshops": "ISSREW",
    "qrs companion": "QRS-Companion",
}


def build_pdf_filename(paper: PaperRecord) -> str:
    """Build a stable, readable PDF filename."""

    year = str(paper.year)
    venue = shorten_venue_name(paper.venue)
    title = sanitize_filename_component(paper.title.rstrip(".") or paper.paper_id, max_length=120)
    return f"{year}-{venue}-{title}.pdf"


def shorten_venue_name(venue: str) -> str:
    """Map a venue to a short label when possible."""

    normalized = _normalize_lookup_key(venue)
    alias = VENUE_ALIASES.get(normalized)
    if alias:
        return alias
    return sanitize_filename_component(venue or "Unknown-Venue", max_length=32)


def sanitize_filename_component(value: str, *, max_length: int) -> str:
    """Sanitize text for filesystem-friendly filenames."""

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = INVALID_COMPONENT_CHARS.sub(" ", normalized)
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip().strip(".")
    cleaned = cleaned.replace("&apos;", "")
    cleaned = cleaned.replace("&amp;", "and")
    cleaned = cleaned.replace("'", "")
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", " ", cleaned)
    cleaned = cleaned.replace("-", " ")
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    underscored = cleaned.replace(" ", "_")
    underscored = re.sub(r"_{2,}", "_", underscored).strip("._-")
    return underscored[:max_length].rstrip("._-") or "unknown"


def _normalize_lookup_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("&apos;", "").replace("&amp;", "and")
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", normalized).strip().lower()
    return WHITESPACE_RE.sub(" ", normalized)


VENUE_ALIASES = {_normalize_lookup_key(key): value for key, value in RAW_VENUE_ALIASES.items()}
