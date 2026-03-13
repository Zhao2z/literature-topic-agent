"""Paper analysis orchestration around parsed section artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.logging import get_logger
from summarize.llm_client import AbstractLlmClient
from summarize.prompts import (
    PROMPT_VERSION,
    SURVEY_ENTRY_PROMPT_VERSION,
    PromptBuildResult,
    build_analysis_prompt,
    build_survey_entry_messages,
)
from summarize.schemas import AnalysisArtifactBundle, PaperAnalysisSchema
from summarize.taxonomy import normalize_analysis_payload

LOGGER = get_logger(__name__)


class PaperAnalyzer:
    """Generate validated analysis JSON for a parsed paper."""

    def __init__(self, *, llm_client: AbstractLlmClient, model_name: str) -> None:
        self.llm_client = llm_client
        self.model_name = model_name

    def analyze(self, *, paper_record: dict[str, Any], sections_path: Path) -> AnalysisArtifactBundle:
        """Analyze one paper from its parsed sections artifact."""

        sections_payload = json.loads(sections_path.read_text(encoding="utf-8"))
        paper_context = _build_paper_context(paper_record=paper_record, sections_payload=sections_payload)
        prompt_package = build_analysis_prompt(paper_context=paper_context, model_name=self.model_name)
        _write_prompt_snapshot(
            artifact_dir=sections_path.parent,
            prompt_package=prompt_package,
            model=self.model_name,
            prompt_version=PROMPT_VERSION,
        )
        raw_json = self.llm_client.generate_json(
            messages=prompt_package.messages,
            model=self.model_name,
            response_schema=PaperAnalysisSchema.model_json_schema(),
            temperature=0.1,
        )
        analysis = PaperAnalysisSchema.model_validate(normalize_analysis_payload(json.loads(raw_json)))
        LOGGER.bind(paper_id=analysis.paper_id, model=self.model_name).info("Validated LLM analysis JSON")
        return AnalysisArtifactBundle(
            analysis=analysis,
            model=self.model_name,
            provider="mimo",
            prompt_version=PROMPT_VERSION,
            prompt_messages=prompt_package.messages,
            raw_response=raw_json,
        )

    def generate_survey_entry(self, *, analysis: PaperAnalysisSchema, citation_key: str) -> tuple[str, list[dict[str, str]]]:
        """Generate a fluent LaTeX survey entry from structured analysis JSON."""

        messages = build_survey_entry_messages(
            analysis_payload=analysis.model_dump(mode="json"),
            citation_key=citation_key,
            model_name=self.model_name,
        )
        content = self.llm_client.generate_text(messages=messages, model=self.model_name, temperature=0.1)
        return content.strip(), messages


def _write_prompt_snapshot(
    *,
    artifact_dir: Path,
    prompt_package: PromptBuildResult,
    model: str,
    prompt_version: str,
) -> None:
    """Persist the full prompt before issuing the LLM request."""

    prompt_path = artifact_dir / "llm_prompt.json"
    prompt_path.write_text(
        json.dumps(
            {
                "model": model,
                "prompt_version": prompt_version,
                "messages": prompt_package.messages,
                "prompt_stats": prompt_package.prompt_stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _build_paper_context(*, paper_record: dict[str, Any], sections_payload: dict[str, Any]) -> dict[str, Any]:
    sections = sections_payload.get("sections", {})
    preferred_keys = [
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
    return {
        "paper_id": paper_record["paper_id"],
        "title": paper_record["title"],
        "venue": paper_record["venue"],
        "year": paper_record["year"],
        "ccf_rank": paper_record.get("ccf_rank"),
        "rank_score": paper_record.get("rank_score"),
        "sections": {
            key: {
                "title": sections[key]["title"],
                "content": sections[key]["content"],
            }
            for key in preferred_keys
            if key in sections
        },
    }
