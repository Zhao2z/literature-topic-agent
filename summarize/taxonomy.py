"""Normalization helpers for classification taxonomy values."""

from __future__ import annotations

from typing import Any

TAXONOMY_ALIASES = {
    "method_paradigm": {
        "llm-based": "llm_based",
        "llm based": "llm_based",
        "retrieval augmented": "retrieval_augmented",
        "search based": "search_based",
        "symbolic execution based": "symbolic_execution_based",
        "constraint solving based": "constraint_solving_based",
    },
    "target_languages": {
        "c/c++": "c_cpp",
        "c++": "c_cpp",
        "cpp": "c_cpp",
        "js": "javascript",
        "unspecified": "language_unspecified",
    },
}

LIST_FIELDS = {
    "target_languages",
    "test_task_types",
    "input_context",
    "output_artifact",
    "validation_repair",
    "evaluation_scope",
    "contribution_type",
}


def normalize_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize taxonomy aliases before strict schema validation."""

    classification = payload.get("classification")
    if not isinstance(classification, dict):
        return payload
    normalized = dict(payload)
    normalized_classification = dict(classification)
    for field_name, aliases in TAXONOMY_ALIASES.items():
        value = normalized_classification.get(field_name)
        if isinstance(value, str):
            normalized_classification[field_name] = aliases.get(value.strip().lower(), value)
    for field_name in LIST_FIELDS:
        items = normalized_classification.get(field_name)
        if not isinstance(items, list):
            continue
        aliases = TAXONOMY_ALIASES.get(field_name, {})
        normalized_classification[field_name] = [aliases.get(str(item).strip().lower(), item) for item in items]
    normalized["classification"] = normalized_classification
    return normalized
