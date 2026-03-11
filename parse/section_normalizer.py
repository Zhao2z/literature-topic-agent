"""Canonical section name normalization."""

from __future__ import annotations

import re

from parse.page_model import NormalizationDecision

WHITESPACE_RE = re.compile(r"\s+")
NUMBER_PREFIX_RE = re.compile(r"^(?:(?:\d+(?:\.\d+)*)|(?:[IVXLCM]+)|(?:[A-Z]))[.)]?\s+", re.IGNORECASE)
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

CANONICAL_SECTION_ORDER = [
    "title",
    "abstract",
    "introduction",
    "related_work",
    "background",
    "method",
    "approach",
    "model",
    "implementation",
    "experiments",
    "evaluation",
    "results",
    "discussion",
    "threats_to_validity",
    "conclusion",
    "limitations",
    "references",
]

SECTION_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("abstract", ("abstract", "summary")),
    ("introduction", ("introduction", "intro")),
    ("related_work", ("related work", "prior work", "previous work", "literature review")),
    ("background", ("background", "preliminaries", "preliminary", "motivation")),
    ("method", ("method", "methods", "methodology", "framework", "framework overview", "system overview")),
    ("approach", ("approach", "proposed approach", "our approach", "proposed method")),
    ("model", ("model", "models", "architecture", "system architecture")),
    ("implementation", ("implementation", "implementation details", "engineering details")),
    ("experiments", ("experiments", "experimental setup", "experiment setup", "empirical study", "experimental study", "case study")),
    ("evaluation", ("evaluation", "evaluations", "empirical evaluation", "experimental evaluation")),
    ("results", ("results", "experimental results", "analysis results", "results and analysis")),
    ("discussion", ("discussion", "discussions")),
    ("threats_to_validity", ("threats to validity", "validity threats", "threats", "limitations and threats")),
    ("conclusion", ("conclusion", "conclusions", "conclusion and future work", "future work")),
    ("limitations", ("limitations", "ethical considerations", "limitations and ethics", "limitation and future direction")),
    ("references", ("references", "bibliography", "reference")),
]

HEADING_CONNECTOR_TOKENS = {
    "and",
    "future",
    "work",
    "analysis",
    "discussion",
    "discussions",
    "study",
    "details",
    "setup",
    "overview",
    "design",
    "findings",
    "implications",
    "future",
    "direction",
}


def strip_heading_prefix(value: str) -> str:
    """Remove numbering prefixes from a section heading."""

    return NUMBER_PREFIX_RE.sub("", value.strip()).strip()


def normalize_heading_text(value: str) -> str:
    """Normalize a heading for comparison."""

    lowered = strip_heading_prefix(value).lower()
    lowered = NON_ALNUM_RE.sub(" ", lowered)
    return WHITESPACE_RE.sub(" ", lowered).strip()


def normalize_section_name(value: str) -> NormalizationDecision:
    """Map a raw heading to a canonical section name when possible."""

    normalized_text = normalize_heading_text(value)
    reasons: list[str] = []

    if not normalized_text:
        return NormalizationDecision(source_text=value, normalized_text=normalized_text, reasons=["empty_heading"])

    for canonical_name, aliases in SECTION_PATTERNS:
        decision = _match_section_alias(value=value, normalized_text=normalized_text, canonical_name=canonical_name, aliases=aliases)
        if decision is not None:
            return decision

    return NormalizationDecision(
        source_text=value,
        normalized_text=normalized_text,
        reasons=["no_canonical_mapping"],
    )


def _match_section_alias(
    *,
    value: str,
    normalized_text: str,
    canonical_name: str,
    aliases: tuple[str, ...],
) -> NormalizationDecision | None:
    reasons: list[str] = []
    canonical_label = canonical_name.replace("_", " ")
    if normalized_text == canonical_label:
        reasons.append("exact_canonical_match")
        return NormalizationDecision(
            source_text=value,
            normalized_text=normalized_text,
            canonical_name=canonical_name,
            reasons=reasons,
        )

    for alias in aliases:
        if normalized_text == alias:
            reasons.append("known_alias")
            return NormalizationDecision(
                source_text=value,
                normalized_text=normalized_text,
                canonical_name=canonical_name,
                reasons=reasons,
            )
        if _has_heading_style_prefix(value=value, alias=alias, normalized_text=normalized_text):
            reasons.append("heading_prefix_match")
            return NormalizationDecision(
                source_text=value,
                normalized_text=normalized_text,
                canonical_name=canonical_name,
                reasons=reasons,
            )
        if _is_compound_heading_match(normalized_text=normalized_text, alias=alias):
            reasons.append("compound_heading_match")
            return NormalizationDecision(
                source_text=value,
                normalized_text=normalized_text,
                canonical_name=canonical_name,
                reasons=reasons,
            )
    return None


def _has_heading_style_prefix(*, value: str, alias: str, normalized_text: str) -> bool:
    compact_source = strip_heading_prefix(value).strip().lower()
    if compact_source.startswith(f"{alias}:") or compact_source.startswith(f"{alias} -") or compact_source.startswith(f"{alias}—"):
        return True
    if alias == "abstract" and normalized_text.startswith("abstract "):
        return True
    return False


def _is_compound_heading_match(*, normalized_text: str, alias: str) -> bool:
    if not normalized_text.startswith(f"{alias} "):
        return False
    suffix_tokens = normalized_text[len(alias) :].strip().split()
    return bool(suffix_tokens) and all(token in HEADING_CONNECTOR_TOKENS for token in suffix_tokens)
