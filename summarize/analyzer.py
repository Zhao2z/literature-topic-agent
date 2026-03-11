"""Paper analysis orchestration around parsed section artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.logging import get_logger
from summarize.llm_client import AbstractLlmClient
from summarize.prompts import PROMPT_VERSION, build_analysis_messages
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
        messages = build_analysis_messages(paper_context=paper_context, model_name=self.model_name)
        raw_json = self.llm_client.generate_json(
            messages=messages,
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
            raw_response=raw_json,
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
