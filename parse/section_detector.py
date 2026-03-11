"""Heuristic heading detection for academic PDFs."""

from __future__ import annotations

import re
from statistics import median

from parse.page_model import HeadingCandidate, PageLine, ParsedPage
from parse.section_normalizer import normalize_section_name

SHORT_HEADING_RE = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*)|(?:[IVXLCM]+)|(?:[A-Z]))[.)]?\s+[A-Z][A-Za-z0-9 ,:/&()'`-]{1,100}$"
)
TOP_LEVEL_NUMBERED_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLCM]+\.?)\s+[A-Z]", re.IGNORECASE)
LETTERED_SPECIAL_HEADING_RE = re.compile(r"^[A-Z]\.\s+[A-Z]", re.IGNORECASE)
SUBSECTION_NUMBER_RE = re.compile(r"^\d+\)\s+")
ROMAN_NUMERAL_RE = re.compile(r"^[IVXLCM]+[.)]?\s+", re.IGNORECASE)
SENTENCE_PUNCTUATION_RE = re.compile(r"[.!?]\s*$")


def detect_heading_candidates(pages: list[ParsedPage]) -> tuple[list[HeadingCandidate], list[HeadingCandidate]]:
    """Score likely section heading lines and split them into accepted and rejected candidates."""

    accepted: list[HeadingCandidate] = []
    rejected: list[HeadingCandidate] = []
    body_font_size = _estimate_body_font_size(pages)

    for page in pages:
        for line in page.lines:
            text = line.text.strip()
            if not text:
                continue

            reasons: list[str] = []
            score = 0.0
            word_count = len(text.split())

            if SHORT_HEADING_RE.match(text):
                score += 0.45
                reasons.append("numbered_heading_pattern")
            if word_count <= 10:
                score += 0.2
                reasons.append("short_line")
            if len(text) <= 80:
                score += 0.15
                reasons.append("compact_length")
            if not SENTENCE_PUNCTUATION_RE.search(text):
                score += 0.1
                reasons.append("no_sentence_punctuation")
            if text == text.upper() and not ROMAN_NUMERAL_RE.match(text):
                score += 0.05
                reasons.append("all_caps_heading")

            normalization = normalize_section_name(text)
            if normalization.canonical_name is not None:
                score += 0.35
                reasons.append("known_section_keyword")

            lowered = text.lower()
            if "copyright" in lowered or "doi" in lowered or "creativecommons" in lowered:
                score -= 0.6
                reasons.append("boilerplate_line")
            if word_count > 16 or len(text) > 120:
                score -= 0.35
                reasons.append("too_long_for_heading")
            if text.count(".") >= 2 and not SHORT_HEADING_RE.match(text):
                score -= 0.3
                reasons.append("sentence_like_line")

            accepted_flag = _is_major_heading_candidate(
                line=line,
                text=text,
                canonical_name=normalization.canonical_name,
                body_font_size=body_font_size,
            )
            candidate = HeadingCandidate(
                page_number=line.page_number,
                line_index=line.line_index,
                text=text,
                score=round(score, 3),
                accepted=accepted_flag and score >= 0.55 and normalization.canonical_name is not None,
                reasons=reasons,
                canonical_name=normalization.canonical_name,
            )
            if candidate.accepted:
                accepted.append(candidate)
            else:
                rejected.append(candidate)

    accepted.sort(key=lambda item: (item.page_number, item.line_index))
    rejected.sort(key=lambda item: (item.page_number, item.line_index))
    return accepted, rejected


def _estimate_body_font_size(pages: list[ParsedPage]) -> float:
    font_sizes = [
        line.font_size
        for page in pages
        for line in page.lines
        if len(line.text) >= 40 and line.font_size > 0
    ]
    if not font_sizes:
        return 0.0
    return float(median(font_sizes))


def _is_major_heading_candidate(
    *,
    line: PageLine,
    text: str,
    canonical_name: str | None,
    body_font_size: float,
) -> bool:
    if canonical_name is None:
        return False

    word_count = len(text.split())
    if canonical_name == "abstract":
        return line.page_number == 1 and text.lower().startswith("abstract")
    if TOP_LEVEL_NUMBERED_HEADING_RE.match(text):
        return word_count <= 10
    if canonical_name in {"threats_to_validity", "limitations"} and LETTERED_SPECIAL_HEADING_RE.match(text):
        return word_count <= 8
    if canonical_name == "references":
        return (text.upper() == text or text.istitle()) and word_count <= 3
    if canonical_name in {"conclusion", "introduction", "related_work", "background", "method", "approach", "model", "implementation", "experiments", "evaluation", "results", "discussion"}:
        if SUBSECTION_NUMBER_RE.match(text) or text.endswith(":"):
            return False
        if word_count > 6:
            return False
        if body_font_size > 0 and line.font_size + 0.01 < body_font_size:
            return False
        return text.upper() == text or text.istitle() or line.is_bold
    return False
