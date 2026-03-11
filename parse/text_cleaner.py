"""Text cleanup utilities for extracted PDF content."""

from __future__ import annotations

import re

BOILERPLATE_PATTERNS = [
    re.compile(r"^authorized licensed use limited to:", re.IGNORECASE),
    re.compile(r"^downloaded on .+ ieee xplore\.", re.IGNORECASE),
    re.compile(r"^restrictions apply\.?$", re.IGNORECASE),
]
PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")
WHITESPACE_RE = re.compile(r"[ \t]+")


def is_noise_line(text: str) -> bool:
    """Return whether a line is obvious PDF extraction noise."""

    stripped = text.strip()
    if not stripped:
        return True
    if PAGE_NUMBER_RE.fullmatch(stripped):
        return True
    return any(pattern.search(stripped) for pattern in BOILERPLATE_PATTERNS)


def normalize_section_content(lines: list[str]) -> str:
    """Convert raw line fragments into cleaner paragraph text."""

    if not lines:
        return ""

    cleaned_lines = [WHITESPACE_RE.sub(" ", line).strip() for line in lines if not is_noise_line(line)]
    if not cleaned_lines:
        return ""

    merged: list[str] = []
    for line in cleaned_lines:
        if merged and merged[-1].endswith("-") and line and line[0].islower():
            merged[-1] = merged[-1][:-1] + line
            continue
        merged.append(line)

    paragraphs: list[str] = []
    current = ""
    for line in merged:
        if not current:
            current = line
            continue
        if _should_join_with_space(current, line):
            current = f"{current} {line}"
        else:
            paragraphs.append(current)
            current = line
    if current:
        paragraphs.append(current)
    return "\n".join(paragraphs).strip()


def _should_join_with_space(current: str, next_line: str) -> bool:
    if current.endswith((".", "?", "!", ":")):
        return False
    if next_line.startswith(("•", "-", "TABLE", "FIG.", "Fig.", "A.", "B.", "C.", "D.", "E.", "F.")):
        return False
    if current.isupper() or next_line.isupper():
        return False
    return True
