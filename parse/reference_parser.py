"""Structured reference entry extraction."""

from __future__ import annotations

import re
from typing import Any

REFERENCE_ENTRY_RE = re.compile(r"(\[\d+\])\s*(.*?)(?=(?:\s*\[\d+\]\s)|\Z)", re.DOTALL)
WHITESPACE_RE = re.compile(r"\s+")
QUOTED_TITLE_RE = re.compile(r"[\"“](.*?)[\"”]")
URL_RE = re.compile(r"https?://\S+")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
UNQUOTED_TITLE_RE = re.compile(
    r"(?:,\s*)(?P<title>[A-Z][^.]{6,}?)\.\s+(?P<venue>[^.]{2,}?)\s*,\s*(?P<year>(?:19|20)\d{2})\b"
)


def parse_reference_entries(content: str) -> list[dict[str, Any]]:
    """Split a references section into structured citation entries."""

    entries: list[dict[str, Any]] = []
    for label, body in REFERENCE_ENTRY_RE.findall(content.strip()):
        normalized_body = _normalize_reference_text(body)
        if not normalized_body:
            continue
        entries.append(_parse_reference_entry(label=label, text=normalized_body))
    return entries


def _parse_reference_entry(*, label: str, text: str) -> dict[str, Any]:
    title = _extract_title(text)
    authors = _extract_authors(text, title=title)
    year = _extract_year(text)
    url = _extract_url(text)
    venue = _extract_venue(text, title=title, authors=authors, year=year, url=url)
    return {
        "label": label,
        "index": int(label.strip("[]")),
        "text": text,
        "authors": authors,
        "title": title,
        "venue": venue,
        "year": year,
        "url": url,
    }


def _normalize_reference_text(text: str) -> str:
    normalized = WHITESPACE_RE.sub(" ", text).strip()
    normalized = normalized.replace(" .", ".").replace(" ,", ",")
    normalized = normalized.replace(" ;", ";").replace(" :", ":")
    return normalized


def _extract_title(text: str) -> str | None:
    quoted_match = QUOTED_TITLE_RE.search(text)
    if quoted_match:
        return quoted_match.group(1).strip(" .,;:")

    unquoted_match = UNQUOTED_TITLE_RE.search(text)
    if unquoted_match:
        return unquoted_match.group("title").strip(" .,;:")

    # Book-style references often omit quotes and put the title after authors.
    first_period = text.find(". ")
    if first_period == -1:
        return None
    tail = text[first_period + 2 :].strip()
    if not tail:
        return None
    second_period = tail.find(". ")
    candidate = tail if second_period == -1 else tail[:second_period]
    candidate = candidate.strip(" .,;:")
    return candidate or None


def _extract_authors(text: str, *, title: str | None) -> list[str]:
    author_segment = text
    if title and title in text:
        author_segment = text.split(title, 1)[0]
    elif ". " in text:
        author_segment = text.split(". ", 1)[0]

    author_segment = author_segment.strip(" ,.;:\"“”")
    if not author_segment:
        return []

    # Normalize conjunctions to commas before splitting.
    normalized = author_segment.replace(", and ", ", ").replace(" and ", ", ")
    raw_parts = [part.strip(" ,.;:\"“”") for part in normalized.split(",") if part.strip(" ,.;:\"“”")]
    if len(raw_parts) >= 2:
        return raw_parts
    cleaned_segment = author_segment.strip(" ,.;:\"“”")
    return [cleaned_segment] if cleaned_segment else []


def _extract_year(text: str) -> int | None:
    matches = [int(match.group(0)) for match in YEAR_RE.finditer(text)]
    if not matches:
        return None
    return matches[-1]


def _extract_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if match is None:
        return None
    return match.group(0).rstrip(".,);")


def _extract_venue(
    text: str,
    *,
    title: str | None,
    authors: list[str],
    year: int | None,
    url: str | None,
) -> str | None:
    working = text
    if title and title in working:
        working = working.split(title, 1)[1]
    if url:
        working = working.replace(url, "")
    if year is not None:
        working = re.sub(rf"\b{year}\b", "", working)

    working = working.strip(" ,.;:")
    if not working:
        return None

    lowered = working.lower()
    prefixes = [
        "in ",
        "blog post, ",
        "ser. ",
        "available: ",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            working = working[len(prefix) :].strip(" ,.;:")
            lowered = working.lower()

    working = working.lstrip("\"“” ")

    # Trim leading publication descriptors but keep venue/source names.
    for marker in ("pp. ", "p. ", "vol. ", "no. "):
        index = working.find(marker)
        if index != -1 and index < 8:
            working = working[index:].strip(" ,.;:")

    if not working:
        return None

    candidates = re.split(r"\.\s+|\[\s*online\s*\]\.?\s*available:\s*", working, maxsplit=1, flags=re.IGNORECASE)
    venue = candidates[0].strip(" ,.;:")
    if not venue:
        return None

    if authors:
        for author in authors:
            if venue == author:
                return None
    return venue or None
